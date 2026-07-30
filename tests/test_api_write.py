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

import glob
import io
import os
import tempfile
import uuid
from datetime import date, time
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("openpyxl")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from sqlalchemy import event, select  # noqa: E402

import receipts.review.api as api_module  # noqa: E402
from config.settings import Settings  # noqa: E402
from receipts.ingest.storage import LocalStorage, make_image_key  # noqa: E402
from receipts.persist.models import (  # noqa: E402
    Base,
    Correction,
    Merchant,
    Receipt,
    ReviewState,
    ReviewTask,
)
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
                # Seconds on purpose: they are what tells an ``isoformat()``
                # round-trip apart from a lossy ``%H:%M`` one.
                txn_time=time(14, 30, 45),
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


def test_the_time_the_detail_returns_patches_back_unchanged(
    reviewer_client, session_factory, receipt_id
):
    """``receipt.time`` is correctable, so the rendering has to round-trip.

    A reviewer's screen is populated from ``GET /receipts/{id}`` and its edits
    go back through ``PATCH``. If the two disagree about how a ``time`` is
    written, a reviewer who merely *confirms* an untouched receipt rewrites the
    stored value -- and ``apply_corrections`` would log that as a correction
    they never made. Asserting the ``corrections`` table stayed empty is what
    makes this test see a lossy rendering: ``14:30:45`` rendered as ``14:30``
    would patch back as a genuine change and write a row.
    """
    rendered = reviewer_client.get(f"/receipts/{receipt_id}").json()["txn_time"]

    response = reviewer_client.patch(
        f"/receipts/{receipt_id}", json={"receipt": {"time": rendered}}
    )

    assert response.status_code == 200
    assert response.json()["txn_time"] == rendered
    with session_factory() as session:
        assert session.get(Receipt, receipt_id).txn_time == time(14, 30, 45)
        assert session.scalars(select(Correction)).all() == []


def test_the_newly_exposed_payment_method_never_returns_a_full_pan(
    reviewer_client, receipt_id
):
    """§18 at the layer that now serves the column (P5.T3b, fix round 1).

    ``payment_method`` became readable over the API in this task, and its
    redaction was bound only one layer down, in ``tests/test_repository.py``.
    Measured: with ``redact_pan`` neutered to the identity function, all 116
    tests across ``test_api_read.py``/``test_api_write.py``/
    ``test_review_queue.py`` still passed while ``test_repository.py`` failed
    11 -- so nothing at the route layer would have noticed a third writer of
    this column, or a serializer that reached around the repository. This is
    that binding.

    ``payment.method`` is the motivating path named in ``_plan_change``'s own
    docstring: it is where a reviewer types "VISA 4111111111111111" straight
    off the slip.
    """
    response = reviewer_client.patch(
        f"/receipts/{receipt_id}", json={"payment": {"method": "VISA 4111111111111111"}}
    )

    assert response.status_code == 200
    assert response.json()["payment_method"] == "VISA ************1111"
    # ...and it stays masked on the way back out, not just in the echo.
    body = reviewer_client.get(f"/receipts/{receipt_id}")
    assert body.json()["payment_method"] == "VISA ************1111"
    assert "4111111111111111" not in body.text


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


def test_a_valid_signature_for_a_missing_blob_is_404_not_500(reviewer_client, other_receipt_id):
    """``other_receipt_id`` has a real ``receipts`` row and a real
    ``image_key``, but its fixture never writes bytes to storage -- the
    same shape a receipt whose blob was evicted or never uploaded would
    have. The signature is genuinely valid (right receipt, right variant,
    right secret); only the file is absent. Before fix round 1 (F5) this
    reached ``storage.get`` unguarded and ``LocalStorage.get`` raised
    ``FileNotFoundError`` straight through the route as an unhandled 500 --
    on the one route in the service that requires no authentication at
    all.
    """
    url = reviewer_client.get(f"/receipts/{other_receipt_id}/image").json()["url"]
    assert reviewer_client.get(url).status_code == 404


def test_a_tampered_signature_is_rejected(reviewer_client, receipt_id, other_receipt_id):
    """Two tampering shapes, not expiry: re-pointing the URL at a different
    receipt (the signature covers ``receipt_id``, so it cannot be replayed
    against one it was not minted for), and corrupting ``exp`` itself (the
    replacement prefixes a digit onto the existing value, producing a
    *larger*, still-unexpired ``exp`` -- but paired with a signature that no
    longer matches it). Neither case waits for real expiry; see
    `test_a_correctly_signed_link_is_refused_once_it_expires` (fix round 1,
    F7) for that -- this test used to be misnamed as covering it.
    """
    url = reviewer_client.get(f"/receipts/{receipt_id}/image").json()["url"]
    swapped_id = url.replace(str(receipt_id), str(other_receipt_id))
    assert reviewer_client.get(swapped_id).status_code == 403
    assert reviewer_client.get(url.replace("exp=", "exp=1")).status_code == 403


