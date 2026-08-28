"""``receipts process`` and ``receipts reprocess`` (P4.T5, spec 14.10, ADR-0013).

Everything here is offline, exactly like ``tests/test_process_receipt.py``: a
scripted in-process client, a temp-directory ``LocalStorage``, and a
file-backed SQLite database. No provider, no Redis, no network -- the fake
queue below stands in for ``rq.Queue`` the same way ``tests/test_worker.py``'s
does, so the enqueue path (production's default) is exercised without a live
broker.

The load-bearing behaviours pinned down below (ADR-0013):

  * ``process`` drains the ``pending`` work list -- the same rows ``receipts
    ingest`` and ``POST /upload`` both write -- oldest first, ``--limit``
    capping it. Omitting ``--limit`` really does mean everything pending, not
    a silent inherited cap of 1000.
  * The enqueue path is production's path; a missing ``REDIS_URL`` is a hard
    failure naming ``--inline``, never a silent fallback.
  * **Both of ``process``'s loops contain a per-job failure identically**
    (``cli._UNCONTAINED``). ``--inline`` runs the pipeline synchronously and
    never turns a receipt routed to review into a non-zero exit code -- but a
    receipt whose own run could not even complete (a build failure from
    ``client_factory``, or the one case ``process_receipt`` itself can raise)
    is reported and does not silently cancel receipts that had not started.
    The default enqueue path had no containment at all: a broker dropping
    mid-batch escaped ``cmd_process`` entirely as a traceback, with no
    summary and exit ``0``, on the path ADR-0013 calls production's own.
    Both loops catch ``BaseException`` and re-raise only
    ``KeyboardInterrupt``/``SystemExit``, because "nothing is silently
    dropped" must not depend on a third party's choice of base class, while
    an operator pressing Ctrl-C is not a receipt failing.
  * ``reprocess`` never overwrites a ``reviewed`` receipt, with or without
    ``--force``: the run still happens, but ``save_extraction``'s own refusal
    (ADR-0012) is what protects the row -- the CLI only reports it, for
    *any* failing stage, not only ``persist``. ``--force`` is a status gate
    (it extends reprocessing to ``auto_approved``) and never a permission
    override.
  * ADR-0013's two named consequences of ``reprocess`` being the first
    routine caller of the P4.T3 dedupe findings: a receipt whose stage failed
    carries ``image_phash = ""`` and so can never be matched as a dedupe
    *original*, and dedupe is skipped entirely for a receipt that already
    holds its own extraction -- which is what stops a reprocess turning a
    duplicate-linked original into an empty ``rejected`` row.
"""

from __future__ import annotations

