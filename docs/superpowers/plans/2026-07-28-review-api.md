# P4.T3 — Review API, Session Auth, and Role Checks: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI review service of SPEC §14.9 — ten routes behind session auth with `reviewer`/`admin` roles plus a machine-upload API key — on branch `feat/service`.

**Architecture:** An app factory (`create_app`) takes its collaborators injected — session factory, storage backend, and a `submit` callable for queueing work — exactly as `process_receipt` does, so the whole suite runs on SQLite + a temp-directory `LocalStorage` + a recording `submit` with no Redis and no network. Accounts live in a new `users` table; the confidence breakdown is persisted at process time in a new `receipts.confidence_reasons` column, because it cannot be honestly recomputed at read time. A receipt row is written as `PENDING` at upload so a job the queue loses is visible rather than vanished.

**Tech Stack:** Python 3.11+ (dev interpreter 3.14.4), FastAPI + Starlette `SessionMiddleware`, SQLAlchemy 2.0, Alembic, pydantic v2 / pydantic-settings, openpyxl, pytest, ruff. Password hashing is stdlib `hashlib.scrypt` — no passlib, no bcrypt.

**Source spec:** `docs/superpowers/specs/2026-07-28-review-api-design.md` (decisions D1–D4 in its §2).

## Global Constraints

Every task inherits these. They are project invariants, not preferences.

- **`Decimal` on the money path, never `float`** (ADR-0001). A structural test walks the schema and fails on any `Float` column.
- **Validation stays deterministic and pure** — never mutates, never raises, stable rule IDs, never renumbered.
- **Prefer `null` over a confident wrong value.** Never invent a number to fill a column.
- **A full PAN is never persisted** — last four only; `redact_pan` guards `extraction_runs.raw_response` (ADR-0007) and is never bypassed.
- **Nothing is silently dropped** — every receipt reaches a terminal state (ADR-0011, SPEC §18).
- **Repository conventions** (ADR-0006): every function takes an explicit `Session` first, **the caller commits** (`apply_corrections` is the documented exception), and a bad argument raises `ValueError` — never a bare `IntegrityError` — at the boundary.
- **`python -m pytest` must stay offline**: fake client, SQLite, temp-dir `LocalStorage`, no Redis, no network. Anything needing an optional extra is guarded with `pytest.importorskip`, matching `tests/test_process_receipt.py`.
- **`python -m ruff check .` must stay clean.** Line length 100. Do not "fix" `from alembic import command` import order in tests — ruff sorts it first-party because the repo-root `alembic/` directory shadows the package.
- **Never stage `.kiro/settings/mcp.json`.** It is a persistent local working-tree edit. Stage only the files your task names.
- Alembic's console script is not on PATH — always `python -m alembic`.
- PowerShell clips piped Python output; capture summaries with `python -m pytest 2>&1 | Select-Object -Last 3` or redirect to a file.
- Commit messages are conventional: `feat(scope): …`, `fix(scope): …`, `chore: …`.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `alembic/versions/a1c4d2f80b31_users_and_confidence_reasons.py` | One revision: the `users` table and `receipts.confidence_reasons` |
| `src/receipts/persist/users.py` | The user store *and* password hashing (stdlib scrypt). Hashing lives here, not in the web layer, because `verify_credentials` needs it and `persist` must never import from `review` |
| `src/receipts/score/thresholds.py` | The two routing thresholds, defined once |
| `src/receipts/review/auth.py` | Session wiring, the role guards, the login/logout router |
| `src/receipts/review/schemas.py` | Request/response models |
| `src/receipts/review/serializers.py` | ORM → response payloads; ORM → `(ReceiptExtraction, ReceiptExportRow)` for export |
| `src/receipts/review/api.py` | `create_app` and the routes |
| `tests/test_users.py`, `tests/test_auth.py`, `tests/test_api_read.py`, `tests/test_api_write.py` | Per-area tests |

**Modified**

| File | Change |
|---|---|
| `src/receipts/persist/models.py` | `+User`, `+Receipt.confidence_reasons` |
| `src/receipts/persist/repository.py` | `save_extraction` update-or-insert + `confidence_reasons`; `+create_pending_receipt`; `+get_findings` |
| `src/receipts/persist/__init__.py` | Lazy exports for the three new names |
| `src/receipts/pipeline.py` | Compute `explain_confidence` next to the score and thread it through |
| `src/receipts/review/queue.py` | `enqueue_review` insert-safe (SAVEPOINT) |
| `src/receipts/score/confidence.py`, `config/settings.py`, `eval/metrics.py`, `src/receipts/export/xlsx.py` | Import the shared thresholds |
| `src/receipts/extract/clients/limits.py` | `_as_money` non-finite gate |
| `src/receipts/ingest/ingest.py` | `max_mb` parameter on `ingest_file` / `ingest_bytes` |
| `pyproject.toml`, `.github/workflows/ci.yml` | The `api` extra; `httpx` in `dev`; CI installs it |

**Two deviations from the spec's §11 task split, both deliberate:**

1. The spec's single "routes" task is split into **Task 4 (read) and Task 5
   (write)**. A reviewer can meaningfully reject the write surface while
   approving the read surface, which is the test for where a task boundary
   belongs; one task carrying eleven routes is not independently reviewable.
2. **Password hashing lives in `persist/users.py`, not `review/auth.py`** (spec
   §3.2 put it in the latter). `verify_credentials` needs it, and `persist` must
   never import from the web layer — the dependency runs the other way.
   `review/auth.py` imports it from there.

---

## Task 1: Schema — users, confidence reasons, and the pending row

**Files:**
- Modify: `src/receipts/persist/models.py` (add `User` after `ReviewTask`; add one column to `Receipt`)
- Modify: `src/receipts/persist/repository.py:263` (`save_extraction`), plus two new functions
- Modify: `src/receipts/persist/__init__.py:56` (`_LAZY` map, `TYPE_CHECKING` block, `__all__`)
- Modify: `src/receipts/pipeline.py:472` (score stage), `:583` (`_persist_outcome`)
- Create: `src/receipts/persist/users.py`
- Create: `alembic/versions/a1c4d2f80b31_users_and_confidence_reasons.py`
- Test: `tests/test_users.py` (new), `tests/test_repository.py` (append)

**Interfaces:**
- Consumes: `Receipt`, `ReceiptJob`, `ValidationFinding`, `save_extraction`, `score_confidence`, `explain_confidence` (all existing).
- Produces, relied on by every later task:
  ```python
  # persist/users.py
  ROLE_REVIEWER = "reviewer"
  ROLE_ADMIN = "admin"
  ROLES = frozenset({ROLE_REVIEWER, ROLE_ADMIN})

  def hash_password(password: str) -> str
  def verify_password(password: str, encoded: str) -> bool
  def create_user(session: Session, username: str, password: str, role: str) -> User
  def get_user(session: Session, username: str) -> User | None
  def verify_credentials(session: Session, username: str, password: str) -> User | None
  def set_role(session: Session, username: str, role: str) -> User
  def deactivate(session: Session, username: str) -> User
  def list_users(session: Session) -> list[User]

  # persist/repository.py
  def create_pending_receipt(session: Session, job: ReceiptJob) -> Receipt
  def get_findings(session: Session, receipt_id: uuid.UUID) -> list[ValidationFinding]
  def save_extraction(..., confidence_reasons: list[tuple[str, Decimal]] | None = None) -> Receipt
  ```

