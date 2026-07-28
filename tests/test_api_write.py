"""Tests for the review API's write routes (P4.T5, spec §14.9).

``pytest.importorskip("fastapi")``/``pytest.importorskip("openpyxl")`` keep
the base test suite offline, matching ``tests/test_api_read.py`` and
``tests/test_xlsx.py``.

Everything runs against a file-backed SQLite database, a ``LocalStorage``
rooted at ``tmp_path``, and a fake ``submit`` that appends to a list instead
of touching Redis/RQ -- the same pattern ``test_api_read.py`` uses.

Fixture design note: ``reviewer_client``/``session_factory`` seed **no
receipts at all** -- only the two accounts. That is load-bearing for
``test_a_rejected_upload_writes_no_row_and_queues_nothing``, which asserts
the *entire* ``receipts`` table is empty after a rejected upload. Every test
that needs a receipt asks for it explicitly (``receipt_id``,
``other_receipt_id``, ``pending_receipt_id``, ``task_id``), and each of
those fixtures inserts its own row into the same shared database the moment
it is requested -- so a test that does not name one never sees it.
``admin_client`` is the one fixture that seeds by side effect (via
``receipt_id``/``other_receipt_id``, plus an open review task): every route
that needs an admin also needs *something* for the admin to act on --
two exportable receipts (so the row-cap test can force an overflow with
``_EXPORT_MAX_ROWS = 1``) and one open task (so ``/review/next`` has
something to claim). ``reviewer_client`` never triggers this, so the upload
tests stay receipt-free.
"""

from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("openpyxl")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from sqlalchemy import select  # noqa: E402

import receipts.review.api as api_module  # noqa: E402
from config.settings import Settings  # noqa: E402
from receipts.ingest.storage import LocalStorage, make_image_key  # noqa: E402
from receipts.persist.models import Base, Correction, Receipt, ReviewTask  # noqa: E402
from receipts.persist.session import make_engine, make_session_factory  # noqa: E402
from receipts.persist.users import ROLE_ADMIN, ROLE_REVIEWER, create_user  # noqa: E402
from receipts.review.api import create_app  # noqa: E402
from receipts.review.queue import enqueue_review, next_task  # noqa: E402
from receipts.score.confidence import ReceiptStatus  # noqa: E402

#: Minimal but genuinely JPEG-sniffable bytes (see
#: ``receipts.ingest.ingest._sniff_content_type``): the ``\xff\xd8`` header
#: is all the validator inspects.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 128 + b"\xff\xd9"

MAIN_RECEIPT = uuid.uuid4()  # receipt_id -- needs_review, image = JPEG_BYTES
OTHER_RECEIPT = uuid.uuid4()  # other_receipt_id -- auto_approved
PENDING_RECEIPT = uuid.uuid4()  # pending_receipt_id -- pending


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "blobs")


@pytest.fixture()
def session_factory(tmp_path):
    """A fresh database with the two accounts and **no receipts**."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'receipts.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        create_user(session, "alice", "pw-alice", ROLE_REVIEWER)
        create_user(session, "bob", "pw-bob", ROLE_ADMIN)
        session.commit()
    return factory


@pytest.fixture()
def settings() -> Settings:
    """Hermetic settings: a developer's ``.env`` must not steer these tests."""
    return Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        receipts_api_key="s3cret-machine-key",
    )


@pytest.fixture()
def submitted() -> list:
    """What a fake ``submit`` records instead of touching Redis/RQ."""
    return []


@pytest.fixture()
def app(session_factory, storage, settings, submitted):
    return create_app(
        session_factory=session_factory,
        storage=storage,
        submit=submitted.append,
        settings=settings,
    )


