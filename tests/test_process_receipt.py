"""``process_receipt`` -- the one function the queue worker calls (spec §14.10).

Everything here is offline: a scripted in-process client, a temp-directory
:class:`LocalStorage`, and a file-backed SQLite database. No provider, no Redis,
no network.

The load-bearing behaviours pinned down below:

  * **Nothing is silently dropped** (§18). A failure injected into *every* stage
    still leaves a receipt row in a terminal state, ``needs_review``, with the
    failing stage named in the reason and a review task waiting -- one test per
    stage, because "the pipeline is wrapped" is exactly the claim that rots.
  * The stored report and the stored score describe the **same object**:
    validation runs on the normalized extraction, so an ambiguous date that the
    normalizer parks in ``date_raw`` is scored and explained consistently.
  * Money round-trips as ``Decimal`` (ADR-0001) and a full PAN never reaches
    ``extraction_runs.raw_response`` (ADR-0007).
  * ``save_extraction`` does not write findings, so the pipeline calls
    ``save_findings`` itself; one audit row per model call is written too.
"""

from __future__ import annotations

import io
import json
import logging
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
from receipts import pipeline as pipeline_module  # noqa: E402
from receipts.extract.clients.base import (  # noqa: E402
    VLMClient,
    VLMResponse,
    VLMTransientError,
)
from receipts.extract.clients.limits import CostGuard, VLMGate, reset_vlm_gate  # noqa: E402
from receipts.extract.schema import (  # noqa: E402
    ConsistencyResult,
    DocumentType,
    Legibility,
    Merchant,
    PrintType,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.extract.schema import LineItem as ExtractedLineItem  # noqa: E402
from receipts.ingest.ingest import ReceiptJob  # noqa: E402
from receipts.ingest.storage import LocalStorage, make_image_key  # noqa: E402
from receipts.persist.models import (  # noqa: E402
    Base,
    Correction,
    ExtractionRun,
    Receipt,
    ReviewState,
    ReviewTask,
    ValidationFinding,
)
from receipts.persist.repository import (  # noqa: E402
    apply_corrections,
    create_pending_receipt,
    get_receipt,
)
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.pipeline import (  # noqa: E402
    _MAX_REASON_CHARS,
    STAGES,
    ProcessResult,
    _heartbeat_sink,
    _stage,
    fan_out,
    process_batch,
    process_receipt,
)
from receipts.progress import ProgressEvent  # noqa: E402
from receipts.score.confidence import ReceiptStatus  # noqa: E402
from receipts.validate.context import ValidationContext  # noqa: E402

CTX = ValidationContext(today=date(2026, 7, 26))


# --------------------------------------------------------------------------- #
# Fixtures and doubles
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
    """A file-backed SQLite database, so several sessions (and threads) share it."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "blobs")


def _png_bytes(seed: int = 0, size: tuple[int, int] = (900, 1400)) -> bytes:
    """A deterministic PNG with enough structure to have a distinctive dHash.

    A flat image is useless here: every uniform bitmap hashes to the same 64
    zero bits, so two unrelated receipts would look like duplicates.
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


@pytest.fixture(params=["insert", "update"])
def existing_row(request, session_factory):
    """Whether the receipt already has the ``pending`` row ``POST /upload`` writes.

    Returns a callable that takes a job and hands it back, having created that
    row (or not) first, so a test reads ``job = existing_row(_job(storage))``.

    Both branches of ``save_extraction`` must behave identically, and only one of
    them used to be exercised: every stage-failure test built a fresh id, so all
    eight took the **insert** branch -- while production, ever since the pending
    row landed at upload, always takes the **update** branch. That gap is where
    three separate defects hid (a reviewed row silently overwritten, a
    duplicate-linked receipt destroyed on reprocess, and stale
    ``confidence_reasons`` left beside a score the row no longer had).
    """

    def prepare(job: ReceiptJob) -> ReceiptJob:
        if request.param == "update":
            with session_factory() as session:
                create_pending_receipt(session, job)
                session.commit()
        return job

    return prepare


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
    """Scripted client.

    Each script entry is a pydantic model (returned as ``parsed``), a ``str``
    (returned as ``parse_error``), or a ``BaseException`` (raised, which is how
    a stage failure is injected).
    """

    def __init__(self, script, *, raw=None, cost: D = D("0.01")) -> None:
        self.model_id = "fake-vlm"
        self.script = list(script)
        self.raw = raw
        self.cost = cost
        self.calls: list[str] = []

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
        index = len(self.calls)
        self.calls.append(schema.__name__)
        if index >= len(self.script):
            raise AssertionError(f"client exhausted at call {index + 1}")
        item = self.script[index]
        if isinstance(item, BaseException):
            raise item

        response = VLMResponse(
            parsed=None,
            raw={"scripted": index} if self.raw is None else self.raw,
            model_id=self.model_id,
            input_tokens=1500,
            output_tokens=400,
            latency_ms=10,
            cost_usd=self.cost,
        )
        if isinstance(item, str):
            response.parse_error = item
        else:
            response.parsed = item
        return response


def _triage() -> TriageResult:
    return TriageResult(
        document_type=DocumentType.POS_RECEIPT,
        legibility=Legibility.GOOD,
        estimated_line_item_count=2,
    )


def _good() -> ReceiptExtraction:
    """A clean, self-consistent extraction (mirrors tests/test_pipeline.py)."""
    return ReceiptExtraction(
        merchant=Merchant(name="SUPERMART INC."),
        receipt=ReceiptMeta(date="2026-07-20", currency="PHP"),
        line_items=[
            ExtractedLineItem(position=0, description_raw="RICE 5KG", qty=D("1"),
                              unit_price=D("100.00"), line_total=D("100.00")),
            ExtractedLineItem(position=1, description_raw="OIL 1L", qty=D("2"),
                              unit_price=D("50.00"), line_total=D("100.00")),
        ],
        totals=Totals(subtotal=D("200.00"), tax=D("24.00"), discount=D("0.00"),
                      total=D("224.00")),
    )


def _ambiguous_date() -> ReceiptExtraction:
    """Clean apart from a DD/MM-vs-MM/DD date the normalizer must park."""
    extraction = _good()
    extraction.receipt.date = "03/04/2026"
    return extraction


def _broken_totals() -> ReceiptExtraction:
    """Totals that cannot reconcile -- guaranteed ERROR findings."""
    extraction = _good()
    extraction.totals.total = D("999.00")
    return extraction


def _run(job, client, session_factory, storage, settings, **kwargs) -> ProcessResult:
    return process_receipt(
        job,
        client=client,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# The extract ladder, on the path an uploaded receipt actually takes
#
# **This is new surface, not a re-test.** `run_passes` has escalated since
# ADR-0047, but `process_receipt` -- the only function the queue worker calls --
# took a single `client` and called `extract_with_repair` directly. Nothing
# built a second rung for it: `make_pass_clients` had no code caller at all, so
# `VLM_MODEL_EXTRACT_FALLBACK` validated, set cleanly, and did nothing to an
# uploaded receipt.
# --------------------------------------------------------------------------- #


def test_a_timed_out_primary_hands_the_receipt_to_the_fallback(
    session_factory, storage, settings
):
    """Owner ruling 2026-08-25: five minutes on local, then the cloud.

    The deadline is enforced by the *client* -- `VLM_PRIMARY_TIMEOUT_S` builds
    the probe rung with that timeout and `max_retries=0` -- so what reaches this
    layer is an exception. `VLMTransientError` is what `OpenAICompatClient`
    raises for `APITimeoutError`, which is the real shape.
    """
    job = _job(storage)
    primary = _Client([_triage(), VLMTransientError("connection: timed out")])
    fallback = _Client([_good()])

    result = _run(
        job, primary, session_factory, storage, settings,
        extract_fallback_client=fallback,
    )

    # The fallback's extraction is the one that got persisted...
    assert result.failed_stage is None
    assert result.status is ReceiptStatus.AUTO_APPROVED
    # ...and it was actually asked, rather than the run merely surviving.
    assert fallback.calls == ["ReceiptExtraction"]


def test_a_primary_that_transcribed_nothing_escalates_too(
    session_factory, storage, settings
):
    """ADR-0047's original trigger, kept alongside the new one.

    A model that answered *fast* and read *nothing* is not a result. Asserted
    separately from the timeout case because they are different conditions and a
    single `except` would satisfy only one of them.
    """
    job = _job(storage)
    primary = _Client([_triage(), ReceiptExtraction()])
    fallback = _Client([_good()])

    _run(
        job, primary, session_factory, storage, settings,
        extract_fallback_client=fallback,
    )

    assert fallback.calls == ["ReceiptExtraction"]


def test_a_primary_that_read_something_is_kept_and_the_fallback_is_never_asked(
    session_factory, storage, settings
):
    """**The expensive half of the contract, and the easy one to get wrong.**

    Escalating whenever the local model is imperfect would send every receipt to
    the cloud and make the local rung pure cost. The triggers are "raised" and
    "read nothing" -- *not* "read something wrong". Measured consequence, stated
    so nobody is surprised by it: granite returned `2.0000` for a receipt whose
    printed total is 2,000, inside the deadline, and that answer IS KEPT.
    """
    job = _job(storage)
    primary = _Client([_triage(), _good()])
    fallback = _Client([_good()])

    result = _run(
        job, primary, session_factory, storage, settings,
        extract_fallback_client=fallback,
    )

    assert result.failed_stage is None
    assert result.status is ReceiptStatus.AUTO_APPROVED
    assert fallback.calls == [], "the fallback was asked for a receipt the primary read"


def test_with_no_fallback_the_single_rung_keeps_its_repair_budget(
    session_factory, storage, settings
):
    """The unconfigured deployment is untouched by any of this.

    `settings.max_repair_attempts` is 1 by default, so a first extract that
    fails to parse gets one repair. That is the behaviour before the ladder
    existed, and this asserts the no-fallback branch still takes it -- the
    escalating branch deliberately gives the probe `repairs=0`, and it would be
    easy to apply that to everyone.
    """
    job = _job(storage)
    primary = _Client([_triage(), "not json at all", _good()])

    result = _run(job, primary, session_factory, storage, settings)

    assert result.failed_stage is None
    # Three calls: triage, the extract that failed to parse, and its repair.
    assert len(primary.calls) == 3


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_clean_receipt_is_persisted_and_auto_approved(session_factory, storage, settings):
    job = _job(storage)
    client = _Client([_triage(), _good()])

    result = _run(job, client, session_factory, storage, settings)

    assert isinstance(result, ProcessResult)
    assert result.receipt_id == job.id
    assert result.status is ReceiptStatus.AUTO_APPROVED
    assert result.failed_stage is None
    assert client.calls == ["TriageResult", "ReceiptExtraction"]

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt is not None
        assert receipt.status is ReceiptStatus.AUTO_APPROVED
        assert receipt.merchant_name_raw == "SUPERMART INC."
        assert receipt.txn_date == date(2026, 7, 20)
        assert receipt.image_key == job.image_key
        assert receipt.image_phash  # dedupe needs it on every row
        assert len(receipt.line_items) == 2
        # Money survives as an exact Decimal (ADR-0001).
        assert receipt.total == D("224.00")
        assert isinstance(receipt.total, D)
        assert isinstance(receipt.line_items[0].line_total, D)
        # Auto-approved work never reaches the review queue.
        assert session.scalars(select(ReviewTask)).all() == []


def test_a_garbage_currency_never_reaches_the_bounded_column(
    session_factory, storage, settings
):
    """The machine-path bound is unreachable from the pipeline, by construction.

    ``normalize`` replaces ``receipt.currency`` with a whitelisted ISO code or
    ``None`` before anything is saved, so a model emitting free text there
    ends as a persisted receipt with a null currency (these hermetic settings
    carry no ``default_currency``, so nothing is resolved in its place) --
    never as a ``ValueError`` from ``save_extraction``'s bound.
    """
    bad = _good()
    bad.receipt.currency = "PESO PHILIPPINES"
    job = _job(storage)

    result = _run(job, _Client([_triage(), bad]), session_factory, storage, settings)

    assert result.failed_stage is None
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt is not None
        assert receipt.currency is None


def test_a_failed_run_never_leaks_raw_model_text_through_its_reason(
    session_factory, storage, settings
):
    """What escapes a failed run is redacted at the carrier, not just the DB sink.

    The reviewed-row guard quotes ``merchant.name`` raw into its
    ``ValueError`` (that is recorded policy -- the review task should say
    what the refused run produced), and ``_persist_failure`` used to hand
    that text to ``ProcessResult.reason`` unredacted -- from where it reached
    CLI stdout and RQ's result store, while only ``review_tasks.reason`` was
    covered. Two PANs in one value (review standard 9): a scanner's failure
    mode lives between two hits.
    """
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()
    with session_factory() as session:
        apply_corrections(
            session, job.id, {"totals": {"total": "999.99"}}, corrected_by="alice"
        )

    bad = _good()
    bad.merchant.name = "SUPERMART 4111111111111111 AND 5555555555554444"

    result = _run(job, _Client([_triage(), bad]), session_factory, storage, settings)

    assert result.failed_stage == "persist"
    assert "************1111" in result.reason
    assert "************4444" in result.reason
    assert "4111111111111111" not in result.reason
    assert "5555555555554444" not in result.reason
    assert len(result.reason) <= _MAX_REASON_CHARS


def test_the_failure_log_renders_a_redacted_traceback(
    session_factory, storage, settings, caplog
):
    """The log keeps its stack trace and loses the raw model text.

    ``exc_info`` renders the exception's own message into the log, so
    redacting the ``%s`` alone still leaked the guard's ``merchant.name``
    quote into log files. The ruling (2026-08-03): render the traceback,
    redact it as text, drop ``exc_info`` -- full fidelity, nothing raw.
    """
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()
    with session_factory() as session:
        apply_corrections(
            session, job.id, {"totals": {"total": "999.99"}}, corrected_by="alice"
        )

    bad = _good()
    bad.merchant.name = "SUPERMART 4111111111111111 AND 5555555555554444"

    with caplog.at_level(logging.WARNING, logger=process_receipt.__module__):
        _run(job, _Client([_triage(), bad]), session_factory, storage, settings)

    text = caplog.text
    assert "persist" in text
    assert "Traceback (most recent call last)" in text
    assert "************1111" in text
    assert "************4444" in text
    assert "4111111111111111" not in text
    assert "5555555555554444" not in text


def test_the_reason_bound_never_bisects_a_pan_into_the_clear(
    session_factory, storage, settings
):
    """Redaction precedes truncation, so the bound can never cut a PAN open.

    ``_persist_failure`` masks the failure text and only then bounds its
    length. Composed the other way round, a card number lying across the
    bound is cut shorter than the length the scanner recognises, stops
    matching, and its leading digits survive into ``reason`` in the clear --
    the redaction undone by the very step meant to keep the row small. The
    merchant name below puts a PAN astride the bound to hold that order down.
    """
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()
    with session_factory() as session:
        apply_corrections(
            session, job.id, {"totals": {"total": "999.99"}}, corrected_by="alice"
        )

    # Padding sized so the PAN straddles the bound: masked first, its asterisks
    # land on the kept side; truncated first, the surviving head is too short
    # to match the scanner and stays raw.
    bad = _good()
    bad.merchant.name = "A" * 161 + "5555555555554444"

    result = _run(job, _Client([_triage(), bad]), session_factory, storage, settings)

    # The receipt id is the only other digit source in the reason; dropping it
    # keeps a random UUID from ever deciding this assertion.
    scrubbed = result.reason.replace(str(job.id), "")
    assert "55555555" not in scrubbed
    # Not vacuous: the mask itself survives on the kept side of the cut.
    assert "************" in result.reason
    assert len(result.reason) <= _MAX_REASON_CHARS


def test_every_model_call_gets_an_audit_row(session_factory, storage, settings):
    job = _job(storage)
    client = _Client([_triage(), _good()])

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        assert [run.pass_name.value for run in runs] == ["triage", "extract"]
        assert all(run.prompt_hash for run in runs)
        assert all(run.cost_usd == D("0.01") for run in runs)
        assert all(isinstance(run.cost_usd, D) for run in runs)


def test_full_pan_never_reaches_the_raw_response(session_factory, storage, settings):
    # ADR-0007: redaction happens inside save_extraction_run and the pipeline
    # must not route around it.
    job = _job(storage)
    client = _Client([_triage(), _good()], raw={"text": "CARD NO.4111111111111111"})

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        blob = json.dumps([run.raw_response for run in runs])
        assert "4111111111111111" not in blob
        assert "1111" in blob  # the last four survive


def test_findings_are_written_and_a_review_task_is_opened(session_factory, storage, settings):
    job = _job(storage)
    # An unreconcilable total produces ERROR findings, so a repair round runs.
    client = _Client([_triage(), _broken_totals(), _broken_totals()])

    result = _run(job, client, session_factory, storage, settings)

    assert result.status is ReceiptStatus.NEEDS_REVIEW
    with session_factory() as session:
        findings = session.scalars(
            select(ValidationFinding).where(ValidationFinding.receipt_id == job.id)
        ).all()
        # save_extraction does NOT write findings; the pipeline must.
        assert findings
        # Rule ids are stored verbatim and never renumbered.
        assert all(finding.rule_id.startswith("R") for finding in findings)

        task = session.scalars(select(ReviewTask)).one()
        assert task.receipt_id == job.id
        assert task.priority >= 0


def test_expected_buyer_reaches_the_rules(settings, session_factory, storage):
    """EXPECTED_BUYER_NAME must survive all the way to a persisted finding.

    The chain is Settings -> the context ``process_receipt`` builds -> the
    per-attempt context ``_evaluate`` builds -> ``validate()`` ->
    ``validation_findings``. Every link lives in a different module and the rule
    unit tests can see none of them: R014/R015 were inert on every real run
    while ``tests/test_rules.py`` was entirely green.

    The ``settings`` fixture is ``Settings(_env_file=None, ...)``, so a
    developer's own ``.env`` cannot steer this either way.
    """
    job = _job(storage)
    configured = settings.model_copy(update={"expected_buyer_name": "IDEAL SOURCE"})
    process_receipt(job, client=_Client([_triage(), _good()]), storage=storage,
                    session_factory=session_factory, settings=configured)
    with session_factory() as session:
        ids = set(session.scalars(select(ValidationFinding.rule_id)))
    assert "R014" in ids   # _good() carries no buyer


def test_repair_resolved_findings_are_kept_as_history(session_factory, storage, settings):
    """Findings accumulate across passes via ``resolved_by_repair``.

    The best attempt here is the repair, which is clean -- so the only findings
    worth storing are the originals the repair fixed. Storing them (rather than
    letting the successful pass erase the record) is what makes the repair loop
    measurable later.
    """
    job = _job(storage)
    client = _Client([_triage(), _broken_totals(), _good()])

    result = _run(job, client, session_factory, storage, settings)

    assert result.status is ReceiptStatus.AUTO_APPROVED
    with session_factory() as session:
        findings = session.scalars(
            select(ValidationFinding).where(ValidationFinding.receipt_id == job.id)
        ).all()
        assert findings
        assert all(finding.resolved_by_repair for finding in findings)

        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        assert [run.pass_name.value for run in runs] == ["triage", "extract", "repair"]
        # Each pass logs the hash of the prompt it actually used, so the repair
        # row must not simply repeat the extraction prompt's hash.
        assert runs[1].prompt_hash != runs[2].prompt_hash


def test_the_pipeline_keeps_the_best_attempt_when_the_repair_is_worse(
    session_factory, storage, settings
):
    """P2.T4's acceptance: proven UNDER THE PIPELINE, not just in isolation.

    `extract_with_repair` promises the best attempt rather than the last, and
    `tests/test_extractor.py` pins the adversarial direction by calling it
    directly. Nothing drove a worse repair through `process_receipt`, so the
    guarantee the pipeline depends on was asserted by no test that persists a
    row -- ISSUE-025, and `git grep -in worse -- tests/test_process_receipt.py`
    returned nothing when it was filed.

    The repair here is strictly worse than the extract it was asked to fix: the
    same unreconcilable total, plus a quantity that no longer multiplies out.
    So the row that lands must carry the EXTRACT's values.
    """
    worse = _broken_totals()
    worse.line_items[0].qty = D("7")  # 7 x 100.00 != 100.00 -- a second ERROR
    job = _job(storage)
    client = _Client([_triage(), _broken_totals(), worse])

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        # **The repair must actually have been attempted.** Without this the
        # test passes on a pipeline that never repairs at all: the extract's
        # values would survive for the wrong reason, and the selection this
        # exists to pin would never run.
        runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.receipt_id == job.id)
        ).all()
        assert [run.pass_name.value for run in runs] == ["triage", "extract", "repair"]

        receipt = get_receipt(session, job.id)
        by_position = sorted(receipt.line_items, key=lambda item: item.position)
        # Asserted on the PERSISTED row rather than on the returned outcome:
        # what the pipeline reports and what it writes are two claims, and this
        # issue is about the one that survives the process.
        assert by_position[0].qty == D("1")


