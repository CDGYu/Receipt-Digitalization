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
from receipts.persist.models import (  # noqa: E402
    Base,
    Correction,
    LineItem,
    Receipt,
    ValidationFinding,
)
from receipts.persist.repository import _LINE_ITEM_FIELDS, _RECEIPT_FIELDS  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.persist.users import ROLE_ADMIN, ROLE_REVIEWER, create_user  # noqa: E402
from receipts.review.api import MAX_PAGE_LIMIT, MAX_PAGE_OFFSET, create_app  # noqa: E402
from receipts.review.queue import close_task, enqueue_review, next_task  # noqa: E402
from receipts.review.serializers import correction_summary  # noqa: E402
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
                # A different party from the merchant, with a different TIN --
                # both distinct from every other value on this row, so a
                # declared detail path that pointed at the wrong column could
                # not pass the comparison above.
                buyer_name_raw="IDEAL SOURCE",
                buyer_tax_id="123-456-789-000",
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
    # Nested, like ``totals``: the buyer is a schema object
    # (:class:`receipts.extract.schema.Buyer`), and the two correction paths
    # are ``buyer.name``/``buyer.tax_id``, so what a reviewer reads is
    # addressed exactly the way what they send back is.
    "buyer_name_raw": ("buyer", "name"),
    "buyer_tax_id": ("buyer", "tax_id"),
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


#: ``line_items`` column -> the key ``_line_item`` exposes it at. Written out
#: for the same reason the receipt map above is: nothing turns a column name
#: into a response key, and the two happening to coincide today is not a rule.
#: A column deliberately renamed on the way out is declared here; a column with
#: no key at all is the defect this exists to catch.
_LINE_ITEM_COLUMN_TO_DETAIL_KEY = {
    "position": "position",
    "description_raw": "description_raw",
    "sku": "sku",
    "qty": "qty",
    "unit": "unit",
    "unit_price": "unit_price",
    "line_total": "line_total",
    # Correctable since the blank-pre-printed-row milestone, and readable only
    # since the branch review that found it missing. A reviewer is shown a
    # normal editable row either way, and this flag decides whether that row
    # leaves the accounting ledger and whether the totals reconcile against it.
    # It is deliberately NOT editable in the review UI -- see ISSUE-006; being
    # shown a value you cannot edit is safe, overwriting one you were never
    # shown is not.
    "is_template_row": "is_template_row",
}


