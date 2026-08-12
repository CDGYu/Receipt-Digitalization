"""Eval metrics + harness tests. Pure and offline — synthetic fixtures only,
no golden data, no network. The pipeline is a stub callable."""

from __future__ import annotations

import json
from decimal import Decimal as D

from eval.harness import run_eval
from eval.metrics import (
    EvalReport,
    EvalResult,
    calibration_curve,
    critical_field_accuracy,
    field_accuracy,
    field_breakdown,
    line_item_f1,
)
from receipts.extract.schema import (
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    TaxBand,
    Totals,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _items() -> list[LineItem]:
    return [
        LineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                 unit_price=D("100.00"), line_total=D("100.00")),
        LineItem(position=1, description_raw="COOKING OIL 1L", qty=D("2"),
                 unit_price=D("50.00"), line_total=D("100.00")),
        LineItem(position=2, description_raw="EGGS DOZEN", qty=D("1"),
                 unit_price=D("80.00"), line_total=D("80.00")),
    ]


def _extraction(
    *,
    total: str | None = "224.00",
    name: str = "SUPERMART INC.",
    date: str = "2026-07-20",
    items: list[LineItem] | None = None,
) -> ReceiptExtraction:
    return ReceiptExtraction(
        merchant=Merchant(name=name),
        receipt=ReceiptMeta(date=date, currency="PHP"),
        line_items=_items() if items is None else items,
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D(total) if total is not None else None),
    )


# --------------------------------------------------------------------------- #
# field_accuracy
# --------------------------------------------------------------------------- #


def test_field_accuracy_total_within_floor_is_true():
    acc = field_accuracy(_extraction(total="949.20"), _extraction(total="949.21"))
    assert acc["totals.total"] is True


def test_field_accuracy_total_beyond_tolerance_is_false():
    acc = field_accuracy(_extraction(total="949.20"), _extraction(total="945.20"))
    assert acc["totals.total"] is False


def test_field_accuracy_text_is_case_and_whitespace_insensitive():
    acc = field_accuracy(
        _extraction(name="Supermart   Inc."), _extraction(name="SUPERMART INC.")
    )
    assert acc["merchant.name"] is True


def test_field_accuracy_none_equals_none():
    acc = field_accuracy(_extraction(total=None), _extraction(total=None))
    assert acc["totals.total"] is True


def test_field_accuracy_path_present_in_one_only_is_false():
    both_items = _items()
    predicted = _extraction(items=both_items)
    truth = _extraction(items=both_items[:2])  # one fewer line item
    acc = field_accuracy(predicted, truth)
    assert acc["line_items[2].line_total"] is False


# --------------------------------------------------------------------------- #
# field_breakdown
# --------------------------------------------------------------------------- #


def test_breakdown_counts_a_filled_truth_path_as_transcription():
    bd = field_breakdown(_extraction(), _extraction())
    # merchant.name, receipt.date, totals.total ... are all filled in truth.
    assert bd.transcription_total > 0
    assert bd.transcription_correct == bd.transcription_total


def test_breakdown_never_counts_an_empty_truth_path_as_transcription():
    # receipt.cashier is None in both fixtures: absent, not transcription.
    bd = field_breakdown(_extraction(), _extraction())
    assert bd.correctly_empty > 0
    assert bd.hallucinated == 0


def test_breakdown_puts_meta_paths_in_self_report_not_transcription():
    bd = field_breakdown(_extraction(), _extraction())
    assert bd.self_report_total > 0
    # No meta path may be inside the transcription denominator.
    assert bd.transcription_total == bd.core_total + bd.line_items_total


def test_breakdown_classifies_by_prefix_not_by_a_list_of_names():
    """A meta path the classifier has never been told about still lands in
    self_report. This is the property review standard 19 asks for: one bounded
    rule, not an enumeration that a new schema field silently escapes."""
    from eval.metrics import _group

    assert _group("meta.some_field_added_next_year") == "meta"
    assert _group("line_items[7].qty") == "line_items"
    assert _group("line_items") == "line_items"
    assert _group("totals.total") == "core"


def test_breakdown_counts_an_invented_value_as_hallucination():
    truth = _extraction()
    predicted = _extraction()
    predicted.receipt.cashier = "MARIA"   # truth leaves this None
    bd = field_breakdown(predicted, truth)
    assert bd.hallucinated == 1


def test_breakdown_treats_an_empty_container_as_absent():
    """flatten emits ``[]`` as a leaf on purpose, so "had none" stays visible.
    But a receipt whose tax_breakdown is empty has no tax breakdown to read, so
    it must not be a point a model can earn.

    Differential, not introspective: it compares two truths differing only in
    that one field. A test that asked the classifier which paths it counted
    would mirror the rule under test and could never fail.

    Measured: core_total is 8 with the empty container and 11 with one band
    (label/base/rate/amount, of which base is None).
    """
    empty_truth = _extraction()
    filled_truth = _extraction()
    filled_truth.totals.tax_breakdown = [
        TaxBand(label="VAT", rate=D("0.12"), amount=D("24.00"))
    ]

    bd_empty = field_breakdown(_extraction(), empty_truth)
    bd_filled = field_breakdown(_extraction(), filled_truth)

    assert bd_empty.core_total < bd_filled.core_total