# --------------------------------------------------------------------------- #
# OCR grounding (P2.T2) -- R060/R061 finally have a text source
# --------------------------------------------------------------------------- #


class _Layer:
    """What a reader returns. Only `.text` is read by the grounding helper."""

    def __init__(self, text: str) -> None:
        self.text = text


def _grounded(settings):
    """`settings` with the pass switched on. Off is the shipped default."""
    return settings.model_copy(update={"ocr_grounding_enabled": True})


def _fired(session_factory, receipt_id) -> set[str]:
    with session_factory() as session:
        return {
            finding.rule_id
            for finding in session.scalars(
                select(ValidationFinding).where(
                    ValidationFinding.receipt_id == receipt_id
                )
            ).all()
        }


def test_a_text_layer_without_the_total_makes_R060_fire(
    session_factory, storage, settings
):
    """The discriminating direction, and the only one that proves the wiring.

    R060 SKIPS when `ctx.ocr_text` is empty and PASSES when the total is found,
    and `validator.py` renders those identically -- no finding either way. So a
    test that grounds successfully cannot tell a wired pipeline from an unwired
    one. This supplies a layer that does NOT contain the total: the rule can
    only fire if something actually put text on the context.
    """
    job = _job(storage)
    client = _Client([_triage(), _good()])

    _run(
        job, client, session_factory, storage, _grounded(settings),
        ocr_reader=lambda b64: _Layer("nothing resembling a receipt"),
    )

    assert "R060" in _fired(session_factory, job.id)


