"""The merchant registry: the only module that touches the `merchants` table.

In-memory SQLite with FK enforcement, mirroring `tests/test_dedupe_db.py`.

`lookup` retrieves the merchant whose normalized key EQUALS the normalized
guess, and the tests below constrain that in both directions: a guess that is
merely close to a stored name retrieves nothing, and when several merchants are
stored the one that comes back is named. Both directions are needed. A guess
that only ever runs against a one-row table cannot tell "found the match" from
"returned the only row", and a near miss that only differs by a substituted
character cannot tell exact matching from prefix or substring matching.

The write paths are gated on the extracted `tax_id` instead: `register` needs
one to create a merchant and `confirm` needs a matching one to learn a
spelling, so a name alone can retrieve a merchant but never make or rename one.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from receipts.extract.schema import Merchant as ExtractMerchant
from receipts.extract.schema import ReceiptExtraction
from receipts.merchants.registry import confirm, increment, lookup, register
from receipts.persist import Merchant
from receipts.persist.models import Base


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


def _merchant(session: Session, name: str, **kw) -> Merchant:
    merchant = Merchant(canonical_name=name, **kw)
    session.add(merchant)
    session.flush()
    return merchant


def _directory(session: Session) -> dict[str, Merchant]:
    """Three merchants whose names deliberately overlap.

    `METRO OIL` normalizes to `metro oil`, a strict prefix of the `metro oil
    subic` belonging to a DIFFERENT merchant. Both are real merchants here, so
    the prefix is not a near miss to be rejected -- it is a second row that a
    matcher looser than equality would collide with the first. `METRO OIL SUBIC
    INC.` is inserted first so that a matcher which returns whatever it reaches
    first returns the wrong row rather than accidentally the right one.
    """
    return {
        "subic": _merchant(
            session, "METRO OIL SUBIC INC.", name_variants=["METRO OIL SUBIC BAY"]
        ),
        "metro": _merchant(session, "METRO OIL"),
        "acme": _merchant(session, "ACME HARDWARE INC."),
    }


def test_lookup_matches_the_canonical_name_exactly(engine: sa.Engine) -> None:
    with Session(engine) as session:
        stored = _merchant(session, "METRO OIL SUBIC INC.")

        found = lookup(session, "METRO OIL SUBIC INC.")

        assert found is not None
        assert found.id == stored.id


def test_lookup_folds_case_punctuation_and_legal_suffix(engine: sa.Engine) -> None:
    """`normalize_merchant_name` is what makes these the same merchant."""
    with Session(engine) as session:
        stored = _merchant(session, "METRO OIL SUBIC INC.")

        found = lookup(session, "Metro Oil Subic Inc")

        assert found is not None
        assert found.id == stored.id


def test_lookup_matches_a_known_variant(engine: sa.Engine) -> None:
    with Session(engine) as session:
        stored = _merchant(
            session, "METRO OIL SUBIC INC.", name_variants=["METRO OIL SUBIC BAY"]
        )

        found = lookup(session, "metro oil subic bay")

        assert found is not None
        assert found.id == stored.id


@pytest.mark.parametrize(
    "guess",
    [
        "METRO OIL",            # the stored key starts with the guess
        "METRO OIL SUBIC BAY",  # the guess starts with the stored key
        "OIL SUBIC",            # the guess sits inside the stored key
        "METRO 0IL SUBIC",      # one character differs (letter O -> digit zero)
    ],
)
def test_lookup_does_not_guess(engine: sa.Engine, guess: str) -> None:
    """No fuzzy matching (spec D2): a near miss is a miss.

    One stored merchant, and four ways of being close to it that must all come
    back empty. The shapes are not interchangeable: a substitution alone is
    rejected by a prefix matcher and by a substring matcher too, so it cannot
    tell them apart from exact matching. Each guess above is accepted by at
    least one matcher that is looser than equality.

    `METRO OIL SUBIC BAY` is a MATCH in `test_lookup_matches_a_known_variant`
    and a miss here, and the only difference is that there it is registered in
    `name_variants`. Being registered is what makes a variant, not resembling
    the canonical name.
    """
    with Session(engine) as session:
        _merchant(session, "METRO OIL SUBIC INC.")

        assert lookup(session, guess) is None


def test_lookup_returns_the_matching_merchant_not_just_any_merchant(
    engine: sa.Engine,
) -> None:
    """Which merchant comes back, with more than one to choose from.

    Against a single-row table, "return the row that matched" and "return the
    first row" are the same function. Here they differ, and so do "matched
    exactly" and "matched loosely": `Metro Oil` is the whole name of one
    merchant and the beginning of another's, so a prefix or substring matcher
    retrieves the wrong one.
    """
    with Session(engine) as session:
        directory = _directory(session)

        for label, guess in (
            ("subic", "METRO OIL SUBIC INC."),
            ("subic", "metro oil subic bay"),
            ("metro", "Metro Oil"),
            ("acme", "acme hardware"),
        ):
            found = lookup(session, guess)

            assert found is not None, f"{guess!r} retrieved nothing"
            assert found.id == directory[label].id, (
                f"{guess!r} retrieved {found.canonical_name!r}"
            )


@pytest.mark.parametrize("guess", [None, "", "   ", "Inc."])
def test_lookup_returns_none_for_an_empty_guess(engine: sa.Engine, guess) -> None:
    """`"Inc."` normalizes to the empty string -- it is all legal suffix."""
    with Session(engine) as session:
        _merchant(session, "METRO OIL SUBIC INC.")

        assert lookup(session, guess) is None


# --------------------------------------------------------------------------- #
# The write paths: register, confirm, increment
# --------------------------------------------------------------------------- #


def _extraction(name: str | None, tax_id: str | None) -> ReceiptExtraction:
    return ReceiptExtraction(merchant=ExtractMerchant(name=name, tax_id=tax_id))


def test_register_creates_a_merchant_from_a_confirmed_extraction(engine) -> None:
    with Session(engine) as session:
        created = register(session, _extraction("METRO OIL SUBIC INC.", "123-456-789"))

        assert created is not None
        assert created.canonical_name == "METRO OIL SUBIC INC."
        assert created.tax_id == "123-456-789"


@pytest.mark.parametrize(
    ("name", "tax_id"),
    [("METRO OIL SUBIC INC.", None), (None, "123-456-789"), (None, None)],
)
def test_register_refuses_without_both_a_name_and_a_tax_id(engine, name, tax_id) -> None:
    """A guess must never create a merchant (spec D2)."""
    with Session(engine) as session:
        assert register(session, _extraction(name, tax_id)) is None
        assert session.scalars(select(Merchant)).all() == []


def test_register_returns_the_existing_merchant_for_a_known_tax_id(engine) -> None:
    with Session(engine) as session:
        first = register(session, _extraction("METRO OIL SUBIC INC.", "123-456-789"))
        again = register(session, _extraction("METRO OIL SUBIC BAY", "123-456-789"))

        assert again is not None and first is not None
        assert again.id == first.id
        assert len(session.scalars(select(Merchant)).all()) == 1


def test_register_creates_a_second_merchant_for_a_colliding_name(engine) -> None:
    """Two TINs are two merchants, even when the names share a fingerprint.

    `Metro Oil Subic Incorporated` normalizes to the same key as `METRO OIL
    SUBIC INC.`, because `incorporated` and `inc` are both stripped as legal
    suffixes. They are still two businesses: the TIN says so, and the TIN is
    the identity here. Refusing the second would let a NAME veto a write that a
    `tax_id` authorised -- the weakest field on the receipt overruling the
    strongest -- and that merchant would then be unregisterable for every
    receipt it ever files. So the collision is accepted, and
    `test_lookup_returns_none_when_two_merchants_share_a_key` says what the
    read path does with it.
    """
    with Session(engine) as session:
        first = register(session, _extraction("METRO OIL SUBIC INC.", "123-456-789"))
        second = register(session, _extraction("Metro Oil Subic Incorporated", "987-654-321"))

        assert first is not None and second is not None
        assert second.id != first.id
        assert len(session.scalars(select(Merchant)).all()) == 2


def test_lookup_returns_none_when_two_merchants_share_a_key(engine) -> None:
    """An ambiguous key retrieves nothing rather than a coin-flip winner.

    `register` can put two merchants behind one normalized key, so `lookup` has
    to decide. Returning the first row scanned is not deterministic -- no query
    here is ordered -- and ordering it would only make the wrong answer stable,
    since either choice hands one merchant's hints to the other merchant's
    receipt. That is the same harm `lookup` refuses fuzzy matching to avoid, so
    an ambiguous key resolves to nothing. The receipt loses its hints and
    nothing else: it still gets its merchant afterwards, from the `tax_id`.
    """
    with Session(engine) as session:
        register(session, _extraction("METRO OIL SUBIC INC.", "123-456-789"))
        register(session, _extraction("Metro Oil Subic Incorporated", "987-654-321"))

        assert lookup(session, "metro oil subic") is None
        assert lookup(session, "Metro Oil Subic, Inc.") is None


def test_confirm_learns_a_new_spelling(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.", tax_id="123-456-789")

        confirm(session, merchant, "123-456-789", "METRO OIL SUBIC BAY")

        assert merchant.name_variants == ["METRO OIL SUBIC BAY"]
        assert lookup(session, "metro oil subic bay") is not None


def test_confirm_ignores_a_mismatched_tax_id(engine) -> None:
    """The TIN is what authorises the rename. Without it, nothing is learned."""
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.", tax_id="123-456-789")

        confirm(session, merchant, "999-999-999", "TOTALLY DIFFERENT SHOP")

        assert merchant.name_variants == []


def test_confirm_does_not_duplicate_a_spelling_it_already_knows(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.", tax_id="123-456-789")

        confirm(session, merchant, "123-456-789", "Metro Oil Subic Inc")

        assert merchant.name_variants == []


def test_confirm_refuses_a_spelling_another_merchant_already_answers_to(engine) -> None:
    """A merchant's own TIN authorises writes to IT, not writes against others.

    `METRO OIL` here is handed `ACME HARDWARE` under its own correct TIN, and
    that key already belongs to a different merchant. Learning it would make
    the key ambiguous, and `lookup` resolves an ambiguous key to nothing -- so
    a write authorised for `METRO OIL` would silently de-register `ACME
    HARDWARE INC.`, which never consented and whose TIN was never presented.
    The refusal is what keeps a `tax_id` scoped to its own merchant.

    Cheap in the other direction: a variant is discretionary widening, so
    declining one costs a spelling. `register` faces the same collision and
    accepts it, because refusing THERE would cost a whole merchant.
    """
    with Session(engine) as session:
        acme = _merchant(session, "ACME HARDWARE INC.", tax_id="111")
        metro = _merchant(session, "METRO OIL", tax_id="222")

        confirm(session, metro, "222", "ACME HARDWARE")

        assert metro.name_variants == []
        found = lookup(session, "ACME HARDWARE INC.")
        assert found is not None and found.id == acme.id


def test_confirm_persists_a_learned_spelling_past_the_transaction(engine) -> None:
    """The spelling has to outlive the session that learned it.

    `name_variants` is a plain JSON column with no `MutableList`, so SQLAlchemy
    notices a change only when the attribute is REASSIGNED. An in-place
    `.append()` satisfies every other assertion in this file -- the list looks
    right for the rest of the transaction -- and then writes nothing: the row
    still reads `[]` afterwards and the spelling is gone, with no error raised
    anywhere. Only a reload in a second session tells the two apart.
    """
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.", tax_id="123-456-789")
        merchant_id = merchant.id

        confirm(session, merchant, "123-456-789", "METRO OIL SUBIC BAY")
        session.commit()

    with Session(engine) as session:
        reloaded = session.get(Merchant, merchant_id)

        assert reloaded is not None
        assert reloaded.name_variants == ["METRO OIL SUBIC BAY"]
        assert lookup(session, "metro oil subic bay") is not None


def test_increment_counts_receipts(engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session, "METRO OIL SUBIC INC.")
        assert merchant.receipt_count == 0

        increment(session, merchant)
        increment(session, merchant)

        assert merchant.receipt_count == 2
