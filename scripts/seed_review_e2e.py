"""Build the fixture database the Playwright acceptance run reads (P5.T5, design 6.3).

    python scripts/seed_review_e2e.py --reset
    python scripts/seed_review_e2e.py --db sqlite:///var/e2e/review-e2e.db --reset
    python scripts/seed_review_e2e.py --dump-corrections <receipt-id>

**This is test fixture tooling, not a management command.** It is pointed at a
throwaway SQLite file, it deletes that file when `--reset` says so, and nothing
in `src/` imports it.

It goes through the repository (`create_user`, `enqueue_review`,
`save_findings`) and the ORM rather than hand-written SQL, so the seed cannot
drift from the schema -- the same reason `tests/test_api_read.py::_seed` is
built that way, and that helper is what this one is modelled on.

What it creates, and why each part is load-bearing for the acceptance run:

  * a reviewer account (`alice` / `pw-alice`) -- `PATCH /receipts/{id}` writes
    `corrections.corrected_by` from the *session* user, so the audit trail this
    run asserts on only exists if a real account signs in;
  * one `needs_review` receipt whose every correctable column holds a distinct
    non-null value. Distinct on purpose: a form that wired two labels to one
    path, or read the wrong key, still passes against a receipt whose fields
    share a value;
  * two line items, at positions 0 and 1. Two, so that an edit to the second
    proves `line_items[i]` addresses a *position* rather than an index;
  * two historical findings and a non-empty `confidence_reasons`, so the
    findings panel and the confidence rail have something to render;
  * an **open** review task. Without it `GET /review/next` answers
    `{"task": null}`, the screen renders "The review queue is empty." and the
    whole spec is vacuous;
  * a real image blob under the receipt's `image_key`. Without it
    `GET /receipts/{id}/image/blob` 404s and `ImagePane` renders a
    `role="alert"` failure, which is both a false signal and a second alert for
    the spec to trip over.

**The manifest carries identifiers, never field values.** `--out` writes the
receipt id and the credentials, and deliberately not the amounts or dates it
seeded: an assertion that compares the API against this script's own idea of
what it wrote is a round trip through one source and is blind to anything that
reformats both sides. The spec reads the pre-edit values from the API instead.

`--dump-corrections` exists because **no API route exposes the `corrections`
table** (checked across `src/receipts/review/`: `apply_corrections` is called by
`PATCH /receipts/{id}`, and no read route selects the rows it writes), while the
audit trail is exactly what design 6.3 asks the acceptance run to assert. The
spec therefore reads it back through this script rather than through HTTP, and
says so where it does.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from base64 import b64decode
from datetime import date, time
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Running a script puts *its own* directory on sys.path, not the repo root, so
# `config` and `receipts` would not import from a non-editable checkout.
# pyproject's `pythonpath` only applies to pytest. Same bootstrap as
# scripts/try_one_receipt.py, and the project imports stay inside the functions
# that need them so this block does not push them past E402.
for _root in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

DEFAULT_DB_URL = "sqlite:///var/e2e/review-e2e.db"
DEFAULT_STORAGE_ROOT = "var/e2e/blobs"
DEFAULT_MANIFEST = "var/e2e/seed.json"

REVIEWER_USERNAME = "alice"
REVIEWER_PASSWORD = "pw-alice"

#: A real, minimal PNG (1x1, transparent). Its only job is to make
#: ``GET /receipts/{id}/image/blob`` answer 200 with image bytes, so the review
#: screen renders an ``<img>`` instead of its "could not load the receipt image"
#: alert. PNG rather than JPEG because the route derives the media type from the
#: key's extension (``mimetypes.guess_type``), and a declared type that
#: contradicts the bytes is a trap for no gain.
_PNG_1X1 = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def _sqlite_file(db_url: str) -> Path:
    """The file behind ``db_url``, or a refusal.

    Only SQLite, and only a file: this script deletes what it is pointed at when
    ``--reset`` is passed, so it must not be able to reach a Postgres deployment
    or an in-memory database it cannot reset at all.
    """
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        raise SystemExit(
            f"--db must be a file-backed SQLite URL ({prefix}...), got {db_url!r}. "
            "This is an end-to-end fixture; point it at a throwaway file."
        )
    path = db_url[len(prefix) :]
    if not path or path == ":memory:":
        raise SystemExit(f"--db must name a file, got {db_url!r}")
    return Path(path)


#: The bytes every SQLite database file begins with (SQLite file format, 1.3).
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _refuse_unless_sqlite(db_file: Path) -> None:
    """Refuse to delete a file that is not a SQLite database.

    :func:`_sqlite_file` proves the target's *shape* -- the URL scheme, and that
    it names a file -- and can say nothing about its **contents**. That is one
    mistyped ``--db`` away from data loss, and it was measured before this
    function existed: a text file holding ``quarterly numbers nobody backed
    up`` was unlinked and replaced with a database, silently, exit 0.

    A zero-byte file is allowed through. SQLite reads one as a valid empty
    database, a half-finished run can leave one behind, and there is nothing in
    it to destroy.
    """
    if db_file.stat().st_size == 0:
        return
    with db_file.open("rb") as handle:
        header = handle.read(len(_SQLITE_MAGIC))
    if header != _SQLITE_MAGIC:
        raise SystemExit(
            f"{db_file} exists and is not a SQLite database -- it does not begin "
            f"with {_SQLITE_MAGIC!r} -- so --reset will not delete it. Check the "
            "--db path."
        )


def seed(db_url: str, storage_root: Path, *, reset: bool) -> dict[str, str]:
    """Create the schema and the fixture rows. Returns the manifest."""
    from receipts.extract.schema import Legibility
    from receipts.ingest.storage import LocalStorage
    from receipts.persist.models import Base, LineItem, Receipt
    from receipts.persist.repository import save_findings
    from receipts.persist.session import make_engine, make_session_factory
    from receipts.persist.users import ROLE_REVIEWER, create_user
    from receipts.review.queue import enqueue_review
    from receipts.score.confidence import ReceiptStatus
    from receipts.validate.report import Finding, Severity, ValidationReport

    db_file = _sqlite_file(db_url)
    if db_file.exists():
        if not reset:
            raise SystemExit(
                f"{db_file} already exists. Pass --reset to delete and rebuild it -- "
                "a second seed into the same file leaves two queued receipts and the "
                "acceptance run cannot tell which one it claimed."
            )
        _refuse_unless_sqlite(db_file)
        db_file.unlink()
    db_file.parent.mkdir(parents=True, exist_ok=True)

    receipt_id = uuid.uuid4()
    image_key = f"receipts/e2e/{receipt_id}/original.png"
    LocalStorage(storage_root).put(image_key, _PNG_1X1, content_type="image/png")

    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        create_user(session, REVIEWER_USERNAME, REVIEWER_PASSWORD, ROLE_REVIEWER)
        session.add(
            Receipt(
                id=receipt_id,
                status=ReceiptStatus.NEEDS_REVIEW,
                confidence=Decimal("0.570"),
                # Penalties reconstruct the stored confidence exactly
                # (1.000 - 0.350 - 0.080), so the rail is not showing arithmetic
                # that does not add up. Non-empty because `null` and `[]` are
                # different facts on this column and the rail renders all three.
                confidence_reasons=[
                    {"reason": "totals do not reconcile", "penalty": "-0.350"},
                    {"reason": "date looks implausible", "penalty": "-0.080"},
                ],
                merchant_name_raw="TOTAL WINE",
                # The *Sold To* party, distinct from the merchant who sold.
                # Both halves are correctable (`buyer.name`, `buyer.tax_id`),
                # so leaving them NULL made two of the receipt's correctable
                # columns untestable and broke this seed's own "every
                # correctable column holds a distinct non-null value" rule --
                # a spec running against the real server never exercised a
                # populated buyer at all. Neither value is a 13-19 digit
                # all-numeric run, for the reason given on `payment_method`
                # below; verified against `redact_pan`, which returns both
                # unchanged.
                buyer_name_raw="IDEAL SOURCE",
                buyer_tax_id="009-123-456-000",
                receipt_number="OR-2026-0042",
                txn_date=date(2026, 7, 2),
                date_raw="02/07/2026",
                # Seconds on purpose: `receipt.time` is correctable, the detail
                # renders `isoformat()`, and a screen that shortened it to
                # `%H:%M` would book a correction for an edit nobody made.
                txn_time=time(14, 30, 45),
                currency="USD",
                # Six distinct amounts. `1000.00` is the one the acceptance run
                # overwrites; the others are here to be left alone, which is
                # what proves the patch carries only what changed.
                subtotal=Decimal("925.00"),
                tax_total=Decimal("80.00"),
                discount_total=Decimal("5.00"),
                total=Decimal("1000.00"),
                tender_amount=Decimal("1100.00"),
                change_amount=Decimal("100.00"),
                # No value here is a 13-19 digit all-numeric run: `redact_pan`
                # masks those on the way in, and a seed that tripped it would
                # look like a rewrite bug the first time anything compared what
                # was sent against what was stored.
                payment_method="VISA",
                card_last4="4242",
                is_handwritten=True,
                legibility=Legibility.FAIR,
                receipt_is_inconsistent=True,
                image_key=image_key,
                image_phash="",
            )
        )
        session.flush()
        session.add_all(
            [
                LineItem(
                    receipt_id=receipt_id,
                    position=0,
                    description_raw="CABERNET SAUVIGNON 2019",
                    sku="SKU-1001",
                    qty=Decimal("2"),
                    unit="btl",
                    unit_price=Decimal("45.00"),
                    line_total=Decimal("90.00"),
                ),
                LineItem(
                    receipt_id=receipt_id,
                    position=1,
                    description_raw="SPARKLING WATER 750ML",
                    sku="SKU-2002",
                    qty=Decimal("3"),
                    unit="btl",
                    unit_price=Decimal("4.50"),
                    line_total=Decimal("13.50"),
                ),
            ]
        )
        # Through `save_findings`, which takes a `ValidationReport` -- not a list
        # of findings, and not `ValidationFinding` rows built here. That keeps
        # the column set (and `context`'s JSON coercion) the repository's
        # business. The cost: `Finding` has no `created_at`, so both rows take
        # the server default and their relative order is not pinned by this
        # script. The findings panel is rendered, not ordered-asserted, by the
        # acceptance run; `tests/test_api_read.py::_seed` sets `created_at` by
        # hand precisely because it *does* assert the order.
        save_findings(
            session,
            receipt_id,
            ValidationReport(
                findings=[
                    Finding(
                        rule_id="R020",
                        severity=Severity.ERROR,
                        message="totals do not reconcile: 925.00 + 80.00 - 5.00 != 1000.00",
                        field_paths=["totals.total"],
                    ),
                    Finding(
                        rule_id="R011",
                        severity=Severity.WARN,
                        message="date looks implausible",
                        field_paths=["receipt.date"],
                    ),
                ]
            ),
        )
        enqueue_review(session, receipt_id, reason="needs_review", priority=1)
        session.commit()

    return {
        "db_url": db_url,
        "storage_root": str(storage_root),
        "receipt_id": str(receipt_id),
        "username": REVIEWER_USERNAME,
        "password": REVIEWER_PASSWORD,
    }


def dump_corrections(db_url: str, receipt_id: str) -> list[dict[str, str | None]]:
    """The `corrections` rows for one receipt: the audit trail, in writing order.

    Ordered by `created_at` then `field_path` rather than by `created_at` alone:
    one `PATCH` writes every row inside a single statement, so on SQLite the
    timestamps tie and an unordered second key would make the dump's order a
    coin toss.
    """
    from sqlalchemy import select

    from receipts.persist.models import Correction
    from receipts.persist.session import make_engine, make_session_factory

    session_factory = make_session_factory(make_engine(db_url))
    with session_factory() as session:
        rows = session.scalars(
            select(Correction)
            .where(Correction.receipt_id == uuid.UUID(receipt_id))
            .order_by(Correction.created_at, Correction.field_path)
        ).all()
        return [
            {
                "field_path": row.field_path,
                "value_before": row.value_before,
                "value_after": row.value_after,
                "corrected_by": row.corrected_by,
            }
            for row in rows
        ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=DEFAULT_DB_URL, help=f"default: {DEFAULT_DB_URL}")
    parser.add_argument(
        "--storage-root", default=DEFAULT_STORAGE_ROOT, help=f"default: {DEFAULT_STORAGE_ROOT}"
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_MANIFEST,
        help=f"where to write the JSON manifest the spec reads (default: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the SQLite file first; required when it already exists",
    )
    parser.add_argument(
        "--dump-corrections",
        metavar="RECEIPT_ID",
        default=None,
        help="print the corrections rows for a receipt as JSON and exit; seeds nothing",
    )
    args = parser.parse_args(argv)

    if args.dump_corrections is not None:
        print(json.dumps(dump_corrections(args.db, args.dump_corrections), indent=2))
        return 0

    manifest = seed(args.db, Path(args.storage_root), reset=args.reset)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # The receipt id on stdout as well as in the manifest: the manifest is how
    # the spec finds it, and stdout is how a human running this by hand does.
    print(f"receipt_id={manifest['receipt_id']}")
    print(f"manifest={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
