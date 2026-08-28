"""Option C: duplicates are allowed -- no semantic (merchant+date+total) merge.

This file used to pin the semantic-dedupe *merge*: a second photo of the same
purchase (same merchant, same date, same total) was flipped to ``rejected`` and
linked to the original. That behaviour was removed on purpose -- a user who
forgets a receipt was already processed and re-uploads it should get a second,
independent receipt rather than a blocked/rejected row.

What is pinned now is the inverse guarantee:

  * a second receipt that matches an existing one on merchant + date + total is
    stored as its **own** receipt, routed on its own confidence, never
    ``rejected`` and never given a ``duplicate_of``;
  * it still gets a full, audited extraction (triage + extract in
    ``extraction_runs``);
  * the original is untouched.

The ledger/export may therefore hold two rows for one purchase. That is the
accepted trade for never blocking a re-upload.
"""

from __future__ import annotations

import io
import random
import uuid
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import select  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts.extract.clients.base import VLMClient, VLMResponse  # noqa: E402
from receipts.extract.clients.limits import reset_vlm_gate  # noqa: E402
from receipts.extract.schema import (  # noqa: E402
    DocumentType,
    Legibility,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.extract.schema import LineItem as ExtractedLineItem  # noqa: E402
from receipts.extract.schema import Merchant as ExtractedMerchant  # noqa: E402
from receipts.ingest.ingest import ReceiptJob  # noqa: E402
from receipts.ingest.storage import LocalStorage, make_image_key  # noqa: E402
from receipts.persist.models import (  # noqa: E402
    Base,
    ExtractionRun,
    Merchant,
    Receipt,
    ReviewTask,
)
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.pipeline import process_receipt  # noqa: E402
from receipts.score.confidence import ReceiptStatus  # noqa: E402
from receipts.validate.context import ValidationContext  # noqa: E402

CTX = ValidationContext(today=date(2026, 7, 26))

MERCHANT_NAME = "METRO OIL SUBIC INC."

#: A TIN no merchant holds yet, so the first run registers a merchant and the
#: second resolves to that same row -- which is what gives both receipts the
#: non-NULL ``merchant_id`` that the old dedupe key needed. Kept so the tests
#: below exercise the *resolved-merchant* case, the one most likely to look like
#: a duplicate, and prove it is still allowed through.
FRESH_TAX_ID = "123-456-789"


# --------------------------------------------------------------------------- #
# Fixtures and fakes
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _fresh_global_gate():
    reset_vlm_gate()
    yield
    reset_vlm_gate()


@pytest.fixture()
def settings() -> Settings:
    """Hermetic settings: a developer's ``.env`` must not steer these tests."""
    return Settings(_env_file=None, max_repair_attempts=1)


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "blobs")


def _png_bytes(seed: int = 0, size: tuple[int, int] = (900, 1400)) -> bytes:
    """A deterministic PNG with enough structure to have a distinctive dHash.

    The seeds used below are far apart perceptually, so even though image dedupe
    no longer rejects anything, the images here are genuinely different photos --
    the tests are about the *semantic* keys, not byte-identical re-uploads.
    """
    rng = random.Random(seed)
    image = Image.new("RGB", size, (240, 240, 240))
    draw = ImageDraw.Draw(image)
    for _ in range(24):
        left = rng.randrange(0, size[0] - 120)
        top = rng.randrange(0, size[1] - 120)
        shade = rng.randrange(0, 200)
        draw.rectangle(
            [left, top, left + rng.randrange(20, 120), top + rng.randrange(20, 120)],
            fill=(shade, shade, shade),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _job(storage: LocalStorage, data: bytes | None = None) -> ReceiptJob:
    receipt_id = uuid.uuid4()
    key = make_image_key(receipt_id, "original")
    storage.put(key, _png_bytes() if data is None else data, "image/png")
    return ReceiptJob(
        id=receipt_id,
        image_key=key,
        source="test",
        original_filename="receipt.png",
        content_type="image/png",
    )


class _Client(VLMClient):
    """A scripted client: one response per call, in order."""

    def __init__(self, script) -> None:
        self.model_id = "fake-vlm"
        self.script = list(script)
        self.calls = 0

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        images,
        schema,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tool_name: str = "record_extraction",
        tool_description: str = "",
    ) -> VLMResponse:
        index = self.calls
        self.calls += 1
        if index >= len(self.script):
            raise AssertionError(f"client exhausted at call {index + 1}")
        return VLMResponse(
            parsed=self.script[index],
            raw={"scripted": index},
            model_id=self.model_id,
            input_tokens=1500,
            output_tokens=400,
            latency_ms=10,
            cost_usd=D("0.01"),
        )


