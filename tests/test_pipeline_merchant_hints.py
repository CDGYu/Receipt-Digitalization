"""What the merchant registry does to a run: hints in, and the merchant out.

The first half is Task 4. Hints reach the extraction prompt AND the prompt hash
rebuilt for the audit -- and the second half of that is the point.
`_attempt_prompt_hash` reconstructs each attempt's prompt from its inputs; if it
is not given the same hints the call used, the stored `prompt_hash` names a
prompt that never existed.

Nothing downstream would notice. The hash is written, the row is valid, every
gate stays green -- and `receipts eval` goes on grouping its results by a prompt
identity that no call ever had. So the test below does not compare the stored
hash against a re-derivation of what the pipeline *should* have sent; it
compares it against the prompt string the client was **actually handed**.

The second half is Task 5, from the marked section down: the merchant resolved
from the completed extraction reaches `receipts.merchant_id`, the count, and --
by way of the normalizer built one stage earlier -- the receipt's currency.
"""

from __future__ import annotations

import io
import json
import logging
import random
import re
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
from receipts.extract.json_io import build_tool_schema  # noqa: E402
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
from receipts.merchants import registry  # noqa: E402
from receipts.persist.models import (  # noqa: E402
    Base,
    ExtractionRun,
    Merchant,
    PassName,
    Receipt,
)
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.pipeline import process_receipt  # noqa: E402
from receipts.validate.context import ValidationContext  # noqa: E402
from receipts.validate.rules import TOTAL_ROW_STRONG, normalize_desc  # noqa: E402

CTX = ValidationContext(today=date(2026, 7, 26))

MERCHANT_NAME = "METRO OIL SUBIC INC."
MERCHANT_HINTS = ["fuel rows are pre-printed; trust the image"]

#: The TIN of the merchant `_register_merchant` puts in the table.
REGISTERED_TAX_ID = "123-456-789-000"

#: A TIN no registered merchant holds, so an extraction carrying it registers a
#: merchant of its own.
FRESH_TAX_ID = "123-456-789"


def _hints() -> P.MerchantHints:
    """Exactly what the pipeline builds from the registered merchant below."""
    return P.MerchantHints(merchant_name=MERCHANT_NAME, hints=list(MERCHANT_HINTS))


# --------------------------------------------------------------------------- #
# The premise: a hinted prompt is a different prompt
# --------------------------------------------------------------------------- #


def test_hints_change_the_extraction_prompt() -> None:
    triage = TriageResult()
    without = P.build_extraction_prompt(triage, None, [])
    with_hints = P.build_extraction_prompt(triage, _hints(), [])

    assert with_hints != without
    assert "METRO OIL SUBIC INC." in with_hints


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