def test_every_correctable_line_item_column_is_readable_in_the_detail(
    reviewer_client, session_factory
):
    """The P5.T3b property, one dict over.

    ``test_every_correctable_receipt_column_is_readable_in_the_detail`` binds
    ``_RECEIPT_FIELDS`` to ``receipt_detail``. It binds nothing about line
    items, and the same defect it exists to catch reappeared in
    ``_LINE_ITEM_FIELDS``: ``is_template_row`` was correctable -- a dotted
    ``PATCH`` of it returns 200 and flips the flag -- while ``_line_item``
    emitted no key for it, so a reviewer could overwrite what the machine read
    without ever being shown it. That flag decides what leaves the accounting
    ledger (``_purchases`` in ``export/xlsx.py``) and what the totals reconcile
    against (``_purchased`` in ``validate/rules.py``).

    Stated as a property over ``_LINE_ITEM_FIELDS``, not as a list of eight
    names, so it fires on the next unpaired addition rather than on the next
    reviewer to notice. The failure names the missing column, which a count
    could not.

    **Editability is a separate judgement and is not asserted here.**
    ``position`` is the worked precedent: readable, deliberately not offered in
    the UI, with a measured reason at ``LineItemsTable.tsx``. Reading and
    writing are pinned apart on purpose --
    ``test_every_correctable_receipt_path_is_offered_by_the_review_client``
    (``tests/test_repository.py``) is what binds the *editable* set, and it
    deliberately excludes line items.
    """
    receipt_uuid = uuid.uuid4()
    with session_factory() as session:
        session.add(
            Receipt(
                id=receipt_uuid,
                status=ReceiptStatus.NEEDS_REVIEW,
                confidence=Decimal("0.500"),
                merchant_name_raw="PILIPINAS FUEL",
                txn_date=date(2026, 7, 5),
                currency="PHP",
                total=Decimal("2000.00"),
                image_key="receipts/2026/07/li/original.jpg",
                image_phash="",
                # Every correctable column distinct and non-null, for the reason
                # ``_seed`` gives RECEIPT_B distinct values: two columns sharing
                # one value (or both being NULL) would let a wrong key through.
                # ``is_template_row=True`` is the non-default setting, so a key
                # wired to the wrong column cannot pass by accident.
                line_items=[
                    LineItem(
                        position=3,
                        description_raw="PREMIUM 97",
                        sku="SKU-97",
                        qty=Decimal("2.5000"),
                        unit="L",
                        unit_price=Decimal("70.0000"),
                        line_total=Decimal("175.0000"),
                        is_template_row=True,
                    )
                ],
            )
        )
        session.commit()

    body = reviewer_client.get(f"/receipts/{receipt_uuid}").json()
    assert len(body["line_items"]) == 1, body["line_items"]
    item = body["line_items"][0]

    with session_factory() as session:
        stored = session.get(Receipt, receipt_uuid).line_items[0]
        columns = {
            column: getattr(stored, column) for column in _LINE_ITEM_COLUMN_TO_DETAIL_KEY
        }

    correctable = {column for column, _coerce in _LINE_ITEM_FIELDS.values()}
    assert correctable == set(_LINE_ITEM_COLUMN_TO_DETAIL_KEY), (
        "_LINE_ITEM_FIELDS changed: add the new column to "
        "_LINE_ITEM_COLUMN_TO_DETAIL_KEY naming the key _line_item exposes "
        "*that column's value* at -- the assertion below compares them, so a "
        "key that merely exists fails"
    )
    assert [
        column
        for column, key in sorted(_LINE_ITEM_COLUMN_TO_DETAIL_KEY.items())
        if key not in item
    ] == [], (
        "a column a reviewer may correct has no key in the line item "
        "receipt_detail returns, so they can overwrite what the machine read "
        "without being shown it. Add it to _line_item "
        "(review/serializers.py)."
    )
    assert {
        column: item[key] for column, key in sorted(_LINE_ITEM_COLUMN_TO_DETAIL_KEY.items())
    } == {column: _rendered(value) for column, value in sorted(columns.items())}


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


def test_detail_returns_the_buyer_under_its_own_key(reviewer_client, receipt_id):
    """The "Sold To" block a reviewer has to check against the paper.

    Nested under ``buyer`` so the key path is the correction path
    (``buyer.name`` / ``buyer.tax_id``) rather than a second vocabulary, and
    asserted alongside ``merchant_name_raw`` because the two names are the
    thing most easily swapped: a sales invoice prints both, and a payload that
    returned the merchant under ``buyer`` would look entirely plausible.
    """
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()

    assert body["buyer"] == {"name": "IDEAL SOURCE", "tax_id": "123-456-789-000"}
    assert body["merchant_name_raw"] == "TOTAL WINE"


def test_a_receipt_with_no_buyer_returns_nulls_not_an_absent_key(
    reviewer_client, pending_receipt_id
):
    """``null`` over confident-wrong, and the key is always there to render.

    ``RECEIPT_C`` is the ``pending`` row: nothing has been extracted onto it,
    so both buyer columns are NULL. The reviewer's form still has to draw the
    two fields, so ``buyer`` is an object with null members rather than a
    missing key -- an absent key is a client-side crash, and ``""`` would read
    as a buyer whose name is blank.
    """
    body = reviewer_client.get(f"/receipts/{pending_receipt_id}").json()

    assert body["buyer"] == {"name": None, "tax_id": None}


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