def test_a_correctly_signed_link_is_refused_once_it_expires(session_factory, storage, receipt_id):
    """A signature that is valid in every other respect -- right receipt,
    right variant, right secret -- is still refused once ``exp`` has
    passed. This is the genuine expiry case
    `test_a_tampered_signature_is_rejected` was misnamed for (fix round 1,
    F7): a separate app, sharing the same database and storage, whose
    ``IMAGE_URL_TTL_S`` is negative -- so the link is already expired at
    the instant ``sign_url`` mints it, with no need to sleep in the test.
    """
    expiring_settings = Settings(
        _env_file=None,
        session_secret="test-secret",
        session_cookie_secure=False,
        image_url_ttl_s=-5,
    )
    expiring_app = create_app(
        session_factory=session_factory,
        storage=storage,
        submit=lambda job: None,
        settings=expiring_settings,
    )
    client = _logged_in(expiring_app, "alice", "pw-alice")
    url = client.get(f"/receipts/{receipt_id}/image").json()["url"]
    assert client.get(url).status_code == 403


def test_review_next_claims_one_task_per_caller(reviewer_client, admin_client):
    first = reviewer_client.get("/review/next").json()["task"]
    second = admin_client.get("/review/next").json()["task"]
    assert first["id"] != (second or {}).get("id")


def test_review_next_returns_the_same_task_when_a_reviewer_reloads(
    reviewer_client, session_factory, receipt_id, other_receipt_id
):
    """The page-reload case ADR-0016 exists for, end to end.

    Nothing releases a claim: ``_claim_stmt`` selects ``state == OPEN`` only,
    ``enqueue_review`` reopens a task only when it is ``DONE``, and none of the
    routes in ``review/api.py`` unclaims -- ``POST /review/{id}/complete``
    closes, which is not a release. So before this, a reviewer who reloaded
    claimed a *second* task and stranded the first out of the queue for good.
    Two tasks are queued here rather than one precisely so a regression could
    take the second: with one task the buggy behaviour and the fixed one both
    return the same id.
    """
    with session_factory() as session:
        enqueue_review(session, receipt_id, reason="quick verify", priority=2)
        enqueue_review(session, other_receipt_id, reason="urgent: no total", priority=0)
        session.commit()

    first = reviewer_client.get("/review/next").json()
    second = reviewer_client.get("/review/next").json()

    assert first["task"]["id"] == second["task"]["id"]
    assert first["receipt"]["id"] == second["receipt"]["id"]
    assert second["task"]["assigned_to"] == "alice"
    with session_factory() as session:
        held = session.scalars(
            select(ReviewTask).where(ReviewTask.state == ReviewState.IN_PROGRESS)
        ).all()
        assert [str(task.id) for task in held] == [first["task"]["id"]]


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


def test_review_complete_requires_authentication(app, task_id):
    """The one non-``/health``, non-blob route that had no pin for "no
    credentials at all" (fix round 1, F4). Its real permission rule --
    assignee or admin -- cannot be expressed as a row in
    ``tests/test_api_read.py``'s role/actor matrix (a reviewer holding an
    allowed role can still get 403 there), which is why it was never added
    as one; that is not a reason for the baseline "every non-``/health``
    route needs 401 without credentials" property to go unpinned. Neither
    an anonymous caller nor the machine upload key -- which authorizes
    ``POST /upload`` and nothing else -- may complete a task.
    """
    anonymous = TestClient(app)
    assert anonymous.post(f"/review/{task_id}/complete").status_code == 401

    keyed = TestClient(app)
    keyed.headers.update({"X-API-Key": "s3cret-machine-key"})
    assert keyed.post(f"/review/{task_id}/complete").status_code == 401


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


# --------------------------------------------------------------------------- #
# Fix round 1 (F1, F2, F3): a leaked temp file, an unbounded read, and an
# N+1 a docstring claimed did not exist.
# --------------------------------------------------------------------------- #


def test_export_with_a_malformed_range_header_leaves_no_temp_file(admin_client):
    """The original implementation wrote the workbook under
    ``tempfile.mkdtemp()`` and returned a ``FileResponse`` whose cleanup was
    a ``BackgroundTask``. In starlette 1.3.1, ``FileResponse.__call__``
    returns early for a malformed or unsatisfiable ``Range`` header --
    skipping ``await self.background()`` -- so a ``Range: bytes=abc`` left
    a complete financial workbook behind in the shared OS temp directory,
    permanently, once per request. The fix builds the response body fully
    in memory and deletes its own working temp directory synchronously
    (``finally``, before ``return``), so there is no deferred cleanup step
    left for any response path -- malformed ``Range``, an out-of-bounds
    one, or a client that disconnects mid-stream -- to skip.
    """
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "receipts-export-*")))
    response = admin_client.get("/export/xlsx", headers={"Range": "bytes=abc"})
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "receipts-export-*")))

    assert after - before == set()
    # A plain Response has no partial-content support: Range is ignored and
    # the whole (valid) workbook comes back, which is the accepted
    # trade-off for never leaking one -- see the route's docstring.
    assert response.status_code == 200
    load_workbook(io.BytesIO(response.content))  # does not raise