def _register_merchant(
    session_factory,
    hints: list[str],
    *,
    canonical_name: str = MERCHANT_NAME,
    tax_id: str = REGISTERED_TAX_ID,
    default_currency: str | None = None,
) -> uuid.UUID:
    with session_factory() as session:
        merchant = Merchant(
            canonical_name=canonical_name,
            tax_id=tax_id,
            name_variants=[],
            hints=hints,
            default_currency=default_currency,
            receipt_count=0,
        )
        session.add(merchant)
        session.commit()
        return merchant.id


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
    """A merchant registered with no hints extracts as an unknown one does.

    ``build_extraction_prompt`` ignores a ``MerchantHints`` carrying an empty
    hints list (``prompts.py``'s ``if hints and hints.hints``), so the string
    the client is handed is byte-identical to the unhinted prompt and the
    recorded hash is the unhinted hash.
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


# --------------------------------------------------------------------------- #
# Task 5: the merchant sticks -- merchant_id, the count, and the currency
# --------------------------------------------------------------------------- #


def _run(job, client, session_factory, storage, settings):
    return process_receipt(
        job,
        client=client,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
    )


def _settings(default_currency: str | None = None) -> Settings:
    return Settings(
        _env_file=None, max_repair_attempts=1, default_currency=default_currency
    )


def _good_with_tax_id(tax_id: str = FRESH_TAX_ID) -> ReceiptExtraction:
    extraction = _good()
    extraction.merchant.tax_id = tax_id
    return extraction


def _merchants(session_factory) -> list[Merchant]:
    with session_factory() as session:
        return list(session.scalars(select(Merchant)).all())


def test_a_confirmed_extraction_populates_merchant_id(
    session_factory, storage, settings
):
    """Without this, semantic dedupe stays blind and receipt_count stays zero."""
    job = _job(storage)
    client = _RecordingClient([_triage(), _good_with_tax_id()])

    result = _run(job, client, session_factory, storage, settings)
    assert result.failed_stage is None

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.merchant_id is not None
        merchant = session.get(Merchant, receipt.merchant_id)
        assert merchant.tax_id == FRESH_TAX_ID
        assert merchant.receipt_count == 1


def test_an_extraction_with_no_tin_and_no_name_match_gets_no_merchant(
    session_factory, storage, settings
):
    """A guess must not create a merchant, so ``merchant_id`` stays NULL.

    ``register`` requires both a name and a ``tax_id``; ``_good()`` carries only
    the name. NULL here is the correct answer, not a gap to be filled -- the
    alternative is a merchants table seeded from a name.

    **Both conditions are in the name because both are load-bearing.** Drop the
    second and the answer changes: see the test below, where the same TIN-less
    extraction is attributed to a merchant that is already registered.
    """
    job = _job(storage)
    client = _RecordingClient([_triage(), _good()])

    result = _run(job, client, session_factory, storage, settings)
    assert result.failed_stage is None

    with session_factory() as session:
        assert session.get(Receipt, job.id).merchant_id is None
    assert _merchants(session_factory) == []


def test_an_extraction_with_no_tin_is_still_matched_by_name_to_a_known_merchant(
    session_factory, storage, settings
):
    """What a populated ``merchant_id`` does NOT promise: that a TIN was read.

    ``register`` declines without a ``tax_id``, but the ``lookup`` fallback
    matches on the name alone -- so a TIN-less extraction whose name is already
    registered is attributed to that merchant and counts toward it. No merchant
    is *created*; an existing one is matched.

    Task 6 keys semantic dedupe on this column, so the distinction is the point:
    ``merchant_id`` means "resolved to a known merchant", not "identified by
    TIN".
    """
    merchant_id = _register_merchant(session_factory, MERCHANT_HINTS)
    job = _job(storage)
    client = _RecordingClient([_triage(), _good()])

    result = _run(job, client, session_factory, storage, settings)
    assert result.failed_stage is None

    merchants = _merchants(session_factory)
    assert len(merchants) == 1, "a name match must not create a second merchant"
    with session_factory() as session:
        assert session.get(Receipt, job.id).merchant_id == merchant_id
        assert session.get(Merchant, merchant_id).receipt_count == 1


def test_a_different_tin_under_the_same_name_is_a_different_merchant(
    session_factory, storage, settings
):
    """The TIN decides, not the spelling.

    Resolving by name first would attribute this receipt to the incumbent and,
    worse, never register the business that actually issued it -- the
    "permanently unregisterable" merchant ``register``'s docstring refuses to
    create. ``lookup`` cannot tell them apart: both names normalize to one key.
    Only the ``tax_id`` can, so it is asked first.
    """
    incumbent_id = _register_merchant(session_factory, MERCHANT_HINTS)
    job = _job(storage)
    client = _RecordingClient([_triage(), _good_with_tax_id()])

    result = _run(job, client, session_factory, storage, settings)
    assert result.failed_stage is None

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.merchant_id is not None
        assert receipt.merchant_id != incumbent_id
        assert session.get(Merchant, receipt.merchant_id).tax_id == FRESH_TAX_ID
        # The incumbent was not credited with someone else's receipt.
        assert session.get(Merchant, incumbent_id).receipt_count == 0


def test_a_new_spelling_under_a_known_tin_is_learned(
    session_factory, storage, settings
):
    """``confirm`` is the only path that widens matching -- so it must be reached.

    Resolving by name first makes it unreachable: ``confirm`` would only ever be
    called with a spelling ``lookup`` had *already* matched, which its own
    ``key in _keys(merchant)`` guard discards. The registry would never learn a
    second spelling for anybody.
    """
    _register_merchant(session_factory, MERCHANT_HINTS)
    extraction = _good_with_tax_id(REGISTERED_TAX_ID)
    extraction.merchant.name = "Metro Oil Subic Olongapo Branch"
    job = _job(storage)

    result = _run(
        job,
        _RecordingClient([_triage(), extraction]),
        session_factory,
        storage,
        settings,
    )
    assert result.failed_stage is None

    merchants = _merchants(session_factory)
    assert len(merchants) == 1, "a known TIN must not spawn a second merchant"
    assert "Metro Oil Subic Olongapo Branch" in merchants[0].name_variants


def test_the_merchants_currency_outranks_the_system_default(session_factory, storage):
    """§9: receipt code -> merchant default -> system default -> null.

    The receipt printed no code, so the merchant's own currency is the answer.
    """
    _register_merchant(session_factory, MERCHANT_HINTS, default_currency="USD")
    extraction = _good_with_tax_id(REGISTERED_TAX_ID)
    extraction.receipt.currency = None
    job = _job(storage)

    result = _run(
        job,
        _RecordingClient([_triage(), extraction]),
        session_factory,
        storage,
        _settings("PHP"),
    )
    assert result.failed_stage is None

    with session_factory() as session:
        assert session.get(Receipt, job.id).currency == "USD"


def test_an_unrecognised_merchant_currency_falls_through_to_the_system_default(
    session_factory, storage
):
    """The two defaults are handed to ``normalize`` separately, not ``or``-ed.

    ``merchant.default_currency or settings.default_currency`` looks equivalent
    and is not: ``normalize_currency`` walks the chain it is *given*, so a
    merchant row holding a code it does not recognise would end that chain and
    the receipt would store no currency at all -- when the system default was
    sitting right there.
    """
    _register_merchant(session_factory, MERCHANT_HINTS, default_currency="ZZZ")
    extraction = _good_with_tax_id(REGISTERED_TAX_ID)
    extraction.receipt.currency = None
    job = _job(storage)

    result = _run(
        job,
        _RecordingClient([_triage(), extraction]),
        session_factory,
        storage,
        _settings("PHP"),
    )
    assert result.failed_stage is None

    with session_factory() as session:
        assert session.get(Receipt, job.id).currency == "PHP"


def test_a_printed_currency_still_outranks_the_merchants_default(
    session_factory, storage
):
    """The merchant's default is a fallback, never an override.

    Without this the currency step over-reaches: a merchant that usually bills
    in USD would rewrite the PHP this receipt actually printed.
    """
    _register_merchant(session_factory, MERCHANT_HINTS, default_currency="USD")
    job = _job(storage)
    client = _RecordingClient([_triage(), _good_with_tax_id(REGISTERED_TAX_ID)])

    result = _run(job, client, session_factory, storage, _settings("PHP"))
    assert result.failed_stage is None

    with session_factory() as session:
        assert session.get(Receipt, job.id).currency == "PHP"


def test_reprocessing_a_receipt_counts_it_once(session_factory, storage, settings):
    """``receipt_count`` counts receipts, not runs.

    Reprocessing is a first-class path here (a retried job, a re-run after a
    provider outage), and each pass reaches ``_persist_outcome`` with the same
    receipt id. Counting every pass would turn the column into a run counter
    that is named ``receipt_count``.
    """
    job = _job(storage)
    for _ in range(2):
        result = _run(
            job,
            _RecordingClient([_triage(), _good_with_tax_id()]),
            session_factory,
            storage,
            settings,
        )
        assert result.failed_stage is None

    merchants = _merchants(session_factory)
    assert len(merchants) == 1
    assert merchants[0].receipt_count == 1


def test_a_registry_error_before_any_write_never_loses_the_paid_for_extraction(
    session_factory, storage, settings, monkeypatch
):
    """§18, from the expensive side: the extraction has already been paid for.

    The ``merchant`` stage fails loudly for a registry that is down, because at
    that point nothing has been spent. Here the model has already been called.
    Letting a merchants-table failure propagate would send the run to
    ``_persist_failure``, which writes a row of nulls -- the receipt's amounts,
    bought and validated, thrown away over bookkeeping. The receipt is stored
    with ``merchant_id`` NULL instead, and the failure is logged with its
    traceback.

    ``register`` raises here *before touching the database*, so the session is
    never poisoned and ``_resolve_merchant``'s ``session.rollback()`` is a
    no-op. The half that needs the rollback is the test below.
    """

    def boom(*args, **kwargs):
        raise RuntimeError("merchants table gone")

    monkeypatch.setattr(registry, "register", boom)
    job = _job(storage)
    client = _RecordingClient([_triage(), _good_with_tax_id()])

    result = _run(job, client, session_factory, storage, settings)

    assert result.failed_stage is None
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt is not None
        assert receipt.total == D("224.00")
        assert receipt.merchant_id is None


def test_a_failed_merchant_flush_never_loses_the_paid_for_extraction(
    session_factory, storage, settings, monkeypatch
):
    """The same bound, from the only failure that needs the rollback.

    A registry that raises before it writes leaves the session usable, so the
    receipt is stored whether or not ``_resolve_merchant`` rolls back. A
    **flush** that fails does not: the session is left awaiting a rollback, and
    every later statement in ``_persist_outcome`` -- ``save_extraction``
    included -- raises on it. That escapes the persist stage and lands in
    ``_persist_failure``, which writes exactly the row of nulls the bound
    forbids.

    So this poisons ``register`` the way a real constraint violation does: a
    ``Merchant`` with a NULL ``canonical_name``, flushed. Without the rollback
    the stored row comes back ``total=None`` with no line items and no
    ``extraction_runs``; with it, the extraction that was paid for survives and
    only the merchant is lost.
    """

    def poison(session, extraction):
        session.add(Merchant(canonical_name=None, name_variants=[], hints=[]))
        session.flush()  # IntegrityError: merchants.canonical_name is NOT NULL
        raise AssertionError("unreachable: the flush above must fail")

    monkeypatch.setattr(registry, "register", poison)
    job = _job(storage)
    client = _RecordingClient([_triage(), _good_with_tax_id()])

    result = _run(job, client, session_factory, storage, settings)

    assert result.failed_stage is None, "a merchants-table flush took the receipt down"
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt is not None
        assert receipt.total == D("224.00"), "the paid-for extraction was thrown away"
        assert len(receipt.line_items) == 2
        assert receipt.merchant_id is None

        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        assert len(runs) == 2, "the audit trail for two paid calls went with it"

    # Control: the failed flush was rolled back, not committed.
    assert _merchants(session_factory) == []


def test_a_late_resolved_merchant_that_disagrees_on_currency_is_reported(
    session_factory, storage, caplog
):
    """The one hole the ordering leaves, and it is not left silent.

    The normalizer is built at the ``merchant`` stage from the merchant triage
    named; the merchant that is *persisted* comes from the completed
    extraction's TIN, and the two can be different rows. Here triage names a
    merchant nobody has registered, so the receipt normalizes against the system
    default -- and the TIN then resolves to a merchant that bills in USD. The
    stored currency is the one that was actually applied, and the disagreement
    is logged rather than absorbed.
    """
    _register_merchant(
        session_factory,
        [],
        canonical_name="AURORA FUEL DEPOT",
        tax_id=FRESH_TAX_ID,
        default_currency="USD",
    )
    extraction = _good_with_tax_id()
    extraction.receipt.currency = None
    job = _job(storage)

    with caplog.at_level(logging.WARNING, logger="receipts.pipeline"):
        result = _run(
            job,
            _RecordingClient([_triage(), extraction]),
            session_factory,
            storage,
            _settings("PHP"),
        )
    assert result.failed_stage is None

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.currency == "PHP"
        assert (
            session.get(Merchant, receipt.merchant_id).canonical_name
            == "AURORA FUEL DEPOT"
        )

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "the disagreement was absorbed silently"
    message = warnings[-1].getMessage()
    assert str(job.id) in message
    assert "USD" in message and "PHP" in message


# --------------------------------------------------------------------------- #
# Task 6: what the model is actually told
#
# `build_extraction_prompt` composes only the user turn; the numbered rules live
# in `SYSTEM_EXTRACTION`, and the model is handed both in ONE request. So the
# tests below assert against the pair, exactly as the hash tests above already
# model a sent prompt (`user_sent + system_sent`). Asserting against either half
# alone would pass or fail on where a sentence was filed rather than on whether
# the model was told it.
# --------------------------------------------------------------------------- #


def _shipped() -> str:
    """Every word of the extraction request: system turn plus user turn."""
    return P.SYSTEM_EXTRACTION + "\n" + P.build_extraction_prompt(TriageResult(), None, [])


def _blocks(text: str) -> list[str]:
    """Blank-line-separated blocks. Each numbered rule is exactly one block."""
    return [b for b in re.split(r"\n\s*\n", text) if b.strip()]


#: The two settings of the flag. Tolerant of whitespace around the `=` and of
#: case; a JSON-style rewrite (`"is_template_row": true`) does not match.
_FLAG_TRUE = re.compile(r"is_template_row\s*=\s*true", re.IGNORECASE)
_FLAG_FALSE = re.compile(r"is_template_row\s*=\s*false", re.IGNORECASE)

#: A numbered rule of `SYSTEM_EXTRACTION`, e.g. "9. BLANK PRE-PRINTED ROWS.".
_RULE_HEADING = re.compile(r"^\s*\d+\.\s+[A-Z]")

#: Clause split: at a sentence end, and at the start of a list item -- a `-`
#: bullet or an "(a)" verify step. `meta.ambiguous_fields` survives it, there
#: being no space after that dot.
#:
#: The list-item half is load-bearing, not tidiness. The verify steps are
#: separated by newlines and not by periods, so on a sentence-only split the
#: whole (a)..(e) checklist collapses into ONE clause -- putting step (a)'s
#: `is_template_row = true` in the same clause as step (b)'s "could not read"
#: and step (e)'s "unsure". Measured: that made the illegibility bound below
#: fail on correct text.
_CLAUSE = re.compile(r"\.\s+|\n\s*(?=[-(])")

#: What "about illegibility" is keyed on. Stems, so `illegible`, `illegibly`
#: and `illegibility` all match. This is a lexical pin and a synonym walks
#: straight past it -- "smudged", "defeats you", "you cannot make out" are all
#: invisible here. Stated rather than implied; see the bound's docstring.
_ILLEGIBILITY = (
    "illegib",
    "unreadab",
    "cannot read",
    "can not read",
    "could not read",
    "couldn't read",
    "cannot be read",
    "could not be read",
)


def _descriptions(node: object) -> list[str]:
    """Every `description` string anywhere in a JSON Schema."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_descriptions(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_descriptions(item))
    return found