def _logged_in(app, username: str, password: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return client


@pytest.fixture()
def reviewer_client(app) -> TestClient:
    return _logged_in(app, "alice", "pw-alice")


@pytest.fixture()
def key_client(app) -> TestClient:
    """No session -- the caller supplies ``X-API-Key`` itself, per call."""
    return TestClient(app)


@pytest.fixture()
def receipt_id(session_factory, storage) -> uuid.UUID:
    """A ``needs_review`` receipt whose image bytes are actually in storage."""
    key = make_image_key(MAIN_RECEIPT, "original")
    with session_factory() as session:
        session.add(
            Receipt(
                id=MAIN_RECEIPT,
                status=ReceiptStatus.NEEDS_REVIEW,
                confidence=Decimal("0.700"),
                merchant_name_raw="COFFEE CO",
                txn_date=date(2026, 7, 1),
                currency="USD",
                total=Decimal("12.50"),
                image_key=key,
                image_phash="",
            )
        )
        session.commit()
    storage.put(key, JPEG_BYTES, "image/jpeg")
    return MAIN_RECEIPT


@pytest.fixture()
def other_receipt_id(session_factory) -> uuid.UUID:
    with session_factory() as session:
        session.add(
            Receipt(
                id=OTHER_RECEIPT,
                status=ReceiptStatus.AUTO_APPROVED,
                confidence=Decimal("0.930"),
                merchant_name_raw="TOTAL WINE",
                txn_date=date(2026, 7, 2),
                currency="USD",
                total=Decimal("40.00"),
                image_key=make_image_key(OTHER_RECEIPT, "original"),
                image_phash="",
            )
        )
        session.commit()
    return OTHER_RECEIPT


@pytest.fixture()
def pending_receipt_id(session_factory) -> uuid.UUID:
    with session_factory() as session:
        session.add(
            Receipt(
                id=PENDING_RECEIPT,
                status=ReceiptStatus.PENDING,
                confidence=Decimal("0"),
                image_key=make_image_key(PENDING_RECEIPT, "original"),
                image_phash="",
            )
        )
        session.commit()
    return PENDING_RECEIPT


@pytest.fixture()
def task_id(session_factory, receipt_id) -> uuid.UUID:
    """The seeded receipt's review task, already claimed by alice -- as if
    she had already called ``GET /review/next`` before these tests exercise
    ``POST /review/{id}/complete``.
    """
    with session_factory() as session:
        enqueue_review(session, receipt_id, reason="quick verify", priority=2)
        task = next_task(session, assignee="alice")
        session.commit()
        return task.id


@pytest.fixture()
def admin_client(app, session_factory, receipt_id, other_receipt_id) -> TestClient:
    """Logged in as bob, with something for an admin to act on: two
    exportable receipts and one open review task.
    """
    with session_factory() as session:
        enqueue_review(session, receipt_id, reason="quick verify", priority=2)
        session.commit()
    return _logged_in(app, "bob", "pw-bob")


@pytest.fixture()
def client_max_1mb(tmp_path) -> TestClient:
    """A reviewer-authenticated client whose app enforces a 1 MB upload cap."""
    settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        max_upload_mb=1,
    )
    engine = make_engine(f"sqlite:///{(tmp_path / 'small.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        create_user(session, "alice", "pw-alice", ROLE_REVIEWER)
        session.commit()
    small_app = create_app(
        session_factory=factory,
        storage=LocalStorage(tmp_path / "small-blobs"),
        submit=lambda job: None,
        settings=settings,
    )
    return _logged_in(small_app, "alice", "pw-alice")


@pytest.fixture()
def empty_reviewer_client(tmp_path) -> TestClient:
    """A second, genuinely empty database -- no receipts, no queue tasks."""
    settings = Settings(_env_file=None, session_secret="test-secret", session_cookie_secure=False)
    engine = make_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        create_user(session, "alice", "pw-alice", ROLE_REVIEWER)
        session.commit()
    empty_app = create_app(
        session_factory=factory,
        storage=LocalStorage(tmp_path / "empty-blobs"),
        submit=lambda job: None,
        settings=settings,
    )
    return _logged_in(empty_app, "alice", "pw-alice")


# --------------------------------------------------------------------------- #
# Brief step 1, verbatim
# --------------------------------------------------------------------------- #


def test_upload_writes_a_pending_row_then_queues(reviewer_client, session_factory, submitted):
    response = reviewer_client.post("/upload", files={"file": ("r.jpg", JPEG_BYTES, "image/jpeg")})
    assert response.status_code == 202
    receipt_id = uuid.UUID(response.json()["receipt_id"])
    with session_factory() as session:
        row = session.get(Receipt, receipt_id)
    # The row exists BEFORE the worker runs: a job the queue loses is visible
    # as a stuck pending row, not a blob with nothing in the database.
    assert row.status is ReceiptStatus.PENDING
    assert [job.id for job in submitted] == [receipt_id]


def test_a_rejected_upload_writes_no_row_and_queues_nothing(
    reviewer_client, session_factory, submitted
):
    response = reviewer_client.post(
        "/upload", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400
    with session_factory() as session:
        assert session.query(Receipt).count() == 0
    assert submitted == []


def test_upload_honours_the_configured_size_limit(client_max_1mb):
    big = b"\xff\xd8" + b"\x00" * (2 * 1024 * 1024)
    response = client_max_1mb.post("/upload", files={"file": ("r.jpg", big, "image/jpeg")})
    assert response.status_code == 400


def test_the_api_key_can_upload_but_nothing_else(key_client, receipt_id):
    headers = {"X-API-Key": "s3cret-machine-key"}
    assert key_client.post("/upload", files={"file": ("r.jpg", JPEG_BYTES, "image/jpeg")},
                           headers=headers).status_code == 202
    assert key_client.patch(f"/receipts/{receipt_id}", json={"totals": {"total": "1.00"}},
                            headers=headers).status_code == 401


def test_patch_writes_a_correction_attributed_to_the_session_user(
    reviewer_client, session_factory, receipt_id
):
    response = reviewer_client.patch(
        f"/receipts/{receipt_id}", json={"totals": {"total": "1234.56"}}
    )
    assert response.status_code == 200
    with session_factory() as session:
        correction = session.scalars(select(Correction)).one()
    # The entire reason session auth was chosen over a shared key.
    assert correction.corrected_by == "alice"
    assert correction.value_after == "1234.56"


def test_patch_rejects_a_json_float_for_money(reviewer_client, receipt_id):
    response = reviewer_client.patch(f"/receipts/{receipt_id}", json={"totals": {"total": 1234.56}})
    assert response.status_code == 422
    assert "string" in response.text


def test_patch_with_an_unmappable_path_changes_nothing(
    reviewer_client, session_factory, receipt_id
):
    response = reviewer_client.patch(
        f"/receipts/{receipt_id}", json={"nonsense": {"field": "x"}}
    )
    assert response.status_code == 400
    with session_factory() as session:
        assert session.query(Correction).count() == 0


def test_image_url_is_signed_and_the_blob_streams(reviewer_client, receipt_id):
    url = reviewer_client.get(f"/receipts/{receipt_id}/image").json()["url"]
    assert reviewer_client.get(url).content == JPEG_BYTES


def test_a_tampered_or_expired_signature_is_rejected(
    reviewer_client, receipt_id, other_receipt_id
):
    url = reviewer_client.get(f"/receipts/{receipt_id}/image").json()["url"]
    swapped_id = url.replace(str(receipt_id), str(other_receipt_id))
    assert reviewer_client.get(swapped_id).status_code == 403
    assert reviewer_client.get(url.replace("exp=", "exp=1")).status_code == 403


def test_review_next_claims_one_task_per_caller(reviewer_client, admin_client):
    first = reviewer_client.get("/review/next").json()["task"]
    second = admin_client.get("/review/next").json()["task"]
    assert first["id"] != (second or {}).get("id")


def test_review_next_on_an_empty_queue_returns_null(empty_reviewer_client):
    assert empty_reviewer_client.get("/review/next").json()["task"] is None


def test_a_reviewer_cannot_complete_someone_elses_task(reviewer_client, session_factory, task_id):
    with session_factory() as session:
        task = session.get(ReviewTask, task_id)
        task.assigned_to = "bob"
        session.commit()
    assert reviewer_client.post(f"/review/{task_id}/complete").status_code == 403


def test_an_admin_can_complete_a_task_assigned_to_someone_else(
    admin_client, session_factory, task_id
):
    with session_factory() as session:
        task = session.get(ReviewTask, task_id)
        task.assigned_to = "alice"
        session.commit()
    assert admin_client.post(f"/review/{task_id}/complete").status_code == 200


def test_completing_an_unknown_task_is_404(reviewer_client):
    assert reviewer_client.post(f"/review/{uuid.uuid4()}/complete").status_code == 404


def test_double_complete_does_not_move_closed_at(reviewer_client, session_factory, task_id):
    reviewer_client.post(f"/review/{task_id}/complete")
    with session_factory() as session:
        first_closed = session.get(ReviewTask, task_id).closed_at
    reviewer_client.post(f"/review/{task_id}/complete")
    with session_factory() as session:
        assert session.get(ReviewTask, task_id).closed_at == first_closed


def test_export_is_admin_only(reviewer_client, admin_client):
    assert reviewer_client.get("/export/xlsx").status_code == 403
    assert admin_client.get("/export/xlsx").status_code == 200


def test_export_writes_all_four_sheets(admin_client, tmp_path):
    response = admin_client.get("/export/xlsx")
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Receipts", "LineItems", "Needs Review", "Summary"]


def _receipt_ids_in(response) -> set[str]:
    """The receipt_id column of the Receipts sheet, as strings."""
    sheet = load_workbook(io.BytesIO(response.content))["Receipts"]
    return {str(row[0].value) for row in sheet.iter_rows(min_row=2) if row[0].value}


def test_export_excludes_pending_and_rejected_unless_asked(admin_client, pending_receipt_id):
    default_rows = _receipt_ids_in(admin_client.get("/export/xlsx"))
    # A pending row is an upload in flight, not a transaction.
    assert str(pending_receipt_id) not in default_rows

    asked = _receipt_ids_in(admin_client.get("/export/xlsx", params={"status": "pending"}))
    assert str(pending_receipt_id) in asked


def test_export_refuses_rather_than_truncating(admin_client, monkeypatch):
    monkeypatch.setattr(api_module, "_EXPORT_MAX_ROWS", 1)
    response = admin_client.get("/export/xlsx")
    assert response.status_code == 400
    assert "narrow" in response.text.lower()
