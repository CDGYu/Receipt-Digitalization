"""Global-constraint guard: no ``float`` in the money path.

The prime directive of this project is that money is ALWAYS ``Decimal`` and
never ``float`` (see ``schema.py`` module docstring and RECEIPT_SYSTEM_SPEC
§18). A single float in the arithmetic path produces tolerance failures that
masquerade as model errors, so this must be enforced structurally.

This test recursively walks ``ReceiptExtraction`` and every nested pydantic
``BaseModel``, resolves each field's annotation down through
``Optional`` / ``list`` / ``Union`` / other generics to its concrete leaf
types, and asserts none of them is ``float``.

Documented exception
--------------------
``LineItem.bbox`` holds normalised ``[x0, y0, x1, y1]`` spatial grounding
coordinates (0-1). Those are explicitly NOT money -- they are pixel geometry --
so ``float`` is the correct type and the field is allowlisted below. It is the
only intentional float reachable from ``ReceiptExtraction``. Any *other* float,
especially on a money field, is a real violation and fails this test. If a new
float ever appears on a money field, this guard fails and that is the point.
"""

from __future__ import annotations

import typing
from typing import get_args, get_origin

from pydantic import BaseModel

from receipts.extract import schema

# (model class name, field name) pairs that are permitted to resolve to
# ``float`` because they are explicitly NOT part of the money path.
_ALLOWED_FLOAT_FIELDS: set[tuple[str, str]] = {
    ("LineItem", "bbox"),  # normalised [x0,y0,x1,y1] grounding coords, not money
}


def _leaf_types(annotation: object) -> set[object]:
    """Flatten an annotation into its set of concrete (non-generic) leaf types.

    Recurses through ``Optional`` / ``Union`` / ``list`` / ``dict`` / ``tuple``
    and any other parameterised generic, discarding ``None`` and ``Ellipsis``.
    """
    args = get_args(annotation)
    if get_origin(annotation) is None and not args:
        return {annotation}
    leaves: set[object] = set()
    for arg in args:
        if arg is type(None) or arg is Ellipsis:
            continue
        leaves |= _leaf_types(arg)
    return leaves


def _walk(model: type[BaseModel], seen: set[type]) -> list[tuple[str, str, set[object]]]:
    """Return ``(model_name, field_name, leaf_types)`` for a model and its nested models."""
    if model in seen:
        return []
    seen.add(model)

    try:
        hints = typing.get_type_hints(model)
    except Exception:  # pragma: no cover - defensive; fall back to raw annotations
        hints = {}

    results: list[tuple[str, str, set[object]]] = []
    for field_name, field_info in model.model_fields.items():
        annotation = hints.get(field_name, field_info.annotation)
        leaves = _leaf_types(annotation)
        results.append((model.__name__, field_name, leaves))
        for leaf in leaves:
            if isinstance(leaf, type) and issubclass(leaf, BaseModel):
                results.extend(_walk(leaf, seen))
    return results


def test_no_float_in_money_path() -> None:
    walked = _walk(schema.ReceiptExtraction, set())

    # Guard against a vacuous pass: if the recursion silently failed to descend
    # into nested models, the float assertion below would pass for the wrong
    # reason. Confirm known nested money fields were actually visited first.
    visited = {(model_name, field_name) for model_name, field_name, _ in walked}
    for expected in (("Totals", "total"), ("LineItem", "line_total"), ("Modifier", "amount")):
        assert expected in visited, f"walk did not reach {expected[0]}.{expected[1]}"

    offenders: list[str] = []
    for model_name, field_name, leaves in walked:
        if float in leaves and (model_name, field_name) not in _ALLOWED_FLOAT_FIELDS:
            offenders.append(f"{model_name}.{field_name}")

    assert not offenders, (
        "float found on money-path field(s): "
        + ", ".join(sorted(offenders))
        + " -- money must be Decimal (see schema.py docstring / SPEC §18)."
    )
