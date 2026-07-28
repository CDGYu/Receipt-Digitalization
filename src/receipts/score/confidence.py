"""Confidence scoring and routing (spec §12).

One pure function folds every uncertainty signal the pipeline has gathered --
the deterministic validation report, the triage classification, the extraction
metadata, and (when it was run) the self-consistency vote -- into a single
confidence ``Decimal`` in ``[0, 1]``. :func:`route` turns that score, plus one
hard override, into a status and a review priority so a review queue can be
worked worst-first.

Design rules that are load-bearing here:

  * Scores are ``Decimal``, never ``float``. This number is compared against
    ``Decimal`` thresholds and persisted at ``numeric(4,3)``; a stray float
    would reintroduce exactly the representation drift the money path avoids.
  * The scorer is pure: no I/O, deterministic, and it never mutates its inputs.
    The same receipt always scores the same.
  * Prefer doubting an extraction to trusting it (the prime directive). Every
    signal only ever *lowers* confidence; the single bonus -- a merchant we have
    verified many times -- is small and additive.

The penalty weights are module constants below. Moving them into
``config/rules.yaml`` -- so a deployment can retune them against the golden set
without a code change, the way the validator's tolerances already do -- is a
deliberate deferred follow-up (calibration, P3.T6). Keeping them here for now
keeps this change self-contained.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from ..extract.schema import (
    ConsistencyResult,
    Legibility,
    ReceiptExtraction,
    TriageResult,
)
from ..validate.report import ValidationReport
from .thresholds import AUTO_APPROVE_THRESHOLD, REVIEW_THRESHOLD

# --------------------------------------------------------------------------- #
# Penalty weights (§12).
#
# DEFERRED FOLLOW-UP: move these into config/rules.yaml (calibration, P3.T6) so
# they can be retuned against the golden set without a code change. Every
# penalty is negative (it lowers confidence); the one bonus is positive.
# --------------------------------------------------------------------------- #

_ONE = Decimal("1")
_ZERO = Decimal("0")
_QUANTUM = Decimal("0.001")

#: Any ERROR finding at all costs a flat penalty -- an error blocks
#: auto-approval regardless of how many rules fired.
PENALTY_ANY_ERROR = Decimal("-0.35")

#: Each WARN finding, summed but bounded: warnings erode trust, they do not (on
#: their own) sink a receipt.
PENALTY_PER_WARN = Decimal("-0.08")
CAP_WARN = Decimal("-0.30")

#: Triage legibility. GOOD and UNREADABLE are intentionally unscored here: GOOD
#: is the no-penalty baseline, and an UNREADABLE document is meant to be caught
#: upstream at triage (is_receipt / document_type gating) rather than scored.
LEGIBILITY_PENALTY: dict[Legibility, Decimal] = {
    Legibility.FAIR: Decimal("-0.10"),
    Legibility.POOR: Decimal("-0.25"),
}

#: Handwriting is materially harder to read than print.
PENALTY_HANDWRITTEN = Decimal("-0.15")

#: Missing critical fields (§12: total, date, merchant name).
PENALTY_TOTAL_NULL = Decimal("-0.30")
PENALTY_DATE_NULL = Decimal("-0.10")
PENALTY_MERCHANT_NULL = Decimal("-0.10")

#: Each field the model itself flagged ambiguous, bounded.
PENALTY_PER_AMBIGUOUS = Decimal("-0.05")
CAP_AMBIGUOUS = Decimal("-0.20")

#: Each field the self-consistency vote could not agree on, bounded. Only
#: applies when a consistency result was actually produced.
PENALTY_PER_DISPUTE = Decimal("-0.06")
CAP_DISPUTE = Decimal("-0.30")

#: Each free-form issue triage raised, bounded.
PENALTY_PER_TRIAGE_ISSUE = Decimal("-0.03")
CAP_TRIAGE_ISSUES = Decimal("-0.10")

#: The lone bonus: a merchant verified at least this many times before is a
#: little more trustworthy.
MERCHANT_PRIOR_MIN = 10
BONUS_MERCHANT_PRIOR = Decimal("0.05")


class ReceiptStatus(str, Enum):
    """Lifecycle state of a receipt (spec §11 schema ``status``).

    Stored in the DB and shown in the review UI, so the string values are
    stable.
    """

    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


def _capped(per_item: Decimal, count: int, cap: Decimal) -> Decimal:
    """A per-item penalty applied ``count`` times, bounded by ``cap``.

    ``per_item`` and ``cap`` are both negative, so the bound is a ``max``.
    """
    if count <= 0:
        return _ZERO
    return max(per_item * count, cap)


def _signals(
    receipt: ReceiptExtraction,
    report: ValidationReport,
    triage: TriageResult | None,
    consistency: ConsistencyResult | None,
    merchant_prior_verified: int,
) -> list[tuple[str, Decimal]]:
    """The ordered ``(reason, signed penalty)`` pairs behind a score.

    Shared by :func:`score_confidence` (which sums them) and
    :func:`explain_confidence` (which returns them verbatim), so the explanation
    can never drift from the number. Only non-zero contributions are emitted.
    """
    signals: list[tuple[str, Decimal]] = []

    # Validation findings.
    if report.has_errors:
        signals.append(("validation errors present", PENALTY_ANY_ERROR))
    warn_count = report.warn_count
    if warn_count:
        signals.append(
            (f"{warn_count} warning finding(s)", _capped(PENALTY_PER_WARN, warn_count, CAP_WARN))
        )

    # Triage: legibility + free-form issues.
    if triage is not None:
        legibility_penalty = LEGIBILITY_PENALTY.get(triage.legibility)
        if legibility_penalty is not None:
            signals.append((f"legibility: {triage.legibility.value}", legibility_penalty))
        issue_count = len(triage.issues)
        if issue_count:
            signals.append(
                (
                    f"{issue_count} triage issue(s)",
                    _capped(PENALTY_PER_TRIAGE_ISSUE, issue_count, CAP_TRIAGE_ISSUES),
                )
            )

    # Extraction metadata.
    if receipt.meta.is_handwritten:
        signals.append(("handwritten receipt", PENALTY_HANDWRITTEN))
    ambiguous_count = len(receipt.meta.ambiguous_fields)
    if ambiguous_count:
        signals.append(
            (
                f"{ambiguous_count} ambiguous field(s)",
                _capped(PENALTY_PER_AMBIGUOUS, ambiguous_count, CAP_AMBIGUOUS),
            )
        )

    # Missing critical fields.
    if receipt.totals.total is None:
        signals.append(("total is missing", PENALTY_TOTAL_NULL))
    if receipt.receipt.date is None:
        signals.append(("date is missing", PENALTY_DATE_NULL))
    if receipt.merchant.name is None:
        signals.append(("merchant name is missing", PENALTY_MERCHANT_NULL))

    # Self-consistency disputes -- only when a vote actually happened.
    if consistency is not None:
        dispute_count = len(consistency.disputed)
        if dispute_count:
            signals.append(
                (
                    f"{dispute_count} disputed field(s) across consistency runs",
                    _capped(PENALTY_PER_DISPUTE, dispute_count, CAP_DISPUTE),
                )
            )

    # The lone bonus.
    if merchant_prior_verified >= MERCHANT_PRIOR_MIN:
        signals.append(("verified merchant prior", BONUS_MERCHANT_PRIOR))

    return signals


def score_confidence(
    receipt: ReceiptExtraction,
    report: ValidationReport,
    triage: TriageResult | None,
    consistency: ConsistencyResult | None = None,
    *,
    merchant_prior_verified: int = 0,
) -> Decimal:
    """Fold every uncertainty signal into one confidence in ``[0, 1]``.

    Starts at ``1.0`` and applies the §12 penalty table (see the module
    constants): a flat penalty for any validation error; bounded per-item
    penalties for warnings, ambiguous fields, consistency disputes, and triage
    issues; fixed penalties for fair/poor legibility, handwriting, and each
    missing critical field (total, date, merchant name); plus a small bonus for
    a repeatedly-verified merchant. The result is clamped to ``[0, 1]`` and
    quantized to three decimals.

    Pure and deterministic; never mutates its inputs. ``consistency`` disputes
    are counted only when a consistency result is supplied.
    """
    total = _ONE
    for _reason, penalty in _signals(
        receipt, report, triage, consistency, merchant_prior_verified
    ):
        total += penalty
    clamped = min(_ONE, max(_ZERO, total))
    return clamped.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def explain_confidence(
    receipt: ReceiptExtraction,
    report: ValidationReport,
    triage: TriageResult | None,
    consistency: ConsistencyResult | None = None,
    *,
    merchant_prior_verified: int = 0,
) -> list[tuple[str, Decimal]]:
    """The ``(reason, signed penalty)`` pairs that made up the score.

    For the review UI: it shows a reviewer precisely why a receipt scored what
    it did. Mirrors :func:`score_confidence` exactly -- same signals, same order
    -- and is empty when nothing lowered (or raised) confidence.
    """
    return _signals(receipt, report, triage, consistency, merchant_prior_verified)


def route(
    confidence: Decimal,
    report: ValidationReport,
    receipt: ReceiptExtraction,
    *,
    auto_threshold: Decimal = AUTO_APPROVE_THRESHOLD,
    review_threshold: Decimal = REVIEW_THRESHOLD,
) -> tuple[ReceiptStatus, int, str]:
    """Map a confidence score to ``(status, review_priority, reason)`` (§12).

    A lower priority number is worked sooner; ``-1`` means no review is needed.

      * ERROR findings *and* a missing total -> ``NEEDS_REVIEW`` priority 0
        (urgent): the receipt both failed validation and lost the one number
        that matters, so it jumps the queue regardless of the score.
      * ``confidence >= auto_threshold`` -> ``AUTO_APPROVED`` (priority -1).
      * ``confidence >= review_threshold`` -> ``NEEDS_REVIEW`` priority 2
        (quick verify).
      * otherwise -> ``NEEDS_REVIEW`` priority 1 (full re-key).
    """
    if report.has_errors and receipt.totals.total is None:
        return (
            ReceiptStatus.NEEDS_REVIEW,
            0,
            "urgent: validation errors and total is missing",
        )
    if confidence >= auto_threshold:
        return (ReceiptStatus.AUTO_APPROVED, -1, f"auto-approved at confidence {confidence}")
    if confidence >= review_threshold:
        return (ReceiptStatus.NEEDS_REVIEW, 2, "quick verify")
    return (ReceiptStatus.NEEDS_REVIEW, 1, "full re-key")
