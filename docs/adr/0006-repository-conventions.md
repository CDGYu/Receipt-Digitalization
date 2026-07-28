# ADR 0006 — Repository conventions: injected session, caller commits, `ValueError` boundary

**Status:** Accepted (implements SPEC §14.8)

## Context

`persist/repository.py` is the only read/write path over the seven tables. It has
to be unit-testable offline (SQLite, no driver), composable inside a larger
pipeline transaction, and predictable for the API layer that will wrap it
(Phase 4).

## Decision

1. **Every function takes `session: Session` as its first argument.** No module
   global engine or ambient session; `persist/session.py` builds them
   (`make_engine` / `make_session_factory`) and nothing connects at import time.
2. **The caller owns the transaction.** Repository functions `flush()` (so ids
   and defaults exist) but do not `commit()`. The single documented exception is
   `apply_corrections`, which SPEC §14.8 specifies as transactional and therefore
   commits or rolls back itself.
3. **`ValueError` is the layer's error currency.** A missing receipt, an
   unmappable field path, a non-finite amount, an over-long bounded string, or a
   constraint the plan could not foresee all surface as `ValueError` (chained
   `from exc`). Callers never have to catch `IntegrityError` as well.
4. **`apply_corrections` validates before mutating.** Phase 1 resolves and
   coerces every dotted path against closed lookup tables
   (`_RECEIPT_FIELDS` / `_LINE_ITEM_FIELDS`); phase 2 applies, writes one
   `corrections` row per *changed* path, sets `status=reviewed`, and commits. So
   an unmappable path cannot leave a half-applied patch. A no-op patch writes no
   rows. Savepoints were rejected: pysqlite's SAVEPOINT behaviour is unreliable.
5. `patch` accepts dotted **and** nested forms, normalised through
   `receipts.extract.paths.flatten` — the same path grammar the corrections log,
   the consistency diff, and the eval harness already speak. `line_items[i]`
   addresses the item at **position** `i`.

## Consequences

- The FastAPI layer (P4.T3) can wrap a request in one session/transaction and
  compose several repository calls.
- An unlisted field path is a hard error, never a silent no-op: a reviewer's edit
  that vanished would be a data-integrity bug.
- `modifiers` and `bbox` are deliberately not correctable via `apply_corrections`
  (they are documents, not scalars).

## References

SPEC §14.8; ADR-0001 (Decimal), ADR-0007 (PAN/money integrity).