# `GET /receipts/{id}/corrections` is deliberately NOT in this table. The
# matrix asserts 200 for every actor in `allowed`, but a reviewer reaching that
# route gets 200 or 403 depending on a `review_tasks` row, not on their role --
# the same reason `POST /review/{id}/complete` is absent. Adding it would either
# assert something false or silently depend on whether the `receipt_id` fixture
# happens to be claimed. Its 401 half is pinned by
# `test_corrections_require_a_session`, and its 200/403 split by the four tests
# beside it.
READ_ROUTES = [
    ("GET", "/receipts", {"reviewer", "admin"}),
    ("GET", "/receipts/{id}", {"reviewer", "admin"}),
    ("GET", "/metrics", {"reviewer", "admin"}),
    # P4.T5 additions (§5.3): each of these is a bare GET against `receipt_id`
    # with no body, so it fits this table as a genuine one-line addition.
    ("GET", "/receipts/{id}/image", {"reviewer", "admin"}),
    ("GET", "/review/next", {"reviewer", "admin"}),
    ("GET", "/export/xlsx", {"admin"}),
    # M2 (design 2026-08-19, decision 3), and beside the workbook deliberately:
    # the two export routes share a scope predicate and differ only in guard.
    ("GET", "/export/receipts", {"reviewer", "admin"}),
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


def test_correction_summary_reads_every_key_off_the_row_it_was_given():
    """Every key is read from the row, and ``null`` is not ``""`` on either side.

    ``value_before``/``value_after`` are already text -- ``_as_text`` rendered
    them at write time. Re-parsing them as ``Decimal`` to re-render would invent
    precision the audit trail never recorded, and would fail outright on the
    ``field_path``s that are not money. ``None`` stays ``None``: the field had no
    value on that side of the change, which is not ``"0"`` and not ``""``.

    **Two rows, because one cannot tell a key that is read from a key that is
    hardcoded to that one row's own value.** Against a lone fixture holding
    ``value_before=None`` and ``corrected_by="alice"``, the constants
    ``"value_before": None`` and ``"corrected_by": "alice"`` both pass -- as
    does ``correction.value_after or ""``, which only reveals itself on a row
    whose ``value_after`` *is* ``None``. Three such mutants survived a
    single-row version of this test.

    So: row A and row B differ in **every** rendered value, and they carry the
    null on **opposite** text fields -- A has no ``value_before``, B has no
    ``value_after``. That exercises each text field as both null and text, in
    both directions, which is what pins ADR-0027 section 5 for both of them
    rather than for ``value_before`` alone.

    The last two assertions are the bound, and they guard the *fixtures*, not
    the code:

      * no key may render the same value for both rows -- otherwise a constant
        would satisfy both dicts above;
      * no row may render the same value under two keys -- otherwise a key
        reading the wrong attribute of the right row would still pass.

    Together those make "every key is read off the row it was given" hold for
    every key in the dict, including keys added later, instead of for the
    handful anyone thought to check by hand.
    """
    row_a = Correction(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
        receipt_id=RECEIPT_B,
        field_path="receipt.total",
        value_before=None,
        value_after="1000",
        corrected_by="alice",
        created_at=datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC),
    )
    row_b = Correction(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000bb"),
        receipt_id=RECEIPT_A,
        field_path="line_items[0].qty",
        value_before="900",
        value_after=None,
        corrected_by="bob",
        created_at=datetime(2026, 7, 4, 17, 30, 5, tzinfo=UTC),
    )

    rendered_a = correction_summary(row_a)
    rendered_b = correction_summary(row_b)

    assert rendered_a == {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "field_path": "receipt.total",
        "value_before": None,
        "value_after": "1000",
        "corrected_by": "alice",
        "created_at": "2026-07-03T09:00:00+00:00",
    }
    assert rendered_b == {
        "id": "00000000-0000-0000-0000-0000000000bb",
        "field_path": "line_items[0].qty",
        "value_before": "900",
        "value_after": None,
        "corrected_by": "bob",
        "created_at": "2026-07-04T17:30:05+00:00",
    }

    constant_keys = sorted(key for key in rendered_a if rendered_a[key] == rendered_b[key])
    assert not constant_keys, (
        f"{constant_keys} render the same for both rows, so a hardcoded constant "
        "would satisfy both dicts above -- give the two fixtures different values"
    )

    for label, rendered in (("A", rendered_a), ("B", rendered_b)):
        values = list(rendered.values())
        assert len(set(values)) == len(values), (
            f"row {label} renders one value under two keys, so a key reading the "
            f"wrong attribute would still satisfy its dict above: {rendered}"
        )