import io
import itertools
import random
import threading
import uuid
from decimal import Decimal as D
from typing import Any

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import select  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts import cli as cli_module  # noqa: E402
from receipts.cli import (  # noqa: E402
    EXIT_FAILED,
    EXIT_OK,
    build_parser,
    cmd_process,
    cmd_reprocess,
)
from receipts.extract.clients.base import VLMClient, VLMResponse  # noqa: E402
from receipts.extract.schema import (  # noqa: E402
    DocumentType,
    Legibility,
    Merchant,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
    TriageResult,
)
from receipts.extract.schema import LineItem as ExtractedLineItem  # noqa: E402
from receipts.ingest.ingest import ReceiptJob  # noqa: E402
from receipts.ingest.storage import LocalStorage, make_image_key  # noqa: E402
from receipts.persist.models import Base, Receipt, ReviewState, ReviewTask  # noqa: E402
from receipts.persist.repository import (  # noqa: E402
    create_pending_receipt,
    save_extraction,
)
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.score.confidence import ReceiptStatus  # noqa: E402
from receipts.validate.report import ValidationReport  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def session_factory(tmp_path):
    """A file-backed SQLite database, so several sessions share it."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


@pytest.fixture()
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "blobs")


@pytest.fixture()
def settings() -> Settings:
    """Hermetic settings with a Redis URL set.

    The default (enqueue) path in ``cmd_process`` needs ``settings.redis_url``
    to be truthy just to get past the "no fallback" gate; every test that
    reaches that far injects its own ``queue_factory``, so nothing here ever
    dials a real broker.
    """
    return Settings(_env_file=None, max_repair_attempts=1, redis_url="redis://localhost:6379/0")


# --------------------------------------------------------------------------- #
# Doubles and helpers (the scripted-client pattern from test_process_receipt.py)
# --------------------------------------------------------------------------- #


#: Seeds for the default-distinct fixture images, one per call.
_PNG_SEEDS = itertools.count()


def _png_bytes(seed: int | None = None) -> bytes:
    """A deterministic PNG with enough structure to carry a distinctive dHash.

    A flat image is useless here: every uniform bitmap hashes to the same 64
    zero bits (dHash keys on gradient direction, not shade), so byte-identical
    fixture blobs made concurrent receipts race into dedupe's near-duplicate
    window -- this module's diagnosed intermittent failure. Mirrors the
    seeded-rectangles fixture in ``tests/test_process_receipt.py``, adding a
    per-call default so every job gets a distinct image unless a test passes
    ``seed`` for reproducible bytes -- or hands one blob to two jobs via
    ``_job(storage, data)``, the sibling module's override, which is how the
    two tests that need a real dedupe match ask for byte-identical images.
    """
    rng = random.Random(next(_PNG_SEEDS) if seed is None else seed)
    size = (900, 1400)
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
    """Scripted client: each entry is a pydantic model, a parse-error string,
    or an exception to raise -- see ``tests/test_process_receipt.py``.
    """

    def __init__(self, script, *, cost: D = D("0.01")) -> None:
        self.model_id = "fake-vlm"
        self.script = list(script)
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
            raw={"scripted": index},
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
    """A clean, self-consistent extraction (mirrors tests/test_process_receipt.py)."""
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


def _broken_totals() -> ReceiptExtraction:
    """Totals that cannot reconcile -- guaranteed ERROR findings."""
    extraction = _good()
    extraction.totals.total = D("999.00")
    return extraction


class _BrokenStorage(LocalStorage):
    """A storage backend whose ``get`` always fails.

    Mirrors ``tests/test_process_receipt.py``'s ``_BrokenStorage``: forces a
    deterministic ``load`` stage failure, which is what a receipt whose blob
    has gone missing looks like to ``process_receipt`` -- as opposed to
    ``persist``, which is the only stage the old reprocess reporting knew
    about.
    """

    def get(self, key: str) -> bytes:
        raise OSError("blob store unreachable")


class _FakeQueue:
    """Stands in for an ``rq.Queue``.

    ``enqueue_receipt`` calls ``queue.enqueue(process_receipt_job, payload,
    job_timeout=...)``, so recording the payload is enough to prove dispatch
    without a live Redis.

    ``fail_on`` makes the *n*-th ``enqueue`` (1-based) raise ``fail_with``,
    which is what a broker dropping part-way through a batch looks like from
    here: ``rq`` surfaces it as ``redis.ConnectionError``, an ordinary
    ``ConnectionError`` subclass.
    """

    def __init__(self, *, fail_on: int | None = None,
                 fail_with: BaseException | None = None) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.attempts = 0
        self.fail_on = fail_on
        self.fail_with = fail_with or ConnectionError("Error 10061 connecting to localhost:6379")

    def enqueue(self, func, payload, **kwargs):
        self.attempts += 1
        if self.fail_on is not None and self.attempts == self.fail_on:
            raise self.fail_with
        self.calls.append((func, payload))
        return object()

    @property
    def jobs(self) -> list[ReceiptJob]:
        from receipts.worker import job_from_payload

        return [job_from_payload(payload) for _func, payload in self.calls]


class _Cancelled(BaseException):
    """A ``BaseException`` that is *not* an ``Exception``.

    Not hypothetical: pytest (``outcomes.Exit``), trio (``Cancelled``) and
    gevent all define types like this, and a ``client_factory`` reaching a
    library that raises one is exactly the case ``except Exception`` misses.
    """


def _pending_receipt(session_factory, storage, *, data: bytes | None = None) -> uuid.UUID:
    """A stored blob plus its ``pending`` row -- what `receipts ingest` leaves behind."""
    job = _job(storage, data)
    with session_factory() as session:
        create_pending_receipt(session, job)
        session.commit()
    return job.id


def _reviewed_receipt(session_factory, storage, *, total: D) -> uuid.UUID:
    """A receipt a human has reviewed, carrying hand-keyed money."""
    job = _job(storage)
    extraction = ReceiptExtraction(totals=Totals(total=total))
    with session_factory() as session:
        save_extraction(session, job, extraction, ValidationReport(), D("1.0"),
                        ReceiptStatus.REVIEWED, image_phash="a1b2c3d4a1b2c3d4")
        session.commit()
    return job.id


def _auto_approved_receipt(session_factory, storage=None) -> uuid.UUID:
    """Same, but ``auto_approved`` -- the status `--force` exists to re-run."""
    job = _job(storage)
    extraction = ReceiptExtraction(totals=Totals(total=D("50.00")))
    with session_factory() as session:
        save_extraction(session, job, extraction, ValidationReport(), D("1.0"),
                        ReceiptStatus.AUTO_APPROVED, image_phash="a1b2c3d4a1b2c3d4")
        session.commit()
    return job.id


# --------------------------------------------------------------------------- #
# process
# --------------------------------------------------------------------------- #


def test_process_enqueues_every_pending_receipt(session_factory, storage, settings, capsys):
    ids = [_pending_receipt(session_factory, storage) for _ in range(3)]
    recorder = _FakeQueue()
    args = build_parser().parse_args(["process"])

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings, queue_factory=lambda: recorder)

    assert code == EXIT_OK
    assert {job.id for job in recorder.jobs} == set(ids)


def test_process_honours_the_limit(session_factory, storage, settings):
    for _ in range(3):
        _pending_receipt(session_factory, storage)
    recorder = _FakeQueue()
    args = build_parser().parse_args(["process", "--limit", "2"])

    cmd_process(args, session_factory=session_factory, storage=storage,
                settings=settings, queue_factory=lambda: recorder)

    assert len(recorder.jobs) == 2


def test_process_without_redis_url_fails_loudly_and_names_inline(session_factory, storage, capsys):
    _pending_receipt(session_factory, storage)
    settings = Settings(_env_file=None, redis_url=None)
    args = build_parser().parse_args(["process"])

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings)

    # Never a silent fallback: a fallback means the operator believes work is
    # queued when it is running in a terminal they are about to close.
    assert code == EXIT_FAILED
    assert "--inline" in capsys.readouterr().err


def test_process_inline_runs_the_pipeline_and_persists(session_factory, storage, settings):
    receipt_id = _pending_receipt(session_factory, storage)
    args = build_parser().parse_args(["process", "--inline"])

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings, client_factory=lambda: _Client([_triage(), _good()]))

    assert code == EXIT_OK
    with session_factory() as session:
        assert session.get(Receipt, receipt_id).status is ReceiptStatus.AUTO_APPROVED


def test_a_receipt_routed_to_review_still_exits_zero(session_factory, storage, settings):
    _pending_receipt(session_factory, storage)
    args = build_parser().parse_args(["process", "--inline"])

    # Review is the system working as designed, not an error. A CLI that exits
    # non-zero here trains operators and CI to ignore its exit status.
    code = cmd_process(
        args, session_factory=session_factory, storage=storage, settings=settings,
        client_factory=lambda: _Client([_triage(), _broken_totals()]),
    )

    assert code == EXIT_OK


def test_inline_one_failing_receipt_does_not_abandon_the_others(
    session_factory, storage, settings, capsys
):
    """One receipt's client build blows up; the rest of the batch must not
    be silently abandoned.

    ``ThreadPoolExecutor.map`` cancels every still-queued future the moment
    one submitted callable raises, so letting that exception escape ``run()``
    used to mean whichever receipts had not yet started when the first one
    failed were left completely untouched -- no line printed, no row
    changed, no indication anything was wrong, and the exception escaped
    ``cmd_process`` entirely instead of becoming ``EXIT_FAILED``. Three
    receipts through a pool of 2 workers is enough to guarantee at least one
    future is still queued when the first result comes back.
    """
    ids = [_pending_receipt(session_factory, storage) for _ in range(3)]
    args = build_parser().parse_args(["process", "--inline", "--workers", "2"])

    lock = threading.Lock()
    calls = {"n": 0}

    def client_factory():
        with lock:
            calls["n"] += 1
            is_first_caller = calls["n"] == 1
        if is_first_caller:
            raise RuntimeError("simulated provider outage")
        return _Client([_triage(), _good()])

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings, client_factory=client_factory)

    # The command could not complete for one receipt, so the run is
    # EXIT_FAILED -- but only for that reason, never because a receipt that
    # did run landed in review.
    assert code == EXIT_FAILED
    out = capsys.readouterr().out
    assert "failed" in out
    assert "total cost" in out
    with session_factory() as session:
        statuses = [session.get(Receipt, receipt_id).status for receipt_id in ids]
    # Nothing was silently dropped: every receipt is accounted for. The two
    # that were not the simulated failure were actually processed -- not
    # abandoned as unstarted futures used to be -- and the failed one is
    # still `pending`, untouched and ready to be retried.
    assert statuses.count(ReceiptStatus.AUTO_APPROVED) == 2
    assert statuses.count(ReceiptStatus.PENDING) == 1


def test_process_without_limit_does_not_silently_cap_at_the_repository_default(
    session_factory, storage, settings, monkeypatch
):
    """``--help`` promises "no cap" when ``--limit`` is omitted; pin that
    ``cmd_process`` actually asks the repository for everything rather than
    silently inheriting ``query_receipts``'s own default of 1000 -- a real
    backlog past that size used to be drained a thousand at a time with
    nothing telling the operator some pending rows were left behind.
    """
    _pending_receipt(session_factory, storage)
    seen_limits: list[int] = []
    real_query_receipts = cli_module.query_receipts

    def spy(session, **kwargs):
        seen_limits.append(kwargs.get("limit"))
        return real_query_receipts(session, **kwargs)

    monkeypatch.setattr(cli_module, "query_receipts", spy)
    recorder = _FakeQueue()
    args = build_parser().parse_args(["process"])

    cmd_process(args, session_factory=session_factory, storage=storage,
               settings=settings, queue_factory=lambda: recorder)

    # The behaviour that actually matters: whatever was asked for is nowhere
    # near the repository's own default of 1000, so a five-figure backlog
    # would never be silently truncated.
    assert len(seen_limits) == 1
    assert seen_limits[0] > 1_000_000
    # Also pins this implementation's specific choice of constant.
    assert seen_limits[0] == cli_module._NO_LIMIT


def test_enqueue_one_failing_job_does_not_abandon_the_batch(
    session_factory, storage, settings, capsys
):
    """The default path had no per-job containment at all.

    Five pending receipts and a queue whose third `enqueue` raises: the
    exception escaped `cmd_process` entirely -- two `queued` lines on stdout,
    no summary, empty stderr, no EXIT_FAILED, just a traceback. Nothing is
    lost (the un-enqueued rows stay `pending` and the next run picks them up),
    but the exit-code contract is violated on the path ADR-0013 calls
    production's own, and the operator loses the summary that would tell them
    how much of the batch actually went out.

    This is fix-round-1's F1 defect, which was fixed for `--inline` and left
    in place here.
    """
    ids = [_pending_receipt(session_factory, storage) for _ in range(5)]
    recorder = _FakeQueue(fail_on=3)
    args = build_parser().parse_args(["process"])

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings, queue_factory=lambda: recorder)

    out = capsys.readouterr().out
    assert code == EXIT_FAILED
    # Every job was attempted -- the two behind the failure were not abandoned.
    assert recorder.attempts == 5
    queued_ids = {job.id for job in recorder.jobs}
    assert len(queued_ids) == 4
    assert queued_ids < set(ids)
    # The summary still prints, and it accounts for the failure.
    assert "queued 4" in out
    assert "failed: 1" in out
    # Nothing was silently dropped: every row is still pending (enqueueing does
    # not change status), so the one that did not go out is picked up next run.
    with session_factory() as session:
        statuses = [session.get(Receipt, rid).status for rid in ids]
    assert statuses.count(ReceiptStatus.PENDING) == 5


def test_both_process_loops_contain_a_non_exception_base_exception(
    session_factory, storage, settings, capsys
):
    """`except Exception` is too narrow for a "nothing is silently dropped"
    guarantee.

    A collaborator raising a `BaseException` subclass -- `SystemExit` from a
    library calling `sys.exit`, a framework's own cancellation type -- sailed
    straight past the inline loop's `except Exception` and out of
    `cmd_process`, with empty stdout: the exact symptom the containment was
    added to prevent, reintroduced through a different base class. Both loops
    now use the same policy (`cli._UNCONTAINED`).
    """
    _pending_receipt(session_factory, storage)

    def cancelled_client():
        raise _Cancelled("provider cancelled")

    inline = cmd_process(
        build_parser().parse_args(["process", "--inline"]),
        session_factory=session_factory, storage=storage, settings=settings,
        client_factory=cancelled_client,
    )
    inline_out = capsys.readouterr().out

    enqueue = cmd_process(
        build_parser().parse_args(["process"]),
        session_factory=session_factory, storage=storage, settings=settings,
        queue_factory=lambda: _FakeQueue(fail_on=1, fail_with=_Cancelled("broker cancelled")),
    )
    enqueue_out = capsys.readouterr().out

    assert inline == EXIT_FAILED
    assert "failed" in inline_out and "total cost" in inline_out
    assert enqueue == EXIT_FAILED
    assert "failed: 1" in enqueue_out


def test_process_still_stops_on_a_keyboard_interrupt(session_factory, storage, settings):
    """The deliberate exception to the policy above.

    Ctrl-C is the operator asking the run to stop, not a receipt failing.
    Contained, it would become a stream of `failed` lines while the batch
    ploughed on -- so `KeyboardInterrupt` and `SystemExit` are re-raised by
    both loops.
    """
    for _ in range(3):
        _pending_receipt(session_factory, storage)

    def interrupt():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        cmd_process(
            build_parser().parse_args(["process", "--inline", "--workers", "1"]),
            session_factory=session_factory, storage=storage, settings=settings,
            client_factory=interrupt,
        )

    with pytest.raises(KeyboardInterrupt):
        cmd_process(
            build_parser().parse_args(["process"]),
            session_factory=session_factory, storage=storage, settings=settings,
            queue_factory=lambda: _FakeQueue(fail_on=1, fail_with=KeyboardInterrupt()),
        )


def test_process_rejects_a_non_positive_limit():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["process", "--limit", "0"])
    assert exc.value.code == 2


def test_process_rejects_a_non_positive_workers():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["process", "--workers", "-1"])
    assert exc.value.code == 2


# --------------------------------------------------------------------------- #
# reprocess
# --------------------------------------------------------------------------- #


def test_reprocess_never_overwrites_a_reviewed_receipt(session_factory, storage, settings):
    receipt_id = _reviewed_receipt(session_factory, storage, total=D("999.99"))
    args = build_parser().parse_args(["reprocess", str(receipt_id)])

    code = cmd_reprocess(args, session_factory=session_factory, storage=storage,
                         settings=settings, client_factory=lambda: _Client([_triage(), _good()]))

    with session_factory() as session:
        row = session.get(Receipt, receipt_id)
        task = session.scalars(select(ReviewTask).where(
            ReviewTask.receipt_id == receipt_id)).one()
    # The one test in this plan that protects a number a human typed.
    assert row.status is ReceiptStatus.REVIEWED
    assert row.total == D("999.99")
    assert task.state is ReviewState.OPEN
    # The pipeline already opened the task, and its reason names what the run
    # produced. Do NOT assert on extraction_runs here -- see Step 5.
    assert "total=224.00" in task.reason
    assert code == EXIT_OK


def test_reprocess_refuses_an_auto_approved_receipt_without_force(
    session_factory, storage, settings, capsys
):
    receipt_id = _auto_approved_receipt(session_factory, storage)
    args = build_parser().parse_args(["reprocess", str(receipt_id)])

    code = cmd_reprocess(args, session_factory=session_factory, storage=storage,
                         settings=settings, client_factory=lambda: _Client([_triage(), _good()]))

    assert code == EXIT_FAILED
    assert "--force" in capsys.readouterr().err


def test_force_extends_to_auto_approved_but_never_to_reviewed(session_factory, storage, settings):
    """The money must actually change under ``--force``, not just the status.

    ``_auto_approved_receipt`` already seeds the row as ``AUTO_APPROVED``, so
    asserting only that it is *still* ``AUTO_APPROVED`` afterwards does not
    discriminate a real ``--force`` re-run from one that silently refused to
    do anything: both look identical on that assertion alone. Asserting the
    total actually moved to the new run's number is what proves ``--force``
    did what it says.
    """
    approved = _auto_approved_receipt(session_factory, storage)
    reviewed = _reviewed_receipt(session_factory, storage, total=D("999.99"))

    code_approved = cmd_reprocess(
        build_parser().parse_args(["reprocess", str(approved), "--force"]),
        session_factory=session_factory, storage=storage, settings=settings,
        client_factory=lambda: _Client([_triage(), _good()]),
    )
    code_reviewed = cmd_reprocess(
        build_parser().parse_args(["reprocess", str(reviewed), "--force"]),
        session_factory=session_factory, storage=storage, settings=settings,
        client_factory=lambda: _Client([_triage(), _good()]),
    )

    with session_factory() as session:
        approved_row = session.get(Receipt, approved)
        reviewed_row = session.get(Receipt, reviewed)
    assert code_approved == EXIT_OK
    # --force is a status gate, not a permission override: it actually ran
    # and overwrote the auto_approved receipt with this run's own number --
    assert approved_row.status is ReceiptStatus.AUTO_APPROVED
    assert approved_row.total == D("224.00")  # _good()'s total, not the seeded 50.00
    # -- and it never touches a reviewed one, force or not.
    assert code_reviewed == EXIT_OK
    assert reviewed_row.total == D("999.99")


def test_reprocess_of_a_reviewed_receipt_that_fails_before_persist_still_reports_unchanged(
    session_factory, storage, settings, capsys
):
    """A reviewed receipt whose blob has vanished fails at ``load``, not
    ``persist`` -- the row is left just as untouched either way (nothing in
    ``_persist_failure`` mutates a row already ``reviewed``, regardless of
    which stage failed), but a report that special-cased only
    ``failed_stage == "persist"`` used to fall through to a bare
    ``reviewed  confidence=1.000`` here, which reads exactly like the re-run
    confirmed the human's numbers when nothing was extracted at all.
    """
    receipt_id = _reviewed_receipt(session_factory, storage, total=D("999.99"))
    broken = _BrokenStorage(storage.root)
    args = build_parser().parse_args(["reprocess", str(receipt_id)])

    code = cmd_reprocess(args, session_factory=session_factory, storage=broken,
                         settings=settings, client_factory=lambda: _Client([]))

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "confidence=1.000" not in out
    assert "reviewed" in out.lower()
    with session_factory() as session:
        row = session.get(Receipt, receipt_id)
        task = session.scalars(
            select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)
        ).one()
    assert row.status is ReceiptStatus.REVIEWED
    assert row.total == D("999.99")
    assert task.state is ReviewState.OPEN
    assert "load" in task.reason


def test_reprocess_prints_the_reason_when_a_non_reviewed_receipt_fails(
    session_factory, storage, settings, capsys
):
    """``reprocess`` used to drop ``result.reason`` on any non-reviewed
    failure, unlike ``process --inline``'s identically shaped line for the
    identical outcome.
    """
    receipt_id = _pending_receipt(session_factory, storage)
    broken = _BrokenStorage(storage.root)
    args = build_parser().parse_args(["reprocess", str(receipt_id)])

    code = cmd_reprocess(args, session_factory=session_factory, storage=broken,
                         settings=settings, client_factory=lambda: _Client([]))

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "load" in out
    with session_factory() as session:
        assert session.get(Receipt, receipt_id).status is ReceiptStatus.NEEDS_REVIEW


def test_reprocess_of_an_unknown_id_is_exit_one(session_factory, storage, settings, capsys):
    args = build_parser().parse_args(["reprocess", str(uuid.uuid4())])
    assert cmd_reprocess(args, session_factory=session_factory, storage=storage,
                         settings=settings) == EXIT_FAILED


# --------------------------------------------------------------------------- #
# reprocess x dedupe -- ADR-0013's two named consequences
#
# `receipts reprocess` is the first routine caller of the two findings parked
# on the P4.T3 branch review, and ADR-0013 says in as many words that "both
# need tests here". Neither had one.
# --------------------------------------------------------------------------- #


def _reprocess(session_factory, storage, settings, receipt_id, *, force=False, script=None):
    """Run one `receipts reprocess` with a fresh scripted client."""
    argv = ["reprocess", str(receipt_id)] + (["--force"] if force else [])
    return cmd_reprocess(
        build_parser().parse_args(argv),
        session_factory=session_factory, storage=storage, settings=settings,
        client_factory=lambda: _Client(script if script is not None else [_triage(), _good()]),
    )


def test_a_second_upload_of_a_failed_receipts_image_is_extracted_in_full(
    session_factory, storage, settings
):
    """A re-upload of an already-seen image is a full receipt (Option C).

    Duplicates are allowed: no dedupe short-circuits a matching image. Here the
    first run failed (so it carries no extraction and an empty `image_phash`),
    and a second upload of the *identical* image is processed normally -- it is
    extracted in full, at full model cost, and both rows survive independently.
    `reprocess` is the command that hits this routinely, because re-running a
    receipt that failed is what it is for.

    Both receipts are handed one byte-identical blob explicitly, so this is the
    strongest form of the case: even a pixel-perfect re-upload is not merged.
    """
    blob = _png_bytes(seed=0)
    failed_id = _pending_receipt(session_factory, storage, data=blob)
    _reprocess(session_factory, _BrokenStorage(storage.root), settings, failed_id, script=[])

    with session_factory() as session:
        failed_row = session.get(Receipt, failed_id)
        assert failed_row.status is ReceiptStatus.NEEDS_REVIEW
        # The gap itself: nothing to match against.
        assert failed_row.image_phash == ""

    # A second receipt carrying an identical image, processed normally.
    second_id = _pending_receipt(session_factory, storage, data=blob)
    code = _reprocess(session_factory, storage, settings, second_id)

    with session_factory() as session:
        second_row = session.get(Receipt, second_id)
    assert code == EXIT_OK
    # Not deduped against the failed original -- extracted for real instead.
    assert second_row.status is ReceiptStatus.AUTO_APPROVED
    assert second_row.duplicate_of is None
    assert second_row.total == D("224.00")
    assert second_row.image_phash != ""


def test_reprocessing_an_original_that_has_a_re_upload_keeps_both_intact(
    session_factory, storage, settings
):
    """Duplicates are allowed, so re-uploads and reprocesses never collide.

    An image is uploaded twice (A then B, byte-identical) and each becomes its
    own independent `auto_approved` receipt -- neither is `rejected`, neither
    carries a `duplicate_of`. Re-running A then leaves both rows exactly as they
    were: full amounts, no link, no rejection. Previously B was linked to A as a
    duplicate and a reprocess of A risked being marked a duplicate of its own
    copy; with dedupe removed there is nothing to collide.
    """
    blob = _png_bytes(seed=0)
    original_id = _pending_receipt(session_factory, storage, data=blob)
    assert _reprocess(session_factory, storage, settings, original_id) == EXIT_OK

    # A second, byte-identical upload -- extracted in full now, not short-circuited.
    copy_id = _pending_receipt(session_factory, storage, data=blob)
    assert _reprocess(session_factory, storage, settings, copy_id) == EXIT_OK

    with session_factory() as session:
        copy_row = session.get(Receipt, copy_id)
        original_row = session.get(Receipt, original_id)
    # Both are independent, real receipts.
    assert copy_row.status is ReceiptStatus.AUTO_APPROVED
    assert copy_row.duplicate_of is None
    assert copy_row.total == D("224.00")
    assert original_row.status is ReceiptStatus.AUTO_APPROVED
    assert original_row.duplicate_of is None

    # Re-run the original. --force, because it is auto_approved.
    code = _reprocess(session_factory, storage, settings, original_id, force=True)

    with session_factory() as session:
        reprocessed = session.get(Receipt, original_id)
        copy_after = session.get(Receipt, copy_id)
    assert code == EXIT_OK
    assert reprocessed.status is ReceiptStatus.AUTO_APPROVED
    assert reprocessed.duplicate_of is None
    assert reprocessed.total == D("224.00")
    # The copy is untouched by the reprocess of the original.
    assert copy_after.status is ReceiptStatus.AUTO_APPROVED
    assert copy_after.duplicate_of is None


def test_an_uncontained_batch_failure_prints_a_redacted_reason(
    session_factory, storage, settings, capsys
):
    """The inline loop's failed-job line is an egress too (ADR-0022).

    ``run()`` catches everything outside ``_UNCONTAINED`` and the loop
    prints the exception straight to stdout -- which a service manager
    journals to disk. A provider error can quote the payload it rejected,
    so the print goes through ``redact_pan`` like every other egress. Two
    PANs in one value (review standard 9).
    """
    _pending_receipt(session_factory, storage)
    args = build_parser().parse_args(["process", "--inline"])

    def client_factory():
        raise RuntimeError(
            "provider rejected payload holding 4111111111111111 and 5555555555554444"
        )

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings, client_factory=client_factory)

    assert code == EXIT_FAILED
    out = capsys.readouterr().out
    assert "failed" in out
    assert "************1111" in out
    assert "************4444" in out
    assert "4111111111111111" not in out
    assert "5555555555554444" not in out


def test_an_enqueue_failure_prints_a_redacted_reason(
    session_factory, storage, settings, capsys
):
    """The enqueue loop's failed-job line is the twin of the inline one.

    ADR-0022's standing rule is that every process egress redacts, and this
    print is the same ``id  failed  reason`` line reached by the other
    branch: the broker refused the job rather than the run failing. A broker
    error can quote what it rejected, so it goes through ``redact_pan`` too.
    Two PANs in one value (review standard 9).
    """
    _pending_receipt(session_factory, storage)
    recorder = _FakeQueue(
        fail_on=1,
        fail_with=RuntimeError(
            "broker rejected job holding 4111111111111111 and 5555555555554444"
        ),
    )
    args = build_parser().parse_args(["process"])

    code = cmd_process(args, session_factory=session_factory, storage=storage,
                       settings=settings, queue_factory=lambda: recorder)

    assert code == EXIT_FAILED
    out = capsys.readouterr().out
    assert "failed" in out
    assert "************1111" in out
    assert "************4444" in out
    assert "4111111111111111" not in out
    assert "5555555555554444" not in out


# --------------------------------------------------------------------------- #
# `_positive_int` -- the bound on `--limit` and `--workers`
# --------------------------------------------------------------------------- #
#
# This validator shipped untested. Nothing under `tests/` referenced it under
# any name, so neither the bound it already had nor the one it was missing was
# pinned.


@pytest.mark.parametrize("flag", ["--limit", "--workers"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_the_batch_flags_refuse_a_value_below_one(flag, value):
    """The pre-existing lower bound, pinned for the first time.

    ``--limit 0`` reads as "take none" and prints ``nothing pending`` against a
    full backlog; a negative ``--limit`` means "no limit" on SQLite and errors
    on Postgres; ``--workers 0`` is accepted by ``ThreadPoolExecutor`` as
    "run sequentially" with nothing saying so. argparse turns the
    ``ArgumentTypeError`` into exit 2.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args(["process", flag, value])