- [ ] **Step 1: Write the failing model + repository tests**

Append to `tests/test_repository.py` (it already builds an in-memory SQLite engine with `PRAGMA foreign_keys=ON`; reuse that fixture):

```python
def test_create_pending_receipt_writes_a_visible_row(session):
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="receipts/2026/07/x/original.jpg",
        source="upload", original_filename="r.jpg", content_type="image/jpeg",
    )
    receipt = create_pending_receipt(session, job)
    session.commit()

    assert receipt.status is ReceiptStatus.PENDING
    assert receipt.confidence == Decimal("0")
    # The perceptual hash is computed by the worker's preprocess stage. An empty
    # hash is what find_duplicate_by_phash skips, so a pending row can never
    # become the "original" a later upload is marked a duplicate of.
    assert receipt.image_phash == ""
    assert receipt.confidence_reasons is None


def test_create_pending_receipt_rejects_a_reused_id(session):
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="upload",
        original_filename="r.jpg", content_type="image/jpeg",
    )
    create_pending_receipt(session, job)
    session.commit()
    with pytest.raises(ValueError, match="already exists"):
        create_pending_receipt(session, job)


def test_save_extraction_updates_the_pending_row_instead_of_colliding(session):
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="upload",
        original_filename="r.jpg", content_type="image/jpeg",
    )
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


def test_save_extraction_replaces_line_items_on_a_second_run(session):
    job = ReceiptJob(
        id=uuid.uuid4(), image_key="k", source="upload",
        original_filename="r.jpg", content_type="image/jpeg",
    )
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


def test_empty_reasons_and_missing_reasons_are_different(session):
    job = ReceiptJob(id=uuid.uuid4(), image_key="k", source="upload",
                     original_filename="r.jpg", content_type="image/jpeg")
    receipt = save_extraction(
        session, job, ReceiptExtraction(), ValidationReport(), Decimal("1.0"),
        ReceiptStatus.AUTO_APPROVED, confidence_reasons=[],
    )
    session.commit()
    # [] means "nothing lowered the score"; NULL means "never recorded".
    assert receipt.confidence_reasons == []


def test_get_findings_returns_them_in_write_order(session):
    job = ReceiptJob(id=uuid.uuid4(), image_key="k", source="upload",
                     original_filename="r.jpg", content_type="image/jpeg")
    receipt = save_extraction(session, job, ReceiptExtraction(), ValidationReport(),
                              Decimal("0.5"), ReceiptStatus.NEEDS_REVIEW)
    report = ValidationReport(findings=[
        Finding(rule_id="R020", severity=Severity.ERROR, message="lines do not sum"),
        Finding(rule_id="R011", severity=Severity.INFO, message="date normalized"),
    ])
    save_findings(session, receipt.id, report)
    session.commit()

    assert [f.rule_id for f in get_findings(session, receipt.id)] == ["R020", "R011"]
```

Add the imports these need at the top of the file: `create_pending_receipt`, `get_findings` from `receipts.persist`, `ReceiptStatus` from `receipts.score.confidence`, and `Finding`, `Severity`, `ValidationReport` from `receipts.validate.report` (check the real module for the exact `Finding` constructor before writing — read `src/receipts/validate/report.py` first).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_repository.py -k "pending or reasons or findings" -v`
Expected: FAIL — `ImportError: cannot import name 'create_pending_receipt'`.

- [ ] **Step 3: Add the `User` model and the `confidence_reasons` column**

In `src/receipts/persist/models.py`, add one column to `Receipt` next to `confidence` (line ~170):

```python
    #: The (reason, penalty) pairs that produced ``confidence``, as JSON:
    #: ``[{"reason": "poor legibility", "penalty": "-0.20"}]``. Penalties are
    #: strings so Decimal survives the round trip (ADR-0001).
    #:
    #: Nullable on purpose: NULL means "not recorded" (a row written before this
    #: column existed, or a run that failed before scoring), while ``[]`` means
    #: "nothing lowered the score" -- a genuinely clean receipt. Collapsing the
    #: two would let the review UI tell a reviewer "no reasons" about a row that
    #: never captured them.
    confidence_reasons: Mapped[Any | None] = mapped_column(_jsonb(), nullable=True, default=None)
```

Then append the new model after `ReviewTask`:

```python
# --------------------------------------------------------------------------- #
# 6.8 users (added with the review API, P4.T3)
# --------------------------------------------------------------------------- #