# --------------------------------------------------------------------------- #
# GET /receipts/{receipt_id}/corrections (P5.T4): existence before scope, and
# 403 is not 404 and is not an empty 200.
# --------------------------------------------------------------------------- #


def _corrections_for(session_factory, receipt_id: uuid.UUID, *, by: str = "alice") -> None:
    """Two audit rows, timestamps explicit so ordering is under test."""
    with session_factory() as session:
        session.add_all(
            [
                Correction(receipt_id=receipt_id, field_path="receipt.total",
                           value_before="900", value_after="1000", corrected_by=by,
                           created_at=datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC)),
                Correction(receipt_id=receipt_id, field_path="payment.method",
                           value_before=None, value_after="VISA", corrected_by=by,
                           created_at=datetime(2026, 7, 3, 9, 0, 1, tzinfo=UTC)),
            ]
        )
        session.commit()


def test_an_admin_reads_a_receipt_they_never_held(session_factory, admin_client, receipt_id):
    _corrections_for(session_factory, receipt_id)

    response = admin_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 200
    body = response.json()
    assert [row["field_path"] for row in body["items"]] == ["receipt.total", "payment.method"]
    assert body["has_more"] is False


def test_the_holding_reviewer_reads_the_history(session_factory, reviewer_client, receipt_id):
    """``_claim_as`` hands alice the seeded priority-1 task, which is
    ``RECEIPT_B``'s -- the same receipt the ``receipt_id`` fixture names."""
    _corrections_for(session_factory, receipt_id)
    _claim_as(session_factory, "alice")

    response = reviewer_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_a_reviewer_who_never_held_the_receipt_is_refused(
    session_factory, reviewer_client, receipt_id
):
    """The seeded task for ``RECEIPT_B`` is ``OPEN`` and unassigned, so alice
    does not hold it. 403, not 404 and not an empty 200: the receipt exists
    (``GET /receipts/{id}`` already discloses that to any signed-in user), and
    "not permitted" is not "none exist".
    """
    _corrections_for(session_factory, receipt_id)

    response = reviewer_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 403


def test_an_unknown_receipt_is_404_even_for_an_admin(admin_client):
    """Existence is checked **before** scope, so a probe for a random id cannot
    be told apart from any other absent receipt."""
    response = admin_client.get(f"/receipts/{uuid.uuid4()}/corrections")

    assert response.status_code == 404


def test_an_in_scope_receipt_with_no_corrections_is_an_empty_200(
    session_factory, reviewer_client, receipt_id
):
    """The other half of the 403 above. Together these two are what make the
    empty list mean something: with only one of them, a route that returned
    ``{"items": []}`` for *everything* would pass.
    """
    _claim_as(session_factory, "alice")

    response = reviewer_client.get(f"/receipts/{receipt_id}/corrections")

    assert response.status_code == 200
    assert response.json() == {"items": [], "has_more": False}


@pytest.mark.parametrize("actor", ["anonymous", "api_key"])
def test_corrections_require_a_session(clients, receipt_id, actor):
    """Written out rather than added to ``READ_ROUTES`` -- see the comment on
    that table for why this route cannot express itself there."""
    assert clients[actor].get(f"/receipts/{receipt_id}/corrections").status_code == 401


def test_corrections_paginate_in_both_directions(session_factory, admin_client, receipt_id):
    """``has_more`` is pinned **true and false**. ``GET /receipts``' own
    ``has_more`` is unpinned in the ``True`` direction -- a constant
    ``has_more: False`` survives all 979 tests, measured at the admin-UI-routes
    close. This route does not inherit that hole.
    """
    _corrections_for(session_factory, receipt_id)

    first = admin_client.get(f"/receipts/{receipt_id}/corrections?limit=1").json()
    assert [row["field_path"] for row in first["items"]] == ["receipt.total"]
    assert first["has_more"] is True

    second = admin_client.get(f"/receipts/{receipt_id}/corrections?limit=1&offset=1").json()
    assert [row["field_path"] for row in second["items"]] == ["payment.method"]
    assert second["has_more"] is False