def test_the_extraction_prompt_asks_for_the_buyer_and_names_every_spelling() -> None:
    """Three golden receipts, three different labels for the same block.

    r001 prints `SOLD TO`, r002 prints `SOLD TO` above `Registered Name :`, and
    r003 prints `Sold to:`. A prompt naming one spelling misses the other two,
    and the assertion is case-SENSITIVE for that reason: lowercasing collapses
    two of the three into one string, so a case-insensitive check would pass on
    a prompt that named only one of them.
    """
    shipped = _shipped()
    for spelling in ('"SOLD TO"', '"Sold to:"', '"Registered Name"'):
        assert spelling in shipped, spelling
    assert "buyer.name" in shipped


def test_the_extraction_prompt_separates_the_three_tins_on_the_form() -> None:
    """Merchant header, buyer block, printer footer -- three different numbers.

    All three golden labels record the footer TIN as the PRINTER's. An empty
    buyer block leaves the footer TIN as the nearest TIN-shaped thing on the
    page, so without the warning it is what an obliging model reaches for. The
    warning has to hang off `buyer.tax_id` rather than float loose in the
    request.

    "merchant" and "footer" are deliberately NOT checked. Both are already true
    of `prompts.py` at 5c4a82f, before this task touched it -- rule 1 names the
    merchant, rule 5 excludes "footer text" -- so no change this task can make
    would fail them. "buyer" and "printer" are both false at that revision, so
    those two bind.
    """
    shipped = _shipped()
    lowered = shipped.lower()
    for who in ("buyer", "printer"):
        assert who in lowered, who

    tin_blocks = [b for b in _blocks(shipped) if "buyer.tax_id" in b]
    assert tin_blocks, "nothing in the request says what buyer.tax_id takes"
    assert any("printer" in b.lower() for b in tin_blocks), (
        "the buyer.tax_id instruction never warns off the printer's TIN"
    )