class User(Base):
    """A person who can sign in to the review service.

    Exists so ``corrections.corrected_by`` names a real account: a shared key
    cannot attribute a correction to a reviewer, which would hollow out the one
    audit trail the review UI depends on.

    ``role`` is deliberately a ``String`` and **not** a database ENUM. The
    migration drift guard runs on SQLite only and cannot see a new ENUM member,
    so an ENUM here would pass locally and fail on Postgres. Validation lives in
    :mod:`receipts.persist.users`, next to the role constants the API guards use.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
```

- [ ] **Step 4: Write `persist/users.py`**

```python
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
```

Then add the bootstrap entry point at the end of the same file, so the first admin can exist before the API does (P4.T5 wraps this as `receipts users add`):

```python
def _main(argv: list[str] | None = None) -> int:
    """``python -m receipts.persist.users create <username> --role admin``.

    The password is read from stdin, never from ``argv``: an argument lands in
    shell history and in ``ps`` output.
    """
    import argparse
    import getpass

    from .session import make_session_factory

    parser = argparse.ArgumentParser(prog="python -m receipts.persist.users")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="add an account")
    create.add_argument("username")
    create.add_argument("--role", default=ROLE_REVIEWER, choices=sorted(ROLES))
    args = parser.parse_args(argv)

    password = getpass.getpass("password: ")
    session = make_session_factory()()
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
```

Check `make_session_factory`'s real signature in `src/receipts/persist/session.py` before writing this — call it the way `process_receipt`'s callers do.

- [ ] **Step 5: Make `save_extraction` update-or-insert, and add the two new functions**

In `src/receipts/persist/repository.py`, add the parameter and the branch. Replace the construction block so an existing row is updated in place:

```python
def _reasons_json(pairs: list[tuple[str, Decimal]] | None) -> list[dict[str, str]] | None:
    """Encode explain_confidence pairs for the JSON column.

    Penalties are stored as strings: a JSON number is a float, and this column
    sits next to a Decimal score that a reviewer reads as an explanation of it.
    """
    if pairs is None:
        return None
    return [{"reason": reason, "penalty": str(penalty)} for reason, penalty in pairs]
```

`save_extraction` gains `confidence_reasons: list[tuple[str, Decimal]] | None = None` as a keyword-only argument, builds the same field values as today, and then:

```python
    existing = session.get(Receipt, job.id)
    if existing is None:
        receipt = Receipt(id=job.id, ...)   # exactly as today
    else:
        # A PENDING row written at upload, or a retry of a job that already
        # persisted. Update in place: re-inserting would collide on the primary
        # key and lose the receipt on the way to recording it.
        receipt = existing
        receipt.merchant_id = merchant_id
        receipt.merchant_name_raw = extraction.merchant.name
        # ... every column the insert branch sets, including image_phash
    receipt.confidence_reasons = _reasons_json(confidence_reasons)
    receipt.line_items = _build_line_items(extraction)
    session.add(receipt)
    session.flush()
    return receipt
```

Write the two branches so they cannot drift: build a `dict` of column values once and apply it to both. `image_phash` must be updated too — the pending row carries `""`.

Then the two new functions:

```python
def create_pending_receipt(session: Session, job: ReceiptJob) -> Receipt:
    """Write the ``pending`` row an upload creates before the worker runs.

    The receipt is visible and queryable the moment it is accepted, so a job the
    queue loses (an evicted Redis entry, a worker killed before it persisted)
    shows up as a stuck ``pending`` row instead of leaving a blob on disk and
    nothing in the database -- the vanished job §18 forbids.

    ``image_phash`` is empty: the perceptual hash is computed in the worker's
    preprocess stage, and inventing one here would be a value nothing read off
    the image. :func:`find_duplicate_by_phash` skips empty hashes, so a pending
    row can never become the original a later upload is marked a duplicate of.

    Flushes; does not commit. ``ValueError`` if the id is already taken.
    """
    if session.get(Receipt, job.id) is not None:
        raise ValueError(f"a receipt with id {job.id} already exists")
    receipt = Receipt(
        id=job.id,
        image_key=job.image_key,
        image_phash="",
        status=ReceiptStatus.PENDING,
        confidence=Decimal("0"),
    )
    session.add(receipt)
    session.flush()
    return receipt


def get_findings(session: Session, receipt_id: uuid.UUID) -> list[ValidationFinding]:
    """Every finding written for a receipt, oldest first.

    Ordered by ``created_at`` then ``id`` -- a total order, so two findings
    written in the same transaction still come back in a stable sequence.
    """
    return list(
        session.scalars(
            select(ValidationFinding)
            .where(ValidationFinding.receipt_id == receipt_id)
            .order_by(ValidationFinding.created_at, ValidationFinding.id)
        )
    )
```

Register both plus nothing else in `persist/__init__.py`: add `"create_pending_receipt": "repository"` and `"get_findings": "repository"` to `_LAZY`, add them to the `TYPE_CHECKING` import block and to `__all__`, and add `User` to the eager `from .models import (...)` list and `__all__`.

- [ ] **Step 6: Run the repository tests**

Run: `python -m pytest tests/test_repository.py -v`
Expected: PASS, including the pre-existing tests — the insert branch must be unchanged for a new receipt.

- [ ] **Step 7: Write and run the user-store tests**

Create `tests/test_users.py`. Cover: a hash verifies and a wrong password does not; a tampered/garbage encoded hash returns `False` rather than raising; two hashes of the same password differ (random salt); `create_user` rejects a duplicate username and an unknown role with `ValueError`; `verify_credentials` returns `None` for an unknown user, a wrong password, and a **deactivated** user; `set_role`/`deactivate` raise `ValueError` for an unknown username. Use the same in-memory SQLite fixture pattern as `tests/test_models.py`.

```python
def test_deactivated_user_cannot_authenticate(session):
    create_user(session, "alice", "correct-horse", ROLE_REVIEWER)
    session.commit()
    deactivate(session, "alice")
    session.commit()
    assert verify_credentials(session, "alice", "correct-horse") is None
```

Run: `python -m pytest tests/test_users.py -v` → PASS.

- [ ] **Step 8: Generate the migration**

```bash
python -m alembic -x db_url=sqlite:///build-migration-check.db upgrade head
python -m alembic -x db_url=sqlite:///build-migration-check.db revision --autogenerate \
  --rev-id a1c4d2f80b31 -m "users and confidence_reasons"
rm build-migration-check.db
```

Then hand-tidy the generated file to match `b9342906a5a6`'s conventions: `down_revision = "b9342906a5a6"`, a module docstring explaining what it adds and why `role` is a `String` rather than an ENUM, `sa.JSON().with_variant(postgresql.JSONB(), "postgresql")` for the new column, and a real `downgrade()` that drops the column and the table. Add `*.db` artifacts are already gitignored — do not commit `build-migration-check.db`.

- [ ] **Step 9: Prove the migration matches the ORM**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS. That suite runs `compare_metadata(MigrationContext, Base.metadata)` and asserts it is empty, so a missed column fails here. If it reports a diff, fix the migration — never the assertion.

- [ ] **Step 10: Thread the reasons through the pipeline**

In `src/receipts/pipeline.py`, import `explain_confidence` alongside `score_confidence` (line 79) and extend the score stage (line ~472):

```python
        with _stage("score"):
            # consistency stays None until self-consistency lands (M6).
            confidence = score_confidence(
                outcome.extraction, outcome.report, triage_result, consistency=None
            )
            # Same inputs, same order: the stored breakdown provably sums to the
            # stored score, which is what the review UI shows a human.
            reasons = explain_confidence(
                outcome.extraction, outcome.report, triage_result, consistency=None
            )
```

Pass `reasons` into `_persist_outcome` as a new keyword argument and on to `save_extraction(..., confidence_reasons=reasons)`. Leave `_persist_duplicate` and `_persist_failure` passing nothing: a rejected duplicate was never scored and a failed run never reached the scorer, so `NULL` — "not recorded" — is the truthful value for both.

- [ ] **Step 11: Test the pipeline change**

Append to `tests/test_process_receipt.py`, reusing that file's existing helpers
(`_job`, `_Client`, `_triage`, `_good`, `_run`) and fixtures
(`session_factory`, `storage`, `settings`) — do not invent a new harness:

```python
def test_persisted_reasons_sum_to_the_persisted_confidence(session_factory, storage, settings):
    """The breakdown a reviewer is shown must add up to the score it explains."""
    job = _job(storage)
    penalised = _good()
    penalised.meta.legibility = Legibility.POOR
    penalised.meta.is_handwritten = True
    client = _Client([_triage(), penalised])

    _run(job, client, session_factory, storage, settings)

    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.confidence_reasons  # non-empty: this receipt lost points
        penalties = [D(entry["penalty"]) for entry in receipt.confidence_reasons]
        expected = min(D("1"), max(D("0"), D("1") + sum(penalties)))
        assert expected.quantize(D("0.001")) == receipt.confidence


def test_a_clean_receipt_records_an_empty_reason_list(session_factory, storage, settings):
    job = _job(storage)
    _run(job, _Client([_triage(), _good()]), session_factory, storage, settings)

    with session_factory() as session:
        # [] means "nothing lowered the score", which is not the same claim as
        # NULL ("never recorded").
        assert session.get(Receipt, job.id).confidence_reasons == []


def test_a_failed_stage_records_no_reasons(session_factory, storage, settings):
    job = _job(storage)
    client = _Client([RuntimeError("triage exploded")])

    result = _run(job, client, session_factory, storage, settings)

    assert result.failed_stage == "triage"
    with session_factory() as session:
        receipt = session.get(Receipt, job.id)
        assert receipt.status is ReceiptStatus.NEEDS_REVIEW
        # Nothing was ever scored, so NULL is the truthful value.
        assert receipt.confidence_reasons is None
```

`Legibility` is already imported in that file; add nothing else.

Run: `python -m pytest tests/test_process_receipt.py -v` → PASS.

- [ ] **Step 12: Full suite, lint, and commit**

```bash
python -m pytest 2>&1 | tail -3
python -m ruff check .
git add src/receipts/persist/models.py src/receipts/persist/users.py \
        src/receipts/persist/repository.py src/receipts/persist/__init__.py \
        src/receipts/pipeline.py alembic/versions/a1c4d2f80b31_users_and_confidence_reasons.py \
        tests/test_users.py tests/test_repository.py tests/test_process_receipt.py
git commit -m "feat(persist): add users, confidence reasons, and the pending receipt row"
```

Expected: every prior test still passes (488 before this task) plus the new ones; ruff clean.

---

## Task 2: Shared fixes the API depends on

Four small, independent corrections. They land before the routes because `POST /upload` needs the upload limit and `GET /metrics` needs the thresholds.

**Files:**
- Create: `src/receipts/score/thresholds.py`
- Modify: `src/receipts/score/confidence.py:249-250`, `config/settings.py:68-69`, `eval/metrics.py:39`, `src/receipts/export/xlsx.py:67`
- Modify: `src/receipts/review/queue.py:105` (`enqueue_review`)
- Modify: `src/receipts/extract/clients/limits.py:204` (`_as_money`)
- Modify: `src/receipts/ingest/ingest.py:194,217` (`ingest_file`, `ingest_bytes`)
- Test: `tests/test_review_queue.py`, `tests/test_vlm_limits.py`, `tests/test_ingest.py`, `tests/test_confidence.py` (append to each)

**Interfaces:**
- Produces: `receipts.score.thresholds.AUTO_APPROVE_THRESHOLD`, `receipts.score.thresholds.REVIEW_THRESHOLD` (both `Decimal`); `ingest_file(..., max_mb: int = _DEFAULT_MAX_MB)`; `ingest_bytes(..., max_mb: int = _DEFAULT_MAX_MB)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_confidence.py
def test_the_routing_thresholds_are_defined_once():
    from config.settings import Settings
    from eval.metrics import AUTO_APPROVE_THRESHOLD as metrics_threshold
    from receipts.export.xlsx import _CONFIDENCE_FLOOR
    from receipts.score.thresholds import AUTO_APPROVE_THRESHOLD, REVIEW_THRESHOLD

    settings = Settings()
    assert settings.auto_approve_threshold == AUTO_APPROVE_THRESHOLD
    assert settings.review_threshold == REVIEW_THRESHOLD
    assert metrics_threshold == AUTO_APPROVE_THRESHOLD
    assert _CONFIDENCE_FLOOR == REVIEW_THRESHOLD


# tests/test_review_queue.py
def test_concurrent_enqueue_for_one_receipt_does_not_raise(engine, receipt_id):
    """Two sessions enqueue the same receipt with no coordination.

    The row is UNIQUE on receipt_id, so the check-then-insert this replaces
    could raise IntegrityError under a real race (ADR-0008's recorded gap).
    """
    from sqlalchemy.orm import Session
    with Session(engine) as a, Session(engine) as b:
        enqueue_review(a, receipt_id, "quick verify", 2)
        enqueue_review(b, receipt_id, "full re-key", 1)
        a.commit()
        b.commit()   # must not raise IntegrityError
    with Session(engine) as check:
        tasks = check.scalars(select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)).all()
        assert len(tasks) == 1
        assert tasks[0].priority == 1        # more urgent wins, as before
        assert tasks[0].reason == "full re-key"


# tests/test_vlm_limits.py
@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_cost_guard_refuses_a_non_finite_amount(bad):
    """NaN >= ceiling is always False, so the ceiling would silently never fire."""
    with pytest.raises(ValueError, match="finite"):
        CostGuard(ceiling=Decimal("0.25")).add(bad)


# tests/test_ingest.py
def test_ingest_bytes_honours_an_explicit_max_mb(tmp_path):
    storage = LocalStorage(tmp_path)
    data = b"\xff\xd8" + b"\x00" * (2 * 1024 * 1024)   # a 2 MB "JPEG"
    with pytest.raises(ValueError, match="too large"):
        ingest_bytes(data, "r.jpg", storage, max_mb=1)
```

Note: this SQLite race test exercises the code path, not true OS-level concurrency — SQLite serializes writers. That is the honest limit of an offline test; the SAVEPOINT retry is what makes the path correct on Postgres. Say so in the test docstring.

- [ ] **Step 2: Run them and verify each fails**

Run: `python -m pytest tests/test_confidence.py tests/test_review_queue.py tests/test_vlm_limits.py tests/test_ingest.py -k "defined_once or concurrent_enqueue or non_finite or max_mb" -v`
Expected: FAIL — missing module `receipts.score.thresholds`, and the other three assertions unmet.

- [ ] **Step 3: Create the shared thresholds module**

```python
"""The two confidence thresholds that decide routing (spec §12, §17).

Defined once, here, because they were previously written out in four places --
``route()``'s defaults, ``Settings``, ``eval.metrics``, and the export sheet's
colour scale -- and four copies of a number that calibration is meant to move
(P3.T6/P8.T1) is three chances to move three of them.

This module deliberately depends on nothing but ``decimal``: ``config.settings``
imports it, so the arrow runs config -> domain. Putting the constants in
``Settings`` instead would make a pure domain module depend on environment
configuration.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = ["AUTO_APPROVE_THRESHOLD", "REVIEW_THRESHOLD"]

#: At or above this, a receipt is auto-approved (§12).
AUTO_APPROVE_THRESHOLD = Decimal("0.85")

#: Between this and the auto-approve cut-off, a receipt gets a quick verify;
#: below it, a full re-key.
REVIEW_THRESHOLD = Decimal("0.60")
```

Then update the four consumers to import these instead of holding their own literal: `route()`'s keyword defaults, the two `Settings` fields, `eval/metrics.py`'s `AUTO_APPROVE_THRESHOLD` (re-export it so existing importers keep working), and `export/xlsx.py`'s `_CONFIDENCE_FLOOR`. Keep each site's existing comment about *why* it uses the value.

- [ ] **Step 4: Make `enqueue_review` insert-safe**

In `src/receipts/review/queue.py`, replace the insert branch:

```python
    if existing is None:
        # SAVEPOINT, not check-then-insert: receipt_id is UNIQUE, so a
        # genuinely concurrent enqueue for one receipt could otherwise raise
        # IntegrityError and lose the review task (ADR-0008's recorded gap).
        # Nesting means the failed INSERT rolls back to the savepoint without
        # poisoning the caller's transaction.
        try:
            with session.begin_nested():
                task = ReviewTask(
                    receipt_id=receipt_id, reason=reason, priority=priority,
                    state=ReviewState.OPEN,
                )
                session.add(task)
                session.flush()
            return task
        except IntegrityError:
            existing = session.scalars(
                select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)
            ).one()
    # ... the existing more-urgent-wins update, unchanged
