"""Tests for the user store and password hashing (P4.T3).

Everything here runs on an in-memory SQLite database with ``PRAGMA
foreign_keys=ON`` -- the same fixture pattern as ``test_models.py`` and
``test_repository.py``. No Postgres, no network.

The load-bearing behaviours pinned down below:

  * a hash verifies the password it was made from and rejects a wrong one;
  * a tampered or garbage encoded hash returns ``False`` rather than raising;
  * two hashes of the same password differ (a random salt per user);
  * ``create_user`` refuses a duplicate username and an unknown role, both with
    ``ValueError`` (repository convention: never a bare ``IntegrityError``);
  * ``verify_credentials`` returns ``None`` -- never raises, never leaks which
    case it was -- for an unknown user, a wrong password, and a deactivated
    account;
  * ``set_role``/``deactivate`` raise ``ValueError`` for an unknown username.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from receipts.persist.models import Base
from receipts.persist.users import (
    ROLE_ADMIN,
    ROLE_REVIEWER,
    ROLES,
    create_user,
    deactivate,
    get_user,
    hash_password,
    list_users,
    set_role,
    verify_credentials,
    verify_password,
)


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
# hash_password / verify_password
# --------------------------------------------------------------------------- #


def test_a_hash_verifies_its_own_password() -> None:
    encoded = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", encoded) is True


def test_a_hash_rejects_a_wrong_password() -> None:
    encoded = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", encoded) is False


def test_hash_password_rejects_an_empty_password() -> None:
    with pytest.raises(ValueError):
        hash_password("")


@pytest.mark.parametrize(
    "garbage",
    [
        "not-a-hash-at-all",
        "scrypt$16384$8$1$onlyfourparts",
        "bcrypt$16384$8$1$c2FsdA==$aGFzaA==",  # wrong scheme
        "scrypt$notanumber$8$1$c2FsdA==$aGFzaA==",  # non-numeric param
        "scrypt$16384$8$1$not-base64!!!$aGFzaA==",  # malformed base64
        "",
    ],
)
def test_verify_password_returns_false_rather_than_raising_on_garbage(garbage: str) -> None:
    assert verify_password("anything", garbage) is False


def test_two_hashes_of_the_same_password_differ() -> None:
    """A random salt per call, so equal passwords never produce equal hashes."""
    first = hash_password("correct-horse-battery-staple")
    second = hash_password("correct-horse-battery-staple")
    assert first != second
    # Both still verify against the same password.
    assert verify_password("correct-horse-battery-staple", first) is True
    assert verify_password("correct-horse-battery-staple", second) is True


# --------------------------------------------------------------------------- #
# create_user / get_user
# --------------------------------------------------------------------------- #


def test_create_user_persists_an_account(engine: sa.Engine) -> None:
    with Session(engine) as session:
        user = create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
        session.commit()

        assert user.username == "alice"
        assert user.role == ROLE_REVIEWER
        assert user.is_active is True
        # The stored password is never the plaintext.
        assert user.password_hash != "correct-horse"


def test_create_user_rejects_a_duplicate_username(engine: sa.Engine) -> None:
    with Session(engine) as session:
        create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
        session.commit()
        with pytest.raises(ValueError, match="already exists"):
            create_user(session, "alice", "another-password", ROLE_ADMIN)


def test_create_user_rejects_an_unknown_role(engine: sa.Engine) -> None:
    with Session(engine) as session:
        with pytest.raises(ValueError):
            create_user(session, "alice", "correct-horse", "superuser")


def test_get_user_returns_none_for_an_unknown_username(engine: sa.Engine) -> None:
    with Session(engine) as session:
        assert get_user(session, "nobody") is None


# --------------------------------------------------------------------------- #
# verify_credentials
# --------------------------------------------------------------------------- #


def test_verify_credentials_accepts_the_right_password(engine: sa.Engine) -> None:
    with Session(engine) as session:
        create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
        session.commit()

        user = verify_credentials(session, "alice", "correct-horse")
        assert user is not None
        assert user.username == "alice"


def test_verify_credentials_returns_none_for_an_unknown_user(engine: sa.Engine) -> None:
    with Session(engine) as session:
        assert verify_credentials(session, "nobody", "anything") is None


def test_verify_credentials_returns_none_for_a_wrong_password(engine: sa.Engine) -> None:
    with Session(engine) as session:
        create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
        session.commit()
        assert verify_credentials(session, "alice", "wrong-password") is None


def test_deactivated_user_cannot_authenticate(engine: sa.Engine) -> None:
    with Session(engine) as session:
        create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
        session.commit()
        deactivate(session, "alice")
        session.commit()
        assert verify_credentials(session, "alice", "correct-horse") is None


# --------------------------------------------------------------------------- #
# set_role / deactivate / list_users
# --------------------------------------------------------------------------- #


def test_set_role_changes_the_role(engine: sa.Engine) -> None:
    with Session(engine) as session:
        create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
        session.commit()
        user = set_role(session, "alice", ROLE_ADMIN)
        session.commit()
        assert user.role == ROLE_ADMIN


def test_set_role_rejects_an_unknown_username(engine: sa.Engine) -> None:
    with Session(engine) as session:
        with pytest.raises(ValueError):
            set_role(session, "nobody", ROLE_ADMIN)


def test_set_role_rejects_an_unknown_role(engine: sa.Engine) -> None:
    with Session(engine) as session:
        create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
        session.commit()
        with pytest.raises(ValueError):
            set_role(session, "alice", "superuser")


def test_deactivate_rejects_an_unknown_username(engine: sa.Engine) -> None:
    with Session(engine) as session:
        with pytest.raises(ValueError):
            deactivate(session, "nobody")


def test_list_users_returns_every_account_ordered_by_username(engine: sa.Engine) -> None:
    with Session(engine) as session:
        create_user(session, "bob", "password-2", ROLE_REVIEWER)
        create_user(session, "alice", "password-1", ROLE_ADMIN)
        session.commit()

        assert [user.username for user in list_users(session)] == ["alice", "bob"]


def test_roles_constant_contains_exactly_reviewer_and_admin() -> None:
    assert ROLES == {ROLE_REVIEWER, ROLE_ADMIN}
