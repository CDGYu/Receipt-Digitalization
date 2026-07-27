"""Eval metrics + harness tests. Pure and offline — synthetic fixtures only,
no golden data, no network. The pipeline is a stub callable."""

from __future__ import annotations

from decimal import Decimal as D

from eval.harness import run_eval
from eval.metrics import (
    EvalReport,
    EvalResult,
    calibration_curve,
    critical_field_accuracy,
    field_accuracy,
    line_item_f1,
)
from receipts.extract.schema import (
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
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
