"""Per-receipt evaluation metrics (spec §16).

Pure and deterministic: no I/O, no network, no mutation of inputs. Every
comparison here answers one question — "did the model read this correctly?" —
and the answers fold up into the six headline metrics the harness reports.

Design notes that are load-bearing:

  * Money is compared with :func:`receipts.validate.rules.within_tolerance`,
    never with ``==``. The eval must use the *same* notion of "close enough" as
    the validator, or a receipt could pass validation yet be scored wrong (or
    vice versa). Tolerance stays bounded in cents — see the rule docstring.
  * ``flatten`` is fed ``model.model_dump()`` (python mode), NOT the model
    directly. ``flatten(model)`` calls ``model_dump(mode="json")`` under the
    hood, which stringifies every ``Decimal`` — comparing "949.20" to "949.21"
    as text would call a within-a-cent read a mismatch. The python-mode dump
    keeps money as ``Decimal`` so the tolerance branch actually fires.
  * ``_norm_text`` is defined locally on purpose. There is no
    ``receipts.normalize`` module yet, and field accuracy must not depend on the
    (future) production normaliser — the eval is the thing that would catch a
    regression in it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from receipts.extract.lineitem_align import align_line_items
from receipts.extract.paths import flatten
from receipts.extract.schema import LineItem, ReceiptExtraction
from receipts.validate.rules import within_tolerance

#: Default auto-approve cut-off (§17 AUTO_APPROVE_THRESHOLD). Used only to
#: compute the headline auto-approval numbers; the full calibration curve is
#: reported alongside so the cut-off can be tuned against the golden set.
AUTO_APPROVE_THRESHOLD = Decimal("0.85")

_WS = re.compile(r"\s+")


def _norm_text(value: str) -> str:
    """Casefold and collapse whitespace for text-field comparison.

    Leading/trailing whitespace is stripped and internal runs are squeezed to a
    single space; casing is folded away. Punctuation is intentionally preserved
    — merchant legal suffixes ("CO.", "INC.") carry meaning.
    """
    return _WS.sub(" ", value.strip()).casefold()


def _values_equal(a: Any, b: Any) -> bool:
    """Compare two flattened leaf values by their runtime type.

    ``None``/``None`` agree; ``None`` against a value disagrees. Two ``Decimal``
    values agree within tolerance; two strings agree after normalisation;
    anything else falls back to ``==``.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return within_tolerance(a, b)
    if isinstance(a, str) and isinstance(b, str):
        return _norm_text(a) == _norm_text(b)
    return bool(a == b)


