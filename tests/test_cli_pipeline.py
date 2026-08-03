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

import hashlib
import inspect
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
from receipts.ingest.dedupe import compute_phash, phash_distance  # noqa: E402
from receipts.ingest.ingest import ReceiptJob  # noqa: E402
from receipts.ingest.storage import LocalStorage, make_image_key  # noqa: E402
from receipts.persist.models import Base, Receipt, ReviewState, ReviewTask  # noqa: E402
from receipts.persist.repository import (  # noqa: E402
    create_pending_receipt,
    find_duplicate_by_phash,
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


def test_a_receipt_whose_run_failed_is_never_matched_as_a_dedupe_original(
    session_factory, storage, settings
):
    """The empty-`image_phash` gap, from the CLI side (ADR-0013).

    A receipt whose stage failed carries `image_phash = ""` -- the perceptual
    hash is only computed at `preprocess`, so a run that died at `load` never
    produced one -- and `find_duplicate_by_phash` skips rows with an empty
    hash outright (`int("", 16)` would raise, and an unhashed receipt is not
    comparable to anything). So a *second* upload of the very same image is
    not recognised as a duplicate of the failed one: it is extracted in full,
    at full model cost, and both rows survive.

    That is the correct trade -- a missed duplicate is recoverable, a wrong
    merge is not -- but it is undocumented behaviour with a real cost, and
    nothing pinned it. `reprocess` is the command that hits it routinely,
    because re-running a receipt that failed is what it is for.

    Both receipts are handed one byte-identical blob explicitly, because the
    fixture is distinct-by-default now and byte-identity is what gives this
    test teeth. Without it the second receipt could not match the failed one
    even if the failed run *had* stored a hash, so the test would certify
    nothing. With it, that mutation is exactly what this test refuses:
    measured in review, a failed row carrying its own hash is matched under
    the shared blob and unmatched under distinct ones.
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


def test_reprocessing_a_duplicate_linked_original_never_empties_it(
    session_factory, storage, settings
):
    """The dedupe skip, from the CLI side (ADR-0013).

    Once a copy B has been linked to original A, re-running A means running
    dedupe over a table that already contains A's own image under B. Without
    the guards, A was marked a duplicate *of its own copy*: emptied of its
    amounts, flipped to `rejected`, and -- because both rows are then
    `rejected` -- dropped out of the default export along with B, taking the
    transaction out of the ledger with nothing left pointing at it.

    Two independent defences stop this, and ADR-0013 records that neither is
    load-bearing alone: `pipeline._find_duplicate_image` skips dedupe entirely
    for a receipt already holding its own extraction (`_ALREADY_EXTRACTED`),
    and `repository.find_duplicate_by_phash` drops candidates whose
    `duplicate_of` is the receipt being run. This test pins the guarantee they
    jointly provide, which is the thing an operator actually depends on.

    The copy is handed the original's exact bytes explicitly, because the
    fixture is distinct-by-default now: the byte-identical second image is
    this test's premise -- it is what makes the copy a dedupe duplicate at
    all, and so what lets it run with an empty client script, dedupe having
    short-circuited extraction before the VLM is ever called.
    """
    blob = _png_bytes(seed=0)
    original_id = _pending_receipt(session_factory, storage, data=blob)
    assert _reprocess(session_factory, storage, settings, original_id) == EXIT_OK

    copy_id = _pending_receipt(session_factory, storage, data=blob)
    assert _reprocess(session_factory, storage, settings, copy_id, script=[]) == EXIT_OK

    with session_factory() as session:
        copy_row = session.get(Receipt, copy_id)
        original_row = session.get(Receipt, original_id)
    # Precondition: the copy really was recognised and linked to the original.
    assert copy_row.status is ReceiptStatus.REJECTED
    assert copy_row.duplicate_of == original_id
    assert original_row.status is ReceiptStatus.AUTO_APPROVED

    # Now re-run the original. --force, because it is auto_approved.
    code = _reprocess(session_factory, storage, settings, original_id, force=True)

    with session_factory() as session:
        reprocessed = session.get(Receipt, original_id)
    assert code == EXIT_OK
    # The original is still the original: not rejected, not linked to its own
    # copy, and still carrying its money.
    assert reprocessed.status is ReceiptStatus.AUTO_APPROVED
    assert reprocessed.duplicate_of is None
    assert reprocessed.total == D("224.00")


def test_reprocess_skips_dedupe_for_a_receipt_that_already_holds_its_own_extraction(
    session_factory, storage, settings
):
    """The `_ALREADY_EXTRACTED` skip on its own, isolated from the repository's
    ``duplicate_of`` exclusion.

    The test above cannot separate the two defences: the copy it builds *is*
    linked to the original, so the repository-side exclusion alone would save
    it. The state below is one only the pipeline-side skip covers -- two
    receipts holding the same image, both `auto_approved`, neither linked to
    the other. That is reachable today: two workers running the same image
    concurrently both read `image_phash = ""` on every candidate row at dedupe
    time, so neither sees the other, and both go on to extract and approve.

    Re-running either of them must not turn it into a duplicate of the other.
    Whichever is reprocessed already holds an extraction *of its own image*,
    so dedupe has nothing to tell it -- and running it anyway would empty the
    row, flip it to `rejected`, and drop the transaction out of the export.
    """
    original_id = _pending_receipt(session_factory, storage)
    assert _reprocess(session_factory, storage, settings, original_id) == EXIT_OK
    with session_factory() as session:
        phash = session.get(Receipt, original_id).image_phash
    assert phash != ""

    # The concurrent twin: same image hash, auto_approved, duplicate_of NULL.
    twin_job = _job(storage)
    with session_factory() as session:
        save_extraction(session, twin_job, _good(), ValidationReport(), D("0.95"),
                        ReceiptStatus.AUTO_APPROVED, image_phash=phash)
        session.commit()

    code = _reprocess(session_factory, storage, settings, original_id, force=True)

    with session_factory() as session:
        row = session.get(Receipt, original_id)
    assert code == EXIT_OK
    assert row.status is ReceiptStatus.AUTO_APPROVED
    assert row.duplicate_of is None
    assert row.total == D("224.00")


def test_fixture_images_are_distinct_beyond_the_dedupe_threshold() -> None:
    """The premise of every multi-receipt test in this module, pinned.

    Byte-identical fixture blobs share a sha256 AND a dHash -- a uniform
    bitmap hashes to the same 64 zero bits at any shade -- so receipts
    processed concurrently race into ``find_duplicate_by_phash``'s
    near-duplicate window, and whichever commits first makes the others
    ``REJECTED`` duplicates. That race is this module's diagnosed
    intermittent failure, and distinct bytes alone are not enough: dedupe is
    perceptual, so the images must sit pairwise beyond the threshold, which
    is read off the real function rather than restated here.
    """
    threshold = inspect.signature(find_duplicate_by_phash).parameters["threshold"].default
    blobs = [_png_bytes(seed=seed) for seed in range(12)]

    assert len({hashlib.sha256(blob).digest() for blob in blobs}) == len(blobs)

    hashes = [compute_phash(Image.open(io.BytesIO(blob))) for blob in blobs]
    for i, first in enumerate(hashes):
        for j, second in enumerate(hashes[i + 1 :], start=i + 1):
            assert phash_distance(first, second) > threshold, (i, j, first, second)