# --------------------------------------------------------------------------- #
# Three clauses the eight tests above left decorative, found by mutating each
# clause of the route one at a time. Each of these three mutants survived the
# **full** suite -- not just this module -- as that suite stood at `6536d0f`,
# the commit before these tests. Each is killed by the test beside it now, so
# read every "survived" below as history, not as a live property.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("actor", ["reviewer", "admin"])
def test_an_unknown_receipt_is_404_for_every_signed_in_role(clients, actor):
    """"Existence before scope" is the route's contract, and an admin cannot
    see the order.

    ``test_an_unknown_receipt_is_404_even_for_an_admin`` asks the one role that
    cannot tell: an admin's ``visible_to`` is ``None``, so ``list_corrections``
    returns ``[]`` and never ``None``, and the 404 comes back whichever side of
    the scope call the existence check sits on. Measured -- moving that check
    below the ``rows is None`` branch left the whole suite green as it stood at
    ``6536d0f``, the commit before this test existed. This test is what closes
    it, so re-running that mutation today is expected to fail *here*; a count
    would rot, and a present-tense "survives" is now simply false.

    A reviewer separates them. An id that names no receipt has no
    ``review_tasks`` row either, so the scope call returns ``None`` and the
    swapped order answers **403** -- telling a caller "not yours" about a
    receipt that does not exist, and making an absent receipt distinguishable
    by status code from a real one they may not read. That is the disclosure
    the ordering exists to prevent, so the property is pinned for every role
    that can reach the route.
    """
    unknown = uuid.uuid4()

    assert clients[actor].get(f"/receipts/{unknown}/corrections").status_code == 404


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_the_corrections_paging_window_is_refused_outside_its_bounds(
    admin_client, receipt_id, query
):
    """The paging window's declared bounds were decorative.

    Measured separately: dropping ``ge=1, le=200`` from ``limit``, and dropping
    ``ge=0`` from ``offset``, each left the whole suite green as it stood at
    ``6536d0f``, the commit before these cases existed. Unbounded,
    ``?limit=100000`` reaches ``list_corrections`` and asks SQLite for 100001
    rows in one query. ``GET /receipts`` has had this pinned since P4.T4
    (``test_list_caps_the_page_size``); this route inherited the declaration
    without the pin.

    **What this closes:** ``limit`` in both directions, and ``offset`` below
    zero. Those three are refused by request validation, before any query runs.

    **The ceiling on ``offset`` is not here.** It was missing entirely when
    these cases were written -- ``?offset=2**63`` satisfied ``ge=0``, reached
    SQLite and raised ``OverflowError`` -- and it was closed for all three
    paginated routes at once by the shared page bound (ADR-0034), which is
    pinned by ``test_every_paginated_route_shares_one_page_bound`` and
    ``test_an_out_of_range_offset_is_refused_by_validation_on_every_paged_route``
    rather than by another case bolted onto this route-specific test.
    """
    response = admin_client.get(f"/receipts/{receipt_id}/corrections?{query}")

    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# The shared page bound (ADR-0034)
# --------------------------------------------------------------------------- #

#: The routes that page, as URL templates. This is a list, so it is a
#: claim (review standard 20) -- and
#: ``test_the_behavioural_cases_cover_every_paginated_route`` is what checks it,
#: by deriving the same set from the built app. No count is written here: one
#: goes stale at the next paginated route, and the list is immediately below.
PAGINATED_PATHS = [
    "/receipts",
    "/review/tasks",
    "/receipts/{receipt_id}/corrections",
    "/export/receipts",
]


