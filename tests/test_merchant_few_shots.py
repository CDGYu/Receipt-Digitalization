"""Few-shot candidate selection: only VERIFIED extractions may teach the model.

Spec D5 -- `status='reviewed'` AND zero `corrections` rows -- plus the dated
note's third condition: exactly one `extraction_runs` row with
`pass_name='extract'`, because `extract_with_repair` returns the BEST attempt
and `_persist_outcome` does not record which one that was.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from receipts.merchants.registry import few_shots_for
from receipts.persist import Merchant, Receipt
from receipts.persist.models import Base, Correction, ExtractionRun, PassName
from receipts.score.confidence import ReceiptStatus

IMAGE = b"\x89PNG\r\n\x1a\n-pretend-this-is-a-receipt"


class _Storage:
    """The one-method slice of StorageBackend this function uses."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = blobs

    def get(self, key: str) -> bytes:
        return self._blobs[key]


@pytest.fixture()
def engine() -> sa.Engine:
    eng = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


def _candidate(
    session: Session,
    merchant: Merchant,
    *,
    status: ReceiptStatus = ReceiptStatus.REVIEWED,
    corrections: int = 0,
    extract_runs: int = 1,
    tax_id: str = "123-456-789",
    receipt_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Receipt:
    """A receipt plus the audit rows that decide whether it may teach."""
    receipt_id = receipt_id or uuid.uuid4()
    receipt = Receipt(
        id=receipt_id,
        merchant_id=merchant.id,
        image_key=f"receipts/{receipt_id}/original.jpg",
        image_phash="",
        status=status,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    session.add(receipt)
    session.flush()

    for i in range(extract_runs):
        session.add(
            ExtractionRun(
                receipt_id=receipt_id,
                pass_name=PassName.EXTRACT,
                attempt=i + 1,
                model_id="test-model",
                prompt_hash="0" * 16,
                raw_response={
                    "raw": None,
                    "parsed": {"merchant": {"name": "METRO OIL", "tax_id": tax_id}},
                    "parse_error": None,
                },
            )
        )
    for _ in range(corrections):
        session.add(
            Correction(
                receipt_id=receipt_id,
                field_path="total",
                value_before="1",
                value_after="2",
                corrected_by="alice",
            )
        )
    session.flush()
    return receipt


def _merchant(session: Session) -> Merchant:
    merchant = Merchant(canonical_name="METRO OIL SUBIC INC.", tax_id="123-456-789")
    session.add(merchant)
    session.flush()
    return merchant


def test_a_clean_reviewed_receipt_becomes_a_few_shot(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        receipt = _candidate(session, merchant)
        storage = _Storage({receipt.image_key: IMAGE})

        shots = few_shots_for(session, storage, merchant)

        assert len(shots) == 1
        assert shots[0].image_b64 == base64.b64encode(IMAGE).decode("ascii")
        assert shots[0].extraction.merchant.tax_id == "123-456-789"


def test_the_tax_id_survives_into_the_example(engine) -> None:
    """The whole reason `_export_extraction` is not the source (spec dated note)."""
    with Session(engine) as session:
        merchant = _merchant(session)
        receipt = _candidate(session, merchant)
        storage = _Storage({receipt.image_key: IMAGE})

        shots = few_shots_for(session, storage, merchant)

        assert shots[0].extraction.merchant.tax_id is not None


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"status": ReceiptStatus.AUTO_APPROVED}, "never reviewed by a human"),
        ({"status": ReceiptStatus.NEEDS_REVIEW}, "not reviewed yet"),
        ({"corrections": 1}, "a human changed something, so it taught an error"),
        ({"extract_runs": 2}, "which attempt won is not recorded"),
        ({"extract_runs": 0}, "no extraction to learn from"),
    ],
)
def test_unverified_receipts_never_teach(engine, kwargs, why) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        receipt = _candidate(session, merchant, **kwargs)
        storage = _Storage({receipt.image_key: IMAGE})

        assert few_shots_for(session, storage, merchant) == [], why


def test_no_merchant_means_no_few_shots(engine) -> None:
    with Session(engine) as session:
        assert few_shots_for(session, _Storage({}), None) == []