```

Import `IntegrityError` from `sqlalchemy.exc`. Restructure so the update block below runs for both the "found it first time" and "lost the race" paths — do not duplicate it.

- [ ] **Step 5: Add the `is_finite` gate and the `max_mb` parameter**

In `src/receipts/extract/clients/limits.py`, in `_as_money`, after the value has become a `Decimal`:

```python
    if not amount.is_finite():
        raise ValueError(
            f"{label} must be a finite amount, not {value!r}; a NaN cost makes "
            "`spent` NaN, and `NaN >= ceiling` is always False -- the ceiling "
            "would silently never fire"
        )
```

Mirror `repository._coerce_money`, which raises `ValueError` for the same case; keep the existing `TypeError` for `float`.

In `src/receipts/ingest/ingest.py`, add `max_mb: int = _DEFAULT_MAX_MB` to `ingest_file` and `ingest_bytes` and pass it through to `validate_upload` / `_check_upload`, replacing the hardcoded `_DEFAULT_MAX_MB` at both call sites. Document that the API passes `settings.max_upload_mb`.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_confidence.py tests/test_review_queue.py tests/test_vlm_limits.py tests/test_ingest.py -v`
Expected: PASS, including every pre-existing test in those files.

- [ ] **Step 7: Full suite, lint, and commit**