def test_a_text_layer_containing_the_total_leaves_R060_silent(
    session_factory, storage, settings
):
    """The other end. Read WITH the test above: alone it proves nothing."""
    job = _job(storage)
    client = _Client([_triage(), _good()])

    _run(
        job, client, session_factory, storage, _grounded(settings),
        ocr_reader=lambda b64: _Layer("SUPERMART INC.\nTOTAL 224.00"),
    )

    assert "R060" not in _fired(session_factory, job.id)


def test_grounding_is_off_by_default_and_the_reader_is_never_asked(
    session_factory, storage, settings
):
    """Off means the pass does not run, not that it runs and finds nothing.

    Asserted on the READER rather than on the findings: with grounding off R060
    skips and produces no finding, which is indistinguishable from grounding
    successfully. The call count is the only thing that separates them -- the
    same confusion this whole task exists to end.
    """
    calls: list[str] = []

    def _recording(b64: str) -> _Layer:
        calls.append(b64)
        return _Layer("nothing resembling a receipt")

    job = _job(storage)
    client = _Client([_triage(), _good()])

    # `settings` unmodified: `ocr_grounding_enabled` defaults False.
    _run(job, client, session_factory, storage, settings, ocr_reader=_recording)

    assert calls == []
    assert "R060" not in _fired(session_factory, job.id)