def test_limit_is_respected(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        blobs = {}
        for _ in range(3):
            receipt = _candidate(session, merchant)
            blobs[receipt.image_key] = IMAGE

        assert len(few_shots_for(session, _Storage(blobs), merchant, limit=2)) == 2


def test_a_missing_blob_is_skipped_not_raised(engine) -> None:
    """A prompting aid must never be the reason a receipt fails to process."""
    with Session(engine) as session:
        merchant = _merchant(session)
        _candidate(session, merchant, tax_id="000-000-000")
        kept = _candidate(session, merchant, tax_id="999-999-999")

        shots = few_shots_for(session, _Storage({kept.image_key: IMAGE}), merchant)

        assert len(shots) == 1
        assert shots[0].extraction.merchant.tax_id == "999-999-999"


def test_a_negative_limit_returns_nothing(engine) -> None:
    """`limit <= 0` is a real guard, not a shortcut past a query that agrees.

    SQL does not agree. Measured on this engine, `LIMIT -1` returns **all** rows
    (`LIMIT 0` returns none, which is why pinning with 0 would prove nothing),
    and Postgres rejects a negative LIMIT at runtime instead. Without the guard
    `limit=-1` hands back every verified receipt the merchant has.
    """
    with Session(engine) as session:
        merchant = _merchant(session)
        blobs = {}
        for _ in range(3):
            receipt = _candidate(session, merchant)
            blobs[receipt.image_key] = IMAGE

        assert few_shots_for(session, _Storage(blobs), merchant, limit=-1) == []


class _ExplodingStorage:
    """A backend that fails the way the old except-tuple could not catch.

    `RuntimeError` is not a `KeyError`, `FileNotFoundError` or `OSError`, and it
    is exactly what `S3Storage.get` raises when boto3 is missing -- and
    `worker.py` wires `S3Storage` in production.
    """

    def get(self, key: str) -> bytes:
        raise RuntimeError("boto3 not installed")


def test_a_storage_failure_outside_the_old_tuple_is_still_skipped(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        _candidate(session, merchant)

        assert few_shots_for(session, _ExplodingStorage(), merchant) == []


def test_an_unvalidatable_stored_extraction_is_skipped(engine) -> None:
    """`redact_pan` masks whole-number scalars of 13+ digits before storage.

    So `totals.total` can already read `"*********0123"` in `raw_response`, and
    `model_validate` raises on it. That is a live path, not only a migration
    risk -- the same bound has to cover it.
    """
    with Session(engine) as session:
        merchant = _merchant(session)
        good = _candidate(session, merchant, tax_id="999-999-999")
        bad = _candidate(session, merchant)
        run = session.scalars(
            sa.select(ExtractionRun).where(ExtractionRun.receipt_id == bad.id)
        ).one()
        run.raw_response = {
            "raw": None,
            "parsed": {
                "merchant": {"name": "METRO OIL", "tax_id": "123-456-789"},
                "totals": {"total": "*********0123"},
            },
            "parse_error": None,
        }
        session.flush()
        blobs = {good.image_key: IMAGE, bad.image_key: IMAGE}

        shots = few_shots_for(session, _Storage(blobs), merchant)

        assert [s.extraction.merchant.tax_id for s in shots] == ["999-999-999"]


def test_the_newest_verified_receipts_are_the_ones_that_teach(engine) -> None:
    """Recency, not `Receipt.id`, decides which examples are used.

    `Receipt.id` is a random UUID, so ordering by it means the same arbitrary
    pair teaches forever -- a merchant that changes its receipt layout would go
    on being taught the old one. Under `limit`, the newest verified receipt wins.

    The ids run **opposite** to the dates on purpose. Left to `Receipt.id` this
    returns the two oldest; leaving the ids random would have made that failure
    a coin toss rather than a proof.
    """
    with Session(engine) as session:
        merchant = _merchant(session)
        blobs = {}
        for n, (year, tax_id) in enumerate(
            ((2024, "old"), (2025, "mid"), (2026, "new")), start=1
        ):
            receipt = _candidate(
                session,
                merchant,
                tax_id=tax_id,
                receipt_id=uuid.UUID(int=n),
                created_at=datetime(year, 1, 1, tzinfo=UTC),
            )
            blobs[receipt.image_key] = IMAGE

        shots = few_shots_for(session, _Storage(blobs), merchant, limit=2)

        assert [s.extraction.merchant.tax_id for s in shots] == ["new", "mid"]


def test_receipts_ingested_together_are_ordered_by_id(engine) -> None:
    """`_attempt_prompt_hash` rebuilds the extraction prompt to recover its hash.

    Two calls against unchanged rows must therefore choose the same examples, so
    the ordering has to be **total**. `created_at` alone is not: it is stored at
    one-second resolution, so a batch ingested together ties, and whatever the
    planner happens to emit becomes the answer. `Receipt.id` breaks the tie.

    The rows are inserted in an order that is neither the expected one nor its
    reverse, so passing by accident takes more than a lucky planner.
    """
    same_second = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
    with Session(engine) as session:
        merchant = _merchant(session)
        blobs = {}
        for n in (3, 1, 2):
            receipt = _candidate(
                session,
                merchant,
                tax_id=str(n),
                receipt_id=uuid.UUID(int=n),
                created_at=same_second,
            )
            blobs[receipt.image_key] = IMAGE

        shots = few_shots_for(session, _Storage(blobs), merchant, limit=3)

        assert [s.extraction.merchant.tax_id for s in shots] == ["1", "2", "3"]
