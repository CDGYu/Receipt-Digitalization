"""Turning a Pydantic model into a provider-safe tool schema, and turning a
model response back into a Pydantic object.

Two problems this module exists to solve, both discovered the hard way:

1. `$ref` / `$defs`. Pydantic emits nested models as JSON-Schema references.
   Several providers do not resolve them inside a tool's input_schema and will
   either error or silently ignore the nested structure. We inline everything.

2. `Decimal`. Pydantic renders a Decimal field as
   `anyOf: [number, string-with-regex, null]`. That string branch actively
   invites the model to emit "949.20" as a STRING, and the regex is rejected by
   some providers' schema validators. We collapse it to `anyOf: [number, null]`.

Getting structured output via tool-use rather than "please reply in JSON" is
worth the extra plumbing: the provider constrains generation to the schema, so
malformed JSON becomes rare rather than a routine failure you retry around.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

__all__ = [
    "build_tool_schema",
    "dereference",
    "parse_model_json",
    "extract_json_blob",
    "JsonParseError",
]


class JsonParseError(ValueError):
    """Raised when a response cannot be coerced into the target model."""


# --------------------------------------------------------------------------- #
# Schema preparation
# --------------------------------------------------------------------------- #

#: Pydantic's Decimal string branch. Matching on the pattern key is more robust
#: than matching the regex text, which changes between pydantic versions.
_DECIMAL_STRING_BRANCH_KEYS = {"pattern", "type"}


def dereference(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline every `$ref` against the schema's own `$defs`, then drop `$defs`.

    Recursive models would loop forever here. The receipt schema is a tree, so
    this is safe — but the depth guard makes the failure loud rather than a hang
    if someone later adds a self-referencing field.
    """
    defs = schema.get("$defs", {})

    def walk(node: Any, depth: int = 0) -> Any:
        if depth > 32:
            raise ValueError("Schema nesting too deep — is a model self-referencing?")
        if isinstance(node, list):
            return [walk(n, depth + 1) for n in node]
        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            ref = node["$ref"]
            name = ref.rsplit("/", 1)[-1]
            if name not in defs:
                raise ValueError(f"Unresolvable $ref: {ref}")
            merged = walk(copy.deepcopy(defs[name]), depth + 1)
            # Preserve any sibling keys (description, default) alongside the ref.
            for key, value in node.items():
                if key != "$ref":
                    merged[key] = walk(value, depth + 1)
            return merged

        return {k: walk(v, depth + 1) for k, v in node.items()}

    out = walk(copy.deepcopy(schema))
    out.pop("$defs", None)
    return out


def _collapse_decimal_unions(node: Any) -> Any:
    """Drop the string branch from Decimal's anyOf so the model emits numbers."""
    if isinstance(node, list):
        return [_collapse_decimal_unions(n) for n in node]
    if not isinstance(node, dict):
        return node

    if "anyOf" in node and isinstance(node["anyOf"], list):
        branches = node["anyOf"]
        has_number = any(b.get("type") == "number" for b in branches if isinstance(b, dict))
        if has_number:
            branches = [
                b
                for b in branches
                if not (
                    isinstance(b, dict)
                    and b.get("type") == "string"
                    and set(b.keys()) <= _DECIMAL_STRING_BRANCH_KEYS
                )
            ]
            node = {**node, "anyOf": branches}

    return {k: _collapse_decimal_unions(v) for k, v in node.items()}


def _strip_noise(node: Any) -> Any:
    """Remove keys that cost tokens without constraining the model."""
    drop = {"title", "default"}
    if isinstance(node, list):
        return [_strip_noise(n) for n in node]
    if not isinstance(node, dict):
        return node
    return {k: _strip_noise(v) for k, v in node.items() if k not in drop}


def build_tool_schema(model: type[BaseModel], *, strip_titles: bool = True) -> dict[str, Any]:
    """Produce a provider-safe JSON Schema for a model.

    Field `description=` text survives this and is the main channel for telling
    the model what a field means. Keep descriptions in the schema short; long
    guidance belongs in the system prompt.
    """
    schema = dereference(model.model_json_schema())
    schema = _collapse_decimal_unions(schema)
    if strip_titles:
        schema = _strip_noise(schema)
    schema.setdefault("type", "object")
    return schema


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def extract_json_blob(text: str) -> str:
    """Recover a JSON object from a text response.

    Only needed on the fallback path — with tool-use the provider hands back a
    parsed dict. Models that ignore "no markdown fences" produce three failure
    shapes, all handled here: fenced blocks, prose before/after the object, and
    trailing commas.
    """
    if not text or not text.strip():
        raise JsonParseError("Empty response")

    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)

    start = text.find("{")
    if start == -1:
        raise JsonParseError("No JSON object found in response")

    # Walk to the matching brace so trailing prose is discarded.
    depth, in_string, escaped, end = 0, False, False, -1
    for i, ch in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        raise JsonParseError("Unterminated JSON object (response likely truncated)")

    return _TRAILING_COMMA.sub(r"\1", text[start:end])


def parse_model_json(payload: str | dict[str, Any], model: type[T]) -> T:
    """Coerce a response into `model`, raising JsonParseError with the detail
    the repair prompt needs (see rule R001)."""
    if isinstance(payload, dict):
        data = payload
    else:
        try:
            data = json.loads(extract_json_blob(payload))
        except json.JSONDecodeError as exc:
            raise JsonParseError(f"Invalid JSON: {exc}") from exc

    try:
        return model.model_validate(data)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise JsonParseError(f"Response did not match schema: {errors}") from exc