def test_a_reader_that_raises_costs_the_grounding_and_not_the_receipt(
    session_factory, storage, settings
):
    """OCR runs on a photograph somebody uploaded; it must not lose the receipt.

    A malformed image, a missing optional extra or a recogniser that dies leaves
    the run to finish with the two rules skipping -- exactly what they did before
    this pass existed. The failure degrades to the status quo.
    """

    def _explodes(b64: str):
        raise RuntimeError("no recogniser here")

    job = _job(storage)
    client = _Client([_triage(), _good()])

    result = _run(
        job, client, session_factory, storage, _grounded(settings),
        ocr_reader=_explodes,
    )

    assert result.status is ReceiptStatus.AUTO_APPROVED
    assert "R060" not in _fired(session_factory, job.id)


def test_the_layer_never_reaches_the_callers_context(
    session_factory, storage, settings
):
    """A context handed in is not written to.

    `run_receipt` reuses one context across receipts, so a pass that assigned
    `ocr_text` onto the caller's object would ground receipt two against receipt
    one's image. The helper returns a replacement; this pins that the object
    passed in is untouched. Calls `process_receipt` directly because `_run`
    supplies its own `ctx`.
    """
    job = _job(storage)
    caller_ctx = ValidationContext(today=date(2026, 7, 26))

    process_receipt(
        job,
        client=_Client([_triage(), _good()]),
        storage=storage,
        session_factory=session_factory,
        ctx=caller_ctx,
        settings=_grounded(settings),
        ocr_reader=lambda b64: _Layer("SUPERMART INC. TOTAL 224.00"),
    )

    assert caller_ctx.ocr_text is None


def test_reprocessing_a_persisted_job_updates_the_row_in_place(
    session_factory, storage, settings
):
    """A re-run of an id that already has a row must not vanish -- or duplicate.

    ``save_extraction`` is update-or-insert (P4.T3): a pending row written at
    upload, or a previous run's row, is updated rather than re-inserted, so a
    retry writes fresh data over the old row instead of colliding on the
    primary key. That collision used to route a retry to ``needs_review``
    purely because it had already been processed once -- an update in place is
    strictly better, since the second run's own result (here, a clean
    auto-approval) is what ends up stored. (``receipts reprocess <id>`` is the
    operator-facing form of this same re-run; it adds a status gate -- refusing
    an ``auto_approved`` row without ``--force`` -- on top of the refusal
    exercised here, which no flag can lift, see
    ``test_a_worker_run_never_overwrites_a_reviewed_receipt``.)
    """
    job = _job(storage)
    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    again = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    assert again.status is ReceiptStatus.AUTO_APPROVED
    with session_factory() as session:
        rows = session.scalars(select(Receipt).where(Receipt.id == job.id)).all()
        assert len(rows) == 1


# --------------------------------------------------------------------------- #
# The raw-report / normalized-extraction reconciliation
# --------------------------------------------------------------------------- #


def test_report_and_score_describe_the_same_normalized_extraction(
    session_factory, storage, settings
):
    """An ambiguous date is parked by ``normalize``; validation must see that.

    Validating the *raw* extraction would report R030 ("not ISO 8601") -- an
    ERROR that both triggers a pointless repair round and leaves the stored
    score's date-null penalty unexplained by the stored report. Validating the
    normalized extraction instead yields R011 at INFO ("acceptable if the
    printed date is genuinely ambiguous"), which is what the persisted row
    actually looks like.
    """
    job = _job(storage)
    client = _Client([_triage(), _ambiguous_date()])

    result = _run(job, client, session_factory, storage, settings)

    # No ERROR, so no repair round was spent second-guessing a parked date.
    assert client.calls == ["TriageResult", "ReceiptExtraction"]

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.txn_date is None
        assert receipt.date_raw == "03/04/2026"

        rule_ids = {
            finding.rule_id
            for finding in session.scalars(
                select(ValidationFinding).where(ValidationFinding.receipt_id == job.id)
            )
        }
        assert "R011" in rule_ids  # explains the missing date
        assert "R030" not in rule_ids  # never validated the pre-normalization value

    # Only the date-null penalty (-0.10) applies, so the receipt still clears
    # the auto-approve threshold -- the score and the report agree.
    assert result.confidence == D("0.900")
    assert result.status is ReceiptStatus.AUTO_APPROVED


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #


def test_duplicate_image_is_linked_without_spending_a_model_call(
    session_factory, storage, settings, existing_row
):
    data = _png_bytes()
    first = _run(existing_row(_job(storage, data)), _Client([_triage(), _good()]),
                 session_factory, storage, settings)

    second_job = existing_row(_job(storage, data))
    second_client = _Client([])  # any model call would raise
    second = _run(second_job, second_client, session_factory, storage, settings)

    assert second_client.calls == []
    assert second.duplicate_of == first.receipt_id
    assert second.status is ReceiptStatus.REJECTED

    with session_factory() as session:
        row = session.get(Receipt, second_job.id)
        assert row.duplicate_of == first.receipt_id
        # The *row* is terminal, not just the returned result -- over a pending
        # row that means save_extraction's update branch actually applied the
        # rejected status rather than leaving the upload's `pending`.
        assert row.status is ReceiptStatus.REJECTED
        assert row.image_phash
        # A duplicate is terminal and must not clutter the review queue.
        assert session.scalars(select(ReviewTask)).all() == []


def test_reprocessing_a_receipt_that_already_has_a_duplicate_keeps_it_intact(
    session_factory, storage, settings
):
    """``A`` processed, ``B`` uploaded as the same image, then ``A`` re-run.

    Dedupe used to exclude only ``job.id``, and it ran even for a receipt that
    already held an extraction -- so the reprocessed original matched the copy
    pointing *at* it and was itself marked a duplicate of it: ``A`` became
    ``rejected`` with no total, no merchant and no line items, ``duplicate_of =
    B``. That is the ``A <-> B`` cycle ``mark_duplicate``'s docstring promises
    cannot happen, and since both rows are then ``rejected`` **both** drop out
    of ``GET /export/xlsx`` by default: the transaction leaves the ledger with
    nothing left pointing at it.
    """
    data = _png_bytes()
    original = _job(storage, data)
    first = _run(original, _Client([_triage(), _good()]), session_factory, storage, settings)
    assert first.status is ReceiptStatus.AUTO_APPROVED

    copy = _run(_job(storage, data), _Client([]), session_factory, storage, settings)
    assert copy.duplicate_of == original.id

    again = _run(original, _Client([_triage(), _good()]), session_factory, storage, settings)

    assert again.status is ReceiptStatus.AUTO_APPROVED
    assert again.duplicate_of is None
    with session_factory() as session:
        receipt = session.get(Receipt, original.id)
        assert receipt.status is ReceiptStatus.AUTO_APPROVED
        assert receipt.duplicate_of is None
        assert receipt.total == D("224.00")
        assert receipt.merchant_name_raw == "SUPERMART INC."
        assert len(receipt.line_items) == 2
        # The copy is untouched, and the chain still runs copy -> original.
        assert session.get(Receipt, copy.receipt_id).duplicate_of == original.id


