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
from dataclasses import dataclass, field, fields
from decimal import Decimal
from typing import Any

from receipts.extract.lineitem_align import align_line_items

# Aliased back to the private names this module already used, so the move of
# the grouping into ``receipts.extract.paths`` changes no call site here.
# ``_SELF_REPORT_LEAVES`` has no code reader left in this module -- it is read
# by the ``FieldBreakdown`` docstring and imported by ``tests/test_eval_metrics``
# -- hence the noqa rather than a deletion.
from receipts.extract.paths import SELF_REPORT_LEAVES as _SELF_REPORT_LEAVES  # noqa: F401
from receipts.extract.paths import flatten
from receipts.extract.paths import group_of as _group
from receipts.extract.paths import is_filled as _is_filled
from receipts.extract.schema import LineItem, ReceiptExtraction

# Default auto-approve cut-off (§17 AUTO_APPROVE_THRESHOLD). Used only to
# compute the headline auto-approval numbers; the full calibration curve is
# reported alongside so the cut-off can be tuned against the golden set.
# Re-exported from receipts.score.thresholds -- the single definition -- so
# existing importers of eval.metrics.AUTO_APPROVE_THRESHOLD keep working.
from receipts.score.thresholds import AUTO_APPROVE_THRESHOLD as AUTO_APPROVE_THRESHOLD
from receipts.validate.rules import within_tolerance

_WS = re.compile(r"\s+")


def _norm_text(value: str) -> str:
    """Casefold and collapse whitespace for text-field comparison.

    Leading/trailing whitespace is stripped and internal runs are squeezed to a
    single space; casing is folded away. Punctuation is intentionally preserved
    — merchant legal suffixes ("CO.", "INC.") carry meaning.
    """
    return _WS.sub(" ", value.strip()).casefold()


def ratio(correct: int, total: int) -> float | None:
    """``correct/total``, or ``None`` when the denominator is zero.

    ``None``, never ``0.0``: a ratio over no decisions is undefined, not bad.
    Same rule as ``auto_approval_precision`` (P8.T3), applied to the new
    metrics before it can bite a second time.
    """
    return (correct / total) if total else None


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


@dataclass(frozen=True)
class FieldBreakdown:
    """One receipt's dotted paths, split into classes that mean different things.

    The old single scalar averaged three unlike quantities — what the model
    read, what it correctly left empty, and what it said about itself — and the
    last two dominate: an extraction containing *nothing* scored 42.50% / 37.50%
    / 36.59% against the three golden labels. See
    ``docs/superpowers/specs/2026-08-12-eval-field-accuracy-honesty-design.md``.

    Two axes decide a path's class. **Group** comes from the path string;
    **filled** is read from the *truth* side only. Reading "filled" from the
    prediction would let a model enlarge its own denominator by inventing
    fields.

      * ``transcription`` — truth filled, group ``core`` or ``line_items``.
        The points a model has to earn by reading.
      * ``self_report`` — truth filled, group ``self_report``. Self-description,
        and in ``meta.notes`` human annotator prose. Reported, never averaged
        in. Everything under ``meta.`` lands here, and so does every leaf
        declared in :data:`_SELF_REPORT_LEAVES` wherever it lives.
      * absent — truth not filled. Split three ways: ``hallucinated`` (the
        model produced a value anyway), ``correctly_empty``, and
        ``structural_mismatch``.

    The classes tile the path set: nothing is dropped, it is only stopped from
    inflating a percentage.

    One bounded property separates the last two, and it is the whole worth of a
    class named for agreement: **no path that :func:`field_accuracy` scores
    ``False`` may be counted in** ``correctly_empty``. Whatever is left over
    lands in ``structural_mismatch``, so the tiling survives the bound.

    ``structural_mismatch`` is that residue: neither side filled, and the
    per-path map *still* scores the path wrong. Usually that means the path
    exists on one side only — a line-item row the model invented brings its own
    empty sub-paths, and a row it never produced leaves truth's empty sub-paths
    with nothing on the other side to compare against. **It is not only that.**
    ``LineItem.bbox`` is typed ``list[float] | None``, so a truth ``[]``
    against a predicted ``None`` is two legal, both-unfilled, unequal values on
    a path *both* sides carry, and it lands here as well.

    So the class means: the two sides disagree about whether a path exists, or
    about null versus empty on one they share. It does **not** say the model
    misread a value — values read wrong are counted in ``transcription``, and
    values invented in ``hallucinated``.
    """

    transcription_correct: int = 0
    transcription_total: int = 0
    core_correct: int = 0
    core_total: int = 0
    line_items_correct: int = 0
    line_items_total: int = 0
    self_report_correct: int = 0
    self_report_total: int = 0
    hallucinated: int = 0
    correctly_empty: int = 0
    structural_mismatch: int = 0

    def __add__(self, other: "FieldBreakdown") -> "FieldBreakdown":
        """Fold two receipts' breakdowns together (micro-averaging)."""
        if not isinstance(other, FieldBreakdown):
            return NotImplemented
        return FieldBreakdown(
            *(
                getattr(self, f.name) + getattr(other, f.name)
                for f in fields(self)
            )
        )