```bash
python -m pytest 2>&1 | tail -3
python -m ruff check .
git add src/receipts/score/thresholds.py src/receipts/score/confidence.py config/settings.py \
        eval/metrics.py src/receipts/export/xlsx.py src/receipts/review/queue.py \
        src/receipts/extract/clients/limits.py src/receipts/ingest/ingest.py \
        tests/test_confidence.py tests/test_review_queue.py tests/test_vlm_limits.py tests/test_ingest.py
git commit -m "fix(core): consolidate thresholds, make enqueue insert-safe, gate non-finite cost, honour max_mb"
```

---

## Task 3: Auth — sessions, roles, and the machine key

**Files:**
- Create: `src/receipts/review/auth.py`
- Modify: `config/settings.py` (five new settings), `pyproject.toml` (the `api` extra, `httpx` in `dev`), `.github/workflows/ci.yml`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `receipts.persist.users` (Task 1) — `ROLE_ADMIN`, `ROLE_REVIEWER`, `verify_credentials`, `get_user`.
- Produces, used by Tasks 4 and 5:
  ```python
  @dataclass(frozen=True)
  class SessionUser:
      username: str
      role: str

  def build_auth_router() -> APIRouter          # POST /auth/login, POST /auth/logout
  def require_user(request: Request) -> SessionUser          # 401 when absent
  def require_role(*roles: str) -> Callable[..., SessionUser]  # 403 on the wrong role
  def require_upload(request: Request) -> SessionUser | None   # API key OR session
  def install_session_middleware(app: FastAPI, settings: Settings) -> None
  def sign_url(payload: str, *, secret: str, ttl_s: int, now: int | None = None) -> tuple[str, int]
  def verify_signature(payload: str, *, secret: str, signature: str, exp: int,
                       now: int | None = None) -> bool
  ```
  App state contract: `app.state.session_factory`, `app.state.storage`, `app.state.settings`, `app.state.submit`.

- [ ] **Step 1: Add the dependencies and the settings**

`pyproject.toml`:

```toml
# The FastAPI review service. Optional so a base install and the worker stay
# light; the API tests importorskip on it exactly as the pipeline tests do.
api = ["fastapi>=0.110", "python-multipart>=0.0.9", "itsdangerous>=2", "uvicorn>=0.27"]
```

and add `"httpx>=0.27"` to `dev` (Starlette's `TestClient` needs it). Update `.github/workflows/ci.yml` to install `.[dev,pipeline,api]`.

`config/settings.py`, in a new `# --- Service (§17: Service) ---` block:

```python
    # Maps SESSION_SECRET. Signs the review session cookie and the expiring
    # image URLs. No default: create_app refuses to start without it. A random
    # per-process fallback would log every reviewer out on each restart and hide
    # the misconfiguration instead of surfacing it.
    session_secret: str | None = None
    # Maps RECEIPTS_API_KEY. The machine-upload key, authorizing POST /upload
    # and nothing else. Unset means the header path is rejected outright --
    # never "unset key equals unset header", which is how this becomes an open
    # door.
    receipts_api_key: str | None = None
    session_cookie_secure: bool = True
    # Maps IMAGE_URL_TTL_S / EXPORT_IMAGE_URL_TTL_S. How long a signed image
    # link stays valid: minutes for the review screen, a day for links embedded
    # in an exported workbook (anyone holding that file can open them until it
    # expires).
    image_url_ttl_s: int = 300
    export_image_url_ttl_s: int = 86400
```

Run `python -m pytest tests/test_settings.py -v` → PASS (the file asserts §17 coverage; extend it if it enumerates fields).

- [ ] **Step 2: Write the failing auth tests**

`tests/test_auth.py`, guarded with `pytest.importorskip("fastapi")`. Build a *minimal* app inside the test that mounts the auth router and three probe routes using the real dependencies — this proves the guards without waiting for Task 4:

```python
def _probe_app(session_factory, settings):
    from fastapi import Depends, FastAPI
    from receipts.persist.users import ROLE_ADMIN
    from receipts.review.auth import (
        SessionUser, build_auth_router, install_session_middleware,
        require_role, require_upload, require_user,
    )

    app = FastAPI()
    app.state.session_factory = session_factory
    app.state.settings = settings
    install_session_middleware(app, settings)
    app.include_router(build_auth_router())

    @app.get("/probe/any")
    def any_role(user: SessionUser = Depends(require_user)):
        return {"username": user.username, "role": user.role}

    @app.get("/probe/admin")
    def admin_only(user: SessionUser = Depends(require_role(ROLE_ADMIN))):
        return {"ok": True}

    @app.post("/probe/upload")
    def upload(user=Depends(require_upload)):
        return {"ok": True}

    return app


def test_no_credentials_is_401(client):
    assert client.get("/probe/any").status_code == 401


def test_reviewer_on_an_admin_route_is_403(client):
    client.post("/auth/login", json={"username": "alice", "password": "pw-alice"})
    assert client.get("/probe/admin").status_code == 403


def test_login_sets_a_session_and_logout_clears_it(client):
    assert client.post("/auth/login", json={"username": "alice", "password": "pw-alice"}).status_code == 200
    assert client.get("/probe/any").json()["role"] == "reviewer"
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/probe/any").status_code == 401


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    wrong = client.post("/auth/login", json={"username": "alice", "password": "nope"})
    missing = client.post("/auth/login", json={"username": "nobody", "password": "nope"})
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()


def test_deactivating_a_user_invalidates_their_live_session(client, session_factory):
    client.post("/auth/login", json={"username": "alice", "password": "pw-alice"})
    with session_factory() as session:
        deactivate(session, "alice")
        session.commit()
    # The role is re-read per request, so this takes effect now, not at expiry.
    assert client.get("/probe/any").status_code == 401


def test_api_key_uploads_but_cannot_read(client_with_key):
    headers = {"X-API-Key": "s3cret-machine-key"}
    assert client_with_key.post("/probe/upload", headers=headers).status_code == 200
    assert client_with_key.get("/probe/any", headers=headers).status_code == 401


def test_an_unset_api_key_rejects_every_key_header(client):   # settings.receipts_api_key is None
    assert client.post("/probe/upload", headers={"X-API-Key": ""}).status_code == 401
    assert client.post("/probe/upload", headers={"X-API-Key": "anything"}).status_code == 401


def test_signed_urls_expire_and_detect_tampering():
    """`now` is injected so expiry is proven without sleeping."""
    secret, payload = "test-secret", "receipt-a|original"
    signature, exp = sign_url(payload, secret=secret, ttl_s=300, now=1_000)

    assert verify_signature(payload, secret=secret, signature=signature, exp=exp, now=1_000)
    # One second past the expiry.
    assert not verify_signature(payload, secret=secret, signature=signature, exp=exp, now=1_301)
    # Same signature, different receipt.
    assert not verify_signature(
        "receipt-b|original", secret=secret, signature=signature, exp=exp, now=1_000
    )
    # Same payload, someone else's secret.
    assert not verify_signature(
        payload, secret="other-secret", signature=signature, exp=exp, now=1_000
    )


def test_create_app_refuses_to_start_without_a_session_secret(session_factory, tmp_path):
    """A random per-process default would sign users out on every restart."""
    from receipts.review.auth import install_session_middleware

    app = FastAPI()
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        install_session_middleware(app, Settings(session_secret=None))
```

Fixtures create a SQLite database, `create_user(session, "alice", "pw-alice", ROLE_REVIEWER)` and `create_user(session, "bob", "pw-bob", ROLE_ADMIN)`, and build `Settings(session_secret="test-secret", session_cookie_secure=False, ...)`.

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'receipts.review.auth'`. If it fails with `ModuleNotFoundError: fastapi`, run `pip install -e ".[dev,pipeline,api]"` first.

- [ ] **Step 4: Write `review/auth.py`**

Key behaviours to implement, each of which one of the tests above pins:

```python
_SESSION_KEY = "username"


@dataclass(frozen=True)
class SessionUser:
    username: str
    role: str


def install_session_middleware(app: FastAPI, settings: Settings) -> None:
    """Signed-cookie sessions. Raises when SESSION_SECRET is unset."""
    if not settings.session_secret:
        raise ValueError(
            "SESSION_SECRET is required to run the review API; a random "
            "per-process default would sign users out on every restart and "
            "hide the misconfiguration"
        )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.session_cookie_secure,
        same_site="lax",
    )