def _triage() -> TriageResult:
    return TriageResult(
        document_type=DocumentType.POS_RECEIPT,
        legibility=Legibility.GOOD,
        estimated_line_item_count=2,
        merchant_name_guess=MERCHANT_NAME,
    )


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction: one attempt, no repair round."""
    return ReceiptExtraction(
        merchant=ExtractedMerchant(name=MERCHANT_NAME),
        receipt=ReceiptMeta(date="2026-07-20", currency="PHP"),
        line_items=[
            ExtractedLineItem(position=0, description_raw="DIESEL", qty=D("1"),
                              unit_price=D("100.00"), line_total=D("100.00")),
            ExtractedLineItem(position=1, description_raw="OIL 1L", qty=D("2"),
                              unit_price=D("50.00"), line_total=D("100.00")),
        ],
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D("224.00")),
    )


def _good_with_tax_id(tax_id: str = FRESH_TAX_ID) -> ReceiptExtraction:
    """``_good()`` plus a TIN, so a merchant is registered and ``merchant_id`` set."""
    extraction = _good()
    extraction.merchant.tax_id = tax_id
    return extraction


def _run(job, client, session_factory, storage, settings):
    return process_receipt(
        job,
        client=client,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
    )


# --------------------------------------------------------------------------- #
# Duplicates are allowed
# --------------------------------------------------------------------------- #


def test_same_merchant_date_and_total_is_stored_as_its_own_receipt(
    session_factory, storage, settings
):
    """Two photographs of one purchase are now two independent receipts.

    Before Option C this was the merge case: the second was flipped to
    ``rejected`` and linked to the first. It must now stand on its own.
    """
    first = _job(storage)
    first_result = _run(
        first, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )
    assert first_result.failed_stage is None
    assert first_result.duplicate_of is None

    second = _job(storage, data=_png_bytes(seed=7))  # a different image
    result = _run(
        second, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )

    assert result.failed_stage is None
    assert result.duplicate_of is None
    assert result.status is ReceiptStatus.AUTO_APPROVED

    with session_factory() as session:
        row = session.get(Receipt, second.id)
        assert row.status is ReceiptStatus.AUTO_APPROVED
        assert row.duplicate_of is None
        assert row.total == D("224.00")
        assert row.txn_date == date(2026, 7, 20)
        assert len(row.line_items) == 2

        # The original is untouched.
        original = session.get(Receipt, first.id)
        assert original.duplicate_of is None
        assert original.status is not ReceiptStatus.REJECTED
        assert original.total == D("224.00")

        # Both resolved to the same merchant -- so the only thing that used to
        # keep them from merging was that the merge no longer happens.
        assert row.merchant_id is not None
        assert row.merchant_id == original.merchant_id
        assert session.scalars(select(Merchant)).all()[0].tax_id == FRESH_TAX_ID


def test_the_second_receipt_still_gets_a_full_audit_trail(
    session_factory, storage, settings
):
    """A re-upload pays for its own extraction, and the calls are recorded.

    Under Option C the model DOES run for the second receipt (there is no
    short-circuit), so its ``extraction_runs`` must hold both the triage and the
    extract call, exactly like any first upload.
    """
    first = _job(storage)
    _run(first, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings)

    second = _job(storage, data=_png_bytes(seed=7))
    result = _run(
        second, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )
    assert result.duplicate_of is None

    with session_factory() as session:
        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == second.id)
        ).all()
    assert len(runs) == 2, "triage and extract both ran for the re-upload"


def test_a_re_upload_is_routed_on_its_own_confidence_not_terminated(
    session_factory, storage
):
    """The second receipt goes through routing like any other.

    With a threshold above the score this extraction earns, the second receipt
    is routed to ``needs_review`` (a normal, actionable outcome) -- it is *not*
    quietly ``rejected`` as a duplicate. It opens its own review task.
    """
    settings = Settings(
        _env_file=None, max_repair_attempts=1, auto_approve_threshold=D("1.01")
    )
    first = _job(storage)
    first_result = _run(
        first, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )
    assert first_result.status is ReceiptStatus.NEEDS_REVIEW

    second = _job(storage, data=_png_bytes(seed=7))
    result = _run(
        second, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )

    assert result.failed_stage is None
    assert result.duplicate_of is None
    assert result.status is ReceiptStatus.NEEDS_REVIEW
    assert result.review_priority >= 0

    with session_factory() as session:
        row = session.get(Receipt, second.id)
        assert row.status is ReceiptStatus.NEEDS_REVIEW
        assert row.duplicate_of is None
        # A re-upload routed to review IS work for a human: it opens its own task.
        tasks = session.scalars(
            select(ReviewTask).where(ReviewTask.receipt_id == second.id)
        ).all()
        assert len(tasks) == 1
