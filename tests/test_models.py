"""ORM model tests for the seven-table data model (spec §6).

These run entirely on an in-memory SQLite database -- no Postgres, no psycopg.
They pin down the load-bearing behaviour of the persistence layer:

  * ``Base.metadata.create_all`` builds exactly the seven tables.
  * Money columns round-trip as ``Decimal`` at full precision, never ``float``
    (the prime directive of this project -- see SPEC §18).
  * The ``line_items`` cascade and the ``(receipt_id, position)`` uniqueness
    constraint both fire.
  * Enum columns store the spec's lowercase token and read back as the enum.
  * No column on any of the seven tables is a SQLAlchemy ``Float`` -- a
    structural guard so money can never silently become a float.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from receipts.extract.schema import Legibility
from receipts.persist import (
    Base,
    Correction,
    ExtractionRun,
    LineItem,
    Merchant,
    Receipt,
    ReviewTask,
    ValidationFinding,
)
from receipts.score.confidence import ReceiptStatus

EXPECTED_TABLES = {
    "merchants",
    "receipts",
    "line_items",
    "extraction_runs",
    "validation_findings",
    "corrections",
    "review_tasks",
}


@pytest.fixture()
def engine() -> sa.Engine:
    """A fresh in-memory SQLite engine with FK enforcement turned on.

    SQLite does not enforce foreign keys (and therefore ``ON DELETE CASCADE``)
    unless ``PRAGMA foreign_keys=ON`` is issued per connection, so we wire that
    up on every ``connect`` before creating the schema.
    """
    eng = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


def _make_receipt(**overrides) -> Receipt:
    """A Receipt with the NOT NULL columns that have no default filled in."""
    fields = {
        "image_key": "s3://bucket/original.jpg",
        "image_phash": "0123456789abcdef",
    }
    fields.update(overrides)
    return Receipt(**fields)


def test_create_all_builds_exactly_seven_tables(engine: sa.Engine) -> None:
    tables = set(sa.inspect(engine).get_table_names())
    assert tables == EXPECTED_TABLES


def test_money_columns_round_trip_as_decimal(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = Merchant(canonical_name="Total Wine & More")
        receipt = _make_receipt(
            merchant=merchant,
            merchant_name_raw="TOTAL WINE",
            txn_date=date(2026, 7, 27),
            txn_time=time(14, 30),
            currency="USD",
            subtotal=Decimal("720.00"),
            tax_total=Decimal("41.60"),
            total=Decimal("761.60"),
            confidence=Decimal("0.912"),
            legibility=Legibility.GOOD,
            status=ReceiptStatus.AUTO_APPROVED,
        )
        receipt.line_items = [
            LineItem(
                position=0,
                description_raw="MERLOT",
                qty=Decimal("2"),
                unit_price=Decimal("18.00"),
                line_total=Decimal("36.00"),
                line_confidence=Decimal("0.990"),
            ),
            LineItem(
                position=1,
                description_raw="CABERNET",
                qty=Decimal("1.5"),
                unit_price=Decimal("20.00"),
                line_total=Decimal("30.00"),
                line_confidence=Decimal("0.980"),
            ),
        ]
        session.add(receipt)
        session.commit()
        receipt_id = receipt.id

    with Session(engine) as session:
        got = session.get(Receipt, receipt_id)
        assert got is not None

        assert isinstance(got.total, Decimal)
        assert got.total == Decimal("761.60")
        assert got.subtotal == Decimal("720.00")
        assert got.tax_total == Decimal("41.60")

        assert isinstance(got.confidence, Decimal)
        assert got.confidence == Decimal("0.912")

        assert len(got.line_items) == 2
        first = min(got.line_items, key=lambda li: li.position)
        assert isinstance(first.qty, Decimal)
        assert first.qty == Decimal("2")
        assert isinstance(first.line_total, Decimal)
        assert first.line_total == Decimal("36.00")
        assert first.line_confidence == Decimal("0.990")


def test_deleting_receipt_cascades_to_line_items(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _make_receipt()
        receipt.line_items = [
            LineItem(position=0, description_raw="A", line_confidence=Decimal("1.000")),
            LineItem(position=1, description_raw="B", line_confidence=Decimal("1.000")),
        ]
        session.add(receipt)
        session.commit()
        receipt_id = receipt.id

    with Session(engine) as session:
        assert session.scalar(select(sa.func.count()).select_from(LineItem)) == 2
        session.delete(session.get(Receipt, receipt_id))
        session.commit()

    with Session(engine) as session:
        assert session.scalar(select(sa.func.count()).select_from(LineItem)) == 0
        assert session.get(Receipt, receipt_id) is None


def test_line_item_position_is_unique_per_receipt(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _make_receipt()
        session.add(receipt)
        session.commit()
        receipt_id = receipt.id

        session.add_all(
            [
                LineItem(
                    receipt_id=receipt_id,
                    position=0,
                    description_raw="first",
                    line_confidence=Decimal("1.000"),
                ),
                LineItem(
                    receipt_id=receipt_id,
                    position=0,
                    description_raw="duplicate position",
                    line_confidence=Decimal("1.000"),
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_enum_columns_store_token_and_read_back_as_enum(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _make_receipt(
            status=ReceiptStatus.AUTO_APPROVED,
            legibility=Legibility.FAIR,
        )
        session.add(receipt)
        session.commit()
        receipt_id = receipt.id

    with Session(engine) as session:
        got = session.get(Receipt, receipt_id)
        assert got is not None
        assert got.status is ReceiptStatus.AUTO_APPROVED
        assert got.legibility is Legibility.FAIR

        # The raw stored token is the enum *value* (the stable, spec'd lowercase
        # string shown in the review UI), not the Python member name.
        raw = session.execute(text("SELECT status, legibility FROM receipts")).one()
        assert raw.status == "auto_approved"
        assert raw.legibility == "fair"


def test_no_float_columns_on_any_table() -> None:
    """Structural guard: money must be ``Numeric``/``Decimal``, never ``Float``.

    ``Float`` is a subclass of ``Numeric`` in SQLAlchemy, so this check flags a
    genuine ``Float`` column without tripping on the money ``Numeric`` columns.
    """
    offenders: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, sa.Float):
                offenders.append(f"{table.name}.{column.name}")
    assert not offenders, (
        "Float column(s) found -- money must be Numeric/Decimal (SPEC §18): "
        + ", ".join(sorted(offenders))
    )


def test_public_api_exports_all_seven_models() -> None:
    # Import-smoke: the seven ORM classes and Base are importable from the package.
    for model in (
        Merchant,
        Receipt,
        LineItem,
        ExtractionRun,
        ValidationFinding,
        Correction,
        ReviewTask,
    ):
        assert issubclass(model, Base)