def _current_user(request: Request) -> SessionUser | None:
    """Resolve the session cookie against the database, or None.

    The cookie carries the username only; the role and is_active are read fresh
    on every request, so a demotion or a deactivation takes effect immediately
    rather than whenever a cookie happens to expire.
    """
    username = request.session.get(_SESSION_KEY)
    if not username:
        return None
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        user = get_user(session, username)
        if user is None or not user.is_active:
            return None
        return SessionUser(username=user.username, role=user.role)


def require_user(request: Request) -> SessionUser:
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def require_role(*roles: str):
    def dependency(request: Request) -> SessionUser:
        user = require_user(request)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user
    return dependency


def require_upload(request: Request) -> SessionUser | None:
    """The API key OR any signed-in user. The key authorizes nothing else."""
    configured = request.app.state.settings.receipts_api_key
    presented = request.headers.get("X-API-Key")
    if configured and presented and hmac.compare_digest(configured, presented):
        return None                      # a machine, not a person
    return require_user(request)
```

`build_auth_router()` returns an `APIRouter` with:
- `POST /auth/login` — a pydantic body `{username, password}`; `verify_credentials`; on success `request.session[_SESSION_KEY] = user.username` and return `{"username", "role"}`; on failure raise `HTTPException(401, "invalid credentials")` — **the identical detail for an unknown user, a wrong password, and a deactivated account.**
- `POST /auth/logout` — `request.session.clear()`, return `Response(status_code=204)`.

And the URL signing helpers, used by Task 5:

```python
def sign_url(payload: str, *, secret: str, ttl_s: int, now: int | None = None) -> tuple[str, int]:
    """Return ``(signature, exp)`` for ``payload``, valid for ``ttl_s`` seconds.

    ``now`` is injectable so a test can prove expiry without sleeping.
    """
    exp = (now if now is not None else int(time.time())) + ttl_s
    message = f"{payload}|{exp}".encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return signature, exp


def verify_signature(payload: str, *, secret: str, signature: str, exp: int,
                     now: int | None = None) -> bool:
    current = now if now is not None else int(time.time())
    if exp < current:
        return False
    message = f"{payload}|{exp}".encode()
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

- [ ] **Step 5: Run the auth tests**

Run: `python -m pytest tests/test_auth.py -v` → PASS.

- [ ] **Step 6: Full suite, lint, and commit**

```bash
python -m pytest 2>&1 | tail -3
python -m ruff check .
git add src/receipts/review/auth.py config/settings.py pyproject.toml \
        .github/workflows/ci.yml tests/test_auth.py tests/test_settings.py
git commit -m "feat(review): add session auth, role guards, and the machine upload key"
```

---

## Task 4: The read API — app factory, receipts, metrics

**Files:**
- Create: `src/receipts/review/schemas.py`, `src/receipts/review/serializers.py`, `src/receipts/review/api.py`
- Test: `tests/test_api_read.py`

**Interfaces:**
- Consumes: Task 1 (`get_findings`, `confidence_reasons`), Task 2 (thresholds), Task 3 (`require_user`, `require_role`, `install_session_middleware`, `build_auth_router`).
- Produces, used by Task 5:
  ```python
  def create_app(*, session_factory, storage, submit=None, settings=None) -> FastAPI
  # serializers.py
  def receipt_summary(receipt: Receipt) -> dict          # list rows
  def receipt_detail(receipt: Receipt, findings: list[ValidationFinding]) -> dict
  def money(value: Decimal | None) -> str | None         # Decimal -> string, None -> None
  ```

- [ ] **Step 1: Write the failing tests**

`tests/test_api_read.py`, `pytest.importorskip("fastapi")`. Fixtures: a SQLite database seeded with an `alice`/reviewer and `bob`/admin account and two receipts (one `auto_approved` with `confidence_reasons=[]`, one `needs_review` with two findings and two reasons), a `LocalStorage(tmp_path)`, and a `submit` that appends to a list.