def test_the_extraction_prompt_asks_for_blank_pre_printed_rows() -> None:
    assert "is_template_row" in _shipped()


def test_the_prompt_ties_the_flag_to_the_paper_not_to_the_models_eyesight() -> None:
    """A wrongly flagged purchase is dropped from every total, silently.

    Nothing downstream can tell a row that was blank on the paper from a filled
    row the model could not read, so the distinction has to be drawn here, and
    the unreadable case has to be given somewhere else to go.

    Located by the two SETTINGS of the flag rather than by the prose
    contrasting them. Locating it by `meta.ambiguous_fields` does NOT work, and
    the first version of this test made exactly that mistake: the user turn's
    verify block names that path for an unrelated reason -- every field you were
    unsure about goes there -- and names the flag as well, in step (a), so an
    `any()` over every block mentioning the flag was satisfied by two unrelated
    instructions sharing a block. Measured: with BOTH statements of the contrast
    deleted, that version passed, and so did all 1216 tests.

    TURN-SCOPED AND RULE-ANCHORED, against this section's header rule, which
    says to assert on the shipped pair because filing a sentence in one turn
    rather than the other should not change a verdict. This guarantee is the
    exception, because it is about WHERE the instruction lives: a checklist that
    mentions both settings is not the rule that defines them. Measured: adding
    one plausible clause to verify
    step (a) -- "not even with is_template_row = false" -- let the user turn
    satisfy the round-1 version of this test with BOTH statements of the
    contrast deleted, taking `meta.ambiguous_fields` free from step (e).

    Inside that rule the two settings are bound to their meanings SEPARATELY,
    because a rule can name both and still say the opposite of the truth.
    Measured: swapping `true` and `false` inside the contrast -- telling the
    model a blank row is `false` and an unreadable purchase is `true` -- passed
    every earlier version of this test, while shipping the instruction to flag
    every unreadable purchase.

    The binding on `true` is an EXISTENCE check, not a universal one: rule 9
    legitimately sets `is_template_row = true` a second time, in the sentence
    asking for the untouched rows, and that sentence has no reason to repeat the
    word "blank". The binding on `false` IS universal -- every clause setting
    the flag false must route the row to `meta.ambiguous_fields`.

    Pinning the word "blank" is a word pin, and word pins on prose are what this
    branch has repeatedly been bitten by. Taken deliberately: the alternative is
    not catching an inversion, and a wrongly flagged purchase leaves the
    arithmetic with nothing downstream able to tell.

    THE MIRROR PROPERTY, and the part that actually holds the guarantee shut:

        No clause anywhere in the shipped request may attach
        `is_template_row = true` to illegibility.

    The checks above bind the PRESENCE of a correct statement; they say nothing
    about an incorrect one alongside it. Four measured shapes shipped the
    destructive instruction with 24 passing: widening the anchored sentence to
    "BLANK ON THE PAPER, or written but illegible"; a clean inversion keeping a
    `blank` mention on the true side and `meta.ambiguous_fields` on the false
    side; an extra bullet reading "if you cannot read a row at all, set
    is_template_row = true"; and the same inversion relocated into rule 5, which
    names only `= true` and so never enters `contrast` at all.

    This bound is the "somewhere else to go" test the `false` side already gets,
    run in the other direction, and it is deliberately NOT turn-scoped or
    rule-anchored -- rule 5 is neither the contrast rule nor the user turn, and
    the shape lands there just as happily. It also removes the load from the
    asymmetry above: the `true` side no longer needs clause [3] to lack the word
    "blank" in order to stay honest.

    ITS FLOOR, stated rather than implied. Detecting "about illegibility" needs
    words, so this is a lexical pin exactly like the `"blank"` one. It keys on
    the stems in `_ILLEGIBILITY`: illegib*, unreadab*, and the "cannot/could not
    (be) read" spellings. A synonym evades it -- "smudged", "you cannot make it
    out", "defeats you" -- and so does a paraphrase that never names reading at
    all. It catches the four shapes above and every other shape that says one of
    those words; it is not a proof that the request is free of the instruction.
    """
    rules = [b for b in _blocks(P.SYSTEM_EXTRACTION) if _RULE_HEADING.match(b)]
    contrast = [b for b in rules if _FLAG_TRUE.search(b) and _FLAG_FALSE.search(b)]
    assert contrast, (
        "no numbered rule states both when is_template_row is true and when it "
        "is false; a verify-step checklist naming both is not that rule"
    )
    for block in contrast:
        clauses = _CLAUSE.split(block)
        assert any(_FLAG_TRUE.search(c) and "blank" in c.lower() for c in clauses), (
            "nothing binds is_template_row = true to the row being blank on the "
            "paper, so the setting could mean anything:\n" + block
        )
        set_false = [c for c in clauses if _FLAG_FALSE.search(c)]
        assert set_false, block
        for clause in set_false:
            assert "meta.ambiguous_fields" in clause, (
                "is_template_row = false is set without routing the row to "
                "meta.ambiguous_fields:\n" + clause
            )

    # The mirror property. Whole shipped request: a clause setting the flag true
    # is wrong wherever it lives, and rule 5 is neither the contrast rule nor the
    # user turn.
    for clause in _CLAUSE.split(_shipped()):
        if not _FLAG_TRUE.search(clause):
            continue
        illegibility = [w for w in _ILLEGIBILITY if w in clause.lower()]
        assert not illegibility, (
            "a clause sets is_template_row = true and talks about illegibility "
            f"({', '.join(illegibility)}). A filled row the model cannot read "
            f"is a PURCHASE; flagging it drops it from every total and nothing "
            f"downstream can tell:\n{clause}"
        )


