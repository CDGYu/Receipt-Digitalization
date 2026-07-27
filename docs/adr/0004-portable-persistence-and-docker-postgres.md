# ADR 0004 — Portable persistence (Postgres/SQLite) + Docker

**Status:** Accepted (implements SPEC §6)

## Context

The system targets **PostgreSQL in production** and **SQLite in dev/tests** via
SQLAlchemy 2.0 (SPEC §4/§5). The seven-table model (SPEC §6) uses Postgres-native
types (`uuid`, `jsonb`, `numeric`, `timestamptz`, enums); tests must run
offline with no DB driver.

## Decision

`persist/models.py` — one set of SQLAlchemy 2.0 models, portable with **no
per-backend branching**:

- `sqlalchemy.Uuid` PKs/FKs (native `UUID` on PG, `CHAR` on SQLite).
- JSONB columns: `sa.JSON().with_variant(postgresql.JSONB(), "postgresql")`
  (JSONB on PG, JSON on SQLite).
- Money: `Numeric(…, asdecimal=True)` (ADR-0001); `DateTime(timezone=True)`;
  `txn_date` naive `Date`.
- Enums persist their **`.value`** token (`values_callable`) — the stable
  lowercase string stored in the DB / shown in the review UI. Reuse existing
  `ReceiptStatus` / `Severity` / `Legibility`; new `PassName` / `ReviewState`.
- Constraints/indexes per §6: cascade delete on `line_items`,
  `UniqueConstraint(receipt_id, position)`, self-FK `duplicate_of`, unique
  `review_tasks.receipt_id`, and the four `receipts` indexes.
- `docker-compose.yml`: `postgres:16` + healthcheck; switch backends via
  `DATABASE_URL` (`postgresql+psycopg://…` vs `sqlite:///…`). `psycopg` is the
  optional `postgres` extra. Tests use SQLite in-memory with `PRAGMA
  foreign_keys=ON`.

## Consequences

- Alembic migrations (P3.T2) are generated against these models next; the
  repository (P3.T3) builds on them.
- Reusing app-layer enums in the ORM couples `persist` → `score`/`validate`/
  `extract`; acceptable to keep enum values single-sourced.

## References

SPEC §6 (data model), §5 (layout); ADR-0001.