```python
def test_health_needs_no_auth(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_money_is_serialized_as_a_string(reviewer_client, receipt_id):
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()
    assert body["totals"]["total"] == "1000.0000"       # never a JSON float
    assert isinstance(body["confidence"], str)


def test_detail_returns_findings_and_the_reasons_that_made_the_score(reviewer_client, receipt_id):
    body = reviewer_client.get(f"/receipts/{receipt_id}").json()
    assert [f["rule_id"] for f in body["findings"]] == ["R020", "R011"]
    penalties = [Decimal(r["penalty"]) for r in body["confidence_reasons"]]
    assert (Decimal("1") + sum(penalties)).quantize(Decimal("0.001")) == Decimal(body["confidence"])


def test_reasons_never_recorded_is_null_not_empty(reviewer_client, pending_receipt_id):
    assert reviewer_client.get(f"/receipts/{pending_receipt_id}").json()["confidence_reasons"] is None


def test_list_filters_and_pages(reviewer_client):
    body = reviewer_client.get("/receipts", params={"status": "needs_review", "limit": 1}).json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False


def test_list_caps_the_page_size(reviewer_client):
    assert reviewer_client.get("/receipts", params={"limit": 10_000}).status_code == 422


def test_unknown_receipt_is_404(reviewer_client):
    assert reviewer_client.get(f"/receipts/{uuid.uuid4()}").status_code == 404


def test_metrics_on_an_empty_database_reports_null_not_a_rate(empty_client):
    body = empty_client.get("/metrics").json()
    # An undefined rate is null. Reporting 1.0 on zero receipts is exactly the
    # vacuous artifact this project already produced once.
    assert body["auto_approval_rate"] is None
    assert body["counts_by_status"] == {}


def test_metrics_reports_the_queue_and_the_thresholds(reviewer_client):
    body = reviewer_client.get("/metrics").json()
    assert body["queue"]["open"] >= 1
    assert body["thresholds"] == {"auto_approve": "0.85", "review": "0.60"}
```

Plus the **auth matrix** over the routes that exist so far:

```python
READ_ROUTES = [
    ("GET", "/receipts", {"reviewer", "admin"}),
    ("GET", "/receipts/{id}", {"reviewer", "admin"}),
    ("GET", "/metrics", {"reviewer", "admin"}),
]

@pytest.mark.parametrize("method,path,allowed", READ_ROUTES)
@pytest.mark.parametrize("actor", ["anonymous", "api_key", "reviewer", "admin"])
def test_auth_matrix(clients, method, path, allowed, actor, receipt_id):
    response = clients[actor].request(method, path.format(id=receipt_id))
    if actor in allowed:
        assert response.status_code == 200
    elif actor in {"anonymous", "api_key"}:
        assert response.status_code == 401
    else:
        assert response.status_code == 403
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_api_read.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'receipts.review.api'`.

- [ ] **Step 3: Write `serializers.py`**

```python
def money(value: Decimal | None) -> str | None:
    """A money column as a string. JSON numbers are floats (ADR-0001)."""
    return None if value is None else str(value)
```

`receipt_summary(receipt)` returns id, status, confidence, merchant_name_raw, txn_date (ISO or `None`), currency, total, created_at. `receipt_detail(receipt, findings)` adds line items, every money column, `date_raw`, `card_last4`, `is_handwritten`, `legibility`, `duplicate_of`, `receipt_is_inconsistent`, the findings (`rule_id`, `severity`, `message`, `context`, `resolved_by_repair`), and `confidence_reasons` **verbatim from the column** — passing `None` through as `null`, never rewriting it to `[]`.

- [ ] **Step 4: Write `schemas.py` and `api.py`**

`create_app` wires state, middleware, the auth router, the exception handlers, and the read routes:

```python
def create_app(*, session_factory, storage, submit=None, settings=None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Receipt review API")
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.settings = settings
    app.state.submit = submit or _default_submit
    install_session_middleware(app, settings)      # raises without SESSION_SECRET
    app.include_router(build_auth_router())
    _install_error_handlers(app)
    _install_read_routes(app)
    return app
```

`_default_submit` imports `receipts.worker` lazily inside the function, so importing this module needs neither `rq` nor `redis`.

Error handlers, one place: `ValueError` → 400 `{"error": {"message": str(exc)}}`; `OperationalError` / `DBAPIError` → 503; `HTTPException` keeps its status with the same body shape. No traceback, no storage path, no SQL in a response body.

Routes for this task:
- `GET /health` — open; runs `SELECT 1`; returns 503 `{"status": "degraded"}` when the database is unreachable.
- `GET /receipts` — `Depends(require_user)`; query parameters map onto `query_receipts`; `limit: int = Query(50, ge=1, le=200)` (FastAPI returns 422 above the cap); fetch `limit + 1` rows and report `has_more` rather than running a `COUNT(*)` per page.
- `GET /receipts/{receipt_id}` — `get_receipt` + `get_findings`; 404 when absent.
- `GET /metrics` — `queue_stats` plus `counts_by_status` from a grouped aggregate, `auto_approval_rate` as `auto_approved / (auto_approved + needs_review + reviewed)` **or `None` when that denominator is zero**, and the two thresholds from `receipts.score.thresholds` as strings.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_api_read.py -v` → PASS.

- [ ] **Step 6: Full suite, lint, and commit**

```bash
python -m pytest 2>&1 | tail -3
python -m ruff check .
git add src/receipts/review/api.py src/receipts/review/schemas.py \
        src/receipts/review/serializers.py tests/test_api_read.py
git commit -m "feat(review): add the read API — app factory, receipts, and metrics"
```

---

## Task 5: The write API — upload, corrections, images, queue, export

**Files:**
- Modify: `src/receipts/review/api.py`, `src/receipts/review/schemas.py`, `src/receipts/review/serializers.py`
- Test: `tests/test_api_write.py`

**Interfaces:**
- Consumes: everything above — `create_pending_receipt`, `apply_corrections`, `next_task`, `close_task`, `enqueue_review`, `ingest_bytes(..., max_mb=)`, `sign_url`/`verify_signature`, `export_workbook`, `ReceiptExportRow`.
- Produces: the finished §14.9 surface.

- [ ] **Step 1: Write the failing tests**

`tests/test_api_write.py`, `pytest.importorskip("fastapi")` and `pytest.importorskip("openpyxl")`.

```python
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


def test_a_rejected_upload_writes_no_row_and_queues_nothing(reviewer_client, session_factory, submitted):
    response = reviewer_client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400
    with session_factory() as session:
        assert session.query(Receipt).count() == 0
    assert submitted == []


def test_upload_honours_the_configured_size_limit(client_max_1mb):
    big = b"\xff\xd8" + b"\x00" * (2 * 1024 * 1024)
    assert client_max_1mb.post("/upload", files={"file": ("r.jpg", big, "image/jpeg")}).status_code == 400


def test_the_api_key_can_upload_but_nothing_else(key_client, receipt_id):
    headers = {"X-API-Key": "s3cret-machine-key"}
    assert key_client.post("/upload", files={"file": ("r.jpg", JPEG_BYTES, "image/jpeg")},
                           headers=headers).status_code == 202
    assert key_client.patch(f"/receipts/{receipt_id}", json={"totals": {"total": "1.00"}},
                            headers=headers).status_code == 401


def test_patch_writes_a_correction_attributed_to_the_session_user(reviewer_client, session_factory, receipt_id):
    response = reviewer_client.patch(f"/receipts/{receipt_id}",
                                     json={"totals": {"total": "1234.56"}})
    assert response.status_code == 200
    with session_factory() as session:
        correction = session.scalars(select(Correction)).one()
    # The entire reason session auth was chosen over a shared key.
    assert correction.corrected_by == "alice"
    assert correction.value_after == "1234.56"


def test_patch_rejects_a_json_float_for_money(reviewer_client, receipt_id):
    response = reviewer_client.patch(f"/receipts/{receipt_id}", json={"totals": {"total": 1234.56}})
    assert response.status_code == 422
    assert "string" in response.text


