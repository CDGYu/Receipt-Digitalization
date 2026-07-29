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
  * ``--inline`` runs the pipeline synchronously in this process and never
    turns a receipt routed to review into a non-zero exit code -- but a
    receipt whose own run could not even complete (a build failure from
    ``client_factory``, or the one case ``process_receipt`` itself can raise)
    is reported and does not silently cancel receipts that had not started.
  * ``reprocess`` never overwrites a ``reviewed`` receipt, with or without
    ``--force``: the run still happens, but ``save_extraction``'s own refusal
    (ADR-0012) is what protects the row -- the CLI only reports it, for
    *any* failing stage, not only ``persist``. ``--force`` is a status gate
    (it extends reprocessing to ``auto_approved``) and never a permission
    override.
"""

from __future__ import annotations

import io
import threading
import uuid
from decimal import Decimal as D
from typing import Any

import pytest

pytest.importorskip("PIL")
pytest.importorskip("pillow_heif")

from PIL import Image  # noqa: E402
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
from receipts.persist.repository import create_pending_receipt, save_extraction  # noqa: E402
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


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1400), (240, 240, 240)).save(buffer, format="PNG")
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
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def enqueue(self, func, payload, **kwargs):
        self.calls.append((func, payload))
        return object()

    @property
    def jobs(self) -> list[ReceiptJob]:
        from receipts.worker import job_from_payload

        return [job_from_payload(payload) for _func, payload in self.calls]


def _pending_receipt(session_factory, storage) -> uuid.UUID:
    """A stored blob plus its ``pending`` row -- what `receipts ingest` leaves behind."""
    job = _job(storage)
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
