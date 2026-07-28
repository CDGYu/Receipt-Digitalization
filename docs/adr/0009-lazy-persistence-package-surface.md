# ADR 0009 — Lazy `receipts.persist` surface so a base install can migrate

**Status:** Accepted

## Context

`alembic/env.py` needs only `Base.metadata`. But the import chain
`receipts.persist` → `repository` → `receipts.ingest.dedupe` → **numpy / Pillow**
pulls the optional `pipeline` extra. A pre-merge review confirmed that
`pip install -e .` followed by `alembic upgrade head` **failed** on an import that
has nothing to do with the schema.

Importing the submodule directly (`from receipts.persist.models import Base`) is
not sufficient on its own: Python still executes the package `__init__`, which
eagerly imported `repository`.

## Decision

- `alembic/env.py` imports `from receipts.persist.models import Base` (the module
  that needs nothing but SQLAlchemy and the project's own enums).
- `receipts/persist/__init__.py` imports the **models eagerly** and resolves the
  **repository/session names lazily** via PEP 562 `__getattr__` (a `_LAZY` name →
  submodule map, cached into `globals()` on first access). `receipts.persist.repository`
  and `.session` remain resolvable as attributes, and
  `from receipts.persist import save_extraction` behaves exactly as before — just
  imported later.
- Two tests pin this: a subprocess asserts `receipts.persist.models` imports with
  `numpy` / `PIL` / `cv2` / `receipts.ingest.dedupe` absent from `sys.modules`,
  and a source check asserts `env.py` imports from the light module.

## Consequences

- Migrations work on a base install; the heavy extras stay optional (ADR-0005).
- Anyone adding an eager import to `persist/__init__.py` will break this — the
  subprocess test is the guard, and the docstring explains why.
- The lazy indirection is invisible to callers but is worth knowing about when
  debugging an import.

## References

ADR-0004, ADR-0005; `alembic/env.py`; `tests/test_migrations.py`.
