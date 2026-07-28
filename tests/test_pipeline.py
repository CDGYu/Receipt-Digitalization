"""M1 pipeline runner tests. Offline: FakeVLMClient replays scripted responses
and every image is synthetic -- no provider, no network.

The runner's call order is load-bearing, so the FakeVLMClient script mirrors it
exactly: response[0] answers the triage call (schema ``TriageResult``) and
response[1] answers the extraction call (schema ``ReceiptExtraction``). A clean
extraction means no repair call fires, so two scripted responses are enough.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

# The preprocess layer needs the optional "pipeline" extras (Pillow + HEIF).
# Skip the whole module rather than erroring at collection when absent.
pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image  # noqa: E402

from eval.harness import run_eval  # noqa: E402
from eval.metrics import EvalReport  # noqa: E402
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
from receipts.pipeline import build_eval_pipeline, prepare_image, run_receipt  # noqa: E402
from receipts.validate.context import ValidationContext  # noqa: E402
from receipts.validate.report import ValidationReport  # noqa: E402

CTX = ValidationContext(today=date(2026, 7, 26))


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction (mirrors test_extractor.good())."""
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
    """The clean extraction with no currency printed on the receipt.

    Mirrors the real corpus: PH BIR invoices never print an ISO code, so the
    configured system default is the only thing that can supply one.
    """
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
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(path)


# --------------------------------------------------------------------------- #
# prepare_image
# --------------------------------------------------------------------------- #


def test_prepare_image_returns_transportable_prepared_image(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)

    prepared = prepare_image(png)

    assert prepared.b64  # non-empty base64 payload
    assert prepared.media_type == "image/jpeg"
    assert prepared.image_hash  # stable digest for cache-keying
    # The extractor turns it into an ImagePart; the payload must survive.
    assert prepared.as_part().b64 == prepared.b64


# --------------------------------------------------------------------------- #
# run_receipt
# --------------------------------------------------------------------------- #


def test_run_receipt_returns_normalized_extraction_and_report(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _good()])

    extraction, report, triage_result = run_receipt(png, client, CTX)

    assert isinstance(extraction, ReceiptExtraction)
    assert isinstance(report, ValidationReport)
    # The triage result is returned too, so callers can score confidence
    # without re-running triage.
    assert isinstance(triage_result, TriageResult)
    # Call order: triage first, extraction second (proves the fake script maps
    # to the real sequence).
    assert len(client.calls) == 2
    assert client.calls[0]["schema"] == "TriageResult"
    assert client.calls[1]["schema"] == "ReceiptExtraction"
    # The scripted extraction survives normalization -- spot-check critical fields.
    assert extraction.merchant.name == "SUPERMART INC."
    assert extraction.receipt.date == "2026-07-20"
    assert extraction.totals.total == D("224.00")
    assert not report.has_errors


def test_run_receipt_applies_configured_default_currency(tmp_path):
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _no_currency()])

    extraction, _report, _triage_result = run_receipt(
        png, client, CTX, default_currency="PHP"
    )

    assert extraction.receipt.currency == "PHP"


def test_run_receipt_without_default_currency_leaves_it_null(tmp_path):
    # No default configured means no currency: null beats a guess.
    png = tmp_path / "receipt.png"
    _write_png(png)
    client = FakeVLMClient([_triage(), _no_currency()])

    extraction, _report, _triage_result = run_receipt(png, client, CTX)

    assert extraction.receipt.currency is None


# --------------------------------------------------------------------------- #
# build_eval_pipeline + eval.harness.run_eval
# --------------------------------------------------------------------------- #


def test_build_eval_pipeline_runs_end_to_end_via_run_eval(tmp_path):
    golden = tmp_path / "golden"
    labels = golden / "labels"
    images = golden / "images"
    labels.mkdir(parents=True)
    images.mkdir(parents=True)

    (labels / "r1.json").write_text(_good().model_dump_json(), encoding="utf-8")
    _write_png(images / "r1.png")

    client = FakeVLMClient([_triage(), _good()])
    pipeline_fn = build_eval_pipeline(client, CTX, images)

    report = run_eval(golden, pipeline_fn, results_dir=tmp_path / "results")

    assert isinstance(report, EvalReport)
    assert report.n_receipts == 1
    assert report.critical_field_accuracy == 1.0
    assert report.line_item_f1 == 1.0
    # The clean receipt scores a perfect 1.000 under real confidence scoring,
    # clearing the auto-approve threshold.
    assert report.n_auto_approved == 1
    assert report.auto_approval_precision == 1.0


def test_build_eval_pipeline_threads_default_currency(tmp_path):
    images = tmp_path / "images"
    _write_png(images / "r1.png")
    client = FakeVLMClient([_triage(), _no_currency()])

    pipeline_fn = build_eval_pipeline(client, CTX, images, default_currency="PHP")
    extraction, _confidence = pipeline_fn(tmp_path / "labels" / "r1.json")

    assert extraction.receipt.currency == "PHP"


def test_build_eval_pipeline_missing_image_raises(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    # No image is written, so the lookup fails before the client is ever called.
    pipeline_fn = build_eval_pipeline(FakeVLMClient([]), CTX, images)

    with pytest.raises(FileNotFoundError):
        pipeline_fn(tmp_path / "labels" / "missing.json")
