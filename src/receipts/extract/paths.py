"""Dotted-path flatten/unflatten for extraction objects.

Used in three places: self-consistency diffing, the corrections log (one row
per changed field path), and field-level accuracy in the eval harness. Keeping
one implementation means all three agree on what "a field" is.

Path grammar:  totals.total | line_items[2].qty | totals.tax_breakdown[0].amount
"""

from __future__ import annotations

import re
from decimal import Decimal
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

#: The grounding side-map ``ReceiptExtraction.field_boxes`` (schema.py). It is
#: neither transcription nor self-report: the model never produces it, the
#: labels never declare it, and the OCR pass fills it AFTER the run from pixel
#: geometry. So it is a fourth family -- ``derived`` -- that :func:`group_of`
#: names and :func:`receipts`' eval (``eval/metrics.py``) counts in nothing.
#: A prefix rather than a leaf name, and structural for the same reason the
#: others are: it classifies every ``field_boxes.merchant.name`` sub-path a
#: future field gains without anyone adding it here.
_FIELD_BOXES = "field_boxes"

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
    """Which family a dotted path belongs to: ``derived``, ``self_report``,
    ``line_items`` or ``core``.

    Read from the path string alone — never from either side's value.

    ``derived`` is checked first and is the whole of :data:`_FIELD_BOXES`'s
    subtree: grounding geometry the model never reads and the labels never
    declare, so it is scored in no class (``eval/metrics.py``). Checking it
    first keeps a future ``field_boxes.meta.*`` path out of ``self_report``.

    ``self_report`` is reached two ways, and there are exactly these two:
    everything under the ``meta.`` prefix, and the leaves declared in
    :data:`SELF_REPORT_LEAVES`. The set is checked before the ``meta.`` prefix,
    because the leaves in it live under prefixes that would otherwise claim them.
    """
    if path == _FIELD_BOXES or path.startswith(f"{_FIELD_BOXES}."):
        return "derived"
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


def _is_vacuous(value: object) -> bool:
    """True when a leaf is its own type's empty value, whatever that type is.

    **The third concept ISSUE-016 asked whether there was room for**, and there
    was: a leaf can be *filled* (:func:`is_filled` says so) and still carry no
    reading. ``""``, ``0`` and ``False`` are each the nothing of their type, and
    an extraction whose leaves are all of that shape transcribed nothing from
    the paper however many keys it emitted.

    **This is deliberately not :func:`is_filled`, and must not be folded into
    it.** ``is_filled`` is shared with ``field_accuracy`` by design (design
    §3.3, §4) so that "content" has exactly one definition: a read zero *is*
    content for accuracy scoring, and a model that correctly reads a zero
    discount must score for it. Vacuity is a different question -- "did this
    rung read the page at all" -- asked in exactly one place, by
    :func:`read_nothing`, and answered for the ladder rather than for scoring.

    **Defined against the value, never against a field list.** Every earlier
    version of this predicate was wrong because some field rested at a default
    ``is_filled`` accepts, and each fix made the baseline more like the thing
    being judged rather than naming the field that had just been found. A list
    would rot on the next schema change; this covers a field nobody has added
    yet.

    ``bool`` is tested before ``int`` because ``isinstance(False, int)`` is true
    in Python, and ``False`` reaching the numeric branch would work by accident
    rather than by statement.
    """
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        # **A money zero arrives here as a string, not a Decimal.** `flatten`
        # renders `Decimal("0")` as `'0'` so the JSON round trip keeps the
        # scale (ADR-0001), so the numeric branch below never sees it and a
        # `str`-only check would call `'0'` a reading. Measured: without this,
        # `totals.total = Decimal("0")` still read as content.
        try:
            return Decimal(text) == 0
        except (ArithmeticError, ValueError):
            return False
    if isinstance(value, bool):
        return value is False
    if isinstance(value, (int, float, Decimal)):
        return value == 0
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _content_paths(extraction: Any) -> dict[str, Any]:
    """The ``core`` and ``line_items`` leaves that carry a reading.

    ``is_filled`` and then ``_is_vacuous``: the first is the shared definition
    of content, the second removes the leaves that are filled and say nothing
    (ISSUE-016). Both, rather than the second alone, so ``is_filled``'s role
    here stays visible -- it is the reason ``[]`` means "had none" rather than
    "not read".
    """
    return {
        path: value
        for path, value in flatten(extraction).items()
        if group_of(path) in ("core", "line_items")
        and is_filled(value)
        and not _is_vacuous(value)
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