def test_reprocessing_a_duplicate_re_establishes_the_same_link(
    session_factory, storage, settings
):
    """The other side of the skip rule: a ``rejected`` row is still deduped.

    ``rejected`` is the pipeline's own marking for a copy, not an extraction of
    that receipt's own content, so re-running one must find the original again
    (and spend no model call) rather than skip dedupe and extract over the link.
    """
    data = _png_bytes()
    original = _job(storage, data)
    _run(original, _Client([_triage(), _good()]), session_factory, storage, settings)

    copy_job = _job(storage, data)
    _run(copy_job, _Client([]), session_factory, storage, settings)

    client = _Client([])  # any model call would raise
    again = _run(copy_job, client, session_factory, storage, settings)

    assert client.calls == []
    assert again.status is ReceiptStatus.REJECTED
    assert again.duplicate_of == original.id
    with session_factory() as session:
        assert session.get(Receipt, copy_job.id).duplicate_of == original.id


# --------------------------------------------------------------------------- #
# A machine run never overwrites a human's review
# --------------------------------------------------------------------------- #


def test_a_worker_run_never_overwrites_a_reviewed_receipt(
    session_factory, storage, settings
):
    """The upload -> review -> worker race, end to end.

    ``POST /upload`` commits the ``pending`` row *before* it queues, and
    ``GET /receipts`` lists pending rows -- that visibility is the point of the
    row. So with the queue backed up a reviewer can open the receipt and re-key
    it off the paper, and the worker then arrives holding a machine extraction
    of the same id. Applying it would break three invariants at once: the
    correction is silently dropped, a receipt a human reviewed reverts to
    ``auto_approved`` (and exports as an approved transaction carrying a number
    the reviewer rejected), and the ``corrections`` audit trail contradicts the
    row it describes.
    """
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()

    with session_factory() as session:
        apply_corrections(
            session,
            job.id,
            {"totals": {"total": "999.99"}, "merchant": {"name": "HAND-KEYED CO"}},
            corrected_by="alice",
        )

    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        # Exactly as the human left it.
        assert receipt.status is ReceiptStatus.REVIEWED
        assert receipt.total == D("999.99")
        assert receipt.merchant_name_raw == "HAND-KEYED CO"
        corrections = session.scalars(select(Correction)).all()
        assert len(corrections) == 2
        assert {row.value_after for row in corrections} == {"999.99", "HAND-KEYED CO"}

        # ...and the attempt is visible, not silent: a task naming the stage,
        # why the write was refused, and what the run produced.
        task = session.scalars(select(ReviewTask).where(ReviewTask.receipt_id == job.id)).one()
        assert task.state is ReviewState.OPEN
        assert "persist" in task.reason
        assert "reviewed" in task.reason
        assert "224" in task.reason

    # The receipt is still terminal, and the result describes the actual row
    # rather than claiming a needs_review it is not in.
    assert result.status is ReceiptStatus.REVIEWED
    assert result.failed_stage == "persist"


# --------------------------------------------------------------------------- #
# No silent drops: one injected failure per stage (§18)
# --------------------------------------------------------------------------- #


def _assert_terminal_needs_review(result, session_factory, stage: str) -> None:
    assert result.status is ReceiptStatus.NEEDS_REVIEW, f"{stage}: not terminal"
    assert result.failed_stage == stage
    assert stage in result.reason
    with session_factory() as session:
        receipt = session.get(Receipt, result.receipt_id)
        assert receipt is not None, f"{stage}: the receipt vanished"
        assert receipt.status is ReceiptStatus.NEEDS_REVIEW
        task = session.scalars(
            select(ReviewTask).where(ReviewTask.receipt_id == result.receipt_id)
        ).one()
        assert stage in task.reason


def test_stage_names_are_declared_in_order():
    assert STAGES == (
        "load", "preprocess", "dedupe", "triage", "merchant", "extract", "normalize",
        "score", "persist",
    )


def test_load_failure_reaches_needs_review(session_factory, storage, settings, existing_row):
    class _BrokenStorage(LocalStorage):
        def get(self, key: str) -> bytes:
            raise OSError("blob store unreachable")

    broken = _BrokenStorage(storage.root)
    job = existing_row(_job(storage))
    result = _run(job, _Client([]), session_factory, broken, settings)

    _assert_terminal_needs_review(result, session_factory, "load")


def test_preprocess_failure_reaches_needs_review(
    session_factory, storage, settings, existing_row
):
    job = existing_row(_job(storage, b"this is not an image"))
    result = _run(job, _Client([]), session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "preprocess")


def test_dedupe_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("phash index offline")

    monkeypatch.setattr(pipeline_module, "find_duplicate_by_phash", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([]), session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "dedupe")


def test_triage_failure_reaches_needs_review(
    session_factory, storage, settings, existing_row
):
    job = existing_row(_job(storage))
    result = _run(job, _Client([RuntimeError("triage exploded")]),
                  session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "triage")


def test_merchant_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    """A registry that is down costs the receipt its hints, not the receipt.

    The merchant lookup is a *prompting aid*: nothing downstream needs it, so
    the tempting shape is to swallow the error and carry on unhinted. That is
    the silent drop §18 forbids -- a registry broken for a week would leave no
    trace anywhere while every receipt quietly extracted without its hints.
    Wrapped as its own stage, the failure is named and a human is asked.
    """

    def boom(*args, **kwargs):
        raise RuntimeError("merchant registry offline")

    monkeypatch.setattr(pipeline_module.registry, "lookup", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([_triage()]), session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "merchant")


def test_extract_failure_reaches_needs_review(
    session_factory, storage, settings, existing_row
):
    job = existing_row(_job(storage))
    client = _Client([_triage(), RuntimeError("extract exploded")])
    result = _run(job, client, session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "extract")