def field_breakdown(
    predicted: ReceiptExtraction, truth: ReceiptExtraction
) -> FieldBreakdown:
    """Split one receipt's path set into the classes of :class:`FieldBreakdown`.

    Derived from the same :func:`field_accuracy` map the harness records, over
    the same ``model_dump()`` (python mode) both sides use, so the counts and
    the per-path map can never disagree.

    That shared map is also what bounds ``correctly_empty``: the class is built
    out of paths the map scores ``True``, so it cannot credit a model for a path
    the map calls wrong. The paths that fall out land in
    ``structural_mismatch`` rather than being dropped.
    """
    pred = flatten(predicted.model_dump())
    tru = flatten(truth.model_dump())

    core_c = core_t = li_c = li_t = sr_c = sr_t = hall = empty = struct = 0
    for path, ok in field_accuracy(predicted, truth).items():
        if not _is_filled(tru.get(path)):
            if _is_filled(pred.get(path)):
                hall += 1
            elif ok:
                empty += 1
            else:
                struct += 1
            continue
        group = _group(path)
        if group == "self_report":
            sr_t += 1
            sr_c += int(ok)
        elif group == "line_items":
            li_t += 1
            li_c += int(ok)
        else:
            core_t += 1
            core_c += int(ok)

    return FieldBreakdown(
        transcription_correct=core_c + li_c,
        transcription_total=core_t + li_t,
        core_correct=core_c,
        core_total=core_t,
        line_items_correct=li_c,
        line_items_total=li_t,
        self_report_correct=sr_c,
        self_report_total=sr_t,
        hallucinated=hall,
        correctly_empty=empty,
        structural_mismatch=struct,
    )


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
    # _money_agree (not within_tolerance) so two null totals count as agreement,
    # symmetric with the date field's null==null; a null vs a value still fails.
    total_ok = _money_agree(predicted.totals.total, truth.totals.total)
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
    #: Per-class counts. Defaults to all-zero so ``cmd_calibrate``, which
    #: rebuilds results from JSON for the curve alone, needs no change.
    breakdown: FieldBreakdown = field(default_factory=FieldBreakdown)


@dataclass
class EvalReport:
    """Aggregate over a golden-set run: counts plus the six §16 metrics.

    ``cost_per_receipt`` and the latency percentiles are part of the §16 metric
    set but are not observable through the injected ``pipeline_fn`` (which
    returns only an extraction and a confidence), so they stay ``None`` here and
    are filled in by callers that measure the real pipeline.

    ``n_failed`` / ``failures`` carry the receipts whose pipeline call raised.
    They are *included* in ``n_receipts`` — a receipt the system could not read
    is processed but not correct, never a receipt that quietly left the batch
    (§18: nothing is ever silently dropped).
    """

    n_receipts: int
    n_auto_approved: int
    n_critical_correct: int
    auto_approve_threshold: Decimal

    # §16 metrics, in priority order.
    #
    # ``auto_approval_precision`` is ``None`` -- not ``1.0``, and not ``0.0`` --
    # when nothing was auto-approved. A ratio over zero decisions is undefined,
    # not perfect and not bad, and this project's rule is null over
    # confident-wrong. It was ``1.0``, which meant a run where every receipt
    # failed persisted flawless precision to the committed artifact.
    auto_approval_precision: float | None  # 1
    auto_approval_rate: float             # 2
    critical_field_accuracy: float        # 3
    # Metric 4 is not one number, because it was never measuring one thing.
    # The report stores the aggregate counts and derives the ratios, so the
    # printed block and the JSON cannot disagree, and so `format_breakdown`
    # can render a whole run and a single receipt with the same code.
    breakdown: FieldBreakdown           # 4
    line_item_precision: float            # 5
    line_item_recall: float               # 5
    line_item_f1: float                   # 5
    cost_per_receipt: Decimal | None = None    # 6
    p50_latency_s: float | None = None         # 6
    p95_latency_s: float | None = None         # 6

    #: Receipts whose pipeline call raised, and ``(receipt_id, error)`` for each.
    n_failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    calibration: list[tuple[Decimal, float, float]] = field(default_factory=list)
    results: list[EvalResult] = field(default_factory=list)

    @property
    def transcription_accuracy(self) -> float | None:
        """Metric 4: of the fields this receipt *has*, how many were read.

        ``None`` when the denominator is zero, never ``0.0`` — the same rule
        ``auto_approval_precision`` learned in P8.T3, applied before it can
        bite a second time.
        """
        return ratio(
            self.breakdown.transcription_correct, self.breakdown.transcription_total
        )

    @property
    def transcription_accuracy_core(self) -> float | None:
        return ratio(self.breakdown.core_correct, self.breakdown.core_total)

    @property
    def transcription_accuracy_line_items(self) -> float | None:
        return ratio(self.breakdown.line_items_correct, self.breakdown.line_items_total)

    @property
    def self_report_agreement(self) -> float | None:
        """``meta.*`` — model self-description, reported, never averaged in."""
        return ratio(
            self.breakdown.self_report_correct, self.breakdown.self_report_total
        )

    @property
    def hallucinated_fields(self) -> int:
        return self.breakdown.hallucinated

    @property
    def correctly_empty_fields(self) -> int:
        return self.breakdown.correctly_empty

    @property
    def structural_mismatch_fields(self) -> int:
        """Paths empty on both sides that the per-path map still scores wrong.

        See :class:`FieldBreakdown` for what does and does not land here. It is
        a count for the same reason ``correctly_empty_fields`` is: its
        would-be denominator is a property of the schema, not of the receipt.
        """
        return self.breakdown.structural_mismatch


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