def test_the_blank_row_flag_is_steered_off_the_rows_R052_calls_an_error() -> None:
    """The BIR summary block is pre-printed too, and R052 is an ERROR.

    `NoTotalRowAsLineItem` reads flagged rows as well as unflagged ones -- it is
    the only remaining signal that a printed amount landed in `line_items`
    instead of `totals` -- and one ERROR costs a flat 0.35 against an
    auto-approve threshold of 0.85. So "transcribe every pre-printed row",
    written without naming the items grid, would put an ERROR on every real
    receipt, once per line of its summary block.

    Each label below is checked against `TOTAL_ROW_STRONG` as well as against
    the prompt. Be exact about what that buys, because the first version of this
    docstring was not: it claimed the two "cannot drift apart", and they can.

    It is a guard against REMOVAL, in both directions. Drop a label from the
    prompt and this fails. Drop one from `TOTAL_ROW_STRONG` and this fails too,
    which is the signal that the prompt is now warning about a row R052 no
    longer polices.

    It is NOT a guard against GROWTH, and growth is the direction that re-opens
    the finding, because a new BIR summary label R052 errors on is one the
    prompt never warns about. Measured 2026-08-18: adding `LESS VAT` and
    `TOTAL DUE VAT INCLUSIVE` to `TOTAL_ROW_STRONG` leaves this test passing
    while the prompt names neither.

    A full converse is not written, and the reason is semantic, not budgetary.
    An earlier draft of this docstring said naming all 42 members would cost a
    system prompt "several times" its ~1200-token cap; that was wrong by an
    order of magnitude, measured at roughly +8%. The real objection is that the
    set is not all BIR. It holds `CASH`, `CHANGE DUE`, `TENDERED`, `THANK YOU`
    and `CUSTOMER COPY` -- thermal-POS footer rows. A sentence telling the model
    the BIR summary block "is ... THANK YOU, CUSTOMER COPY" would be wrong
    guidance bought for nothing.

    What stands in for the converse is the cardinality tripwire below. It fires
    when the set changes SIZE, and forces one human decision: is the new member a
    BIR summary label the blank-row rule has to name? A cardinality-preserving
    edit -- swapping one member for another -- passes it untouched. That hole is
    known and parked, not overlooked. Marking a BIR-summary subset in the rule
    set would close it properly -- that is `rules.py`, reported rather than
    reached.
    """
    assert len(TOTAL_ROW_STRONG) == 42, (
        "TOTAL_ROW_STRONG changed size. Decide whether the new or removed member "
        "is a BIR summary label the blank-row rule must name, then update this "
        "count -- growth is the direction the list below cannot see."
    )
    shipped = _shipped()
    for label in (
        "TOTAL SALES",
        "VATABLE SALES",
        "VAT EXEMPT SALES",
        "TOTAL AMOUNT",
        "AMOUNT DUE",
    ):
        assert normalize_desc(label) in TOTAL_ROW_STRONG, label
        assert label in shipped, label

    flag_blocks = [b for b in _blocks(shipped) if "is_template_row" in b]
    assert any("TOTAL SALES" in b for b in flag_blocks), (
        "the summary-block exclusion is not attached to the flag instruction"
    )


