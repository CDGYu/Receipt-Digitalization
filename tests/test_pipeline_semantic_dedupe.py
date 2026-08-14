"""Task 6: semantic dedupe -- same merchant, same date, same total.

This is the only stage in the milestone that can do damage that *feels*
irreversible. Everything else is additive: a receipt that gets no hints behaves
exactly as it does today. This one **merges two receipts**, and a false match
marks a genuinely different purchase as a duplicate of another one.

Three properties are pinned here, and each closes a different way of being
wrong:

  * a real re-key of one purchase is caught (the whole point);
  * two receipts whose merchant is **unresolved** are never merged, even though
    the repository function this calls would happily match them -- the pipeline
    is deliberately stricter than
    :func:`~receipts.persist.repository.find_duplicate_by_content`;
  * the duplicate **keeps the extraction that was paid for**. Image dedupe runs
    before the model call and so writes an empty row; this runs after, and by
    then the extraction has been bought, validated and scored. Storing it is
    what makes a wrong merge *readable* rather than merely undoable -- a human
    looking at the rejected row can see the amounts it was merged over.

There is no cost-control claim on this path. Image dedupe saves a model call;
this cannot, because none of the three keys it matches on exists until the
extraction has already been paid for in full.
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
#: non-NULL ``merchant_id`` the dedupe key needs.
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

    The seeds used below are far apart perceptually (measured: 30-43 bits,
    against a dedupe threshold of 5), so **image** dedupe never fires in this
    file. Without that, every test here would pass for the wrong reason.
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


def _good_no_tax_id() -> ReceiptExtraction:
    """``_good()`` with no TIN, so nothing registers and ``merchant_id`` stays NULL.

    ``register`` requires a ``tax_id``, and the ``lookup`` fallback finds nothing
    because no merchant was ever put in the table. Both receipts therefore land
    with an unresolved merchant -- the case the pipeline must refuse to merge.
    """
    extraction = _good()
    extraction.merchant.tax_id = None
    return extraction


def _a_cheaper_purchase() -> ReceiptExtraction:
    """Same merchant, same date, a different total -- and internally consistent.

    Kept arithmetically clean (subtotal 150 + 12% VAT 18 = 168) so it takes the
    same single-attempt path as ``_good()``; a total that merely disagreed with
    its own line items would spend a repair round and test the repair loop
    instead of the dedupe key.
    """
    extraction = _good_with_tax_id()
    extraction.line_items[1].unit_price = D("25.00")
    extraction.line_items[1].line_total = D("50.00")
    extraction.totals = Totals(
        subtotal=D("150.00"), tax=D("18.00"), discount=D("0.00"), total=D("168.00")
    )
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
# The catch
# --------------------------------------------------------------------------- #


def test_a_second_receipt_from_the_same_merchant_date_and_total_is_a_duplicate(
    session_factory, storage, settings
):
    """Two different photographs of one purchase are one purchase.

    Image dedupe cannot see this: the images differ, so their hashes differ.
    Only the extracted merchant, date and total say they are the same receipt --
    and none of the three exists before the model has been paid for.
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
    assert result.duplicate_of == first.id
    assert result.status is ReceiptStatus.REJECTED

    with session_factory() as session:
        row = session.get(Receipt, second.id)
        assert row.status is ReceiptStatus.REJECTED
        assert row.duplicate_of == first.id
        assert row.total is not None, "the paid-for extraction is kept (spec D4)"
        assert row.total == D("224.00")
        assert row.txn_date == date(2026, 7, 20)
        assert len(row.line_items) == 2, "the line items were paid for too"

        # The original is untouched: a merge must never damage the receipt it
        # merged into.
        original = session.get(Receipt, first.id)
        assert original.duplicate_of is None
        assert original.status is not ReceiptStatus.REJECTED
        assert original.total == D("224.00")


def test_the_duplicates_model_calls_stay_in_the_audit_trail(
    session_factory, storage, settings
):
    """A merge that hid the calls it paid for would be unauditable.

    ``extraction_runs`` is where the cost and the raw response live. If the
    duplicate branch skipped them, the money spent on this receipt would be
    invisible and the merge would be a claim with no evidence under it.
    """
    first = _job(storage)
    _run(first, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings)

    second = _job(storage, data=_png_bytes(seed=7))
    result = _run(
        second, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )
    assert result.duplicate_of == first.id

    with session_factory() as session:
        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == second.id)
        ).all()
    assert len(runs) == 2, "triage and extract were both called and both cost money"


def test_a_semantic_duplicate_opens_no_review_task(session_factory, storage, settings):
    """``rejected`` is terminal. A duplicate is not work for a human."""
    first = _job(storage)
    _run(first, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings)

    second = _job(storage, data=_png_bytes(seed=7))
    result = _run(
        second, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings
    )
    assert result.duplicate_of == first.id
    assert result.review_priority == -1

    with session_factory() as session:
        tasks = session.scalars(
            select(ReviewTask).where(ReviewTask.receipt_id == second.id)
        ).all()
    assert tasks == []


# --------------------------------------------------------------------------- #
# The refusals
# --------------------------------------------------------------------------- #


def test_two_unresolved_merchants_are_never_merged(session_factory, storage, settings):
    """The pipeline is stricter than the repository: NULL merchant_id never matches.

    :func:`~receipts.persist.repository.find_duplicate_by_content` permits
    NULL-to-NULL, and that is right for its own contract. It is wrong here.
    Under exact-match-only merchant resolution many early receipts have no
    merchant at all, so two genuinely different shops that happen to share a
    date and a total would be merged -- and the shop is the only one of the
    three keys that distinguishes them.
    """
    first = _job(storage)
    _run(first, _Client([_triage(), _good_no_tax_id()]), session_factory, storage, settings)

    second = _job(storage, data=_png_bytes(seed=9))
    result = _run(
        second, _Client([_triage(), _good_no_tax_id()]), session_factory, storage, settings
    )

    assert result.failed_stage is None
    assert result.duplicate_of is None
    with session_factory() as session:
        assert session.get(Receipt, first.id).merchant_id is None
        row = session.get(Receipt, second.id)
        assert row.merchant_id is None, "the premise: neither receipt has a merchant"
        assert row.duplicate_of is None
        assert row.status is not ReceiptStatus.REJECTED


def test_a_different_total_at_the_same_merchant_and_date_is_not_a_duplicate(
    session_factory, storage, settings
):
    """All three keys are load-bearing. Two purchases in one day are two purchases."""
    first = _job(storage)
    _run(first, _Client([_triage(), _good_with_tax_id()]), session_factory, storage, settings)

    second = _job(storage, data=_png_bytes(seed=7))
    result = _run(
        second, _Client([_triage(), _a_cheaper_purchase()]), session_factory, storage, settings
    )

    assert result.failed_stage is None
    assert result.duplicate_of is None
    with session_factory() as session:
        row = session.get(Receipt, second.id)
        assert row.duplicate_of is None
        assert row.total == D("168.00")
        # The premise: they *did* resolve to the same merchant, so the total is
        # the only thing that kept them apart.
        assert row.merchant_id is not None
        assert row.merchant_id == session.get(Receipt, first.id).merchant_id
        assert session.scalars(select(Merchant)).all()[0].tax_id == FRESH_TAX_ID
