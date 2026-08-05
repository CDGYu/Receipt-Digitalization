"""Tests for the review API's read routes and app factory (P4.T4, spec §14.9).

``pytest.importorskip("fastapi")`` keeps the base test suite offline, matching
``tests/test_auth.py``.

Everything runs against a file-backed SQLite database (shared across threads,
unlike ``:memory:`` -- same fixture pattern as ``test_auth.py``), a
``LocalStorage`` rooted at ``tmp_path``, and a fake ``submit`` that appends to
a list instead of touching Redis/RQ. ``create_app``'s real
``_default_submit`` (which imports ``receipts.worker`` lazily) is never
exercised by this module -- it needs the optional ``worker`` extra, which the
offline suite does not install.

The database is seeded once per test with three receipts:

  * ``RECEIPT_A`` -- ``auto_approved``, ``confidence_reasons=[]`` (a
    genuinely clean receipt: nothing lowered the score).
  * ``RECEIPT_B`` -- ``needs_review``, two findings (``R020`` then ``R011``,
    oldest first) and two ``confidence_reasons`` whose penalties reconstruct
    the stored confidence exactly; also the one open review-queue task. This
    is the ``receipt_id`` fixture.
  * ``RECEIPT_C`` -- ``pending``, ``confidence_reasons`` left at its column
    default (``None``): the score was never recorded, which must reach the
    API as ``null``, not ``[]``. This is the ``pending_receipt_id`` fixture.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from config.settings import Settings  # noqa: E402
from receipts.extract.schema import Legibility  # noqa: E402
from receipts.ingest.storage import LocalStorage  # noqa: E402
from receipts.persist.models import Base, Receipt, ValidationFinding  # noqa: E402
from receipts.persist.repository import _RECEIPT_FIELDS  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.persist.users import ROLE_ADMIN, ROLE_REVIEWER, create_user  # noqa: E402
from receipts.review.api import create_app  # noqa: E402
from receipts.review.queue import close_task, enqueue_review, next_task  # noqa: E402
from receipts.score.confidence import ReceiptStatus  # noqa: E402
from receipts.validate.report import Severity  # noqa: E402

RECEIPT_A = uuid.uuid4()  # auto_approved, confidence_reasons=[]
RECEIPT_B = uuid.uuid4()  # needs_review; two findings, two reasons
RECEIPT_C = uuid.uuid4()  # pending; confidence_reasons never recorded


def _seed(session_factory) -> None:
    """Two reviewer/admin accounts and the three receipts described above."""
    with session_factory() as session:
        create_user(session, "alice", "pw-alice", ROLE_REVIEWER)
        create_user(session, "bob", "pw-bob", ROLE_ADMIN)

        session.add(
            Receipt(
                id=RECEIPT_A,
                status=ReceiptStatus.AUTO_APPROVED,
                confidence=Decimal("0.930"),
                confidence_reasons=[],
                merchant_name_raw="COFFEE CO",
                txn_date=date(2026, 7, 1),
                currency="USD",
                total=Decimal("12.50"),
                image_key="receipts/2026/07/a/original.jpg",
                image_phash="",
            )
        )
        session.add(
            Receipt(
                id=RECEIPT_B,
                status=ReceiptStatus.NEEDS_REVIEW,
                confidence=Decimal("0.570"),
                confidence_reasons=[
                    {"reason": "an ERROR finding", "penalty": "-0.350"},
                    {"reason": "a WARN finding", "penalty": "-0.080"},
                ],
                # Every correctable column carries a **distinct** value, and
                # deliberately so: ``test_every_correctable_receipt_column_is_
                # readable_in_the_detail`` compares the value at each declared
                # path against the column it names, and two columns sharing a
                # value (or both being NULL) would let a wrong declared path
                # pass. See that test.
                merchant_name_raw="TOTAL WINE",
                receipt_number="OR-2026-0042",
                txn_date=date(2026, 7, 2),
                date_raw="02/07/2026",
                # Seconds on purpose: a ``%H:%M`` rendering would drop them,
                # and ``receipt.time`` is a correctable path, so what the API
                # renders has to be what PATCH takes back.
                txn_time=time(14, 30, 45),
                currency="USD",
                subtotal=Decimal("900"),
                tax_total=Decimal("80"),
                discount_total=Decimal("5"),
                total=Decimal("1000"),
                tender_amount=Decimal("1100"),
                change_amount=Decimal("100"),
                payment_method="VISA",
                card_last4="4242",
                is_handwritten=True,
                legibility=Legibility.FAIR,
                receipt_is_inconsistent=True,
                image_key="receipts/2026/07/b/original.jpg",
                image_phash="",
            )
        )
        session.add(
            Receipt(
                id=RECEIPT_C,
                status=ReceiptStatus.PENDING,
                confidence=Decimal("0"),
                image_key="receipts/2026/07/c/original.jpg",
                image_phash="",
            )
        )
        session.flush()

        # Oldest first: R020 must come back before R011 (get_findings orders
        # by created_at then id).
        session.add_all(
            [
                ValidationFinding(
                    receipt_id=RECEIPT_B,
                    rule_id="R020",
                    severity=Severity.ERROR,
                    message="totals do not reconcile",
                    context={},
                    resolved_by_repair=False,
                    created_at=datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC),
                ),
                ValidationFinding(
                    receipt_id=RECEIPT_B,
                    rule_id="R011",
                    severity=Severity.WARN,
                    message="date looks implausible",
                    context={},
                    resolved_by_repair=False,
                    created_at=datetime(2026, 7, 2, 12, 0, 1, tzinfo=UTC),
                ),
            ]
        )
        enqueue_review(session, RECEIPT_B, reason="needs_review", priority=1)
        session.commit()


@pytest.fixture()
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    _seed(factory)
    return factory


#: Deliberately *not* the ``receipts.score.thresholds`` defaults. ``/metrics``
#: must echo what this deployment is configured with -- a fixture that left them
#: at 0.85/0.60 cannot tell "read from Settings" apart from "hardcoded".
CONFIGURED_AUTO_APPROVE = Decimal("0.95")
CONFIGURED_REVIEW = Decimal("0.75")


@pytest.fixture()
def settings() -> Settings:
    """Hermetic settings: a developer's ``.env`` must not steer these tests."""
    return Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        auto_approve_threshold=CONFIGURED_AUTO_APPROVE,
        review_threshold=CONFIGURED_REVIEW,
    )


