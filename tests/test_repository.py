"""Repository-layer tests: the persistence read/write API (spec §14.8).

Everything here runs on an in-memory SQLite database with ``PRAGMA
foreign_keys=ON`` (the same fixture pattern as ``test_models.py``) -- no
Postgres, no psycopg, no network.

The load-bearing behaviours pinned down below:

  * money survives the round trip as ``Decimal`` at full precision, and a
    reviewer's correction round-trips as ``Decimal`` too (ADR-0001);
  * an unparseable or missing date leaves ``txn_date`` NULL and keeps the raw
    string -- the repository never invents a date;
  * a full card number (PAN) never reaches ``extraction_runs.raw_response``
    (spec §18), while money, hashes, and a 4-digit ``card_last4`` are left
    exactly as they were -- the silent case matters as much as the firing one;
  * ``apply_corrections`` is transactional: one ``corrections`` row per changed
    field path, zero rows for a no-op, and nothing at all when a path in the
    patch cannot be mapped.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import date, time
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from receipts.extract.clients.base import VLMResponse
from receipts.extract.schema import (
    ExtractionMeta,
    Legibility,
    Payment,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
)
from receipts.extract.schema import LineItem as ExtractedLineItem
from receipts.extract.schema import Merchant as ExtractedMerchant
from receipts.ingest.ingest import ReceiptJob
from receipts.persist import (
    Correction,
    ExtractionRun,
    LineItem,
    Merchant,
    PassName,
    Receipt,
    ValidationFinding,
    apply_corrections,
    create_pending_receipt,
    get_findings,
    get_receipt,
    query_receipts,
    redact_pan,
    save_extraction,
    save_extraction_run,
    save_findings,
)
from receipts.persist.models import Base
from receipts.persist.session import make_engine, make_session_factory
from receipts.score.confidence import ReceiptStatus
from receipts.validate.report import Finding, Severity, ValidationReport

PHASH = "0123456789abcdef"
PROMPT_HASH = "abc123def4560000"


@pytest.fixture()
def engine() -> sa.Engine:
    """In-memory SQLite with FK enforcement on (mirrors ``test_models.py``)."""
    eng = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _job(receipt_id: uuid.UUID | None = None) -> ReceiptJob:
    receipt_id = receipt_id or uuid.uuid4()
    return ReceiptJob(
        id=receipt_id,
        image_key=f"receipts/2026/07/{receipt_id}/original.jpg",
        source="upload",
        original_filename="receipt.jpg",
        content_type="image/jpeg",
    )


def _extraction(
    *,
    date_iso: str | None = "2026-07-27",
    date_raw: str | None = None,
    total: Decimal | None = Decimal("761.60"),
    card_last4: str | None = "1111",
    is_handwritten: bool = False,
    inconsistent: bool = False,
) -> ReceiptExtraction:
    return ReceiptExtraction(
        merchant=ExtractedMerchant(name="TOTAL WINE"),
        receipt=ReceiptMeta(
            number="A-1234",
            date=date_iso,
            date_raw=date_raw,
            time="14:30",
            currency="USD",
        ),
        line_items=[
            ExtractedLineItem(
                position=0,
                description_raw="MERLOT",
                qty=Decimal("2"),
                unit_price=Decimal("18.00"),
                line_total=Decimal("36.00"),
            ),
            ExtractedLineItem(
                position=1,
                description_raw="CABERNET",
                sku="CAB-1",
                qty=Decimal("1.5"),
                unit="btl",
                unit_price=Decimal("20.00"),
                line_total=Decimal("30.00"),
            ),
        ],
        totals=Totals(
            subtotal=Decimal("720.00"),
            tax=Decimal("41.60"),
            discount=Decimal("0.00"),
            total=total,
            tender=Decimal("800.00"),
            change=Decimal("38.40"),
        ),
        payment=Payment(method="card", card_last4=card_last4),
        meta=ExtractionMeta(
            is_handwritten=is_handwritten,
            legibility=Legibility.GOOD,
            receipt_is_inconsistent=inconsistent,
        ),
    )


def _report() -> ValidationReport:
    return ValidationReport(
        findings=[
            Finding(
                rule_id="R021",
                severity=Severity.ERROR,
                message="Line items sum to 66.00 but the subtotal is 720.00.",
                field_paths=["line_items", "totals.subtotal"],
                context={"line_sum": "66.00", "subtotal": "720.00"},
            ),
            Finding(
                rule_id="R041",
                severity=Severity.WARN,
                message="Implied tax rate is 5.8%.",
                field_paths=["totals.tax"],
            ),
            Finding(
                rule_id="R011",
                severity=Severity.INFO,
                message="receipt.date is null but date_raw was captured.",
            ),
        ]
    )


def _save(
    session: Session,
    *,
    extraction: ReceiptExtraction | None = None,
    status: ReceiptStatus = ReceiptStatus.AUTO_APPROVED,
    confidence: Decimal = Decimal("0.912"),
    job: ReceiptJob | None = None,
) -> Receipt:
    return save_extraction(
        session,
        job or _job(),
        extraction or _extraction(),
        ValidationReport(),
        confidence,
        status,
        image_phash=PHASH,
    )


# --------------------------------------------------------------------------- #
# save_extraction
# --------------------------------------------------------------------------- #


def test_save_extraction_persists_receipt_and_line_items(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        receipt = _save(session, job=job)
        assert receipt.id == job.id
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None

        assert got.image_key == job.image_key
        assert got.image_phash == PHASH
        assert got.merchant_name_raw == "TOTAL WINE"
        assert got.receipt_number == "A-1234"
        assert got.txn_date == date(2026, 7, 27)
        assert got.txn_time == time(14, 30)
        assert got.currency == "USD"
        assert got.payment_method == "card"
        assert got.card_last4 == "1111"
        assert got.is_handwritten is False
        assert got.receipt_is_inconsistent is False
        assert got.legibility is Legibility.GOOD
        assert got.status is ReceiptStatus.AUTO_APPROVED

        # Money reads back as Decimal at full precision -- never float.
        assert isinstance(got.total, Decimal)
        assert got.total == Decimal("761.60")
        assert got.subtotal == Decimal("720.00")
        assert got.tax_total == Decimal("41.60")
        assert got.discount_total == Decimal("0.00")
        assert got.tender_amount == Decimal("800.00")
        assert got.change_amount == Decimal("38.40")
        assert isinstance(got.confidence, Decimal)
        assert got.confidence == Decimal("0.912")

        assert [item.position for item in got.line_items] == [0, 1]
        first, second = got.line_items
        assert first.description_raw == "MERLOT"
        assert isinstance(first.qty, Decimal)
        assert first.qty == Decimal("2")
        assert first.unit_price == Decimal("18.00")
        assert first.line_total == Decimal("36.00")
        assert second.sku == "CAB-1"
        assert second.unit == "btl"
        assert second.qty == Decimal("1.5")


def test_save_extraction_keeps_date_raw_and_leaves_txn_date_null(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(
            session,
            job=job,
            extraction=_extraction(date_iso=None, date_raw="3/4/26"),
        )
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.txn_date is None
        assert got.date_raw == "3/4/26"


def test_save_extraction_never_invents_a_date_from_an_unparseable_value(
    engine: sa.Engine,
) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job, extraction=_extraction(date_iso="27 July, maybe"))
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.txn_date is None
        # Nothing is silently dropped: the unparseable string is kept verbatim.
        assert got.date_raw == "27 July, maybe"


def test_save_extraction_stores_only_the_last_four_card_digits(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job, extraction=_extraction(card_last4="4111111111111111"))
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.card_last4 == "1111"


def test_save_extraction_carries_meta_flags(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(
            session,
            job=job,
            extraction=_extraction(is_handwritten=True, inconsistent=True),
            status=ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.is_handwritten is True
        assert got.receipt_is_inconsistent is True
        assert got.status is ReceiptStatus.NEEDS_REVIEW


def test_save_extraction_falls_back_to_list_order_on_duplicate_positions(
    engine: sa.Engine,
) -> None:
    """All-zero positions (a model that never emitted them) must not collide."""
    extraction = _extraction()
    for item in extraction.line_items:
        item.position = 0

    job = _job()
    with Session(engine) as session:
        _save(session, job=job, extraction=extraction)
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert [item.position for item in got.line_items] == [0, 1]


def test_get_receipt_returns_none_for_an_unknown_id(engine: sa.Engine) -> None:
    with Session(engine) as session:
        assert get_receipt(session, uuid.uuid4()) is None


# --------------------------------------------------------------------------- #
# create_pending_receipt + save_extraction as update-or-insert
# --------------------------------------------------------------------------- #


def test_create_pending_receipt_writes_a_visible_row(engine: sa.Engine) -> None:
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="receipts/2026/07/x/original.jpg",
        source="upload", original_filename="r.jpg", content_type="image/jpeg",
    )
    with Session(engine) as session:
        receipt = create_pending_receipt(session, job)
        session.commit()

        assert receipt.status is ReceiptStatus.PENDING
        assert receipt.confidence == Decimal("0")
        # The perceptual hash is computed by the worker's preprocess stage. An empty
        # hash is what find_duplicate_by_phash skips, so a pending row can never
        # become the "original" a later upload is marked a duplicate of.
        assert receipt.image_phash == ""
        assert receipt.confidence_reasons is None


def test_create_pending_receipt_rejects_a_reused_id(engine: sa.Engine) -> None:
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="upload",
        original_filename="r.jpg", content_type="image/jpeg",
    )
    with Session(engine) as session:
        create_pending_receipt(session, job)
        session.commit()
        with pytest.raises(ValueError, match="already exists"):
            create_pending_receipt(session, job)


def test_save_extraction_updates_the_pending_row_instead_of_colliding(engine: sa.Engine) -> None:
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="upload",
        original_filename="r.jpg", content_type="image/jpeg",
    )
    with Session(engine) as session:
        create_pending_receipt(session, job)
        session.commit()

        extraction = ReceiptExtraction(
            merchant=ExtractedMerchant(name="METRO OIL SUBIC, INC."),
            totals=Totals(total=Decimal("1000.00")),
            line_items=[ExtractedLineItem(position=1, description_raw="CLEAN DIESEL")],
        )
        receipt = save_extraction(
            session, job, extraction, ValidationReport(), Decimal("0.900"),
            ReceiptStatus.AUTO_APPROVED, image_phash="ffff0000ffff0000",
            confidence_reasons=[("poor legibility", Decimal("-0.20"))],
        )
        session.commit()

        assert session.query(Receipt).count() == 1
        assert receipt.id == job.id
        assert receipt.status is ReceiptStatus.AUTO_APPROVED
        assert receipt.total == Decimal("1000.00")
        assert len(receipt.line_items) == 1
        assert receipt.confidence_reasons == [
            {"reason": "poor legibility", "penalty": "-0.20"}
        ]


def test_save_extraction_replaces_line_items_on_a_second_run(engine: sa.Engine) -> None:
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="upload",
        original_filename="r.jpg", content_type="image/jpeg",
    )
    with Session(engine) as session:
        first = ReceiptExtraction(
            line_items=[ExtractedLineItem(position=1, description_raw="A"),
                        ExtractedLineItem(position=2, description_raw="B")]
        )
        save_extraction(session, job, first, ValidationReport(), Decimal("0.5"),
                        ReceiptStatus.NEEDS_REVIEW)
        session.commit()

        second = ReceiptExtraction(
            line_items=[ExtractedLineItem(position=1, description_raw="A only")]
        )
        receipt = save_extraction(session, job, second, ValidationReport(), Decimal("0.5"),
                                  ReceiptStatus.NEEDS_REVIEW)
        session.commit()

        assert [item.description_raw for item in receipt.line_items] == ["A only"]
        assert session.query(LineItem).count() == 1


def test_save_extraction_refuses_to_overwrite_a_reviewed_row(engine: sa.Engine) -> None:
    """A machine run must never write over a human's review (§18, ADR-0006).

    ``POST /upload`` commits the ``pending`` row before it queues, so a reviewer
    can re-key a receipt while the worker's job is still waiting. Applying the
    machine extraction on top would silently drop the correction, re-label the
    receipt ``auto_approved``, and leave the ``corrections`` rows describing
    values no longer in the row. ``ValueError`` -- the layer's error currency --
    is what the pipeline turns into a visible ``needs_review`` task, and what the
    API turns into a 400.
    """
    job = ReceiptJob(id=uuid.uuid4(), image_key="k", source="upload",
                     original_filename="r.jpg", content_type="image/jpeg")
    with Session(engine) as session:
        create_pending_receipt(session, job)
        session.commit()
        apply_corrections(
            session, job.id, {"totals.total": Decimal("999.99")}, corrected_by="alice"
        )

        machine = ReceiptExtraction(
            merchant=ExtractedMerchant(name="SUPERMART INC."),
            totals=Totals(total=Decimal("224.00")),
        )
        with pytest.raises(ValueError, match="reviewed"):
            save_extraction(session, job, machine, ValidationReport(), Decimal("0.93"),
                            ReceiptStatus.AUTO_APPROVED)
        session.rollback()

    with Session(engine) as session:
        receipt = get_receipt(session, job.id)
        assert receipt is not None
        assert receipt.status is ReceiptStatus.REVIEWED
        assert receipt.total == Decimal("999.99")


def test_save_extraction_still_updates_every_non_reviewed_status(engine: sa.Engine) -> None:
    """The refusal is narrow: only a human's own state is protected.

    A retried job whose row is ``pending``, ``needs_review``, ``auto_approved``
    or ``rejected`` must still be updated in place -- re-inserting would collide
    on the primary key and lose the receipt on the way to recording it.
    """
    for status in (
        ReceiptStatus.PENDING,
        ReceiptStatus.NEEDS_REVIEW,
        ReceiptStatus.AUTO_APPROVED,
        ReceiptStatus.REJECTED,
    ):
        job = ReceiptJob(id=uuid.uuid4(), image_key="k", source="upload",
                         original_filename="r.jpg", content_type="image/jpeg")
        with Session(engine) as session:
            save_extraction(session, job, ReceiptExtraction(), ValidationReport(),
                            Decimal("0.5"), status)
            session.commit()

            receipt = save_extraction(
                session, job, ReceiptExtraction(totals=Totals(total=Decimal("7.00"))),
                ValidationReport(), Decimal("0.9"), ReceiptStatus.AUTO_APPROVED,
            )
            session.commit()
            assert receipt.total == Decimal("7.00"), status
            assert receipt.status is ReceiptStatus.AUTO_APPROVED, status


def test_save_extraction_redacts_a_pan_the_model_put_in_free_text(engine: sa.Engine) -> None:
    """§18 again, on the model-driven side of the same hole as ``_plan_change``.

    ``payment.method`` and ``merchant.name`` were copied to their columns
    verbatim, so a model that read the card line into either landed a full PAN
    in ``receipts``. Only ``payment.card_last4`` was ever narrowed.
    """
    job = _job()
    with Session(engine) as session:
        receipt = save_extraction(
            session,
            job,
            ReceiptExtraction(
                merchant=ExtractedMerchant(name="SUPERMART 4111111111111111"),
                payment=Payment(method="VISA 4111-1111-1111-1111", card_last4="1111"),
            ),
            ValidationReport(),
            Decimal("0.5"),
            ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()

        assert receipt.payment_method == "VISA ************1111"
        assert receipt.merchant_name_raw == "SUPERMART ************1111"
        # The silent case: a genuine 4-digit last4 is not a PAN and is untouched.
        assert receipt.card_last4 == "1111"


def test_empty_reasons_and_missing_reasons_are_different(engine: sa.Engine) -> None:
    job = ReceiptJob(id=uuid.uuid4(), image_key="k", source="upload",
                     original_filename="r.jpg", content_type="image/jpeg")
    with Session(engine) as session:
        receipt = save_extraction(
            session, job, ReceiptExtraction(), ValidationReport(), Decimal("1.0"),
            ReceiptStatus.AUTO_APPROVED, confidence_reasons=[],
        )
        session.commit()
        # [] means "nothing lowered the score"; NULL means "never recorded".
        assert receipt.confidence_reasons == []


# --------------------------------------------------------------------------- #
# save_findings
# --------------------------------------------------------------------------- #


def test_save_findings_writes_one_row_per_finding(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        rows = save_findings(session, job.id, _report())
        assert len(rows) == 3
        session.commit()

    with Session(engine) as session:
        stored = list(
            session.scalars(
                select(ValidationFinding)
                .where(ValidationFinding.receipt_id == job.id)
                .order_by(ValidationFinding.rule_id)
            )
        )
        assert [row.rule_id for row in stored] == ["R011", "R021", "R041"]
        by_rule = {row.rule_id: row for row in stored}
        assert by_rule["R021"].severity is Severity.ERROR
        assert by_rule["R041"].severity is Severity.WARN
        assert by_rule["R011"].severity is Severity.INFO
        assert by_rule["R021"].context == {"line_sum": "66.00", "subtotal": "720.00"}
        assert by_rule["R041"].context == {}
        assert by_rule["R021"].resolved_by_repair is False
        assert "720.00" in by_rule["R021"].message


def test_save_findings_on_a_clean_report_writes_nothing(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        assert save_findings(session, job.id, ValidationReport()) == []
        session.commit()

    with Session(engine) as session:
        assert session.scalar(select(sa.func.count()).select_from(ValidationFinding)) == 0


def test_get_findings_returns_them_in_write_order(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        receipt = save_extraction(session, job, ReceiptExtraction(), ValidationReport(),
                                  Decimal("0.5"), ReceiptStatus.NEEDS_REVIEW)
        report = ValidationReport(findings=[
            Finding(rule_id="R020", severity=Severity.ERROR, message="lines do not sum"),
            Finding(rule_id="R011", severity=Severity.INFO, message="date normalized"),
        ])
        save_findings(session, receipt.id, report)
        session.commit()

        assert [f.rule_id for f in get_findings(session, receipt.id)] == ["R020", "R011"]


# --------------------------------------------------------------------------- #
# save_extraction_run + PAN redaction
# --------------------------------------------------------------------------- #


def _response(raw: object) -> VLMResponse:
    return VLMResponse(
        parsed=None,
        raw=raw,
        model_id="fake-model-1",
        input_tokens=1500,
        output_tokens=400,
        latency_ms=1234,
        cost_usd=Decimal("0.012345"),
        parse_error="unterminated string",
    )


def test_save_extraction_run_records_the_audit_row(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        run = save_extraction_run(
            session, job.id, PassName.EXTRACT, 2, _response({"scripted": 0}), PROMPT_HASH
        )
        run_id = run.id
        session.commit()

    with Session(engine) as session:
        got = session.get(ExtractionRun, run_id)
        assert got is not None
        assert got.receipt_id == job.id
        assert got.pass_name is PassName.EXTRACT
        assert got.attempt == 2
        assert got.model_id == "fake-model-1"
        assert got.prompt_hash == PROMPT_HASH
        assert got.input_tokens == 1500
        assert got.output_tokens == 400
        assert got.latency_ms == 1234
        assert isinstance(got.cost_usd, Decimal)
        assert got.cost_usd == Decimal("0.012345")
        assert got.raw_response["raw"] == {"scripted": 0}
        assert got.raw_response["parse_error"] == "unterminated string"


def test_save_extraction_run_accepts_a_pass_name_string(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        run = save_extraction_run(
            session, job.id, "repair", 1, _response("plain text"), PROMPT_HASH
        )
        session.commit()
        assert run.pass_name is PassName.REPAIR


def test_save_extraction_run_redacts_a_full_pan(engine: sa.Engine) -> None:
    job = _job()
    raw = {
        "text": "VISA 4111111111111111 APPROVED",
        "blocks": [
            "CARD 4111-1111-1111-1111",
            "CARD 4111 1111 1111 1111",
            "TOTAL 1234.56",
        ],
        "trace_id": PHASH,
        "card_last4": "1234",
    }
    with Session(engine) as session:
        _save(session, job=job)
        run = save_extraction_run(session, job.id, PassName.EXTRACT, 1, _response(raw), PROMPT_HASH)
        run_id = run.id
        session.commit()

    with Session(engine) as session:
        stored = json.dumps(session.get(ExtractionRun, run_id).raw_response)

    # No full PAN, in any separator style, survives.
    assert "4111111111111111" not in stored
    assert "4111-1111-1111-1111" not in stored
    assert "4111 1111 1111 1111" not in stored
    assert "4111" not in stored
    # The last four digits are still there.
    assert "1111" in stored

    # The silent case: nothing else was touched.
    assert "1234.56" in stored
    assert PHASH in stored
    assert '"1234"' in stored


def test_redact_pan_masks_full_card_numbers() -> None:
    assert redact_pan("4111111111111111") == "************1111"
    assert redact_pan("4111 1111 1111 1111") == "************1111"
    assert redact_pan("4111-1111-1111-1111") == "************1111"
    # Amex, 4-6-5 grouping and unseparated, keeps only the last four.
    assert redact_pan("CARD 3782 822463 10005 OK") == "CARD ***********0005 OK"
    assert redact_pan("CARD 378282246310005 OK") == "CARD ***********0005 OK"


def test_redact_pan_masks_a_pan_printed_after_a_label_period() -> None:
    """``CARD NO.`` / ``ACCT NO.`` / ``REF.`` is exactly what a thermal receipt prints.

    A period before the digits is label punctuation, not a decimal point, so the
    PAN behind it must still be masked (§18).
    """
    assert redact_pan("CARD NO.4111111111111111") == "CARD NO.************1111"
    assert redact_pan("ACCT NO.4111-1111-1111-1111") == "ACCT NO.************1111"
    assert redact_pan("REF.378282246310005") == "REF.***********0005"


def test_redact_pan_masks_a_pan_with_mixed_separators() -> None:
    """OCR of a worn thermal print reads one separator differently from the rest."""
    assert redact_pan("CARD 4111 1111-1111 1111 OK") == "CARD ************1111 OK"
    assert redact_pan("4111-1111 1111-1111") == "************1111"
    assert redact_pan("3782-822463 10005") == "***********0005"


def test_redact_pan_redacts_dict_keys_as_well_as_values() -> None:
    assert redact_pan({"4111111111111111": "x"}) == {"************1111": "x"}
    assert redact_pan({"CARD NO.4111111111111111": {"nested 4111111111111111": 1}}) == {
        "CARD NO.************1111": {"nested ************1111": 1}
    }
    # The silent case survives the walk: an ordinary key is untouched.
    assert redact_pan({"total": "1234.56"}) == {"total": "1234.56"}


def test_redact_pan_masks_a_float_pan_but_not_a_money_float() -> None:
    assert redact_pan(4111111111111111.0) == "************1111"
    # Money keeps its type and value -- a float amount is never turned into a mask.
    assert redact_pan(1234.56) == 1234.56
    assert redact_pan(18.0) == 18.0
    # A non-finite float is not a number to inspect; it passes through untouched.
    assert math.isnan(redact_pan(float("nan")))
    assert redact_pan(float("inf")) == float("inf")


def test_redact_pan_walks_sets() -> None:
    assert redact_pan({"4111111111111111"}) == {"************1111"}
    assert redact_pan(frozenset({"CARD 4111111111111111"})) == frozenset({"CARD ************1111"})
    assert isinstance(redact_pan(frozenset({"x"})), frozenset)


def test_redact_pan_is_silent_on_money_hashes_and_last4() -> None:
    for value in (
        "TOTAL 1234.56",
        "last4 1234",
        PHASH,
        "prompt_bundle 0123456789abcdef",
        "2026-07-27 14:30",
        "phone 555-1234",
        "SUBTOTAL 1234567890123.45",
        "qty 2 x 18.00",
        # A decimal fraction is still not a PAN, however long it is.
        "confidence 0.4111111111111111",
        "amount 1234.5678",
        # A short run after a label period stays a short run.
        "REF.1234",
        # A run of small space-separated numbers is not swept into one match.
        "2 18.00 3 20.00 4 25.00 5 30.00",
    ):
        assert redact_pan(value) == value


def test_redact_pan_walks_containers_and_never_mutates_its_input() -> None:
    payload = {
        "text": "PAN 4111111111111111",
        "items": ["ok 1234", {"nested": "4111-1111-1111-1111"}],
        "tokens": 1500,
        "flag": True,
        "nothing": None,
    }
    out = redact_pan(payload)

    assert out == {
        "text": "PAN ************1111",
        "items": ["ok 1234", {"nested": "************1111"}],
        "tokens": 1500,
        "flag": True,
        "nothing": None,
    }
    # Pure: the input is untouched.
    assert payload["text"] == "PAN 4111111111111111"
    assert payload["items"][1]["nested"] == "4111-1111-1111-1111"


def test_redact_pan_masks_a_numeric_pan_but_not_a_small_int() -> None:
    assert redact_pan(4111111111111111) == "************1111"
    assert redact_pan(1234) == 1234
    assert redact_pan(True) is True


# --------------------------------------------------------------------------- #
# query_receipts
# --------------------------------------------------------------------------- #


@pytest.fixture()
def populated(engine: sa.Engine) -> sa.Engine:
    """Five receipts spread across statuses, dates, and confidences."""
    rows = [
        ("2026-07-01", Decimal("0.950"), ReceiptStatus.AUTO_APPROVED),
        ("2026-07-05", Decimal("0.880"), ReceiptStatus.AUTO_APPROVED),
        ("2026-07-10", Decimal("0.400"), ReceiptStatus.NEEDS_REVIEW),
        ("2026-07-20", Decimal("0.700"), ReceiptStatus.NEEDS_REVIEW),
        (None, Decimal("0.100"), ReceiptStatus.NEEDS_REVIEW),
    ]
    with Session(engine) as session:
        for date_iso, confidence, status in rows:
            _save(
                session,
                extraction=_extraction(date_iso=date_iso),
                confidence=confidence,
                status=status,
            )
        session.commit()
    return engine


def test_query_receipts_returns_everything_by_default(populated: sa.Engine) -> None:
    with Session(populated) as session:
        assert len(query_receipts(session)) == 5


def test_query_receipts_filters_by_status(populated: sa.Engine) -> None:
    with Session(populated) as session:
        auto = query_receipts(session, status=ReceiptStatus.AUTO_APPROVED)
        assert len(auto) == 2
        assert all(row.status is ReceiptStatus.AUTO_APPROVED for row in auto)


def test_query_receipts_filters_by_min_confidence(populated: sa.Engine) -> None:
    with Session(populated) as session:
        rows = query_receipts(session, min_confidence=Decimal("0.700"))
        assert sorted(row.confidence for row in rows) == [
            Decimal("0.700"),
            Decimal("0.880"),
            Decimal("0.950"),
        ]


def test_query_receipts_filters_by_date_range(populated: sa.Engine) -> None:
    with Session(populated) as session:
        rows = query_receipts(session, date_from=date(2026, 7, 5), date_to=date(2026, 7, 10))
        # Range is inclusive at both ends, and the undated receipt is excluded.
        assert sorted(row.txn_date for row in rows) == [date(2026, 7, 5), date(2026, 7, 10)]


def test_query_receipts_filters_compose(populated: sa.Engine) -> None:
    with Session(populated) as session:
        rows = query_receipts(
            session,
            status=ReceiptStatus.NEEDS_REVIEW,
            date_from=date(2026, 7, 1),
            min_confidence=Decimal("0.500"),
        )
        assert [row.confidence for row in rows] == [Decimal("0.700")]


def test_query_receipts_paginates_deterministically(populated: sa.Engine) -> None:
    with Session(populated) as session:
        everything = [row.id for row in query_receipts(session)]
        first_page = [row.id for row in query_receipts(session, limit=2)]
        second_page = [row.id for row in query_receipts(session, limit=2, offset=2)]
        tail = [row.id for row in query_receipts(session, limit=2, offset=4)]

    assert first_page == everything[:2]
    assert second_page == everything[2:4]
    assert tail == everything[4:]
    assert len(set(first_page + second_page + tail)) == 5


def test_query_receipts_filters_by_merchant(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = Merchant(canonical_name="Total Wine & More")
        session.add(merchant)
        session.flush()
        merchant_id = merchant.id

        mine = save_extraction(
            session,
            _job(),
            _extraction(),
            ValidationReport(),
            Decimal("0.900"),
            ReceiptStatus.AUTO_APPROVED,
            image_phash=PHASH,
            merchant_id=merchant_id,
        )
        mine_id = mine.id
        _save(session)  # a second receipt with no merchant
        session.commit()

    with Session(engine) as session:
        rows = query_receipts(session, merchant_id=merchant_id)
        assert [row.id for row in rows] == [mine_id]
        assert query_receipts(session, merchant_id=uuid.uuid4()) == []


# --------------------------------------------------------------------------- #
# apply_corrections
# --------------------------------------------------------------------------- #


def test_apply_corrections_writes_one_row_per_changed_field(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        receipt = apply_corrections(
            session,
            job.id,
            {"totals.total": Decimal("761.61"), "line_items[1].qty": Decimal("3")},
            "reviewer@example.com",
        )
        assert receipt.status is ReceiptStatus.REVIEWED

    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(Correction)
                .where(Correction.receipt_id == job.id)
                .order_by(Correction.field_path)
            )
        )
        assert [row.field_path for row in rows] == ["line_items[1].qty", "totals.total"]
        assert all(row.corrected_by == "reviewer@example.com" for row in rows)

        qty_row, total_row = rows
        assert Decimal(qty_row.value_before) == Decimal("1.5")
        assert Decimal(qty_row.value_after) == Decimal("3")
        assert Decimal(total_row.value_before) == Decimal("761.60")
        assert Decimal(total_row.value_after) == Decimal("761.61")

        got = get_receipt(session, job.id)
        assert got is not None
        assert got.status is ReceiptStatus.REVIEWED
        assert isinstance(got.total, Decimal)
        assert got.total == Decimal("761.61")
        assert got.line_items[1].qty == Decimal("3")


def test_apply_corrections_accepts_nested_and_text_patches(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        apply_corrections(
            session,
            job.id,
            {
                "merchant": {"name": "Total Wine & More"},
                "receipt": {"date": "2026-07-28"},
                "totals": {"total": "800.00"},
            },
            "reviewer",
        )

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.merchant_name_raw == "Total Wine & More"
        assert got.txn_date == date(2026, 7, 28)
        assert isinstance(got.total, Decimal)
        assert got.total == Decimal("800.00")
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 3


def test_apply_corrections_noop_patch_writes_no_rows(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        apply_corrections(
            session,
            job.id,
            {"totals.total": Decimal("761.6000"), "merchant.name": "TOTAL WINE"},
            "reviewer",
        )

    with Session(engine) as session:
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 0
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.total == Decimal("761.60")
        # A reviewer confirming an already-correct receipt is still a review.
        assert got.status is ReceiptStatus.REVIEWED


def test_apply_corrections_empty_patch_is_harmless(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        apply_corrections(session, job.id, {}, "reviewer")

    with Session(engine) as session:
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"totals.bogus": Decimal("1")},
        {"nope": "x"},
        {"line_items[9].qty": Decimal("1")},
        {"line_items[0].modifiers": "x"},
        {"totals.total": Decimal("999.99"), "totals.bogus": Decimal("1")},
    ],
)
def test_apply_corrections_rejects_unmappable_paths_and_changes_nothing(
    engine: sa.Engine, patch: dict
) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(ValueError):
            apply_corrections(session, job.id, patch, "reviewer")
        # The failed call rolled back, so a later commit on the same session
        # cannot flush a half-applied patch.
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.total == Decimal("761.60")
        assert got.status is ReceiptStatus.AUTO_APPROVED
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 0


def test_apply_corrections_rejects_a_float_on_the_money_path(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(ValueError):
            apply_corrections(session, job.id, {"totals.total": 761.61}, "reviewer")

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.total == Decimal("761.60")


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_apply_corrections_rejects_a_non_finite_money_string(
    engine: sa.Engine, value: str
) -> None:
    """``Decimal("nan")`` is a legal Decimal -- and a destroyed money column.

    On SQLite it lands as NULL while the ``corrections`` row records ``NaN``, so
    the audit trail disagrees with the column it describes. Refuse it outright.
    """
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(ValueError):
            apply_corrections(session, job.id, {"totals.total": value}, "reviewer")
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.total == Decimal("761.60")
        assert got.status is ReceiptStatus.AUTO_APPROVED
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 0


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_apply_corrections_rejects_a_non_finite_decimal_passed_directly(
    engine: sa.Engine, value: Decimal
) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(ValueError):
            apply_corrections(session, job.id, {"totals.total": value}, "reviewer")
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.total == Decimal("761.60")
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 0


def test_apply_corrections_position_collision_raises_value_error_and_changes_nothing(
    engine: sa.Engine,
) -> None:
    """A collision that only surfaces at commit still honours the documented contract.

    Integrity holds either way -- nothing partial persists -- but the caller is
    promised ``ValueError``, not a raw ``IntegrityError``.
    """
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(ValueError):
            apply_corrections(session, job.id, {"line_items[0].position": 1}, "reviewer")
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert [(item.position, item.description_raw) for item in got.line_items] == [
            (0, "MERLOT"),
            (1, "CABERNET"),
        ]
        assert got.status is ReceiptStatus.AUTO_APPROVED
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 0


def test_apply_corrections_rejects_text_longer_than_the_column(engine: sa.Engine) -> None:
    """``currency`` is ``String(3)``: silently stored on SQLite, a ``DataError`` on Postgres."""
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        with pytest.raises(ValueError):
            apply_corrections(session, job.id, {"receipt.currency": "EURO-LONG"}, "reviewer")
        session.commit()

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.currency == "USD"
        assert got.status is ReceiptStatus.AUTO_APPROVED
        assert session.scalar(select(sa.func.count()).select_from(Correction)) == 0


def test_apply_corrections_accepts_a_currency_that_fits(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        apply_corrections(session, job.id, {"receipt.currency": "EUR"}, "reviewer")

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.currency == "EUR"


def test_apply_corrections_on_an_unknown_receipt_raises(engine: sa.Engine) -> None:
    with Session(engine) as session:
        with pytest.raises(ValueError):
            apply_corrections(session, uuid.uuid4(), {"totals.total": Decimal("1")}, "reviewer")


def test_apply_corrections_keeps_only_the_last_four_card_digits(engine: sa.Engine) -> None:
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        apply_corrections(
            session, job.id, {"payment.card_last4": "4111-1111-1111-4242"}, "reviewer"
        )

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.card_last4 == "4242"


def test_apply_corrections_redacts_a_pan_typed_into_a_free_text_field(
    engine: sa.Engine,
) -> None:
    """§18 through the correction path, **including the audit copy**.

    Only ``payment.card_last4`` was narrowed by ``_last4``; every other text
    path went through ``_coerce_optional_text`` untouched, so a reviewer typing
    the card line off the slip stored a full PAN in ``receipts.payment_method``
    *and* in ``corrections.value_after`` -- and the audit trail is precisely the
    copy nothing later scrubs.
    """
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        apply_corrections(
            session,
            job.id,
            {"payment": {"method": "VISA 4111111111111111"},
             "merchant": {"name": "SUPERMART 4111-1111-1111-1111"}},
            "reviewer",
        )

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.payment_method == "VISA ************1111"
        assert got.merchant_name_raw == "SUPERMART ************1111"

        stored = json.dumps(
            [row.value_after for row in session.scalars(select(Correction))]
        )
        assert "4111111111111111" not in stored
        assert "4111-1111-1111-1111" not in stored
        assert "1111" in stored  # the last four survive


def test_apply_corrections_leaves_non_pan_text_and_money_alone(engine: sa.Engine) -> None:
    """The silent case: redaction must not fire on ordinary reviewer edits."""
    job = _job()
    with Session(engine) as session:
        _save(session, job=job)
        session.commit()

    with Session(engine) as session:
        apply_corrections(
            session,
            job.id,
            {
                "merchant.name": "7-ELEVEN 555-1234",
                "receipt.number": "OR-2026-0001",
                "receipt.date": "2026-07-20",
                "totals.total": Decimal("1234.56"),
                "payment.card_last4": "4242",
            },
            "reviewer",
        )

    with Session(engine) as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.merchant_name_raw == "7-ELEVEN 555-1234"
        assert got.receipt_number == "OR-2026-0001"
        assert got.txn_date == date(2026, 7, 20)
        assert got.total == Decimal("1234.56")
        assert got.card_last4 == "4242"


# --------------------------------------------------------------------------- #
# session helpers
# --------------------------------------------------------------------------- #


def test_make_engine_enables_sqlite_foreign_keys() -> None:
    eng = make_engine("sqlite+pysqlite:///:memory:")
    with eng.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_make_engine_falls_back_to_the_configured_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    eng = make_engine()
    assert eng.url.database == ":memory:"


def test_make_session_factory_produces_working_sessions() -> None:
    eng = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(eng)
    factory = make_session_factory(eng)

    job = _job()
    with factory() as session:
        _save(session, job=job)
        session.commit()

    with factory() as session:
        got = get_receipt(session, job.id)
        assert got is not None
        assert got.total == Decimal("761.60")
        assert isinstance(got.line_items[0], LineItem)