def _money_agree(a: Decimal | None, b: Decimal | None) -> bool:
    """Tolerance comparison that treats two missing values as agreement.

    ``within_tolerance`` returns ``False`` when either side is ``None`` (callers
    are meant to gate on presence). For line-item field matching we want
    ``None`` vs ``None`` to count as agreement and ``None`` vs a value to count
    as disagreement.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return within_tolerance(a, b)


def field_accuracy(
    predicted: ReceiptExtraction, truth: ReceiptExtraction
) -> dict[str, bool]:
    """Per dotted-path correctness of ``predicted`` against ``truth``.

    Both sides are flattened to ``{dotted_path: value}``. Money paths are
    compared within tolerance, text paths after normalisation, everything else
    by equality. A path present on only one side scores ``False`` — a missing
    or hallucinated line item is a real error, not a skip.
    """
    pred = flatten(predicted.model_dump())
    tru = flatten(truth.model_dump())
    result: dict[str, bool] = {}
    for path in pred.keys() | tru.keys():
        if path not in pred or path not in tru:
            result[path] = False
        else:
            result[path] = _values_equal(pred[path], tru[path])
    return result


def _line_fields_agree(a: LineItem, b: LineItem) -> bool:
    """True when qty, unit_price and line_total all agree (tolerance-aware)."""
    return (
        _money_agree(a.qty, b.qty)
        and _money_agree(a.unit_price, b.unit_price)
        and _money_agree(a.line_total, b.line_total)
    )


def line_item_f1(
    predicted: list[LineItem], truth: list[LineItem]
) -> tuple[float, float, float]:
    """Precision, recall and F1 over line items.

    Rows are aligned by normalised-description similarity (see
    :func:`receipts.extract.lineitem_align.align_line_items`), so a single
    inserted or dropped row does not cascade. A matched pair is a true positive
    only when qty, unit_price and line_total all agree. A matched pair whose
    numbers disagree is counted as both a false positive (the predicted row is
    wrong) and a false negative (the truth row was not captured correctly).
    Unmatched predicted rows are false positives; unmatched truth rows are false
    negatives. Each ratio is ``0.0`` when its denominator is zero.
    """
    tp = fp = fn = 0
    for i, j in align_line_items(predicted, truth):
        if i is not None and j is not None:
            if _line_fields_agree(predicted[i], truth[j]):
                tp += 1
            else:
                fp += 1
                fn += 1
        elif i is not None:
            fp += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return precision, recall, f1


def critical_field_accuracy(
    predicted: ReceiptExtraction, truth: ReceiptExtraction
) -> bool:
    """The metric that actually matters: merchant name, date and total all right.

    Merchant name is compared after normalisation, date exactly, total within
    tolerance. This is the definition of "correct" used to score auto-approval
    precision, so it is deliberately strict — a wrong total here is money lost.
    """
    name_ok = _norm_text(predicted.merchant.name or "") == _norm_text(
        truth.merchant.name or ""
    )
    date_ok = predicted.receipt.date == truth.receipt.date
    total_ok = within_tolerance(predicted.totals.total, truth.totals.total)
    return name_ok and date_ok and total_ok


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #


@dataclass
class EvalResult:
    """One receipt's scored outcome. ``field_acc`` maps dotted path -> correct."""

    receipt_id: str
    confidence: Decimal
    critical_correct: bool
    field_acc: dict[str, bool]


@dataclass
class EvalReport:
    """Aggregate over a golden-set run: counts plus the six §16 metrics.

    ``cost_per_receipt`` and the latency percentiles are part of the §16 metric
    set but are not observable through the injected ``pipeline_fn`` (which
    returns only an extraction and a confidence), so they stay ``None`` here and
    are filled in by callers that measure the real pipeline.
    """

    n_receipts: int
    n_auto_approved: int
    n_critical_correct: int
    auto_approve_threshold: Decimal

    # §16 metrics, in priority order
    auto_approval_precision: float        # 1
    auto_approval_rate: float             # 2
    critical_field_accuracy: float        # 3
    field_accuracy: float                 # 4
    line_item_precision: float            # 5
    line_item_recall: float               # 5
    line_item_f1: float                   # 5
    cost_per_receipt: Decimal | None = None    # 6
    p50_latency_s: float | None = None         # 6
    p95_latency_s: float | None = None         # 6

    calibration: list[tuple[Decimal, float, float]] = field(default_factory=list)
    results: list[EvalResult] = field(default_factory=list)


def calibration_curve(
    results: list[EvalResult],
) -> list[tuple[Decimal, float, float]]:
    """Map each candidate threshold to ``(threshold, auto_approve_rate, precision)``.

    Candidates are every distinct confidence observed plus a 0.0–1.0 sweep in
    0.1 steps, so the curve is populated even for a tiny result set. A receipt is
    auto-approved when ``confidence >= threshold``; precision is the fraction of
    auto-approved receipts that are critical-correct, defined as ``1.0`` when
    none are approved. Triples are sorted by ascending threshold — pick the
    lowest whose precision clears the target.
    """
    thresholds: set[Decimal] = {r.confidence for r in results}
    thresholds.update(Decimal(step) / Decimal(10) for step in range(11))

    total = len(results)
    curve: list[tuple[Decimal, float, float]] = []
    for threshold in sorted(thresholds):
        approved = [r for r in results if r.confidence >= threshold]
        rate = len(approved) / total if total else 0.0
        if approved:
            correct = sum(1 for r in approved if r.critical_correct)
            precision = correct / len(approved)
        else:
            precision = 1.0
        curve.append((threshold, rate, precision))
    return curve
