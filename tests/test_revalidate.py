"""Round-trip fidelity, and the re-validation built on it.

The property under test: **persisting a receipt and rebuilding it must not
change what ``validate()`` says about it.** Re-validating a reviewer's
correction is worthless otherwise -- the reviewer would be shown findings
caused by the database, attributed to their edit.
"""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from eval.golden_set import DEFAULT_LABELS_DIR, load_labels
from receipts.extract.schema import ReceiptExtraction, TaxBand
from receipts.ingest.ingest import ReceiptJob
from receipts.persist.models import Base, ReceiptStatus
from receipts.persist.repository import create_pending_receipt, save_extraction
from receipts.review.serializers import _export_extraction
from receipts.validate.context import ValidationContext
from receipts.validate.report import ValidationReport
from receipts.validate.validator import validate

GOLDEN_LABELS = load_labels(DEFAULT_LABELS_DIR)


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


def _round_trip(engine: sa.Engine, extraction: ReceiptExtraction) -> ReceiptExtraction:
    """Persist through the real writer, rebuild through the real reader."""
    rid = uuid.uuid4()
    job = ReceiptJob(
        id=rid,
        image_key=f"receipts/2026/08/{rid}/original.jpg",
        source="upload",
        original_filename="receipt.jpg",
        content_type="image/jpeg",
    )
    with Session(engine) as session:
        receipt = save_extraction(
            session, job, extraction, ValidationReport(),
            D("0.9"), ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()
        return _export_extraction(receipt)


def _finding_ids(extraction: ReceiptExtraction) -> list[str]:
    return sorted(f"{f.rule_id}/{f.severity.value}" for f in validate(extraction).findings)


def _refund() -> ReceiptExtraction:
    """r001 as a refund: every printed amount negated, ``is_refund`` set.

    This is the fixture that matters. Measured 2026-08-24, before the columns
    existed: it validated clean at extraction and produced ``R040/ERROR`` after
    a round trip, because ``meta.is_refund`` was a column on nothing and the
    rebuild assumed a sale. No reviewer touched it.
    """
    raw = json.loads((DEFAULT_LABELS_DIR / "r001.json").read_text(encoding="utf-8"))
    r = ReceiptExtraction.model_validate(raw)
    r.meta.is_refund = True
    r.totals.total = D("-1000.00")
    r.totals.subtotal = D("-892.86")
    r.totals.tax = D("-107.14")
    for item in r.line_items:
        if not item.is_template_row:
            item.line_total = D("-1000.00")
            item.unit_price = D("-102.00")
    return r


def _r002_with_a_tax_band() -> ReceiptExtraction:
    """A fresh r002 carrying a real tax band.

    Fresh rather than ``GOLDEN_LABELS["r002"]``, because the module-level dict
    is shared with the parametrized test and editing it in place would change
    what that test measures.

    **The band has to be there for the assertion below to be able to fail.**
    Every golden label ships ``tax_breakdown: []`` and ``Totals.tax_breakdown``
    defaults to ``[]``, so against an empty breakdown ``rebuilt == original``
    holds whether or not :func:`_export_extraction` reads the column at all --
    measured 2026-08-24, deleting the rebuild left the *whole suite* green. One
    band summing to r002's printed tax gives the round trip something to lose,
    and keeps R025 (bands sum to ``totals.tax``) silent so the findings still
    agree.
    """
    raw = json.loads((DEFAULT_LABELS_DIR / "r002.json").read_text(encoding="utf-8"))
    r = ReceiptExtraction.model_validate(raw)
    r.totals.tax_breakdown = [
        TaxBand(label="VAT", base=D("1785.71"), rate=D("0.12"), amount=D("214.29"))
    ]
    return r


@pytest.mark.parametrize("case_id", [*sorted(GOLDEN_LABELS), "refund"])
def test_a_round_trip_does_not_change_what_validate_says(engine, case_id) -> None:
    """The standing guard. No edit is involved anywhere in this test."""
    original = _refund() if case_id == "refund" else GOLDEN_LABELS[case_id]
    rebuilt = _round_trip(engine, original)
    assert _finding_ids(rebuilt) == _finding_ids(original), (
        f"{case_id}: the database changed the answer. "
        f"extraction={_finding_ids(original)} rebuilt={_finding_ids(rebuilt)}"
    )


def test_a_round_trip_preserves_the_fields_no_rule_happens_to_read_today(engine) -> None:
    """Asserted on the VALUES, not only on the findings.

    Findings agreeing is a weaker claim than the fields surviving: r002 carries
    ``prices_include_tax=True`` and loses it to ``None`` without changing r002's
    findings at all, because ``None`` merely accepts both conventions. The
    silent loosening is the defect; this is what sees it.
    """
    original = _r002_with_a_tax_band()
    rebuilt = _round_trip(engine, original)
    assert rebuilt.totals.prices_include_tax == original.totals.prices_include_tax
    assert rebuilt.meta.is_refund == original.meta.is_refund
    assert rebuilt.totals.tax_breakdown == original.totals.tax_breakdown


def test_a_row_that_recorded_no_tax_breakdown_still_rebuilds(engine) -> None:
    """A pending receipt has no tax_bands rows.

    ``create_pending_receipt`` writes id/image_key/image_phash/status/confidence
    and nothing else, so ``tax_bands`` is an empty list (no child rows). The
    rebuild in :func:`_export_extraction` must handle that gracefully and produce
    an empty ``tax_breakdown`` in the schema rather than raising.
    """
    job = ReceiptJob(
        id=uuid.uuid4(),
        image_key="receipts/2026/08/pending/original.jpg",
        source="upload",
        original_filename="receipt.jpg",
        content_type="image/jpeg",
    )
    with Session(engine) as session:
        receipt = create_pending_receipt(session, job)
        session.commit()
        # A pending receipt has zero tax_bands rows.
        assert receipt.tax_bands == []
        assert _export_extraction(receipt).totals.tax_breakdown == []


# --------------------------------------------------------------------------- #
# Re-validation on read (Task 4)
# --------------------------------------------------------------------------- #


def test_revalidate_runs_the_content_rules_on_the_stored_receipt(engine) -> None:
    """A defect introduced after extraction is found, with no re-extraction."""
    from receipts.review.serializers import revalidate

    original = GOLDEN_LABELS["r001"]
    rid = uuid.uuid4()
    job = ReceiptJob(
        id=rid, image_key=f"receipts/2026/08/{rid}/original.jpg", source="upload",
        original_filename="receipt.jpg", content_type="image/jpeg",
    )
    with Session(engine) as session:
        receipt = save_extraction(
            session, job, original, ValidationReport(),
            D("0.9"), ReceiptStatus.NEEDS_REVIEW,
        )
        session.commit()
        assert revalidate(receipt).findings == []

        # What a reviewer does with the Template checkbox: flag the only row
        # that was actually bought. R026 exists for exactly this.
        for item in receipt.line_items:
            item.is_template_row = True
        session.commit()
        assert revalidate(receipt).fired("R026")


def test_revalidate_never_runs_a_rule_whose_subject_is_the_extraction_run() -> None:
    """The RUN rules must be absent, not merely silent.

    Silence is what they would produce anyway with no context -- so asserting
    "no R060 finding" proves nothing. This asserts on the rule set that RAN.
    """
    from receipts.review.serializers import _CONTENT_RULES, not_rechecked

    run_ids = {"R001", "R013", "R060", "R061", "R070", "R071"}
    assert {r.id for r in _CONTENT_RULES} & run_ids == set()
    assert not_rechecked() == ["R001", "R013", "R060", "R061", "R070", "R071"]


def test_a_rule_that_crashes_is_contained_and_the_loop_carries_on(
    engine, monkeypatch, caplog
) -> None:
    """A broken rule costs one rule's answer, not the whole review screen.

    :func:`revalidate` runs its own loop rather than calling ``validate()``, so
    it does not inherit that function's crash containment and needs its own.
    The two containments are **not** the same: ``validate()`` turns the crash
    into an INFO ``{id}.crashed`` finding a reviewer can see, while this one
    only logs -- which is why the log line is asserted here. A bare
    ``except Exception: pass`` would leave nothing at all behind.

    R010 is broken rather than R026 so that the surviving R026 finding proves
    the loop carried *past* the crash: ``_CONTENT_RULES`` is id-ordered, so R010
    is reached first.
    """
    from receipts.review.serializers import _CONTENT_RULES, revalidate

    victim = next(rule for rule in _CONTENT_RULES if rule.id == "R010")

    def boom(self, r, ctx):
        raise RuntimeError("deliberate crash in a rule")

    original = GOLDEN_LABELS["r001"]
    rid = uuid.uuid4()
    job = ReceiptJob(
        id=rid, image_key=f"receipts/2026/08/{rid}/original.jpg", source="upload",
        original_filename="receipt.jpg", content_type="image/jpeg",
    )
    with Session(engine) as session:
        receipt = save_extraction(
            session, job, original, ValidationReport(),
            D("0.9"), ReceiptStatus.NEEDS_REVIEW,
        )
        for item in receipt.line_items:
            item.is_template_row = True
        session.commit()

        # Not vacuous: a rule whose ``applies()`` said no would never reach the
        # ``check()`` this test breaks, and the containment would go unexercised.
        assert victim.applies(_export_extraction(receipt), ValidationContext())

        monkeypatch.setattr(type(victim), "check", boom)
        with caplog.at_level(logging.ERROR, logger="receipts.review.serializers"):
            report = revalidate(receipt)

    assert report.fired("R026")
    assert "R010" in caplog.text