def test_breakdown_an_extra_predicted_row_is_hallucination_not_a_miss():
    both = _items()
    extra = LineItem(position=3, description_raw="ZZZ NOVELTY WIDGET",
                     qty=D("1"), unit_price=D("5.00"), line_total=D("5.00"))
    bd = field_breakdown(_extraction(items=both + [extra]), _extraction(items=both))
    # The invented row's paths are absent in truth, so they are hallucination.
    assert bd.hallucinated > 0


def test_breakdown_sums_with_plus():
    a = field_breakdown(_extraction(), _extraction())
    b = field_breakdown(_extraction(), _extraction())
    total = a + b
    assert total.transcription_total == a.transcription_total * 2
    assert total.correctly_empty == a.correctly_empty * 2


def test_ratio_is_none_on_an_empty_denominator_never_zero():
    from eval.metrics import ratio

    assert ratio(0, 0) is None
    assert ratio(0, 4) == 0.0
    assert ratio(1, 4) == 0.25


# --------------------------------------------------------------------------- #
# line_item_f1
# --------------------------------------------------------------------------- #


def test_line_item_f1_identical_lists_is_perfect():
    items = _items()
    assert line_item_f1(items, items) == (1.0, 1.0, 1.0)


def test_line_item_f1_extra_predicted_row_lowers_precision_only():
    truth = _items()
    extra = LineItem(position=3, description_raw="ZZZ NOVELTY WIDGET",
                     qty=D("1"), unit_price=D("5.00"), line_total=D("5.00"))
    precision, recall, _f1 = line_item_f1(truth + [extra], truth)
    assert recall == 1.0
    assert precision < 1.0


def test_line_item_f1_empty_lists_are_zero_not_crash():
    assert line_item_f1([], []) == (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# critical_field_accuracy
# --------------------------------------------------------------------------- #


def test_critical_field_accuracy_all_correct():
    assert critical_field_accuracy(_extraction(), _extraction()) is True


def test_critical_field_accuracy_wrong_total_is_false():
    assert critical_field_accuracy(
        _extraction(total="224.00"), _extraction(total="999.00")
    ) is False


def test_critical_field_accuracy_wrong_date_is_false():
    assert critical_field_accuracy(
        _extraction(date="2026-07-20"), _extraction(date="2026-01-01")
    ) is False


def test_critical_field_accuracy_both_null_total_agrees():
    # Two null totals agree, consistent with the date field's null==null.
    assert critical_field_accuracy(
        _extraction(total=None), _extraction(total=None)
    ) is True


def test_critical_field_accuracy_one_null_total_is_false():
    # A null total against a real one is still a mismatch, not agreement.
    assert critical_field_accuracy(
        _extraction(total="224.00"), _extraction(total=None)
    ) is False


# --------------------------------------------------------------------------- #
# calibration_curve
# --------------------------------------------------------------------------- #


def test_calibration_curve_rate_is_monotonic_and_high_conf_error_hurts_precision():
    results = [
        EvalResult(receipt_id="a", confidence=D("0.95"), critical_correct=True,
                   field_acc={}),
        EvalResult(receipt_id="b", confidence=D("0.97"), critical_correct=False,
                   field_acc={}),
        EvalResult(receipt_id="c", confidence=D("0.50"), critical_correct=True,
                   field_acc={}),
    ]
    curve = calibration_curve(results)

    # auto-approve rate never increases as the threshold rises
    rates = [rate for _thr, rate, _prec in curve]
    assert all(a >= b for a, b in zip(rates, rates[1:]))

    # at 0.95 both a and b are approved; b is wrong -> precision drops below 1.0
    at_095 = [prec for thr, _rate, prec in curve if thr == D("0.95")]
    assert at_095 and at_095[0] < 1.0

    # nothing approved above the top confidence -> precision defined as 1.0
    at_100 = [prec for thr, _rate, prec in curve if thr == D("1.0")]
    assert at_100 and at_100[0] == 1.0


# --------------------------------------------------------------------------- #
# run_eval (harness)
# --------------------------------------------------------------------------- #


def test_run_eval_counts_and_writes_results_file(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)

    truth1 = _extraction(total="224.00")
    truth2 = _extraction(total="500.00", name="OTHER STORE")
    (labels / "r1.json").write_text(truth1.model_dump_json(), encoding="utf-8")
    (labels / "r2.json").write_text(truth2.model_dump_json(), encoding="utf-8")

    def pipeline_fn(path):
        if path.stem == "r1":
            return _extraction(total="224.00"), D("0.95")          # correct
        return _extraction(total="499.00", name="OTHER STORE"), D("0.90")  # wrong total

    results_dir = tmp_path / "results"
    report = run_eval(golden, pipeline_fn, results_dir=results_dir)

    assert isinstance(report, EvalReport)
    assert report.n_receipts == 2
    assert report.n_auto_approved == 2          # both >= 0.85
    assert report.n_critical_correct == 1       # only r1 fully correct
    assert report.auto_approval_rate == 1.0
    assert report.auto_approval_precision == 0.5

    written = list(results_dir.glob("*.json"))
    assert len(written) == 1


def test_an_all_failed_run_reports_no_precision_rather_than_a_perfect_one(tmp_path):
    """A run where every receipt failed must not claim perfect precision.

    ``_build_report`` defined ``auto_approval_precision`` as ``1.0`` when
    nothing was auto-approved -- a ratio over zero decisions, asserted as
    certainty. Two guards were built for that value and **neither covers this
    case**: ``calibrate`` refuses a zero-receipt *result set*, and ``eval``
    refuses a zero-receipt *run*. Here ``n_receipts`` is 3, so both stand down,
    and ``n_auto_approved`` is 0 because every receipt failed.

    Measured before the fix: the report said ``1.0`` and
    ``_report_to_dict`` persisted ``1.0`` into the committed JSON artifact --
    a run that read nothing successfully, recorded as flawless.

    ``None``, not ``0.0``: no receipt was approved, so precision is undefined
    rather than bad. This is the project's "null over confident-wrong"
    invariant at the one place that writes the number down, and ADR-0027
    decision 5's rule -- ``null`` must never look like ``0`` -- applied to the
    artifact instead of the screen.

    The console path was already honest (``run_baseline`` prints ``n/a`` when
    nothing was approved); only the persisted value lied.
    """
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)
    for name in ("r1", "r2", "r3"):
        (labels / f"{name}.json").write_text(
            _extraction(total="224.00").model_dump_json(), encoding="utf-8"
        )

    def pipeline_fn(path):
        raise RuntimeError("the provider is down")

    results_dir = tmp_path / "results"
    report = run_eval(golden, pipeline_fn, results_dir=results_dir)

    # The zero-receipt guards cannot fire here: receipts were read, and failed.
    assert report.n_receipts == 3
    assert report.n_failed == 3
    assert report.n_auto_approved == 0

    assert report.auto_approval_precision is None

    written = json.loads(
        next(results_dir.glob("*.json")).read_text(encoding="utf-8")
    )
    assert written["metrics"]["auto_approval_precision"] is None