@pytest.fixture()
def submitted() -> list:
    """What a fake ``submit`` records instead of touching Redis/RQ."""
    return []


@pytest.fixture()
def app(session_factory, settings, tmp_path, submitted):
    return create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "blobs"),
        submit=submitted.append,
        settings=settings,
    )


@pytest.fixture()
def client(app) -> TestClient:
    """Unauthenticated -- only ``GET /health`` is expected to work through it."""
    return TestClient(app)


def _logged_in(app, username: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return client


@pytest.fixture()
def reviewer_client(app) -> TestClient:
    return _logged_in(app, "alice", "pw-alice")


@pytest.fixture()
def admin_client(app) -> TestClient:
    return _logged_in(app, "bob", "pw-bob")


@pytest.fixture()
def receipt_id() -> uuid.UUID:
    return RECEIPT_B


@pytest.fixture()
def pending_receipt_id() -> uuid.UUID:
    return RECEIPT_C


@pytest.fixture()
def clients(app, reviewer_client, admin_client) -> dict[str, TestClient]:
    anonymous = TestClient(app)
    api_key = TestClient(app)
    api_key.headers.update({"X-API-Key": "not-configured-but-irrelevant-here"})
    return {
        "anonymous": anonymous,
        "api_key": api_key,
        "reviewer": reviewer_client,
        "admin": admin_client,
    }


@pytest.fixture()
def empty_session_factory(tmp_path):
    """A second, genuinely empty database -- no receipts, no queue tasks."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        create_user(session, "alice", "pw-alice", ROLE_REVIEWER)
        session.commit()
    return factory


@pytest.fixture()
def empty_client(empty_session_factory, settings, tmp_path) -> TestClient:
    empty_app = create_app(
        session_factory=empty_session_factory,
        storage=LocalStorage(tmp_path / "empty-blobs"),
        submit=lambda job: None,
        settings=settings,
    )
    return _logged_in(empty_app, "alice", "pw-alice")


# --------------------------------------------------------------------------- #
# Brief step 1, verbatim
# --------------------------------------------------------------------------- #


def test_health_needs_no_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_money_is_serialized_as_a_string(reviewer_client, receipt_id):
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()
    assert body["totals"]["total"] == "1000.0000"  # never a JSON float
    assert isinstance(body["confidence"], str)


def test_detail_returns_findings_and_the_reasons_that_made_the_score(reviewer_client, receipt_id):
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()
    assert [f["rule_id"] for f in body["findings"]] == ["R020", "R011"]
    penalties = [Decimal(r["penalty"]) for r in body["confidence_reasons"]]
    assert (Decimal("1") + sum(penalties)).quantize(Decimal("0.001")) == Decimal(body["confidence"])


def test_reasons_never_recorded_is_null_not_empty(reviewer_client, pending_receipt_id):
    body = reviewer_client.get(f"/receipts/{pending_receipt_id}").json()
    assert body["confidence_reasons"] is None


# --------------------------------------------------------------------------- #
# A reviewer can read every field they are allowed to correct (P5.T3b)
# --------------------------------------------------------------------------- #

#: ``receipts`` column -> the path ``receipt_detail`` exposes it at. Written out
#: rather than derived, because the money columns are deliberately *renamed*
#: on the way out: ``receipt_detail`` names them after
#: :class:`receipts.extract.schema.Totals` (``tax``, ``tender``, ``change``)
#: rather than after the table (``tax_total``, ``tender_amount``,
#: ``change_amount``), so no rule turns one into the other.
_COLUMN_TO_DETAIL_PATH = {
    "merchant_name_raw": ("merchant_name_raw",),
    "receipt_number": ("receipt_number",),
    "txn_date": ("txn_date",),
    "date_raw": ("date_raw",),
    "txn_time": ("txn_time",),
    "currency": ("currency",),
    "subtotal": ("totals", "subtotal"),
    "tax_total": ("totals", "tax"),
    "discount_total": ("totals", "discount"),
    "total": ("totals", "total"),
    "tender_amount": ("totals", "tender"),
    "change_amount": ("totals", "change"),
    "payment_method": ("payment_method",),
    "card_last4": ("card_last4",),
    "is_handwritten": ("is_handwritten",),
    "legibility": ("legibility",),
    "receipt_is_inconsistent": ("receipt_is_inconsistent",),
}

_ABSENT = object()


def _at(body: dict, path: tuple[str, ...]) -> object:
    """``body`` at ``path``, or :data:`_ABSENT` if any segment is missing."""
    cursor: object = body
    for segment in path:
        if not isinstance(cursor, dict) or segment not in cursor:
            return _ABSENT
        cursor = cursor[segment]
    return cursor


def _rendered(value: object) -> object:
    """A column value as ``receipt_detail`` is entitled to render it.

    The serializer applies exactly three transformations on the correctable
    columns -- ``money()`` (``Decimal`` -> ``str``, ADR-0001), ``_iso_date`` /
    ``_iso_time`` (``isoformat()``), and ``.value`` on the ``Legibility`` enum
    -- and passes text and booleans through untouched. Mirroring only those
    three keeps this a check on *which column reached which key*, not a second
    copy of the serializer.
    """
    if isinstance(value, Legibility):
        return value.value
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def test_every_correctable_receipt_column_is_readable_in_the_detail(
    reviewer_client, session_factory, receipt_id
):
    """A field a reviewer may overwrite is a field they must first be able to see.

    ``_RECEIPT_FIELDS`` (the closed map ``apply_corrections`` resolves a patch
    against) and ``receipt_detail`` are two independently written lists of the
    same columns, and until P5.T3b nothing bound them together: three
    correctable paths -- ``receipt.number``, ``receipt.time``,
    ``payment.method`` -- had no key in the detail response at all, so a
    reviewer could replace what the machine read without ever being shown it.
    This test is that binding, and it fails on the next unpaired addition
    rather than on the next reviewer to notice.

    **The value is asserted, not merely the key's presence** (fix round 1).
    Presence alone made the guidance message below satisfiable *incorrectly*:
    declaring a new column at some path that merely happens to exist passed.
    Measured -- an 18th correctable path (``image_phash``) declared as
    ``("currency",)`` gave ``50 passed, 0 failures``. Comparing the value at
    the declared path against the column it names is what closes that, and it
    is why ``_seed`` gives every correctable column on ``RECEIPT_B`` a
    distinct, non-null value: two columns sharing one (or both being NULL)
    would let a wrong path through again.
    """
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()
    with session_factory() as session:
        receipt = session.get(Receipt, receipt_id)
        stored = {column: getattr(receipt, column) for column in _COLUMN_TO_DETAIL_PATH}

    correctable = {column for column, _coerce in _RECEIPT_FIELDS.values()}
    assert correctable == set(_COLUMN_TO_DETAIL_PATH), (
        "_RECEIPT_FIELDS changed: add the new column to _COLUMN_TO_DETAIL_PATH "
        "naming the path where receipt_detail exposes *that column's value* -- "
        "the assertion below compares them, so a path that merely exists fails"
    )
    assert [
        column
        for column, path in sorted(_COLUMN_TO_DETAIL_PATH.items())
        if _at(body, path) is _ABSENT
    ] == []
    assert {
        column: _at(body, path) for column, path in sorted(_COLUMN_TO_DETAIL_PATH.items())
    } == {column: _rendered(value) for column, value in sorted(stored.items())}


def test_detail_returns_the_number_the_time_and_the_payment_method(reviewer_client, receipt_id):
    """The three values, rendered the way the correction path takes them back.

    ``txn_time`` is ``isoformat()``, not ``strftime("%H:%M")``: the seconds in
    the seeded ``14:30:45`` survive, which is what makes the value a reviewer
    reads identical to the value ``PATCH receipt.time`` would store again --
    see ``test_the_time_the_detail_returns_patches_back_unchanged`` in
    ``tests/test_api_write.py``.
    """
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()

    assert body["receipt_number"] == "OR-2026-0042"
    assert body["txn_time"] == "14:30:45"
    assert body["payment_method"] == "VISA"


def test_the_three_added_fields_are_null_when_the_column_is(reviewer_client, pending_receipt_id):
    """``None`` in, ``null`` out -- never ``""`` and never an invented time.

    ``RECEIPT_C`` is the ``pending`` row: nothing has been extracted onto it
    yet, so all three columns are NULL and the API must say so rather than
    render an empty string a reviewer could mistake for "the receipt printed
    nothing here".
    """
    body = reviewer_client.get(f"/receipts/{pending_receipt_id}").json()

    assert body["receipt_number"] is None
    assert body["txn_time"] is None
    assert body["payment_method"] is None


def test_list_filters_and_pages(reviewer_client):
    body = reviewer_client.get("/receipts", params={"status": "needs_review", "limit": 1}).json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False


def test_list_caps_the_page_size(reviewer_client):
    assert reviewer_client.get("/receipts", params={"limit": 10_000}).status_code == 422


def test_unknown_receipt_is_404(reviewer_client):
    assert reviewer_client.get(f"/receipts/{uuid.uuid4()}").status_code == 404


def test_metrics_on_an_empty_database_reports_null_not_a_rate(empty_client):
    body = empty_client.get("/metrics").json()
    # An undefined rate is null. Reporting 1.0 on zero receipts is exactly the
    # vacuous artifact this project already produced once.
    assert body["auto_approval_rate"] is None
    assert body["counts_by_status"] == {}


def test_metrics_reports_the_queue_and_the_thresholds(reviewer_client):
    """The thresholds are **this deployment's**, not the module defaults.

    ``process_receipt`` routes on ``settings.auto_approve_threshold`` /
    ``settings.review_threshold``, so anything else on ``/metrics`` is a wrong
    number on the one endpoint an operator uses to reason about auto-approval
    precision -- and it misleads exactly when calibration moves the cut-off.
    """
    body = reviewer_client.get("/metrics").json()
    assert body["queue"]["open"] >= 1
    assert body["thresholds"] == {
        "auto_approve": str(CONFIGURED_AUTO_APPROVE),
        "review": str(CONFIGURED_REVIEW),
    }


# --------------------------------------------------------------------------- #
# The interactive docs are opt-in (DOCS_ENABLED)
# --------------------------------------------------------------------------- #

DOC_ROUTES = ["/openapi.json", "/docs", "/redoc"]


@pytest.mark.parametrize("path", DOC_ROUTES)
def test_the_docs_are_not_served_by_default(client, path):
    """FastAPI publishes all three to anyone who can reach the port.

    The schema names every write route, every request body, and the
    ``X-API-Key`` header, and none of these endpoints takes a session or a key
    -- so the default must be off. ``client`` here is deliberately the
    unauthenticated one: that is who could read them.
    """
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", DOC_ROUTES)
def test_the_docs_can_be_turned_on(session_factory, settings, tmp_path, path):
    """...and a deployment that wants them opts in, rather than opting out."""
    app = create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "docs-blobs"),
        submit=lambda job: None,
        settings=settings.model_copy(update={"docs_enabled": True}),
    )
    assert TestClient(app).get(path).status_code == 200


READ_ROUTES = [
    ("GET", "/receipts", {"reviewer", "admin"}),
    ("GET", "/receipts/{id}", {"reviewer", "admin"}),
    ("GET", "/metrics", {"reviewer", "admin"}),
    # P4.T5 additions (§5.3): each of these is a bare GET against `receipt_id`
    # with no body, so it fits this table as a genuine one-line addition.
    ("GET", "/receipts/{id}/image", {"reviewer", "admin"}),
    ("GET", "/review/next", {"reviewer", "admin"}),
    ("GET", "/export/xlsx", {"admin"}),
    # Not a P4.T5 receipt route: the admin UI's reload path (design 2026-08-05 §2).
    ("GET", "/auth/me", {"reviewer", "admin"}),
    # Also the admin UI's and also not a receipt route: the queue listing
    # (design 2026-08-05 §3). Its row is about status codes only -- see the
    # block comment below for what this table cannot say about it.
    ("GET", "/review/tasks", {"reviewer", "admin"}),
]


@pytest.mark.parametrize("method,path,allowed", READ_ROUTES)
@pytest.mark.parametrize("actor", ["anonymous", "api_key", "reviewer", "admin"])
def test_auth_matrix(clients, method, path, allowed, actor, receipt_id):
    response = clients[actor].request(method, path.format(id=receipt_id))
    if actor in allowed:
        assert response.status_code == 200
    elif actor in {"anonymous", "api_key"}:
        assert response.status_code == 401
    else:
        assert response.status_code == 403


# --------------------------------------------------------------------------- #
# P4.T5: the two write routes whose auth is still pure role/actor (§5.3),
# but whose request shape (files, a JSON body) does not fit a bare
# ``clients[actor].request(method, path)`` call. Kept in this module,
# against the same `clients` fixture, rather than a second matrix in
# `tests/test_api_write.py` (ambiguity resolution #7).
#
# `POST /review/{id}/complete` is deliberately NOT added here: per §5.3 it
# is "reviewer, admin", but the actual rule (ambiguity resolution #1) is
# "assignee or admin" -- a reviewer who is not the assignee gets 403 despite
# holding an allowed role. That is not a role/actor predicate this table's
# boolean-per-role shape can express; it is covered behaviourally in
# `tests/test_api_write.py` instead
# (`test_a_reviewer_cannot_complete_someone_elses_task` and
# `test_an_admin_can_complete_a_task_assigned_to_someone_else`).
#
# `GET /review/tasks` is the second route this table cannot fully express,
# and it differs from that one by taking a row anyway: both roles do get 200,
# so the boolean-per-role shape is right about the status code and the row
# above is true as far as it goes. What the table cannot say is that the two
# roles get *different rows back* (ADR-0026) -- a difference in content, not
# in access -- so its row covers status codes only, and the content half is
# pinned behaviourally at the bottom of this module by
# `test_the_reviewer_scope_never_returns_someone_elses_name`,
# `test_a_reviewer_sees_their_own_claimed_task` and
# `test_an_admin_sees_a_task_assigned_to_someone_else` -- one per half of the
# reviewer scope, plus the admin's.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("actor", ["anonymous", "api_key", "reviewer", "admin"])
def test_upload_auth_matrix(clients, actor):
    """POST /upload: reviewer and admin may upload; an unauthenticated
    caller may not.

    ``clients["api_key"]``'s header does not match any configured key (this
    module's shared ``settings`` fixture never sets ``RECEIPTS_API_KEY`` --
    see ``require_upload``'s docstring: an unset key rejects every header,
    including a well-formed one), so it behaves exactly like ``anonymous``
    here, the same as it does against every other route in this matrix. The
    positive case -- a correctly configured key genuinely uploading, and
    genuinely nothing else -- is `test_the_api_key_can_upload_but_nothing_
    else` in ``tests/test_api_write.py``, which configures a real key.
    """
    response = clients[actor].post(
        "/upload", files={"file": ("r.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 32, "image/jpeg")}
    )
    if actor in {"reviewer", "admin"}:
        assert response.status_code == 202
    else:
        assert response.status_code == 401


@pytest.mark.parametrize("actor", ["anonymous", "api_key", "reviewer", "admin"])
def test_patch_auth_matrix(clients, actor, receipt_id):
    """PATCH /receipts/{id}: reviewer and admin only -- the machine key
    authorizes upload and nothing else (§5.3).
    """
    response = clients[actor].patch(f"/receipts/{receipt_id}", json={})
    if actor in {"reviewer", "admin"}:
        assert response.status_code == 200
    else:
        assert response.status_code == 401


# --------------------------------------------------------------------------- #
# GET /review/tasks (design 2026-08-05 §3): equal access, role-dependent
# content. A read route -- the write-route block comment above introduces
# `test_upload_auth_matrix` and `test_patch_auth_matrix` and stops here.
# --------------------------------------------------------------------------- #


def _extra_tasks(session_factory) -> None:
    """Three more tasks so a scope has something to hide.

    Every row is produced through the **public queue API** -- enqueue, claim,
    close -- so the shapes are exactly the ones the system can actually reach,
    rather than hand-built rows that might not be.

    ``next_task`` resumes before it claims (ADR-0016), so carol's second call
    would return her first task unchanged; closing the first is what lets her
    hold one ``DONE`` row and one ``IN_PROGRESS`` row.

    **Carol's first claim takes the *seeded* task, not one of these three.**
    ``_seed`` enqueues ``RECEIPT_B`` at priority 1 and these are priority 2,
    and the queue serves the lowest priority number first -- so the ``DONE``
    row ends up being ``RECEIPT_B``'s and the ``IN_PROGRESS`` row is one of
    these. The end state is four tasks: one ``DONE`` (carol), one
    ``IN_PROGRESS`` (carol), two ``OPEN`` and unassigned. Every assertion
    below is written against that end state, so do not "fix" the priorities
    without re-reading them.
    """
    with session_factory() as session:
        for _ in range(3):
            extra_id = uuid.uuid4()
            session.add(
                Receipt(
                    id=extra_id,
                    status=ReceiptStatus.NEEDS_REVIEW,
                    confidence=Decimal("0.400"),
                    image_key=f"receipts/2026/08/{extra_id}/original.jpg",
                    image_phash="",
                )
            )
            session.flush()
            enqueue_review(session, extra_id, reason="needs_review", priority=2)

        first = next_task(session, "carol")
        assert first is not None
        close_task(session, first.id)
        second = next_task(session, "carol")
        assert second is not None
        session.commit()


def _claim_as(session_factory, assignee: str) -> None:
    """Hand ``assignee`` one open task through the public queue API.

    ``next_task`` resumes before it claims (ADR-0016), and ``assignee`` holds
    nothing at the point this is called, so it genuinely claims: an ``OPEN``
    row leaves that state carrying this name.

    Kept as a separate helper rather than folded into ``_extra_tasks`` as a
    claimant parameter, so that helper's end state -- four tasks, one ``DONE``
    and one ``IN_PROGRESS`` both carol's, two ``OPEN`` and unassigned -- stays
    exactly what the six tests written against it already assume.
    """
    with session_factory() as session:
        task = next_task(session, assignee)
        assert task is not None
        session.commit()


def test_the_reviewer_scope_never_returns_someone_elses_name(session_factory, reviewer_client):
    """The privacy pin for ADR-0026's dual scope.

    A reviewer's page may contain only rows whose ``assigned_to`` is NULL or
    their own. That holds because every path producing an ``OPEN`` row clears
    ``assigned_to`` -- pinned per-path in ``tests/test_review_queue.py`` -- and
    this asserts the property the *route* actually claims, which is where a
    fourth ``OPEN``-producer would show up.

    Goes red if ``list_tasks`` stops scoping: carol's ``IN_PROGRESS`` row
    arrives with her name on it.
    """
    _extra_tasks(session_factory)

    body = reviewer_client.get("/review/tasks?limit=200").json()

    # Not decoration: without rows this assertion set is vacuous, and a
    # vacuously-passing privacy test is worse than none.
    assert body["items"]
    assert {row["assigned_to"] for row in body["items"]} <= {None, "alice"}


def test_a_reviewer_sees_their_own_claimed_task(session_factory, reviewer_client):
    """The other half of the reviewer scope: "plus that caller's own rows".

    ``test_the_reviewer_scope_never_returns_someone_elses_name`` bounds the page
    from **above** -- no name but alice's may appear -- and that bound is
    satisfied vacuously as long as every visible row is unassigned. Nothing else
    in this module ever assigns a row to alice (``_extra_tasks`` claims only as
    carol), so without this test the ``user.username`` half of the route's
    ``visible_to`` mapping is a surviving mutant: replacing it with any constant
    other than "carol" leaves every other test in this module green while a
    reviewer silently loses their own claimed task from the queue page.

    Asserted in this order on purpose. The ``assigned_to == "alice"`` assertion
    is the one this test exists for; the subset assertion after it re-checks the
    upper bound now that a *real* name is genuinely in the page rather than only
    NULLs, so the privacy pin above is no longer the only thing standing between
    the two halves.
    """
    _extra_tasks(session_factory)
    _claim_as(session_factory, "alice")

    body = reviewer_client.get("/review/tasks?limit=200").json()

    assert any(row["assigned_to"] == "alice" for row in body["items"])
    assert {row["assigned_to"] for row in body["items"]} <= {None, "alice"}


def test_an_admin_sees_a_task_assigned_to_someone_else(session_factory, admin_client):
    """The other half of the scope: an admin needs the holder's name, because
    that is who they are taking the task away from (ADR-0025).
    """
    _extra_tasks(session_factory)

    body = admin_client.get("/review/tasks?limit=200").json()

    assert any(row["assigned_to"] == "carol" for row in body["items"])


def test_tasks_come_back_in_queue_order(session_factory, admin_client):
    """Lower priority number first -- the same total order ``_claim_stmt``
    uses. The seeded ``RECEIPT_B`` task is priority 1 and ``_extra_tasks``
    adds priority 2s, so the seeded one must lead.
    """
    _extra_tasks(session_factory)

    items = admin_client.get("/review/tasks?limit=200").json()["items"]

    priorities = [row["priority"] for row in items]
    assert priorities == sorted(priorities)
    assert priorities[0] == 1


def test_has_more_is_true_only_when_a_further_page_exists(session_factory, admin_client):
    """Read off a ``limit + 1`` fetch, like ``GET /receipts`` -- never a
    ``COUNT(*)`` per page. Four tasks total: the seeded one plus three.
    """
    _extra_tasks(session_factory)

    first = admin_client.get("/review/tasks?limit=2").json()
    rest = admin_client.get("/review/tasks?limit=2&offset=2").json()

    assert len(first["items"]) == 2
    assert first["has_more"] is True
    assert len(rest["items"]) == 2
    assert rest["has_more"] is False


def test_the_state_filter_narrows_and_rejects_an_unknown_value(session_factory, admin_client):
    _extra_tasks(session_factory)

    in_progress = admin_client.get("/review/tasks?state=in_progress").json()

    assert in_progress["items"]
    assert {row["state"] for row in in_progress["items"]} == {"in_progress"}
    assert admin_client.get("/review/tasks?state=nonsense").status_code == 422


def test_the_literal_tasks_path_is_not_captured_by_a_task_id_route(admin_client):
    """``/review/tasks`` must never be matched as ``/review/{task_id}``.
    FastAPI matches in declaration order, so a future ``GET /review/{task_id}``
    declared *before* this route would bind ``task_id="tasks"`` and fail UUID
    validation with a 422. No such route exists today; this asserts the
    outcome rather than the absence, so it keeps guarding if one is added.
    """
    assert admin_client.get("/review/tasks").status_code == 200