@pytest.mark.parametrize("flag", ["--limit", "--workers"])
def test_the_batch_flags_accept_an_ordinary_value(flag):
    """The control. Without it, a validator that refused everything would pass
    every rejection case above and below."""
    args = build_parser().parse_args(["process", flag, "50"])

    assert getattr(args, flag.lstrip("-")) == 50


@pytest.mark.parametrize("flag", ["--limit", "--workers"])
def test_the_batch_flags_refuse_an_integer_too_large_for_the_database(flag):
    """``--limit 9223372036854775808`` reached SQLite and raised OverflowError.

    Measured before the bound existed: ``query_receipts(limit=2**63)`` raises
    ``OverflowError: Python int too large to convert to SQLite INTEGER``,
    straight out of the driver, as an unhandled traceback rather than a usage
    error. ``2**63 - 1`` is fine, so the boundary is exactly the signed 64-bit
    ceiling.

    **This is a representability bound, not a policy one** -- deliberately
    unlike ADR-0034's ``MAX_PAGE_OFFSET``. A page offset past a million is a
    scan no index removes, but ``--limit 5000000`` is a legitimate batch size
    for an operator with that many pending receipts, so the only defensible
    ceiling here is what the database can actually store.

    ``--workers`` is bounded by the same validator and **does not need it**:
    measured, ``ThreadPoolExecutor(max_workers=2**63)`` constructs fine and
    runs a task, because threads are spawned lazily. It is covered here because
    the two flags share one validator, not because a second defect was found.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args(["process", flag, str(2**63)])


@pytest.mark.parametrize("flag", ["--limit", "--workers"])
def test_the_batch_flags_accept_the_largest_value_the_database_can_store(flag):
    """The boundary's other side: ``2**63 - 1`` must still parse.

    This is what makes the case above a bound rather than an anecdote -- a
    validator that rejected everything large would satisfy it otherwise.
    """
    args = build_parser().parse_args(["process", flag, str(2**63 - 1)])

    assert getattr(args, flag.lstrip("-")) == 2**63 - 1