def test_upload_bounds_the_read_by_the_configured_limit(client_max_1mb, monkeypatch):
    """``await file.read()`` with no argument buffers the *entire* body
    into one ``bytes`` object before ``ingest_bytes`` ever gets a chance to
    reject it on size -- an allocation bounded only by whatever the client
    chooses to send, from any reviewer session or the machine key. The fix
    reads ``max_bytes + 1`` instead, so ``ingest_bytes`` -- spied on here --
    never sees more than one byte past the configured cap, regardless of
    how much larger the uploaded body actually is.
    """
    captured_sizes: list[int] = []
    original_ingest_bytes = api_module.ingest_bytes

    def _spy(data, *args, **kwargs):
        captured_sizes.append(len(data))
        return original_ingest_bytes(data, *args, **kwargs)

    monkeypatch.setattr(api_module, "ingest_bytes", _spy)

    max_bytes = 1 * 1024 * 1024  # client_max_1mb's configured cap
    big = b"\xff\xd8" + b"\x00" * (32 * 1024 * 1024)
    response = client_max_1mb.post("/upload", files={"file": ("r.jpg", big, "image/jpeg")})

    assert response.status_code == 400
    assert captured_sizes == [max_bytes + 1]


def test_export_does_not_issue_one_query_per_receipt_for_line_items_or_merchant(
    admin_client, session_factory
):
    """``build_export_rows`` touches ``receipt.line_items`` (to rebuild the
    extraction) and ``receipt.merchant`` (for the canonical name) for every
    row. Both are default-lazy relationships
    (:mod:`receipts.persist.models`); left lazy, each access is its own
    SELECT -- an N+1 a two-receipt test run does not surface but that
    becomes 5,000-10,000 round trips at the route's own
    ``_EXPORT_MAX_ROWS`` design point. ``_query_export_receipts`` now
    eager-loads both with ``selectinload``, so the statement count must not
    grow with the number of matching receipts.

    Two of the extra receipts get **distinct** ``Merchant`` rows, on
    purpose: every other receipt fixture in this module leaves
    ``merchant_id`` NULL, and a many-to-one lazy loader skips the query
    entirely when the local FK is NULL -- a NULL-only fixture would record
    zero merchant statements whether or not ``selectinload(Receipt.
    merchant)`` is present, discriminating on nothing (this is exactly the
    gap a re-review caught in the first version of this test). Two
    *distinct* merchants close it a second way too: SQLAlchemy's lazy
    loader checks the session's identity map before it queries, so if both
    receipts pointed at the *same* merchant, the second access could be
    served from the map with no second query even without eager loading.
    Distinct merchants force two genuinely separate per-object SELECTs when
    unbatched. The third extra receipt (plus ``receipt_id``/
    ``other_receipt_id`` from ``admin_client``'s own fixture) keeps
    ``merchant_id`` NULL, which also exercises the ``merchant is None``
    fallback in :func:`~receipts.review.serializers.build_export_rows`.
    """
    # admin_client's own fixture already seeded two receipts (receipt_id,
    # other_receipt_id, both merchant_id=NULL); add three more so a
    # per-receipt query pattern is unmistakable against a batched one.
    with session_factory() as session:
        merchant_a = Merchant(id=uuid.uuid4(), canonical_name="Merchant A", name_variants=[])
        merchant_b = Merchant(id=uuid.uuid4(), canonical_name="Merchant B", name_variants=[])
        session.add_all([merchant_a, merchant_b])
        session.flush()

        for merchant_id in (merchant_a.id, merchant_b.id, None):
            extra_id = uuid.uuid4()
            session.add(
                Receipt(
                    id=extra_id,
                    status=ReceiptStatus.AUTO_APPROVED,
                    confidence=Decimal("0.900"),
                    merchant_id=merchant_id,
                    merchant_name_raw="EXTRA CO",
                    txn_date=date(2026, 7, 3),
                    currency="USD",
                    total=Decimal("5.00"),
                    image_key=make_image_key(extra_id, "original"),
                    image_phash="",
                )
            )
        session.commit()
        engine = session.get_bind()

    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        response = admin_client.get("/export/xlsx")
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert response.status_code == 200
    line_item_queries = [s for s in statements if "line_items" in s.lower()]
    merchant_queries = [s for s in statements if "merchants" in s.lower()]
    # Five qualifying receipts (two with distinct real merchants), at most
    # one batched SELECT each -- not five, and not two for merchant either.
    assert len(line_item_queries) <= 1
    assert len(merchant_queries) <= 1


def test_build_export_rows_without_a_secret_leaves_the_image_column_empty(
    session_factory, receipt_id
):
    from receipts.review.serializers import build_export_rows, query_export_receipts

    with session_factory() as session:
        receipts = query_export_receipts(
            session, status=None, merchant_id=None, date_from=None,
            date_to=None, min_confidence=None, limit=100,
        )
        _extractions, rows = build_export_rows(
            session, receipts, secret=None, image_url_ttl_s=86400
        )

    assert rows, "fixture should produce at least one exportable receipt"
    # An unverifiable link is worse than no link.
    assert all(row.image_url is None for row in rows)