def test_patch_with_an_unmappable_path_changes_nothing(reviewer_client, session_factory, receipt_id):
    assert reviewer_client.patch(f"/receipts/{receipt_id}",
                                 json={"nonsense": {"field": "x"}}).status_code == 400
    with session_factory() as session:
        assert session.query(Correction).count() == 0


def test_image_url_is_signed_and_the_blob_streams(reviewer_client, receipt_id):
    url = reviewer_client.get(f"/receipts/{receipt_id}/image").json()["url"]
    assert reviewer_client.get(url).content == JPEG_BYTES


def test_a_tampered_or_expired_signature_is_rejected(reviewer_client, receipt_id, other_receipt_id):
    url = reviewer_client.get(f"/receipts/{receipt_id}/image").json()["url"]
    assert reviewer_client.get(url.replace(str(receipt_id), str(other_receipt_id))).status_code == 403
    assert reviewer_client.get(url.replace("exp=", "exp=1")).status_code == 403


def test_review_next_claims_one_task_per_caller(reviewer_client, admin_client):
    first = reviewer_client.get("/review/next").json()["task"]
    second = admin_client.get("/review/next").json()["task"]
    assert first["id"] != (second or {}).get("id")


def test_review_next_on_an_empty_queue_returns_null(empty_reviewer_client):
    assert empty_reviewer_client.get("/review/next").json()["task"] is None


def test_a_reviewer_cannot_complete_someone_elses_task(reviewer_client, session_factory, task_id):
    with session_factory() as session:
        task = session.get(ReviewTask, task_id)
        task.assigned_to = "bob"
        session.commit()
    assert reviewer_client.post(f"/review/{task_id}/complete").status_code == 403


def test_an_admin_can_complete_a_task_assigned_to_someone_else(admin_client, session_factory, task_id):
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
```

Extend the auth matrix from Task 4 with every new route and its allowed actors, per the spec's §5.3 table.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_api_write.py -v`
Expected: FAIL — 404 from routes that do not exist yet.

- [ ] **Step 3: Implement upload, patch, and the image routes**

- `POST /upload` — `Depends(require_upload)`; read the `UploadFile` bounded by `settings.max_upload_mb`; `ingest_bytes(data, file.filename, storage, source="api", max_mb=settings.max_upload_mb)` inside a `try/except ValueError` → 400 with the ingest reason; then, in one transaction, `create_pending_receipt(session, job)` and commit; then `app.state.submit(job)`. Return **202** `{"receipt_id", "image_key", "status": "pending"}`. If `submit` raises, the row already exists and is visible — return 503 with the receipt id so the caller can retry, and log it.
- `PATCH /receipts/{receipt_id}` — `Depends(require_user)`; the body model types every money field as `str | int | None` so a JSON float fails validation with 422 (add an explicit message: *send money as a string; a JSON number is a float and cannot represent an exact amount*); call `apply_corrections(session, receipt_id, patch, corrected_by=user.username)` (it owns its transaction); `ValueError` → 400; return the re-read detail payload.
- `GET /receipts/{receipt_id}/image` — `Depends(require_user)`; 404 if the receipt is unknown; pick `processed_image_key` when `?variant=processed` and it is set, else `image_key`; sign `f"{receipt_id}|{variant}"` with `settings.session_secret` and `settings.image_url_ttl_s`; return `{"url": f"/receipts/{receipt_id}/image/blob?variant={variant}&exp={exp}&sig={sig}"}`.
- `GET /receipts/{receipt_id}/image/blob` — **no session dependency** (it must work in an `<img>` tag); `verify_signature` or 403; stream `storage.get(key)` with the right media type. The signature covers the receipt id, so it cannot be re-pointed at another receipt.

- [ ] **Step 4: Implement the queue and export routes**

- `GET /review/next` — `Depends(require_user)`; `next_task(session, assignee=user.username)`, commit, and return `{"task": …, "receipt": …}` or `{"task": None}`. A 200 with an explicit `null` beats a 204 here: the client has one shape to parse rather than an empty-body special case.
- `POST /review/{task_id}/complete` — `Depends(require_user)`; 404 for an unknown task; **403 when the task is assigned to someone else and the caller is not an admin**; `close_task`, commit; return the task.
- `GET /export/xlsx` — `Depends(require_role(ROLE_ADMIN))`; filters as `/receipts`; **excludes `PENDING` and `REJECTED` unless `status=` names them** (a pending row is an upload in flight, not a transaction; a rejected one is a duplicate the pipeline keeps out of exports); count first and return 400 above `_EXPORT_MAX_ROWS = 5000` telling the caller to narrow the filter; build `(ReceiptExtraction, ReceiptExportRow)` pairs in `serializers.py`, joining `review_tasks` for `review_reason`/`review_priority` and signing image links with `settings.export_image_url_ttl_s`; write to a `tempfile.TemporaryDirectory()` path and return a `FileResponse` with `Content-Disposition: attachment`.

The ORM → `ReceiptExtraction` mapping is lossy against the full extraction schema (`tax_breakdown`, `prices_include_tax`, `ambiguous_fields`, merchant address/TIN are not columns) but must be **lossless for every §13 header** — that is the contract that matters, since the database is the source of truth and Excel is output only. Say so in the function's docstring.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_api_write.py -v` → PASS.

- [ ] **Step 6: Full suite, lint, and commit**

```bash
python -m pytest 2>&1 | tail -3
python -m ruff check .
git add src/receipts/review/api.py src/receipts/review/schemas.py \
        src/receipts/review/serializers.py tests/test_api_write.py
git commit -m "feat(review): add upload, corrections, signed images, queue, and export routes"
```

---

## After the tasks (controller work, not a subagent's)

1. **ADR-0012** recording D1–D4, the app-factory shape, the app-signed image URL, and the accepted CSRF/rate-limit limits; index it in `docs/adr/README.md`.
2. **Spec edits:** §17 absorbs `VLM_MAX_CONCURRENCY`, `MAX_COST_USD_PER_RECEIPT`, `STORAGE_ROOT`, `SESSION_SECRET`, `RECEIPTS_API_KEY`, `SESSION_COOKIE_SECURE`, `IMAGE_URL_TTL_S`, `EXPORT_IMAGE_URL_TTL_S`; §14.9 absorbs `/auth/login`, `/auth/logout`, and the image blob sub-route; §6 gains `users` and `receipts.confidence_reasons`.
3. **Delete `eval/results/2026-07-27-1.0.0.json`** — an empty-set artifact claiming `auto_approval_precision: 1.0` on zero receipts. Never commit or cite it.
4. Update `docs/MEMORY.md` and append to `.superpowers/sdd/progress.md`.
5. Then P4.T5/T6 (`cli.py`), the whole-branch review of `feat/service`, and the fast-forward merge to `master`.

## Out of scope

Frontend (P5), `cli.py` (P4.T5/T6), merchant registry (P6), self-consistency (P7), calibration (P8 — blocked on ISSUE-001). **No accuracy claim is made or implied by this work:** there are still no measured numbers until ISSUE-001 runs.
