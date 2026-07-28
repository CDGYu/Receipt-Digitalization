"""Confidence scoring + routing tests (spec §12).

Pure and deterministic: ``score_confidence`` folds the validation report plus
the triage and self-consistency signals into one ``Decimal`` in ``[0, 1]``;
``route`` maps that score (and the error + null-total override) to a status and
a review priority.

Fixtures mirror tests/test_pipeline.py -- a clean, self-consistent extraction
paired with a GOOD-legibility triage scores a perfect 1.000. Validation reports
are built directly from ``Finding`` objects (see report.py / test_rules.py) so
each penalty in the §12 table can be isolated.
"""

from __future__ import annotations

from decimal import Decimal as D

from receipts.extract.schema import (
    ConsistencyResult,
    Legibility,
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.score.confidence import (
    ReceiptStatus,
    explain_confidence,
    route,
    score_confidence,
)
from receipts.validate.report import Finding, Severity, ValidationReport

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _good() -> ReceiptExtraction:
    """A clean extraction with every critical field present (mirrors
    tests/test_pipeline._good())."""
    return ReceiptExtraction(
        merchant=Merchant(name="SUPERMART INC."),
        receipt=ReceiptMeta(date="2026-07-20", currency="PHP"),
        line_items=[
            LineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                     unit_price=D("100.00"), line_total=D("100.00")),
            LineItem(position=1, description_raw="OIL 1L", qty=D("2"),
                     unit_price=D("50.00"), line_total=D("100.00")),
        ],
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D("224.00")),
    )


def _triage(legibility: Legibility = Legibility.GOOD,
            issues: list[str] | None = None) -> TriageResult:
    return TriageResult(legibility=legibility, issues=list(issues or []))


def _clean_report() -> ValidationReport:
    return ValidationReport(findings=[])


def _report(*severities: Severity) -> ValidationReport:
    """A report carrying one finding per requested severity, with unique IDs."""
    return ValidationReport(
        findings=[
            Finding(rule_id=f"R{i:03d}", severity=sev, message="test finding")
            for i, sev in enumerate(severities)
        ]
    )


# --------------------------------------------------------------------------- #
# Clean receipt -> perfect score, auto-approved
# --------------------------------------------------------------------------- #


def test_clean_receipt_scores_perfect_and_auto_approves():
    receipt = _good()
    report = _clean_report()
    triage = _triage()

    score = score_confidence(receipt, report, triage)
    assert score == D("1.000")

    status, priority, _reason = route(score, report, receipt)
    assert status is ReceiptStatus.AUTO_APPROVED
    assert priority == -1


# --------------------------------------------------------------------------- #
# Validation findings
# --------------------------------------------------------------------------- #


def test_error_finding_subtracts_035():
    score = score_confidence(_good(), _report(Severity.ERROR), _triage())
    assert score == D("0.650")


def test_multiple_errors_still_subtract_035_once():
    # "any ERROR finding: -0.35" is a flat penalty, not per-error.
    score = score_confidence(_good(), _report(Severity.ERROR, Severity.ERROR), _triage())
    assert score == D("0.650")


def test_warn_penalty_is_linear_then_caps_at_030():
    receipt = _good()
    # Below the cap: 3 warns -> -0.24.
    assert score_confidence(receipt, _report(*([Severity.WARN] * 3)), _triage()) == D("0.760")
    # At/over the cap: 5 warns -> -0.40 clamped to -0.30.
    assert score_confidence(receipt, _report(*([Severity.WARN] * 5)), _triage()) == D("0.700")


def test_info_findings_do_not_lower_confidence():
    score = score_confidence(_good(), _report(Severity.INFO, Severity.INFO), _triage())
    assert score == D("1.000")


# --------------------------------------------------------------------------- #
# Missing critical fields
# --------------------------------------------------------------------------- #


def test_null_total_subtracts_030():
    receipt = _good()
    receipt.totals.total = None
    assert score_confidence(receipt, _clean_report(), _triage()) == D("0.700")


def test_null_date_subtracts_010():
    receipt = _good()
    receipt.receipt.date = None
    assert score_confidence(receipt, _clean_report(), _triage()) == D("0.900")


def test_null_merchant_name_subtracts_010():
    receipt = _good()
    receipt.merchant.name = None
    assert score_confidence(receipt, _clean_report(), _triage()) == D("0.900")


# --------------------------------------------------------------------------- #
# Triage + extraction-metadata signals
# --------------------------------------------------------------------------- #


def test_legibility_fair_subtracts_010():
    assert score_confidence(_good(), _clean_report(), _triage(Legibility.FAIR)) == D("0.900")


def test_legibility_poor_subtracts_025():
    assert score_confidence(_good(), _clean_report(), _triage(Legibility.POOR)) == D("0.750")


def test_handwritten_subtracts_015():
    receipt = _good()
    receipt.meta.is_handwritten = True
    assert score_confidence(receipt, _clean_report(), _triage()) == D("0.850")


def test_ambiguous_fields_cap_at_020():
    receipt = _good()
    receipt.meta.ambiguous_fields = [f"f{i}" for i in range(6)]  # 6*0.05=0.30 -> cap 0.20
    assert score_confidence(receipt, _clean_report(), _triage()) == D("0.800")


def test_triage_issues_cap_at_010():
    triage = _triage(issues=[f"i{i}" for i in range(5)])  # 5*0.03=0.15 -> cap 0.10
    assert score_confidence(_good(), _clean_report(), triage) == D("0.900")


# --------------------------------------------------------------------------- #
# Self-consistency disputes (only when a consistency result is supplied)
# --------------------------------------------------------------------------- #