def _walk_routes(carrier):
    """Every route, recursing through ``_IncludedRouter``.

    ``include_router`` wraps the auth router, so a flat walk of ``app.routes``
    cannot see anything it carries -- the trap ADR-0028 section 3 names.
    Nothing under ``/auth/*`` pages today, and a walk that cannot see those
    routes could not promise that.
    """
    for route in carrier.routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from _walk_routes(inner)
        else:
            yield route


def _declared_upper_bound(field):
    """A query param's declared ``le``, or ``None`` when it declares none.

    Under Pydantic v2 the constraints live in ``field_info.metadata`` as
    ``annotated_types`` objects (``[Ge(ge=0), Le(le=1000000)]``); there is no
    ``field_info.le`` to read. Probed against the built app rather than
    assumed -- reading ``.le`` directly returns the attribute's absence for
    every param, bounded or not, which would make this helper answer ``None``
    always and the pin below vacuous.
    """
    for constraint in field.field_info.metadata:
        if hasattr(constraint, "le"):
            return constraint.le
    return None


def _paginated_params(app, name):
    """``{route path: declared upper bound}`` for every param called *name*."""
    found = {}
    for route in _walk_routes(app):
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for field in dependant.query_params:
            if field.name == name:
                found[route.path] = _declared_upper_bound(field)
    return found


@pytest.mark.parametrize(
    ("param", "expected"),
    [("offset", MAX_PAGE_OFFSET), ("limit", MAX_PAGE_LIMIT)],
)
def test_every_paginated_route_shares_one_page_bound(app, param, expected):
    """One bound, every paginated route, both parameters.

    The property is stated over the **built app**, not over three declarations,
    which is what makes it converge: a fourth paginated route that re-declares
    ``offset`` by hand fails here without anybody having thought of that route.
    That is how the third route acquired the defect in the first place -- it
    copied ``Query(0, ge=0)`` verbatim from a brief.

    Equality rather than "some bound exists" is deliberate: *shared* is the
    property, so a route that invents its own ceiling is as much a failure as
    one that declares none.
    """
    declared = _paginated_params(app, param)

    assert declared, f"no route declares a {param!r} query parameter"
    assert declared == dict.fromkeys(declared, expected)


def test_the_behavioural_cases_cover_every_paginated_route(app):
    """``PAGINATED_PATHS`` is written down, so the app is asked to confirm it."""
    from_app = set(_paginated_params(app, "offset"))

    assert from_app == set(PAGINATED_PATHS)


@pytest.mark.parametrize("path", PAGINATED_PATHS)
@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (0, 200),
        (MAX_PAGE_OFFSET, 200),
        (MAX_PAGE_OFFSET + 1, 422),
        (2**63 - 1, 422),
        (2**63, 422),
    ],
)
def test_an_out_of_range_offset_is_refused_by_validation_on_every_paged_route(
    admin_client, receipt_id, path, offset, expected
):
    """``?offset=2**63`` was an unhandled 500 on every paged route that then existed.

    "Then" is load-bearing and the count is deliberately not written: routes
    added after the bound landed were born declaring ``PageOffset`` and never
    carried the defect, so a sentence saying "all of these routes" would grow
    false as this parametrisation grows.

    ``offset`` was declared ``Query(0, ge=0)`` with no ceiling, so ``2**63``
    satisfied validation, reached SQLite and raised ``OverflowError`` -- which
    is an ``ArithmeticError``, not a ``ValueError``, so none of
    ``_install_error_handlers``' three handlers caught it and the body came
    back as Starlette's plain ``Internal Server Error`` rather than this
    service's ``{"error": {"message": ...}}``.

    The bound makes an over-large offset behave exactly like ``offset=-1``
    already did: refused by request validation, before any query runs. Out of
    range is out of range in both directions, and neither direction reaches
    the database.

    ``MAX_PAGE_OFFSET`` and ``MAX_PAGE_OFFSET + 1`` are both here so the
    assertion is a boundary rather than an anecdote; ``2**63 - 1`` is the
    largest offset that used to answer 200 and now does not, which is the one
    behaviour change a caller could notice.
    """
    url = path.format(receipt_id=receipt_id)

    assert admin_client.get(url, params={"offset": offset}).status_code == expected


