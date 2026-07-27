"""Hosted implementation using the Anthropic Messages API.

Structured output is obtained via TOOL USE, not by asking for JSON in prose.
The provider constrains generation to the tool's input_schema, which turns
malformed output from a routine failure into a rare one.

The SDK is imported lazily so this module can be imported (and the rest of the
package tested) without the dependency installed.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

from ..json_io import JsonParseError, build_tool_schema, parse_model_json
from .base import (
    ImagePart,
    PricePer1M,
    VLMClient,
    VLMPermanentError,
    VLMResponse,
    VLMTransientError,
)

T = TypeVar("T", bound=BaseModel)


class AnthropicVLMClient(VLMClient):
    def __init__(
        self,
        model_id: str,
        *,
        api_key: str | None = None,
        price: PricePer1M | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install anthropic to use AnthropicVLMClient") from exc

        self._sdk = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s)
        self.model_id = model_id
        # Prices move. Source this from config, never hardcode in production.
        self.price = price or PricePer1M(input=Decimal("3.00"), output=Decimal("15.00"))

    # ------------------------------------------------------------------ #

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        images: list[ImagePart],
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tool_name: str = "record_extraction",
        tool_description: str = "Record the structured data read from the document.",
    ) -> VLMResponse:
        content: list[dict[str, Any]] = []

        # Images first, target LAST. Recency matters: whichever image is
        # closest to the instruction text is the one the model treats as the
        # subject. Few-shot examples must therefore precede the real receipt.
        for part in images:
            if part.label:
                content.append({"type": "text", "text": part.label})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": part.b64,
                    },
                }
            )
        content.append({"type": "text", "text": user})

        tool = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": build_tool_schema(schema),
        }

        started = time.perf_counter()
        try:
            message = self._client.messages.create(
                model=self.model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": content}],
                tools=[tool],
                # Force the tool. Without this the model may reply in prose.
                tool_choice={"type": "tool", "name": tool_name},
            )
        except self._sdk.RateLimitError as exc:
            raise VLMTransientError(f"rate limited: {exc}") from exc
        except (self._sdk.APITimeoutError, self._sdk.APIConnectionError) as exc:
            raise VLMTransientError(f"connection: {exc}") from exc
        except self._sdk.APIStatusError as exc:
            if exc.status_code >= 500:
                raise VLMTransientError(f"server error {exc.status_code}") from exc
            raise VLMPermanentError(f"status {exc.status_code}: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(message, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0

        response = VLMResponse(
            parsed=None,
            raw=message.model_dump() if hasattr(message, "model_dump") else message,
            model_id=self.model_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
            cost_usd=self.price.cost(in_tok, out_tok),
        )

        # A truncated response is the single most common cause of a "corrupt"
        # extraction on long receipts. Surface it explicitly rather than
        # letting it look like a schema violation.
        if getattr(message, "stop_reason", None) == "max_tokens":
            response.parse_error = (
                f"Response hit the {max_tokens}-token limit and was truncated. "
                "Split the receipt into strips or raise max_tokens."
            )
            return response

        payload = next(
            (block.input for block in message.content if getattr(block, "type", "") == "tool_use"),
            None,
        )
        if payload is None:
            text = " ".join(
                getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text"
            )
            payload = text or None

        if payload is None:
            response.parse_error = "Model returned neither a tool call nor text."
            return response

        try:
            response.parsed = parse_model_json(payload, schema)
        except JsonParseError as exc:
            response.parse_error = str(exc)

        return response
