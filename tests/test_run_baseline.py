"""One-command baseline runner: settings -> client -> pipeline -> harness.

Offline like the rest of the suite -- an injected FakeVLMClient replays scripted
responses (triage then extraction, mirroring tests/test_pipeline.py) and every
image is synthetic, so no provider or network is touched. The provider-guard
test drives the ``client=None`` path with ``VLM_PROVIDER`` pinned to ``"fake"``
via monkeypatch, proving the runner refuses the response-less default before it
ever reaches the pipeline.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from eval.metrics import EvalReport, FieldBreakdown
from eval.run_baseline import format_breakdown, format_report, run_baseline
from receipts.extract.clients.fake import FakeVLMClient
from receipts.extract.schema import (
    DocumentType,
    Legibility,
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.validate.context import ValidationContext

CTX = ValidationContext(today=date(2026, 7, 26))


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction (mirrors test_pipeline.good())."""
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


def _no_currency() -> ReceiptExtraction:
    """The clean extraction with no currency printed (mirrors PH BIR invoices)."""
    extraction = _good()
    extraction.receipt.currency = None
    return extraction


def _triage() -> TriageResult:
    # GOOD legibility keeps the clean receipt at a perfect confidence so it
    # stays auto-approved under real scoring.
    return TriageResult(document_type=DocumentType.POS_RECEIPT,
                        legibility=Legibility.GOOD,
                        estimated_line_item_count=2)


