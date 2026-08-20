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

from .schema import LineItem, ReceiptExtraction

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


#: Path prefixes that decide a leaf's family. Structural on purpose: a prefix
#: test classifies a schema field added next year without anybody deciding it
#: should be, where a list of field names would silently let it through
#: (review standard 19 — an enumerated defence never converges). A leaf that no
#: prefix can reach is declared just below, together with the rule that admits
#: one.
_META_PREFIX = "meta."
_LINE_ITEMS = "line_items"

#: The self-report leaves that do **not** live under ``meta.``. One declaration,
#: read by :func:`group_of` and by nothing else.
#:
#: The admission rule, and the whole of it: a leaf belongs here when it records
#: the model's **claim about the paper** — the state of the document, or of the
#: model's own reading of it — rather than a transcription of content printed
#: on it. ``is_template_row`` says "this pre-printed row was left blank"; the
#: paper nowhere reads "false", and a model that looks at nothing is right on
#: every row that is not blank, which is a free point per line item inside a
#: group that averages.
#:
#: ``receipt.decimal_convention`` is the near miss on the other side of that
#: line and is deliberately **not** here: it also rests at a usually-correct
#: default, but it names a convention the document prints, so it is something
#: the model had to read.
SELF_REPORT_LEAVES = frozenset({"is_template_row"})


def group_of(path: str) -> str:
    """Which family a dotted path belongs to: ``self_report``, ``line_items`` or ``core``.

    Read from the path string alone — never from either side's value.

    ``self_report`` is reached two ways, and there are exactly these two:
    everything under the ``meta.`` prefix, and the leaves declared in
    :data:`SELF_REPORT_LEAVES`. The set is checked **first**, because the
    leaves in it live under prefixes that would otherwise claim them.
    """
    if path.rsplit(".", 1)[-1] in SELF_REPORT_LEAVES:
        return "self_report"
    if path.startswith(_META_PREFIX):
        return "self_report"
    if path == _LINE_ITEMS or path.startswith(f"{_LINE_ITEMS}["):
        return "line_items"
    return "core"


def is_filled(value: object) -> bool:
    """True when a leaf carries information the model could have read.

    ``None`` is not filled, and neither is an empty container. ``flatten``
    emits ``[]``/``{}`` as leaves deliberately, so that "had none" is visible
    rather than absent — but a receipt whose ``totals.tax_breakdown`` is empty
    has no tax breakdown to transcribe, so it is not a point anyone can earn.

    Written with ``isinstance``/``len`` rather than ``value in (None, [], {})``:
    that form compares with ``==``, and equality against a container is not a
    test this rule should rest on.
    """
    if value is None:
        return False
    return not (isinstance(value, (list, dict)) and len(value) == 0)


def _content_paths(extraction: Any) -> dict[str, Any]:
    """The filled ``core`` and ``line_items`` leaves of one extraction."""
    return {
        path: value
        for path, value in flatten(extraction).items()
        if group_of(path) in ("core", "line_items") and is_filled(value)
    }


def read_nothing(extraction: Any) -> bool:
    """True when an extraction transcribed nothing from the paper.

    Compared against a **default-constructed** extraction rather than against
    emptiness, because emptiness is unreachable: ``ReceiptExtraction()`` carries
    ``receipt.decimal_convention = 'point'``, which is ``core`` by design — the
    convention is something the document prints, so a model is expected to read
    it (:func:`group_of`'s own note says so).

    Comparing to the default is what keeps this schema-derived in both
    directions: a field added later that rests at a default is excluded without
    anybody deciding, and a field the model actually fills is counted the same
    way.

    Covers the no-parse case without a clause of its own — ``_evaluate``
    resolves a failed parse to exactly ``ReceiptExtraction()``.

    The baseline is recomputed per call rather than cached in a module-level
    constant: one call per rung costs microseconds against a VLM call measured
    in minutes, and a cached copy is a second statement of the schema's defaults
    that can go stale — the drift this predicate's whole design avoids.

    **The baseline is shaped like the extraction, not merely default.** A row
    the model emitted but read nothing into is still nothing read, and a bare
    ``ReceiptExtraction()`` baseline could not say so: ``LineItem()`` rests at
    ``position=0`` and ``description_raw=""``, both of which :func:`is_filled`
    accepts — ``0`` is content, and ``""`` is a ``str`` rather than an empty
    *container*. So ``line_items: [{}]`` compared against a zero-row baseline
    read as content, and the fallback it gates would not have fired. That is
    reachable rather than theoretical: R013's repair prompt tells a model
    "Triage estimated roughly 1 line items", and triage returned exactly that on
    r002.

    Each baseline row mirrors its counterpart's ``position`` because position is
    **structural** — ``normalize`` fills missing ones by order and sorts, so the
    same two blank rows can arrive numbered ``0,0`` or ``0,1``. Neither spelling
    is something read off the paper, so neither may count as content.
    """
    baseline = ReceiptExtraction(
        line_items=[LineItem(position=item.position) for item in extraction.line_items]
    )
    return _content_paths(extraction) == _content_paths(baseline)