def test_normalize_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("normalizer exploded")

    monkeypatch.setattr(pipeline_module, "normalize", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    # The failure happened inside the repair loop's normalize hook, and it is
    # still attributed to `normalize` rather than to the enclosing stage.
    _assert_terminal_needs_review(result, session_factory, "normalize")


def test_score_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(pipeline_module, "score_confidence", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    _assert_terminal_needs_review(result, session_factory, "score")


def test_persist_failure_reaches_needs_review(
    session_factory, storage, settings, monkeypatch, existing_row
):
    def boom(*args, **kwargs):
        raise RuntimeError("findings table gone")

    monkeypatch.setattr(pipeline_module, "save_findings", boom)
    job = existing_row(_job(storage))
    result = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    # Even a half-written transaction is rolled back and replaced by a terminal
    # row -- a job that fails is far better than one that vanishes.
    _assert_terminal_needs_review(result, session_factory, "persist")


def test_a_job_is_never_dropped_silently_when_the_database_is_unreachable(storage, settings):
    """The only case that may raise: nothing could be written at all.

    Raising hands the job back to the queue's failed registry. Returning
    "success" here would be the silent drop §18 forbids.
    """

    def no_session():
        raise RuntimeError("database unreachable")

    job = _job(storage)
    with pytest.raises(RuntimeError, match="database unreachable"):
        _run(job, _Client([_triage(), _good()]), no_session, storage, settings)


# --------------------------------------------------------------------------- #
# Concurrency cap and cost guard
# --------------------------------------------------------------------------- #


def test_every_model_call_goes_through_the_concurrency_gate(
    session_factory, storage, settings
):
    gate = VLMGate(limit=1)
    job = _job(storage)

    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings, gate=gate)

    # Zero would mean the gate was never entered, i.e. the cap is decorative.
    assert gate.peak_in_flight == 1


def test_cost_ceiling_stops_the_run_cleanly_at_needs_review(
    session_factory, storage, settings
):
    job = _job(storage)
    client = _Client([_triage(), _good()], cost=D("0.01"))
    guard = CostGuard(ceiling=D("0.005"))

    result = _run(job, client, session_factory, storage, settings, cost_guard=guard)

    # Triage was paid for; the extract call is refused before it is made.
    assert client.calls == ["TriageResult"]
    assert guard.spent == D("0.01")
    _assert_terminal_needs_review(result, session_factory, "extract")
    assert "cost" in result.reason.lower()


def test_result_reports_what_the_run_cost(session_factory, storage, settings):
    job = _job(storage)
    result = _run(job, _Client([_triage(), _good()], cost=D("0.02")),
                  session_factory, storage, settings)

    assert result.cost_usd == D("0.04")
    assert isinstance(result.cost_usd, D)


# --------------------------------------------------------------------------- #
# process_batch (§14.10)
# --------------------------------------------------------------------------- #


def test_process_batch_processes_every_path_and_reports_rejects(
    tmp_path, session_factory, storage, settings
):
    good_paths = []
    for index in range(3):
        path = tmp_path / f"receipt_{index}.png"
        # Distinct pixel content so the perceptual hashes differ and nothing is
        # mistaken for a duplicate.
        path.write_bytes(_png_bytes(seed=index))
        good_paths.append(path)

    bad = tmp_path / "notes.txt"
    bad.write_text("not a receipt", encoding="utf-8")

    def client_factory() -> VLMClient:
        return _Client([_triage(), _good()])

    batch = process_batch(
        [*good_paths, bad],
        client_factory=client_factory,
        storage=storage,
        session_factory=session_factory,
        ctx=CTX,
        settings=settings,
        workers=2,
    )

    assert len(batch.processed) == 3
    assert all(isinstance(item, ProcessResult) for item in batch.processed)
    assert len(batch.rejected) == 1
    assert batch.rejected[0][0].endswith("notes.txt")
    assert batch.total_cost_usd == D("0.06")
    assert batch.counts[ReceiptStatus.AUTO_APPROVED] == 3


# --------------------------------------------------------------------------- #
# confidence_reasons (P4.T3)
# --------------------------------------------------------------------------- #


def test_persisted_reasons_sum_to_the_persisted_confidence(session_factory, storage, settings):
    """The breakdown a reviewer is shown must add up to the score it explains."""
    job = _job(storage)
    penalised = _good()
    penalised.meta.legibility = Legibility.POOR
    penalised.meta.is_handwritten = True
    client = _Client([_triage(), penalised])

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.confidence_reasons  # non-empty: this receipt lost points
        penalties = [D(entry["penalty"]) for entry in receipt.confidence_reasons]
        expected = min(D("1"), max(D("0"), D("1") + sum(penalties)))
        assert expected.quantize(D("0.001")) == receipt.confidence


def test_a_clean_receipt_records_an_empty_reason_list(session_factory, storage, settings):
    job = _job(storage)
    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    with session_factory() as session:
        # [] means "nothing lowered the score", which is not the same claim as
        # NULL ("never recorded").
        assert session.get(Receipt, job.id).confidence_reasons == []


def test_a_failed_stage_records_no_reasons(session_factory, storage, settings):
    job = _job(storage)
    client = _Client([RuntimeError("triage exploded")])

    result = _run(job, client, session_factory, storage, settings)

    assert result.failed_stage == "triage"
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.status is ReceiptStatus.NEEDS_REVIEW
        # Nothing was ever scored, so NULL is the truthful value.
        assert receipt.confidence_reasons is None


def test_a_failed_reprocess_clears_the_reasons_for_the_score_it_replaced(
    session_factory, storage, settings
):
    """D2: the breakdown must always explain the score sitting next to it.

    ``_persist_failure``'s update branch set ``status`` and ``confidence`` but
    not ``confidence_reasons``, so a retry that died in ``extract`` left the row
    -- and ``GET /receipts/{id}`` -- showing ``confidence "0.000"`` beside a
    breakdown that still summed to the score of the run before it.
    """
    job = _job(storage)
    penalised = _good()
    penalised.meta.legibility = Legibility.POOR
    penalised.meta.is_handwritten = True
    first = _run(job, _Client([_triage(), penalised]), session_factory, storage, settings)

    with session_factory() as session:
        stale = session.get(Receipt, job.id).confidence_reasons
        assert stale, "the first run must record a breakdown for this to be a regression"
        assert sum(D(entry["penalty"]) for entry in stale) != D("0")
        assert first.confidence > D("0")

    result = _run(job, _Client([_triage(), RuntimeError("extract exploded")]),
                  session_factory, storage, settings)

    assert result.failed_stage == "extract"
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.confidence == D("0")
        assert receipt.confidence_reasons is None


def test_a_reprocess_that_auto_approves_closes_the_open_review_task(
    session_factory, storage, settings
):
    """A resolved receipt must not leave its old task behind.

    ``_persist_outcome`` enqueued when the receipt was not auto-approved but
    never closed an existing task when it was, so ``GET /review/next`` could
    hand a reviewer an auto-approved receipt and ``/metrics`` overstated the
    backlog for as long as the row lived.
    """
    job = _job(storage)
    first = _run(job, _Client([_triage(), _broken_totals(), _broken_totals()]),
                 session_factory, storage, settings)
    assert first.status is ReceiptStatus.NEEDS_REVIEW
    with session_factory() as session:
        assert session.scalars(select(ReviewTask)).one().state is ReviewState.OPEN

    again = _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    assert again.status is ReceiptStatus.AUTO_APPROVED
    with session_factory() as session:
        task = session.scalars(select(ReviewTask)).one()
        assert task.state is ReviewState.DONE
        assert task.closed_at is not None


def test_progress_reports_only_real_pipeline_stages(
    session_factory, storage, settings
) -> None:
    """The vocabulary is bound to `STAGES`, not re-typed beside it.

    Those strings also land in `review_tasks.reason` and in the logs, so a
    progress name that is not a stage name would be a second vocabulary that
    can drift from the first.
    """
    from receipts.pipeline import STAGES

    seen: list = []
    job = _job(storage)
    process_receipt(
        job,
        client=_Client([_triage(), _good()]),
        storage=storage,
        session_factory=session_factory,
        settings=settings,
        progress=seen.append,
    )

    assert seen, "no progress was reported at all"
    assert [e.stage for e in seen if e.stage not in STAGES] == []
    # The stages a healthy run must pass through, in order of first sighting.
    order = [e.stage for e in seen]
    for name in ("load", "preprocess", "triage", "extract", "score", "persist"):
        assert name in order, f"{name} never reported"
    assert order.index("load") < order.index("extract") < order.index("persist")


def test_the_extract_stage_reports_each_attempt(
    session_factory, storage, settings
) -> None:
    """The repair loop is the only stage worth narrating, so it must say more
    than its own name. A broken first pass then a good repair is two attempts."""
    seen: list = []
    job = _job(storage)
    process_receipt(
        job,
        client=_Client([_triage(), _broken_totals(), _good()]),
        storage=storage,
        session_factory=session_factory,
        settings=settings,
        progress=seen.append,
    )

    details = [e.detail for e in seen if e.stage == "extract" and e.detail]
    # Shape, not cardinality. A healthy repair run reports three details, so
    # `len(details) >= 2` was satisfied by any two of them: each of the three
    # emits could be deleted on its own with the whole suite still green.
    per_attempt = [d for d in details if d.startswith("attempt ")]
    kept = [d for d in details if d.startswith("kept attempt ")]
    assert len(per_attempt) >= 2, f"expected an event per attempt, got {details}"
    assert len(kept) == 1, f"expected exactly one kept-attempt event, got {details}"


def test_passing_no_sink_changes_nothing(tmp_path, settings) -> None:
    """The property that makes this safe on the hot path.

    Same inputs, same client script, with and without a sink: the outcome must
    be identical. Asserted rather than assumed, because `progress` is threaded
    through the one function every receipt goes through.

    **Each run gets its own database and blob store.** Sharing one would not
    hold the sink as the only difference: `_png_bytes` is deterministic, so the
    two jobs carry byte-identical images and the second run would take the
    dedupe short-circuit and come back `rejected` without ever extracting. The
    comparison would then measure accumulated database state instead of the
    sink, and would fail identically with no sink passed at all.
    """
    def run(label, progress):
        world = tmp_path / label
        world.mkdir()
        engine = make_engine(f"sqlite:///{(world / 'receipts.db').as_posix()}")
        Base.metadata.create_all(engine)
        storage = LocalStorage(world / "blobs")
        return process_receipt(
            _job(storage),
            client=_Client([_triage(), _good()]),
            storage=storage,
            session_factory=make_session_factory(engine),
            settings=settings,
            progress=progress,
        )

    without = run("without-sink", None)
    with_sink = run("with-sink", [].append)
    # Guards the comparison itself: two runs that both failed would agree
    # trivially and pin nothing.
    assert without.status is ReceiptStatus.AUTO_APPROVED
    assert without.status == with_sink.status
    assert without.failed_stage == with_sink.failed_stage


def test_a_sink_that_raises_never_takes_the_receipt_down(
    session_factory, storage, settings
) -> None:
    """Narration is a nicety; the extraction is not.

    Every emit is wrapped, so a sink that raises on *every* event must leave
    the outcome exactly as it would have been with no sink at all.
    """
    def _boom(_event):
        raise RuntimeError("sink")

    result = process_receipt(
        _job(storage),
        client=_Client([_triage(), _good()]),
        storage=storage,
        session_factory=session_factory,
        settings=settings,
        progress=_boom,
    )

    assert result.status is ReceiptStatus.AUTO_APPROVED
    assert result.failed_stage is None


def test_a_raising_sink_does_not_escape_the_stage_guard() -> None:
    """`_stage`'s own guard, called directly because nothing else can reach it.

    `process_receipt` now hands `_stage` a `fan_out` product, and `fan_out`
    swallows per delivery -- so a raising sink routed through the pipeline is
    caught before `_stage` ever sees it. A test written that way proves
    `fan_out` works and leaves this guard unpinned, which is exactly how it
    came to be unpinned: removing it left the whole suite green.

    So the sink is handed to `_stage` raw. That is a real path rather than a
    contrivance -- the signature takes a `ProgressSink` and `_normalizer`
    already calls `_stage` directly -- and what the guard buys is not losing
    an extraction to a database blip in the heartbeat.

    `seen` is asserted as well as the block running: without it this would
    still pass if `_stage` stopped calling the sink at all, which is a guard
    that guards nothing.
    """
    seen: list[str] = []

    def boom(event):
        seen.append(event.stage)
        raise RuntimeError("sink")

    entered = False
    with _stage("load", boom):
        entered = True

    assert seen == ["load"], "the sink was never called, so nothing was guarded"
    assert entered, "the guard let the exception escape and skipped the block"


# --------------------------------------------------------------------------- #
# The heartbeat: a run cannot be constructed without one
# --------------------------------------------------------------------------- #


def test_process_receipt_heartbeats_with_no_progress_argument(
    session_factory, storage, settings
) -> None:
    """The guarantee's signal does not depend on the caller remembering.

    This test never names the sink. It goes through `_run`, which calls
    process_receipt exactly as `--inline`, `reprocess` and `process_batch` do
    -- with no `progress=` -- and asserts the row was stamped anyway. Deleting
    the sink construction inside process_receipt is what turns it red.
    """
    job = _job(storage)
    # The row must exist first, and that is the real shape rather than a
    # convenience: `record_progress` is an UPDATE, and every live path creates
    # the pending row before processing -- upload at `review/api.py:635`,
    # ingest at `cli.py:654`, and `--inline` draws from
    # `query_receipts(status=PENDING)`. Measured during Task 4: with no row,
    # all ten beats match zero rows and write nothing.
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()

    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    with session_factory() as session:
        receipt = get_receipt(session, job.id)
        # Checked first so this reddens on the assertion it is about. This is
        # the sole guard for the whole milestone -- measured: removing the
        # wiring is 1 failure in 1405 -- and without this line a `None` row
        # would fail it with `'NoneType' object has no attribute
        # 'progress_at'`, which names the wrong problem.
        assert receipt is not None
        assert receipt.progress_at is not None
        assert receipt.progress_stage is not None


def test_a_receipt_with_no_row_beats_nothing_and_raises_nothing(
    session_factory, storage, settings
) -> None:
    """The boundary of the heartbeat, stated rather than left implicit.

    `record_progress` is an UPDATE and its contract is that an unknown id
    writes nothing and raises nothing. So a run with no pre-existing row
    narrates nothing -- it does not fail, and it does not conjure a row.

    This is reachable only through `process_batch`, which has **no production
    caller**: `git grep -n "process_batch" -- src/` returns its definition at
    `pipeline.py:1350` and three docstring mentions (`pipeline.py:19`,
    `pipeline.py:459`, `cli.py:797`), and nothing else. Every path that can
    actually strand a receipt creates the row first, so the milestone's
    guarantee is unaffected: a receipt with no row is not stranded, it was
    never recorded.
    """
    job = _job(storage)

    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    with session_factory() as session:
        receipt = get_receipt(session, job.id)
        # persist created it at the end of the run, so it exists now -- but no
        # beat reached it, because none of the ten had a row to update.
        assert receipt is not None
        assert receipt.progress_stage is None
        assert receipt.progress_at is None


def test_fan_out_delivers_to_every_sink() -> None:
    seen_a: list[str] = []
    seen_b: list[str] = []
    sink = fan_out(lambda e: seen_a.append(e.stage), lambda e: seen_b.append(e.stage))
    sink(ProgressEvent(stage="extract"))
    assert seen_a == ["extract"]
    assert seen_b == ["extract"]


def test_fan_out_ignores_none_sinks() -> None:
    seen: list[str] = []
    sink = fan_out(None, lambda e: seen.append(e.stage), None)
    sink(ProgressEvent(stage="triage"))
    assert seen == ["triage"]


def test_one_raising_sink_does_not_starve_the_other() -> None:
    """The heartbeat must survive a broken Redis writer.

    This is the whole reason fan_out isolates each sink rather than letting an
    exception escape to the outer guard: if a raising narration sink stopped
    the heartbeat, a Redis outage would silently reopen the stranded-receipt
    hole this milestone exists to close.
    """
    seen: list[str] = []

    def boom(event):
        raise RuntimeError("redis is down")

    sink = fan_out(boom, lambda e: seen.append(e.stage))
    sink(ProgressEvent(stage="persist"))
    assert seen == ["persist"]


# --------------------------------------------------------------------------- #
# The heartbeat sink's own contract
# --------------------------------------------------------------------------- #


class _RecordingSession:
    """A Session stand-in that records the lifecycle calls the sink makes."""

    def __init__(self, calls: list[str], *, raise_on_commit: bool = False) -> None:
        self.calls = calls
        self._raise = raise_on_commit

    def execute(self, *_a, **_k):
        self.calls.append("execute")

    def flush(self) -> None:
        self.calls.append("flush")

    def commit(self) -> None:
        self.calls.append("commit")
        if self._raise:
            raise RuntimeError("database went away")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


def test_the_heartbeat_sink_commits_its_own_session() -> None:
    """A heartbeat no other process can see is not a heartbeat.

    This is the ADR-0006 asymmetry: repository functions never commit, and this
    sink -- which is the caller -- must.
    """
    calls: list[str] = []
    sink = _heartbeat_sink(lambda: _RecordingSession(calls), uuid.uuid4())
    sink(ProgressEvent(stage="extract"))
    assert "commit" in calls


def test_the_heartbeat_sink_closes_its_session_on_success() -> None:
    calls: list[str] = []
    sink = _heartbeat_sink(lambda: _RecordingSession(calls), uuid.uuid4())
    sink(ProgressEvent(stage="extract"))
    assert calls[-1] == "close"


def test_a_failing_beat_rolls_back_closes_and_re_raises() -> None:
    """It must not swallow.

    If this is ever softened to a swallow, the three guarded call sites become
    the only thing between a database blip and a lost beat, and nothing would
    notice.
    """
    calls: list[str] = []
    sink = _heartbeat_sink(
        lambda: _RecordingSession(calls, raise_on_commit=True), uuid.uuid4()
    )
    with pytest.raises(RuntimeError, match="database went away"):
        sink(ProgressEvent(stage="extract"))
    assert "rollback" in calls
    assert calls[-1] == "close"


def test_the_beat_writes_the_event_stage_not_a_constant(
    session_factory, storage, settings
) -> None:
    """Last beat wins, and it is the event's stage that lands."""
    job = _job(storage)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()

    sink = _heartbeat_sink(session_factory, job.id)
    sink(ProgressEvent(stage="triage"))
    sink(ProgressEvent(stage="persist"))

    with session_factory() as session:
        assert get_receipt(session, job.id).progress_stage == "persist"


# --------------------------------------------------------------------------- #
# P7.T1 -- self-consistency, gated
# --------------------------------------------------------------------------- #


def _handwritten() -> TriageResult:
    """Triage that satisfies `is_handwritten` through `print_type`, not
    `document_type`.

    Deliberately the *narrower* spelling's blind spot: P7.T1's checkbox says
    gate on `document_type == "handwritten_receipt"`, and the STATUS note above
    it says gate on `is_handwritten`, **never** `document_type`. They are not in
    conflict -- `is_handwritten` is a property, `document_type is
    HANDWRITTEN_RECEIPT or print_type in (HANDWRITTEN, MIXED)` -- so the note is
    a correction the checkbox never absorbed. A hand-annotated thermal receipt
    is exactly what the checkbox would miss, so that is what this fixture is.
    """
    return TriageResult(
        document_type=DocumentType.POS_RECEIPT,
        print_type=PrintType.HANDWRITTEN,
        legibility=Legibility.GOOD,
        estimated_line_item_count=2,
    )


def _spy_consistency(monkeypatch):
    """Replace `run_consistency` and record whether it ran.

    A spy rather than an injected seam, and that is the point project-35 made
    while wiring the OCR flag: if the dependency is injectable and an injected
    one runs regardless, the flag becomes untestable -- "off" and "on but
    working" produce identical output and nothing can tell them apart. The gate
    is the flag, so the spy must be reachable only through it.
    """
    calls: list[dict] = []
    result = ConsistencyResult(runs=3, disputed=["totals.total"])

    def fake(image, client, **kwargs):
        calls.append(kwargs)
        return result, []

    monkeypatch.setattr("receipts.pipeline.run_consistency", fake)
    return calls, result


def _spy_score(monkeypatch):
    """Capture the `consistency` argument scoring was given."""
    seen: list[object] = []
    real = pipeline_module.score_confidence

    def fake(extraction, report, triage, *, consistency=None):
        seen.append(consistency)
        return real(extraction, report, triage, consistency=consistency)

    monkeypatch.setattr("receipts.pipeline.score_confidence", fake)
    return seen


def test_consistency_does_not_run_while_the_flag_is_off(
    monkeypatch, session_factory, storage, settings
):
    """OFF is the default, and a handwritten receipt does not override it.

    The cost is the reason: `run_consistency` is n extra extract calls, and on
    this box ADR-0039 measures a single extract in minutes. A flag that starts
    spending on every deployment that upgrades is not a flag anyone consented to.
    """
    calls, _ = _spy_consistency(monkeypatch)
    seen = _spy_score(monkeypatch)
    job = _job(storage)

    _run(job, _Client([_handwritten(), _good()]), session_factory, storage, settings)

    assert calls == []
    assert seen == [None]


def test_consistency_runs_for_a_handwritten_receipt_when_enabled(
    monkeypatch, session_factory, storage, settings
):
    """Both conditions, and the result reaches scoring rather than the floor."""
    calls, result = _spy_consistency(monkeypatch)
    seen = _spy_score(monkeypatch)
    enabled = settings.model_copy(update={"consistency_enabled": True})
    job = _job(storage)

    _run(job, _Client([_handwritten(), _good()]), session_factory, storage, enabled)

    assert len(calls) == 1
    # The disputed fields are the whole point (§12): a consistency run whose
    # result never reached `score_confidence` would be n extract calls spent on
    # nothing, and every gate would stay green.
    assert seen == [result]


def test_consistency_does_not_run_for_a_printed_receipt(
    monkeypatch, session_factory, storage, settings
):
    """The flag is necessary, not sufficient.

    Without this the gate could be the flag alone and every receipt would pay
    for a pass aimed at handwriting.
    """
    calls, _ = _spy_consistency(monkeypatch)
    enabled = settings.model_copy(update={"consistency_enabled": True})
    job = _job(storage)

    _run(job, _Client([_triage(), _good()]), session_factory, storage, enabled)

    assert calls == []


def test_consistency_runs_for_a_poorly_legible_printed_receipt(
    monkeypatch, session_factory, storage, settings
):
    """The other half of the trigger, which the task's TITLE carries and its
    STATUS note does not: "handwritten **/low-legibility**".

    A thermal receipt that photographed badly is printed, so `is_handwritten` is
    false, and it is exactly the case where independent extractions disagree.
    Gating on handwriting alone would spend the pass on the receipts most likely
    to be read correctly and skip the ones most likely not to be.

    `UNREADABLE` is deliberately **not** included: triage saying it cannot read
    the page at all is not a case where three more reads help, and it is already
    routed by confidence.
    """
    calls, _ = _spy_consistency(monkeypatch)
    enabled = settings.model_copy(update={"consistency_enabled": True})
    smudged = TriageResult(
        document_type=DocumentType.POS_RECEIPT,
        print_type=PrintType.THERMAL,
        legibility=Legibility.POOR,
        estimated_line_item_count=2,
    )
    job = _job(storage)

    _run(job, _Client([smudged, _good()]), session_factory, storage, enabled)

    assert len(calls) == 1


def test_consistency_does_not_run_for_an_unreadable_receipt(
    monkeypatch, session_factory, storage, settings
):
    """The bound on the clause above. `UNREADABLE` is not "low legibility"; it
    is triage saying there is nothing to read, and three more attempts at
    nothing is `consistency_runs` extract calls spent to learn that."""
    calls, _ = _spy_consistency(monkeypatch)
    enabled = settings.model_copy(update={"consistency_enabled": True})
    blank = TriageResult(
        document_type=DocumentType.POS_RECEIPT,
        print_type=PrintType.THERMAL,
        legibility=Legibility.UNREADABLE,
        estimated_line_item_count=0,
    )
    job = _job(storage)

    _run(job, _Client([blank, _good()]), session_factory, storage, enabled)

    assert calls == []
