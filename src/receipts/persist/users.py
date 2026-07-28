"""The user store and password hashing for the review service (P4.T3).

Hashing lives here rather than in the web layer for one structural reason:
:func:`verify_credentials` needs it, and ``persist`` must never import from
``review`` -- the dependency runs the other way.

Hashing is stdlib :func:`hashlib.scrypt` with a per-user random salt, encoded as
``scrypt$n$r$p$<salt_b64>$<hash_b64>``. No passlib, no bcrypt, no new dependency.

Conventions inherited from the repository layer (ADR-0006): every function takes
an explicit ``Session`` first, **the caller commits**, and a bad argument raises
``ValueError`` at the boundary.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User

__all__ = [
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_REVIEWER",
    "create_user",
    "deactivate",
    "get_user",
    "hash_password",
    "list_users",
    "set_role",
    "verify_credentials",
    "verify_password",
]

ROLE_REVIEWER = "reviewer"
ROLE_ADMIN = "admin"
ROLES = frozenset({ROLE_REVIEWER, ROLE_ADMIN})

_SCHEME = "scrypt"
_N = 2**14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32

#: Hashed once at import and compared against when the username is unknown, so a
#: failed login takes the same work whether or not the account exists.
_DUMMY_PASSWORD = "the-account-that-does-not-exist"


def _derive(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_KEY_LEN)


def hash_password(password: str) -> str:
    """Encode ``password`` as ``scrypt$n$r$p$salt$hash``.

    The parameters travel with the hash so they can be raised later without
    invalidating existing accounts.
    """
    if not password:
        raise ValueError("password must not be empty")
    salt = os.urandom(_SALT_BYTES)
    derived = _derive(password, salt, n=_N, r=_R, p=_P)
    return "$".join([
        _SCHEME, str(_N), str(_R), str(_P),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    ])


def verify_password(password: str, encoded: str) -> bool:
    """Whether ``password`` matches ``encoded``. Never raises on a malformed hash."""
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = encoded.split("$")
        if scheme != _SCHEME:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = _derive(password, salt, n=int(n_s), r=int(r_s), p=int(p_s))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, expected)


def _validated_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {sorted(ROLES)}")
    return role


def create_user(session: Session, username: str, password: str, role: str) -> User:
    """Add an account. Flushes; does not commit. ``ValueError`` on a duplicate."""
    username = username.strip()
    if not username:
        raise ValueError("username must not be empty")
    _validated_role(role)
    if get_user(session, username) is not None:
        raise ValueError(f"user {username!r} already exists")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def get_user(session: Session, username: str) -> User | None:
    return session.scalars(select(User).where(User.username == username)).one_or_none()


def verify_credentials(session: Session, username: str, password: str) -> User | None:
    """The active account matching these credentials, or ``None``.

    An unknown username still runs a derivation against a dummy hash, so login
    timing does not tell an attacker which usernames exist. A deactivated account
    fails exactly like a wrong password -- the caller must not be able to
    distinguish them either.
    """
    user = get_user(session, username)
    if user is None:
        verify_password(password, hash_password(_DUMMY_PASSWORD))
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def set_role(session: Session, username: str, role: str) -> User:
    user = get_user(session, username)
    if user is None:
        raise ValueError(f"no user named {username!r}")
    user.role = _validated_role(role)
    session.flush()
    return user


def deactivate(session: Session, username: str) -> User:
    user = get_user(session, username)
    if user is None:
        raise ValueError(f"no user named {username!r}")
    user.is_active = False
    session.flush()
    return user


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.username)))


def _main(argv: list[str] | None = None) -> int:
    """``python -m receipts.persist.users create <username> --role admin``.

    The password is read from stdin, never from ``argv``: an argument lands in
    shell history and in ``ps`` output.
    """
    import argparse
    import getpass

    from .session import make_engine, make_session_factory

    parser = argparse.ArgumentParser(prog="python -m receipts.persist.users")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="add an account")
    create.add_argument("username")
    create.add_argument("--role", default=ROLE_REVIEWER, choices=sorted(ROLES))
    args = parser.parse_args(argv)

    password = getpass.getpass("password: ")
    engine = make_engine()
    session = make_session_factory(engine)()
    try:
        create_user(session, args.username, password, args.role)
        session.commit()
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        session.close()
    print(f"created {args.username} ({args.role})")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())
