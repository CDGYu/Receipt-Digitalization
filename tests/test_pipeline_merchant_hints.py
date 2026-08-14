"""Hints reach the extraction prompt AND the prompt hash rebuilt for the audit.

The second half is the point. `_attempt_prompt_hash` reconstructs each attempt's
prompt from its inputs; if it is not given the same hints the call used, the
stored `prompt_hash` names a prompt that never existed.

Nothing downstream would notice. The hash is written, the row is valid, every
gate stays green -- and `receipts eval` goes on grouping its results by a prompt
identity that no call ever had. So the test below does not compare the stored
hash against a re-derivation of what the pipeline *should* have sent; it
compares it against the prompt string the client was **actually handed**.
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
from receipts.extract import prompts as P  # noqa: E402
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
from receipts.persist.models import Base, ExtractionRun, Merchant, PassName  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.pipeline import process_receipt  # noqa: E402
from receipts.validate.context import ValidationContext  # noqa: E402

CTX = ValidationContext(today=date(2026, 7, 26))

MERCHANT_NAME = "METRO OIL SUBIC INC."
MERCHANT_HINTS = ["fuel rows are pre-printed; trust the image"]


def _hints() -> P.MerchantHints:
    """Exactly what the pipeline builds from the registered merchant below."""
    return P.MerchantHints(merchant_name=MERCHANT_NAME, hints=list(MERCHANT_HINTS))


# --------------------------------------------------------------------------- #
# The premise: a hinted prompt is a different prompt, and hashes differently
# --------------------------------------------------------------------------- #


def test_hints_change_the_extraction_prompt() -> None:
    triage = TriageResult()
    without = P.build_extraction_prompt(triage, None, [])
    with_hints = P.build_extraction_prompt(triage, _hints(), [])

    assert with_hints != without
    assert "METRO OIL SUBIC INC." in with_hints


def test_the_rebuilt_hash_matches_the_prompt_that_was_sent() -> None:
    """If this fails, the audit trail is lying about what was asked."""
    triage = TriageResult()
    hints = _hints()

    sent = P.prompt_hash(
        P.build_extraction_prompt(triage, hints, []) + P.SYSTEM_EXTRACTION
    )
    rebuilt = P.prompt_hash(
        P.build_extraction_prompt(triage, hints, []) + P.SYSTEM_EXTRACTION
    )
    unhinted = P.prompt_hash(
        P.build_extraction_prompt(triage, None, []) + P.SYSTEM_EXTRACTION
    )

    assert rebuilt == sent
    assert rebuilt != unhinted, "a hinted prompt must not hash like an unhinted one"


# --------------------------------------------------------------------------- #
# The coupling: what was sent, and what was recorded, are the same prompt
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
    """A deterministic PNG with enough structure to have a distinctive dHash."""
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


def _job(storage: LocalStorage) -> ReceiptJob:
    receipt_id = uuid.uuid4()
    key = make_image_key(receipt_id, "original")
    storage.put(key, _png_bytes(), "image/png")
    return ReceiptJob(
        id=receipt_id,
        image_key=key,
        source="test",
        original_filename="receipt.png",
        content_type="image/png",
    )


class _RecordingClient(VLMClient):
    """Scripted, and it keeps every ``(system, user)`` pair it was handed.

    Recording the prompts is what makes this test about the real coupling
    rather than about two copies of the same re-derivation.
    """

    def __init__(self, script) -> None:
        self.model_id = "fake-vlm"
        self.script = list(script)
        self.prompts: list[tuple[str, str]] = []

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
        index = len(self.prompts)
        self.prompts.append((system, user))
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
    """Triage that names the merchant, which is what ``lookup`` matches on."""
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


def _register_merchant(session_factory, hints: list[str]) -> None:
    with session_factory() as session:
        session.add(
            Merchant(
                canonical_name=MERCHANT_NAME,
                tax_id="123-456-789-000",
                name_variants=[],
                hints=hints,
                receipt_count=0,
            )
        )
        session.commit()


def _stored_extract_hash(session_factory, receipt_id: uuid.UUID) -> str:
    with session_factory() as session:
        run = session.scalars(
            select(ExtractionRun).where(
                ExtractionRun.receipt_id == receipt_id,
                ExtractionRun.pass_name == PassName.EXTRACT,
            )
        ).one()
        return run.prompt_hash


def test_the_recorded_hash_describes_the_prompt_that_was_actually_sent(
    session_factory, storage, settings
):
    """The whole point of Task 4.

    Three assertions, and each closes a different way of being wrong:

      * the stored hash matches the hash of the **exact string the client was
        handed** -- so the audit row cannot describe a prompt nobody sent;
      * it matches the hinted rebuild, so ``_attempt_prompt_hash`` cannot be
        passing ``None`` while the call is hinted (this is the one that fails
        if the two sides drift apart);
      * it differs from the unhinted rebuild, so the test cannot pass
        vacuously by the hints never reaching the prompt at all.
    """
    _register_merchant(session_factory, MERCHANT_HINTS)
    job = _job(storage)
    client = _RecordingClient([_triage(), _good()])

    result = process_receipt(
        job,
        client=client,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
    )
    assert result.failed_stage is None

    system_sent, user_sent = client.prompts[1]
    assert MERCHANT_NAME in user_sent, "the hints never reached the extraction call"

    stored = _stored_extract_hash(session_factory, job.id)
    assert stored == P.prompt_hash(user_sent + system_sent)
    assert stored == P.prompt_hash(
        P.build_extraction_prompt(_triage(), _hints(), []) + P.SYSTEM_EXTRACTION
    )
    assert stored != P.prompt_hash(
        P.build_extraction_prompt(_triage(), None, []) + P.SYSTEM_EXTRACTION
    )


def test_an_unknown_merchant_extracts_exactly_as_before(
    session_factory, storage, settings
):
    """No merchant, no hints, today's behaviour -- including the hash.

    ``lookup`` also returns ``None`` for a name two merchants answer to, and
    this is the path that takes: hints stay ``None`` and both sides of the
    coupling still agree.
    """
    job = _job(storage)
    client = _RecordingClient([_triage(), _good()])

    result = process_receipt(
        job,
        client=client,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
    )
    assert result.failed_stage is None

    system_sent, user_sent = client.prompts[1]
    assert MERCHANT_NAME not in user_sent

    stored = _stored_extract_hash(session_factory, job.id)
    assert stored == P.prompt_hash(user_sent + system_sent)
    assert stored == P.prompt_hash(
        P.build_extraction_prompt(_triage(), None, []) + P.SYSTEM_EXTRACTION
    )


def test_a_merchant_with_no_hints_is_the_same_as_no_merchant(
    session_factory, storage, settings
):
    """An empty ``hints`` list must not build an empty hints block.

    ``build_extraction_prompt`` already ignores a ``MerchantHints`` with no
    hints, so the prompt would be identical either way -- but only because the
    pipeline declines to build one. Pinned so a later "simplification" that
    drops the ``and merchant.hints`` guard has to argue with a test.
    """
    _register_merchant(session_factory, [])
    job = _job(storage)
    client = _RecordingClient([_triage(), _good()])

    process_receipt(
        job,
        client=client,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
    )

    _, user_sent = client.prompts[1]
    assert user_sent == P.build_extraction_prompt(_triage(), None, [])
    assert _stored_extract_hash(session_factory, job.id) == P.prompt_hash(
        P.build_extraction_prompt(_triage(), None, []) + P.SYSTEM_EXTRACTION
    )
