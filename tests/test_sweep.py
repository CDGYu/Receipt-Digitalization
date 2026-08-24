"""The terminal-state sweep.

Every test here runs against a fixture holding all six shapes at once --
stranded-started, warm-started, old-never-started, recent-never-started, a
terminal row, and a reviewed row. A fixture of only stranded rows would stay
green with the entire progress_at clause deleted, which is the shape that has
produced surviving mutants on this project before.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from config.settings import Settings
from receipts.ingest.ingest import ReceiptJob
from receipts.persist.models import Base, ReviewTask
from receipts.persist.repository import create_pending_receipt, get_receipt
from receipts.persist.session import make_engine, make_session_factory
from receipts.score.confidence import ReceiptStatus
from receipts.sweep import strand_if_cold, strand_receipt, sweep_stranded

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _job() -> ReceiptJob:
    return ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="t",
        original_filename="r.jpg", content_type="image/jpeg",
    )


def _make(session, *, status, progress_at, created_at, stage="extract"):
    job = _job()
    receipt = create_pending_receipt(session, job)
    receipt.status = status
    receipt.progress_at = progress_at
    receipt.created_at = created_at
    receipt.progress_stage = stage if progress_at is not None else None
    session.flush()
    return job.id


@pytest.fixture
def six_shapes(session_factory):
    """All six shapes, keyed by name.

    The cutoffs these ages are chosen against, derived rather than quoted so a
    reader can check them:

        one_call        = vlm_timeout_s x _SDK_ATTEMPTS = 600 x 3   = 1800s
        started_cutoff  = one_call x STRAND_MARGIN      = 1800 x 2  = 1h
        unstarted_cutoff= one_call x calls x UNSTARTED_MARGIN
                        = 1800 x 3 x 12                             = 18h

    So: 2h and 48h are cold; 1 minute is warm; and 6h is the discriminating
    one -- past `started` but short of `unstarted`, which is the only age that
    can tell the two thresholds apart. If you change STRAND_MARGIN or
    UNSTARTED_MARGIN, every age here must move with them.
    """
    ids: dict[str, uuid.UUID] = {}
    with session_factory() as session:
        ids["stranded_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=NOW - timedelta(hours=2), created_at=NOW - timedelta(hours=3),
        )
        ids["warm_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=NOW - timedelta(minutes=1), created_at=NOW - timedelta(hours=3),
        )
        ids["old_never_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=None, created_at=NOW - timedelta(days=2),
        )
        # 6h is deliberately BETWEEN the two cutoffs: older than started (1h),
        # younger than unstarted (18h). At exactly 1h it sat on the started
        # boundary and discriminated nothing -- collapsing the two thresholds
        # left it unswept either way, so the mutation survived.
        ids["recent_never_started"] = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=None, created_at=NOW - timedelta(hours=6),
        )
        ids["terminal"] = _make(
            session, status=ReceiptStatus.AUTO_APPROVED,
            progress_at=NOW - timedelta(hours=5), created_at=NOW - timedelta(hours=6),
        )
        ids["reviewed"] = _make(
            session, status=ReceiptStatus.REVIEWED,
            progress_at=NOW - timedelta(hours=5), created_at=NOW - timedelta(hours=6),
        )
        session.commit()
    return ids


def _settings() -> Settings:
    return Settings(_env_file=None, vlm_timeout_s=600, max_repair_attempts=1)


def test_a_stranded_receipt_reaches_needs_review(session_factory, six_shapes) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["stranded_started"] in swept
    with session_factory() as session:
        receipt = get_receipt(session, six_shapes["stranded_started"])
        assert receipt.status is ReceiptStatus.NEEDS_REVIEW


def test_the_reason_names_the_stage_it_died_in(session_factory, six_shapes) -> None:
    sweep_stranded(session_factory, settings=_settings(), now=NOW)
    with session_factory() as session:
        task = session.query(ReviewTask).filter(
            ReviewTask.receipt_id == six_shapes["stranded_started"]
        ).one()
        assert "extract" in task.reason


def test_a_warm_receipt_is_left_alone(session_factory, six_shapes) -> None:
    """Slow is not stranded. This is what the heartbeat bought."""
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["warm_started"] not in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["warm_started"]).status is ReceiptStatus.PENDING


def test_a_receipt_that_never_started_is_swept_once_it_is_old(
    session_factory, six_shapes
) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["old_never_started"] in swept


def test_a_recently_queued_receipt_is_not_swept(session_factory, six_shapes) -> None:
    """A backlog is not a strand.

    This is the case that makes the two thresholds necessary: with one
    threshold, a healthy receipt waiting behind a queue would be marked
    needs_review while the worker was still going to process it.
    """
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["recent_never_started"] not in swept


def test_a_terminal_receipt_is_never_touched(session_factory, six_shapes) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["terminal"] not in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["terminal"]).status is ReceiptStatus.AUTO_APPROVED


def test_a_reviewed_receipt_is_never_touched(session_factory, six_shapes) -> None:
    """A machine run never overwrites a reviewed row.

    This pins the end-to-end outcome. It does NOT pin either rule that
    produces it: `find_stranded`'s status clause and `strand_receipt`'s own
    guard each refuse a reviewed row, so on this path deleting either leaves
    the other refusing and this test green. The two tests below pin them
    separately, each on the path where it is the only thing standing.
    """
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert six_shapes["reviewed"] not in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["reviewed"]).status is ReceiptStatus.REVIEWED


def test_the_query_alone_refuses_every_non_pending_row(session_factory, six_shapes) -> None:
    """`find_stranded`'s status clause, on the one path where it stands alone.

    A dry run reports straight from the query without calling
    `strand_receipt`, so nothing else can refuse on its behalf. Asserting the
    exact SET rather than one id is what makes it discriminate: deleting the
    status clause admits the terminal and reviewed rows, and this is the only
    test that would see it.
    """
    swept = set(
        sweep_stranded(session_factory, settings=_settings(), now=NOW, dry_run=True)
    )
    assert swept == {six_shapes["stranded_started"], six_shapes["old_never_started"]}


def test_strand_receipt_alone_refuses_a_non_pending_row(
    session_factory, six_shapes
) -> None:
    """`strand_receipt`'s own guard, called directly -- its other caller's path.

    `strand_if_cold` hands it a row it loaded itself, never one already
    filtered by `find_stranded`, so on that path this guard is the only thing
    standing. Going through `sweep_stranded` would let the query refuse first
    and prove nothing.
    """
    with session_factory() as session:
        receipt = get_receipt(session, six_shapes["reviewed"])
        assert strand_receipt(session, receipt) is False
        session.commit()

    with session_factory() as session:
        assert get_receipt(session, six_shapes["reviewed"]).status is ReceiptStatus.REVIEWED


def test_sweeping_twice_opens_one_task_not_two(session_factory, six_shapes) -> None:
    sweep_stranded(session_factory, settings=_settings(), now=NOW)
    second = sweep_stranded(session_factory, settings=_settings(), now=NOW)
    assert second == []
    with session_factory() as session:
        tasks = session.query(ReviewTask).filter(
            ReviewTask.receipt_id == six_shapes["stranded_started"]
        ).all()
        assert len(tasks) == 1


def test_dry_run_reports_without_writing(session_factory, six_shapes) -> None:
    swept = sweep_stranded(session_factory, settings=_settings(), now=NOW, dry_run=True)
    assert six_shapes["stranded_started"] in swept
    with session_factory() as session:
        assert get_receipt(session, six_shapes["stranded_started"]).status is ReceiptStatus.PENDING


def test_the_two_attempt_constants_cannot_drift() -> None:
    """sweep.py duplicates worker.py's _SDK_ATTEMPTS to keep its imports narrow.

    A duplicated constant is a second source, so it is pinned rather than
    trusted. Importing worker here is fine: this is a test, not the module.
    """
    from receipts import sweep, worker

    assert sweep._SDK_ATTEMPTS == worker._SDK_ATTEMPTS


def test_a_naive_stored_timestamp_is_read_as_utc(session_factory) -> None:
    """SQLite stores these columns naive; the comparison must still work.

    Measured rather than assumed: an aware `12:00+00:00` written to
    `progress_at` comes back from SQLite as a naive `12:00`, and comparing it
    with an aware cutoff raises
    `TypeError: can't compare offset-naive and offset-aware datetimes`. So
    without `_as_utc` this test errors rather than failing an assertion --
    louder than a wrong answer, and on SQLite only, which means it would pass
    review on Postgres and redden the suite.
    """
    with session_factory() as session:
        receipt_id = _make(
            session, status=ReceiptStatus.PENDING,
            progress_at=datetime(2026, 8, 24, 10, 0),  # deliberately naive
            created_at=NOW - timedelta(hours=3),
        )
        session.commit()
    with session_factory() as session:
        receipt = get_receipt(session, receipt_id)
        assert strand_if_cold(receipt=receipt, session=session, settings=_settings(), now=NOW)