def test_run_eval_survives_a_failing_receipt(tmp_path):
    # A single receipt that raises must not abort the batch. At minutes per call
    # that would throw away the whole run and write no results file at all --
    # the one artifact §16 treats as non-negotiable.
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)

    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )
    (labels / "r2.json").write_text(
        _extraction(total="500.00", name="OTHER STORE").model_dump_json(),
        encoding="utf-8",
    )

    def pipeline_fn(path):
        if path.stem == "r2":
            raise RuntimeError("connection: Request timed out.")
        return _extraction(total="224.00"), D("0.95")

    results_dir = tmp_path / "results"
    report = run_eval(golden, pipeline_fn, results_dir=results_dir)

    # The run completes and the failure is counted, not dropped.
    assert report.n_receipts == 2
    assert report.n_failed == 1
    assert report.failures == [("r2", "RuntimeError: connection: Request timed out.")]

    # A receipt the system could not read is processed but never a success.
    failed = next(r for r in report.results if r.receipt_id == "r2")
    assert failed.critical_correct is False
    assert failed.confidence == D("0")
    assert failed.field_acc == {}
    assert report.n_critical_correct == 1
    assert report.n_auto_approved == 1  # only r1; confidence 0 can never approve

    # The empty field map keeps the field-accuracy denominator honest: r1 read
    # perfectly, so the aggregate stays 1.0 rather than being halved by a
    # receipt that produced nothing.
    assert report.field_accuracy == 1.0

    # The error detail reaches the committed artifact.
    written = list(results_dir.glob("*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["counts"]["receipts"] == 2
    assert payload["counts"]["failed"] == 1
    assert payload["failures"] == [
        ["r2", "RuntimeError: connection: Request timed out."]
    ]


def test_run_eval_records_an_unreadable_label_as_a_failure(tmp_path):
    # Resilience covers the label load too: corrupt golden data is recorded and
    # the remaining receipts still get scored.
    golden = tmp_path / "golden"
    labels = golden / "labels"
    labels.mkdir(parents=True)

    (labels / "r1.json").write_text(
        _extraction(total="224.00").model_dump_json(), encoding="utf-8"
    )
    (labels / "r2.json").write_text("{not json", encoding="utf-8")

    def pipeline_fn(path):
        return _extraction(total="224.00"), D("0.95")

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert report.n_receipts == 2
    assert report.n_failed == 1
    assert [rid for rid, _detail in report.failures] == ["r2"]
    assert report.n_auto_approved == 1
