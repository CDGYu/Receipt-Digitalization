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

# run_baseline pulls in the pipeline, which needs the optional "pipeline" extras
# (Pillow + HEIF). Skip the whole module rather than erroring at collection.
pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image  # noqa: E402

from eval.metrics import EvalReport  # noqa: E402
from eval.run_baseline import format_report, run_baseline  # noqa: E402
from receipts.extract.clients.fake import FakeVLMClient  # noqa: E402
from receipts.extract.schema import (  # noqa: E402
    DocumentType,
    Legibility,
    LineItem,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.validate.context import ValidationContext  # noqa: E402

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


def _triage() -> TriageResult:
    # GOOD legibility keeps the clean receipt at a perfect confidence so it
    # stays auto-approved under real scoring.
    return TriageResult(document_type=DocumentType.POS_RECEIPT,
                        legibility=Legibility.GOOD,
                        estimated_line_item_count=2)


def _write_png(path: Path) -> None:
    """A synthetic RGB PNG, sized so resize_for_model logs no legibility warning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(path)


def _write_golden(golden: Path) -> None:
    """One labelled receipt (label + matching image) under a tmp golden dir."""
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
        field_accuracy=0.95,
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
        "Field accuracy",
        "Line-item F1",
    ):
        assert label in text
