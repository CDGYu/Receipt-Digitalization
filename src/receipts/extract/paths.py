"""Dotted-path flatten/unflatten for extraction objects.

Used in three places: self-consistency diffing, the corrections log (one row
per changed field path), and field-level accuracy in the eval harness. Keeping
one implementation means all three agree on what "a field" is.

Path grammar:  totals.total | line_items[2].qty | totals.tax_breakdown[0].amount
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

_INDEXED = re.compile(r"^(.*?)\[(\d+)\]$")


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Model or dict -> {dotted_path: leaf_value}.

    Empty containers are emitted as leaves so that "had 3 line items" versus
    "had none" is a visible difference rather than silently absent.
    """
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")

    out: dict[str, Any] = {}

    if isinstance(obj, dict):
        if not obj and prefix:
            out[prefix] = {}
        for key, value in obj.items():
            out.update(flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(obj, list):
        if not obj and prefix:
            out[prefix] = []
        for i, value in enumerate(obj):
            out.update(flatten(value, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj

    return out


def unflatten(paths: dict[str, Any]) -> dict[str, Any]:
    """Inverse of flatten. Missing list indices are filled with None."""
    root: dict[str, Any] = {}

    for path, value in sorted(paths.items(), key=_sort_key):
        cursor: Any = root
        parts = path.split(".")
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            match = _INDEXED.match(part)

            if match:
                name, index = match.group(1), int(match.group(2))
                container = cursor.setdefault(name, [])
                while len(container) <= index:
                    container.append(None)
                if last:
                    container[index] = value
                else:
                    if not isinstance(container[index], dict):
                        container[index] = {}
                    cursor = container[index]
            else:
                if last:
                    cursor[part] = value
                else:
                    cursor = cursor.setdefault(part, {})

    return root


def _sort_key(item: tuple[str, Any]) -> tuple:
    """Sort so parents are created before children and list indices ascend."""
    path = item[0]
    key: list = []
    for part in path.split("."):
        match = _INDEXED.match(part)
        if match:
            key.extend([match.group(1), int(match.group(2))])
        else:
            key.extend([part, -1])
    return tuple(str(k) if isinstance(k, str) else f"{k:09d}" for k in key)


def count_nulls(obj: Any) -> int:
    """How many leaf fields are null. Used as the final tie-break when picking
    between extraction attempts — all else equal, prefer the one that read
    more of the receipt."""
    return sum(1 for v in flatten(obj).values() if v is None)