@pytest.mark.parametrize("path", PAGINATED_PATHS)
def test_no_offset_reaches_the_database_as_a_500(admin_client, receipt_id, path):
    """The regression this closes, swept rather than sampled at one value.

    **How the defect surfaces here is not a 500.** ``TestClient`` is built with
    ``raise_server_exceptions=True``, so an unhandled ``OverflowError`` in the
    route propagates into this test rather than being turned into a response --
    measured: before the bound, this test failed with ``OverflowError: Python
    int too large to convert to SQLite INTEGER``, not with a failed assertion.
    Over a real ASGI server the same input answers 500 with Starlette's plain
    ``Internal Server Error`` body. Either way the request must not reach
    SQLite, which is what the sweep checks; the ``assert`` is the backstop for
    a future handler that catches the overflow and returns 500 instead of
    letting it escape.
    """
    url = path.format(receipt_id=receipt_id)
    offsets = [0, 1, MAX_PAGE_OFFSET - 1, MAX_PAGE_OFFSET, MAX_PAGE_OFFSET + 1, 2**63 - 1, 2**63]

    statuses = {
        offset: admin_client.get(url, params={"offset": offset}).status_code
        for offset in offsets
    }

    assert 500 not in statuses.values(), statuses


# --------------------------------------------------------------------------- #
# The two export routes' filter surface (design 2026-08-19, decision 1)
# --------------------------------------------------------------------------- #


def _query_param_names(app, path):
    """Every query parameter one route path declares **directly**, off the
    built app.

    Read the way ``_paginated_params`` reads it -- ``route.dependant``'s
    ``query_params`` rather than the source signature.

    ``directly`` is the bound: a sub-dependency's query parameters live in
    ``dependant.dependencies`` and this does not recurse. Both export routes
    declare every filter inline, so nothing is missed today.
    """
    names = set()
    for route in _walk_routes(app):
        dependant = getattr(route, "dependant", None)
        if dependant is None or route.path != path:
            continue
        names.update(field.name for field in dependant.query_params)
    return names


def test_the_two_export_routes_declare_the_same_filters(app):
    """One filter surface at both ends, derived from the app rather than listed.

    ``GET /export/receipts`` and ``GET /export/xlsx`` answer for the same set of
    receipts (design 2026-08-19, decision 1). The section 8 property that pins
    that is witnessed on the ``status`` axis only -- it compares the two routes'
    ids for the default scope and for ``status=pending``, and never sends a
    merchant, a date or a confidence. A filter added to one route and not the
    other, or two of them transposed, changes what one side answers for
    arguments no test sends, and every test here stays green.

    This names no filter, so it fails on the next filter added to either route
    without anybody having thought of that filter: the bounded-property shape
    ADR-0045 decision 5 asks for. An enumeration of the filters that exist today
    is the thing that would go stale instead.

    ``limit`` and ``offset`` are subtracted because the list pages and the
    workbook does not -- the workbook is bounded by ``_EXPORT_MAX_ROWS`` and
    refuses rather than truncating. That is the one difference between the two
    surfaces that is deliberate.

    Equality rather than a subset in one direction: a filter the workbook
    honours and the list does not is the same defect seen from the other end.
    """
    listing = _query_param_names(app, "/export/receipts")
    workbook = _query_param_names(app, "/export/xlsx")

    # Anti-vacuity: two empty sets are equal, and a mistyped path yields them.
    assert workbook, "no query parameters found on /export/xlsx"
    assert listing - {"limit", "offset"} == workbook


# --------------------------------------------------------------------------- #
# GET /receipts/{id}/progress
# --------------------------------------------------------------------------- #


def _progress_client(session_factory, settings, tmp_path, reader) -> TestClient:
    """A signed-in client whose app reads progress from `reader`.

    Built inline rather than from the `app` fixture, following `empty_client`:
    this variant needs an argument the shared fixture does not pass. The
    injected reader is what keeps the suite offline -- `_default_read_progress`
    is the only thing that touches Redis and no test reaches it.
    """
    app = create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "progress-blobs"),
        submit=lambda job: None,
        settings=settings,
        read_progress=reader,
    )
    return _logged_in(app, "alice", "pw-alice")