def _write_png(path: Path) -> None:
    """A synthetic RGB PNG, sized so resize_for_model logs no legibility warning."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(path)


def _write_golden(golden: Path) -> None:
    """One labelled receipt (label + matching image) under a tmp golden dir.

    The optional ``pipeline`` extra (Pillow + HEIF) is needed here and nowhere
    else in this file, so the guard sits on the fixture that needs it. It used
    to open the module::

        pytest.importorskip("PIL")
        pytest.importorskip("pillow_heif")

    which took every test in the file with it — including the
    ``format_breakdown`` tests at the bottom, covering the renderer this module
    shares with ``scripts/try_one_receipt.py``, which needs neither an image
    nor the pipeline. Measured with ``pillow_heif`` blocked: the module-level
    form reported ``1 skipped`` and ran nothing.

    Attached to the fixture rather than listed against test names, because a
    list of names is an enumeration a test added next year escapes: a test that
    builds a golden set is guarded because it built one.

    **What this does not buy, measured.** ``eval.run_baseline`` imports
    ``receipts.pipeline``, whose module-top import graph reaches Pillow (in
    ``receipts.pipeline`` itself) and ``pillow_heif`` (in
    ``receipts.preprocess.image_ops``), so this file cannot be *collected*
    without either — guard or no guard, the narrowed form turns a skip into a
    collection error there. That
    costs nothing today: blocking ``pillow_heif`` and collecting
    ``tests/test_cli_reports.py`` and ``tests/test_preprocess_cv.py`` one at a
    time errors on each, so a run without the extra is already interrupted
    before this file is reached. The guard was buying a tidy skip inside a
    suite that could not start. What the narrowing does buy is that the file no
    longer says the formatting tests need an image library, and that they stop
    being hidden the day that import chain is untangled.
    """
    pytest.importorskip("PIL")
    pytest.importorskip("pillow_heif")

    labels = golden / "labels"
    images = golden / "images"
    labels.mkdir(parents=True)
    images.mkdir(parents=True)
    (labels / "r1.json").write_text(_good().model_dump_json(), encoding="utf-8")
    _write_png(images / "r1.png")


# --------------------------------------------------------------------------- #
# run_baseline: injected client, fully offline
# --------------------------------------------------------------------------- #


def test_run_baseline_with_injected_client_scores_golden_set(tmp_path):
    golden = tmp_path / "golden"
    _write_golden(golden)
    client = FakeVLMClient([_triage(), _good()])

    report = run_baseline(
        golden_dir=golden,
        client=client,
        ctx=CTX,
        results_dir=tmp_path / "results",
    )

    assert isinstance(report, EvalReport)
    assert report.n_receipts == 1
    # The scripted extraction matches the label, so the run is clean end to end.
    assert report.critical_field_accuracy == 1.0
    # Real confidence scoring: the clean receipt scores 1.000 and auto-approves.
    assert report.n_auto_approved == 1
    # A results file was written under the injected results_dir.
    assert list((tmp_path / "results").glob("*.json"))


def test_run_baseline_applies_configured_default_currency(monkeypatch, tmp_path):
    # The label says PHP; the model returns no currency at all (PH BIR invoices
    # never print one). DEFAULT_CURRENCY has to close that gap or every receipt
    # in the corpus scores a currency miss. VLM_PROVIDER is pinned to the
    # response-less "fake" default to prove the injected-client path still needs
    # no real provider even though settings are now read for the currency.
    monkeypatch.setenv("DEFAULT_CURRENCY", "PHP")
    monkeypatch.setenv("VLM_PROVIDER", "fake")
    golden = tmp_path / "golden"
    _write_golden(golden)
    client = FakeVLMClient([_triage(), _no_currency()])

    report = run_baseline(
        golden_dir=golden,
        client=client,
        ctx=CTX,
        results_dir=tmp_path / "results",
    )

    assert report.results[0].field_acc["receipt.currency"] is True


# --------------------------------------------------------------------------- #
# run_baseline: client=None refuses the response-less fake provider
# --------------------------------------------------------------------------- #


def test_run_baseline_refuses_fake_provider(monkeypatch, tmp_path):
    # Pin the resolved provider to "fake" regardless of ambient env / .env.
    monkeypatch.setenv("VLM_PROVIDER", "fake")

    with pytest.raises(RuntimeError, match="(?i)provider"):
        run_baseline(golden_dir=tmp_path, client=None)


# --------------------------------------------------------------------------- #
# format_report
# --------------------------------------------------------------------------- #


def test_format_report_contains_metric_labels():
    report = EvalReport(
        n_receipts=2,
        n_auto_approved=1,
        n_critical_correct=2,
        auto_approve_threshold=D("0.85"),
        auto_approval_precision=1.0,
        auto_approval_rate=0.5,
        critical_field_accuracy=1.0,
        breakdown=FieldBreakdown(
            transcription_correct=19, transcription_total=20,
            core_correct=9, core_total=10,
            line_items_correct=10, line_items_total=10,
            self_report_correct=2, self_report_total=4,
            hallucinated=2, correctly_empty=11,
        ),
        line_item_precision=1.0,
        line_item_recall=1.0,
        line_item_f1=1.0,
    )

    text = format_report(report)

    assert isinstance(text, str) and text.strip()
    for label in (
        "Auto-approval precision",
        "Auto-approval rate",
        "Critical-field accuracy",
        "Transcription accuracy",
        "Line-item F1",
        "Hallucinated fields",
    ):
        assert label in text


def test_format_report_shows_failed_count():
    # A run that partially failed must say so on screen, not just in the JSON.
    report = EvalReport(
        n_receipts=3,
        n_auto_approved=1,
        n_critical_correct=1,
        auto_approve_threshold=D("0.85"),
        auto_approval_precision=1.0,
        auto_approval_rate=1 / 3,
        critical_field_accuracy=1 / 3,
        breakdown=FieldBreakdown(
            transcription_correct=19, transcription_total=20,
            core_correct=9, core_total=10,
            line_items_correct=10, line_items_total=10,
            self_report_correct=2, self_report_total=4,
            hallucinated=2, correctly_empty=11,
        ),
        line_item_precision=1.0,
        line_item_recall=1.0,
        line_item_f1=1.0,
        n_failed=2,
        failures=[("r2", "RuntimeError: boom"), ("r3", "RuntimeError: boom")],
    )

    text = format_report(report)

    assert "Failed" in text
    failed_line = next(line for line in text.splitlines() if "Failed" in line)
    assert "2" in failed_line


# --------------------------------------------------------------------------- #
# format_breakdown
# --------------------------------------------------------------------------- #


def _row(text: str, label: str) -> str:
    """The one rendered line carrying ``label``.

    Raises ``StopIteration`` when the label is absent, so asserting on a row
    also asserts the row exists.
    """
    return next(line for line in text.splitlines() if label in line)


def test_format_breakdown_renders_every_class():
    """Each labelled row carries *its own* value, not merely a value.

    Asserted per row rather than as substrings of the block, because a
    substring test passes under any permutation of its rows. Measured, on
    the substring version this replaces: swapping ``hallucinated`` with
    ``correctly_empty``, and swapping the transcription and core rows, both
    left it green. ``"2" in text`` was satisfied by the self-report row's
    ``25.00%`` whatever the hallucinated count rendered as, and ``"90.00%" in
    text`` did not care which row carried the 90. The two counts are the novel
    part of this design and nothing was checking which one printed where.
    """
    text = format_breakdown(FieldBreakdown(
        transcription_correct=9, transcription_total=10,
        core_correct=5, core_total=5,
        line_items_correct=4, line_items_total=5,
        self_report_correct=1, self_report_total=4,
        hallucinated=2, correctly_empty=11, structural_mismatch=3,
    ))

    assert _row(text, "Transcription accuracy").split()[-2:] == ["90.00%", "(9/10)"]
    assert _row(text, "core:").split()[-2:] == ["100.00%", "(5/5)"]
    assert _row(text, "line items:").split()[-2:] == ["80.00%", "(4/5)"]
    assert _row(text, "Self-report agreement").split()[-2:] == ["25.00%", "(1/4)"]
    assert _row(text, "Hallucinated fields").split()[-1] == "2"
    assert _row(text, "Correctly empty fields").split()[-1] == "11"
    assert _row(text, "Structural mismatches").split()[-1] == "3"


def test_format_breakdown_renders_an_empty_denominator_as_na_not_zero():
    """A ratio over no paths is undefined, not 0% — the P8.T3 rule, on screen.

    Every ratio row is checked, not just one: ``"n/a" in text`` would pass on a
    block where a single row got the ``None`` treatment and the other three
    printed ``0.00%``.
    """
    text = format_breakdown(FieldBreakdown())

    for label in ("Transcription accuracy", "core:", "line items:",
                  "Self-report agreement"):
        assert _row(text, label).split()[-2:] == ["n/a", "(0/0)"]
    assert "0.00%" not in text