def test_consistency_disputes_cap_at_030():
    receipt = _good()
    consistency = ConsistencyResult(runs=3, disputed=[f"p{i}" for i in range(7)])
    # 7*0.06=0.42 -> cap 0.30.
    assert score_confidence(receipt, _clean_report(), _triage(), consistency=consistency) == D(
        "0.700"
    )


def test_consistency_ignored_when_not_provided():
    receipt = _good()
    # The same disputed fields do not count when consistency is omitted.
    assert score_confidence(receipt, _clean_report(), _triage()) == D("1.000")


# --------------------------------------------------------------------------- #
# Clamping, quantization, and the lone bonus
# --------------------------------------------------------------------------- #


def test_score_clamps_to_zero():
    receipt = _good()
    receipt.totals.total = None       # -0.30
    receipt.receipt.date = None       # -0.10
    receipt.merchant.name = None      # -0.10
    receipt.meta.is_handwritten = True  # -0.15
    report = _report(Severity.ERROR, Severity.WARN, Severity.WARN)  # -0.35, -0.16
    score = score_confidence(receipt, report, _triage(Legibility.POOR))  # -0.25
    assert score == D("0.000")  # sum is negative, clamped to the floor


def test_score_is_quantized_to_three_decimals():
    score = score_confidence(_good(), _report(Severity.WARN), _triage())
    assert score == D("0.920")
    assert score.as_tuple().exponent == -3


def test_merchant_prior_verified_adds_bonus():
    receipt = _good()
    report = _report(Severity.WARN)  # -0.08
    # 1.0 - 0.08 + 0.05 = 0.97.
    assert score_confidence(receipt, report, _triage(), merchant_prior_verified=10) == D("0.970")
    # Below the threshold there is no bonus.
    assert score_confidence(receipt, report, _triage(), merchant_prior_verified=9) == D("0.920")


def test_bonus_never_pushes_score_above_one():
    # A clean receipt is already 1.0; the bonus cannot exceed the ceiling.
    assert score_confidence(_good(), _clean_report(), _triage(), merchant_prior_verified=25) == D(
        "1.000"
    )


# --------------------------------------------------------------------------- #
# explain_confidence
# --------------------------------------------------------------------------- #


def test_explain_confidence_lists_contributing_pairs():
    receipt = _good()
    receipt.receipt.date = None
    triage = _triage(Legibility.POOR)
    report = _clean_report()

    pairs = explain_confidence(receipt, report, triage)

    assert all(isinstance(reason, str) and isinstance(pen, D) for reason, pen in pairs)
    reasons = {reason.lower() for reason, _ in pairs}
    assert any("legib" in r for r in reasons)
    assert any("date" in r for r in reasons)
    # The pairs are exactly what built the score (no clamping here: 1 - .25 - .10).
    total = D("1.0") + sum((pen for _, pen in pairs), D("0"))
    assert total == D("0.65")
    assert score_confidence(receipt, report, triage) == D("0.650")


def test_explain_confidence_empty_for_clean_receipt():
    assert explain_confidence(_good(), _clean_report(), _triage()) == []


# --------------------------------------------------------------------------- #
# route
# --------------------------------------------------------------------------- #


def test_route_error_and_null_total_is_urgent():
    receipt = _good()
    receipt.totals.total = None
    report = _report(Severity.ERROR)
    score = score_confidence(receipt, report, _triage())

    status, priority, reason = route(score, report, receipt)
    assert status is ReceiptStatus.NEEDS_REVIEW
    assert priority == 0
    assert reason.startswith("urgent")


def test_route_mid_confidence_is_quick_verify():
    receipt = _good()
    status, priority, reason = route(D("0.700"), _clean_report(), receipt)
    assert status is ReceiptStatus.NEEDS_REVIEW
    assert priority == 2
    assert reason == "quick verify"


def test_route_low_confidence_is_full_rekey():
    receipt = _good()
    status, priority, reason = route(D("0.400"), _clean_report(), receipt)
    assert status is ReceiptStatus.NEEDS_REVIEW
    assert priority == 1
    assert reason == "full re-key"


def test_route_errors_without_null_total_are_not_urgent():
    # An ERROR alone (total present) is not the urgent override; it routes by score.
    receipt = _good()
    report = _report(Severity.ERROR)
    status, priority, _reason = route(D("0.650"), report, receipt)
    assert status is ReceiptStatus.NEEDS_REVIEW
    assert priority == 2  # 0.60 <= 0.65 < 0.85


# --------------------------------------------------------------------------- #
# The thresholds are defined once, in receipts.score.thresholds, and every
# other site (Settings, eval.metrics, the export colour scale) reads from
# there rather than holding its own copy.
# --------------------------------------------------------------------------- #


def test_the_routing_thresholds_are_defined_once():
    from config.settings import Settings
    from eval.metrics import AUTO_APPROVE_THRESHOLD as metrics_threshold
    from receipts.export.xlsx import _CONFIDENCE_FLOOR
    from receipts.score.thresholds import AUTO_APPROVE_THRESHOLD, REVIEW_THRESHOLD

    # ``_env_file=None`` like every other Settings fixture here: this asserts
    # that the *defaults* are wired to one definition, and a developer's .env
    # setting AUTO_APPROVE_THRESHOLD would otherwise fail it for no defect.
    settings = Settings(_env_file=None)
    assert settings.auto_approve_threshold == AUTO_APPROVE_THRESHOLD
    assert settings.review_threshold == REVIEW_THRESHOLD
    assert metrics_threshold == AUTO_APPROVE_THRESHOLD
    assert _CONFIDENCE_FLOOR == REVIEW_THRESHOLD