def test_no_shipped_instruction_confines_line_items_to_purchases() -> None:
    """The request must not ask for the blank rows and then ask for them back.

    Before Task 6 the system turn said "One object per purchasable line" and the
    user turn's verify step said "every line item you listed is a purchasable
    item, not a subtotal or footer line" -- while the tool schema, built from
    `LineItem.is_template_row`, described a row that is deliberately NOT a
    purchase. All three shipped in the same request.

    Scoped to the extraction request. `TRIAGE_PROMPT` is a separate call that
    builds no line items at all, and its purchasable-rows-only count is correct
    where it stands.

    The guard below is not decoration. Without it this test was vacuable:
    measured, rewording `purchasable` to `purchased` in both places and
    restoring the pre-Task-6 confinement left ZERO matching blocks, so the loop
    never ran and the test passed with the contradiction fully back in the
    shipped request.

    Its floor, stated rather than papered over: the guard fires when the word
    disappears from the request entirely, not when only one of the two blocks is
    reworded. Keying on the constrained thing instead -- blocks naming "line
    item" -- is broader but wrong: rule 1 mentions line items while telling the
    model not to add them up, and has no business naming the flag.
    """
    constraining = [b for b in _blocks(_shipped()) if "purchasable" in b.lower()]
    assert constraining, (
        "no block constrains line_items to purchases at all; the word this test "
        "keys on was reworded, and the loop below would pass vacuously"
    )
    for block in constraining:
        assert "is_template_row" in block, block


