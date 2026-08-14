"""The merchant registry: the only module that touches the `merchants` table.

In-memory SQLite with FK enforcement, mirroring `tests/test_dedupe_db.py`.

`lookup` retrieves the merchant whose normalized key EQUALS the normalized
guess, and the tests below constrain that in both directions: a guess that is
merely close to a stored name retrieves nothing, and when several merchants are
stored the one that comes back is named. Both directions are needed. A guess
that only ever runs against a one-row table cannot tell "found the match" from
"returned the only row", and a near miss that only differs by a substituted
character cannot tell exact matching from prefix or substring matching.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from receipts.merchants.registry import lookup
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