def test_progress_reports_the_stage_a_reader_supplies(
    session_factory, settings, tmp_path, receipt_id
) -> None:
    from receipts.progress import ProgressEvent

    client = _progress_client(
        session_factory, settings, tmp_path,
        lambda _id: ProgressEvent(stage="extract", detail="attempt 1"),
    )
    reply = client.get(f"/receipts/{receipt_id}/progress")

    assert reply.status_code == 200
    body = reply.json()
    assert body["stage"] == "extract"
    assert body["detail"] == "attempt 1"


def test_progress_still_answers_when_there_is_no_record(
    session_factory, settings, tmp_path, pending_receipt_id
) -> None:
    """Silence is not an error, and it is not "still working" either.

    Progress is narration; the receipt's own status is the truth. A missing
    record answers 200 with a null stage and the real status, so a screen can
    tell "nothing to narrate" from "nothing happened".
    """
    client = _progress_client(session_factory, settings, tmp_path, lambda _id: None)
    reply = client.get(f"/receipts/{pending_receipt_id}/progress")

    assert reply.status_code == 200
    body = reply.json()
    assert body["stage"] is None
    assert body["detail"] is None
    assert body["status"] == "pending"


def test_progress_for_an_unknown_receipt_is_404(
    session_factory, settings, tmp_path
) -> None:
    from receipts.progress import ProgressEvent

    client = _progress_client(
        session_factory, settings, tmp_path,
        lambda _id: ProgressEvent(stage="extract"),
    )
    reply = client.get(f"/receipts/{uuid.uuid4()}/progress")

    assert reply.status_code == 404


def test_progress_needs_a_signed_in_caller(
    session_factory, settings, tmp_path, receipt_id
) -> None:
    """Same guard as every other receipt route: `require_user`."""
    from receipts.progress import ProgressEvent

    app = create_app(
        session_factory=session_factory,
        storage=LocalStorage(tmp_path / "progress-anon-blobs"),
        submit=lambda job: None,
        settings=settings,
        read_progress=lambda _id: ProgressEvent(stage="extract"),
    )
    reply = TestClient(app).get(f"/receipts/{receipt_id}/progress")

    assert reply.status_code == 401


def test_progress_survives_a_reader_that_cannot_answer(
    session_factory, settings, tmp_path, pending_receipt_id, caplog
) -> None:
    """A Redis outage costs the narration, never the status.

    ``_default_read_progress`` catches a record it cannot decode, but not a
    ``ConnectionError`` from redis and not the ``RuntimeError`` ``make_redis``
    raises when ``REDIS_URL`` is unset or the ``worker`` extra is missing --
    the rare failure was guarded and the common one was not. Unguarded, those
    propagate *after* ``status`` has been read, so the caller gets a 500 and
    never learns the receipt's real state: precisely the outcome the ``status``
    field exists to prevent.

    The guard is at the route rather than inside the reader, so it also covers
    an injected reader -- which is what this test is.
    """

    def _cannot_answer(_id):
        raise RuntimeError("redis is unreachable")

    client = _progress_client(session_factory, settings, tmp_path, _cannot_answer)
    reply = client.get(f"/receipts/{pending_receipt_id}/progress")

    assert reply.status_code == 200
    body = reply.json()
    assert body["status"] == "pending"
    assert body["stage"] is None
    assert body["detail"] is None

    # A bare `except` is only an acceptable trade if the cause survives it.
    # Without `exc_info`, this guard would silently erase a bug in a custom
    # reader, and nothing else in the suite would notice it had.
    swallowed = [record for record in caplog.records if record.name == "receipts.review.api"]
    assert swallowed, "the swallowed failure was never logged"
    assert swallowed[-1].levelname == "WARNING"
    assert swallowed[-1].exc_info is not None, "logged without the traceback"