def test_every_description_the_model_is_shown_is_inside_the_bundle_hash() -> None:
    """Pydantic `description=` text ships to the model inside the tool schema
    (`build_tool_schema` keeps descriptions -- that is what they are for), so it
    is prompt text built outside `prompts.py`, in violation of that module's own
    first line. Task 1 reworded `is_template_row` and added `Buyer`; runs from
    before and after that change group under an identical hash.
    """
    bundle = P._bundle_text()
    assert P.prompt_bundle_hash() == P.prompt_hash(bundle)

    descriptions = _descriptions(build_tool_schema(ReceiptExtraction))
    assert descriptions, "the tool schema carries no descriptions at all"
    for text in descriptions:
        # The bundle embeds the tool schema as JSON, so a description holding a
        # newline appears escaped. Compare it in the form it is hashed in.
        assert json.dumps(text)[1:-1] in bundle, text[:60]


def test_the_bundle_hash_moves_when_a_description_the_model_sees_changes() -> None:
    """The containment test above would still pass on a bundle nobody hashes.

    Rewording the real field and rebuilding the model is the only check that the
    bundle hash actually moves. The mutation is undone in `finally` and the
    restoration is asserted, because `LineItem` is global to the whole suite.
    """
    field = ExtractedLineItem.model_fields["is_template_row"]
    original = field.description
    before = P.prompt_bundle_hash()
    try:
        field.description = "SENTINEL: a materially different instruction"
        ExtractedLineItem.model_rebuild(force=True)
        ReceiptExtraction.model_rebuild(force=True)
        assert P.prompt_bundle_hash() != before
    finally:
        field.description = original
        ExtractedLineItem.model_rebuild(force=True)
        ReceiptExtraction.model_rebuild(force=True)
    assert P.prompt_bundle_hash() == before
