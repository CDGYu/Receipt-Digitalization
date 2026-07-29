# ADR 0014 — Optional dependencies stay out of every import path

**Status:** Accepted (forced by two shipped defects during P4.T5/T6, 2026-07-29)

## Context

This project splits its dependencies into extras on purpose. The base
distribution installs only `alembic`, `pydantic`, `pydantic-settings`, `pyyaml`
and `sqlalchemy`. `pillow`, `opencv-python-headless`, `pillow-heif`,
`pypdfium2` and `openpyxl` live in the `pipeline` extra; `rq`/`redis` in
`worker`; `fastapi` and friends in `api`; and `eval/` is not shipped at all —
`pyproject.toml` calls it "dev/research tooling, not part of the installed CLI".
A base install is a supported configuration, and `receipts users list` has no
business needing an image library.

**The same defect shipped twice in one milestone, and the test suite could not
see it either time.**

1. `cli.py` imported `eval.harness`, `eval.metrics` and `eval.run_baseline` at
   module top. In an installed environment **every** `receipts` command died at
   import with `ModuleNotFoundError: No module named 'eval'` — not just `eval`
   and `calibrate`. All 689 tests passed.
2. After that was fixed, `cli.py` still imported `export.xlsx` (`openpyxl`) and
   `pipeline` (`PIL`, `cv2`) at module top, with the same consequence. All 690
   tests passed.

`python -m pytest` cannot detect this **by construction**: `pyproject.toml` sets
`pythonpath = ["src", "."]`, which puts the repo root on `sys.path`, and every
extra is installed on a development machine. The suite is not the environment the
software runs in. Both defects were found only by running the real console script
from outside the repository.

The second fix also showed the problem is not confined to the module you are
editing. Cutting `cli.py`'s two imports was not enough: the graph reached the
`pipeline` extra through four more edges — `.worker` → `.pipeline`,
`ingest/__init__` → `dedupe`, `persist/repository` → `dedupe`, and
`ingest/ingest` → `pypdfium2`.

## Decision

**No module reachable from an entry point may import an optional extra at module
top.** Entry points are `receipts.cli`, `receipts.worker`, `receipts.review.api`,
and anything Alembic loads.

Two mechanisms, both already established in this codebase:

- **In-function import** for a dependency one command needs —
  `extract/clients/factory.py` and `receipts/worker.py` (for `rq`/`redis`) are the
  precedents.
- **PEP 562 `__getattr__` on the package surface** when the cut has to happen at
  a re-export — ADR-0009 introduced this for `receipts.persist` so a base install
  could run migrations, and P4.T5/T6 applied the same pattern to
  `receipts.ingest`.

**A missing optional dependency is reported, never raised as a traceback.** The
command exits `1` naming the extra that supplies it. The check keys on
`ModuleNotFoundError.name`, never a bare `except ModuleNotFoundError`: `eval`
transitively imports the `pipeline` extra, so a bare catch would mislabel a
missing Pillow as "eval is not installed" and send an operator to fix the wrong
thing.

**The guard is a subprocess test whose blocked set is derived from the code's own
constant.** `tests/test_cli_reports.py` installs a `sys.meta_path` finder that
raises `ModuleNotFoundError` for `eval` and for every name in
`cli._PIPELINE_EXTRA_MODULES | {"numpy"}`, then asserts `import receipts.cli`
succeeds. It must be a subprocess — an in-process assertion is exactly what
masked the bug, since the modules are already in `sys.modules`. It must derive
from the constant rather than restate a subset: the first version of this guard
hardcoded `{PIL, openpyxl, cv2}`, and restoring a module-top `pypdfium2` left it
passing.

`numpy` is named explicitly because `ingest/dedupe.py` imports it directly while
it arrives only transitively through opencv/Pillow, undeclared in the extra.

## Consequences

- Adding a dependency to an extra means adding it to `_PIPELINE_EXTRA_MODULES`
  (or the equivalent) so the guard covers it automatically.
- **Verification for anything with an entry point includes running it from
  outside the repository**, not only `python -m pytest`. A green suite is not
  evidence that an installed command works.
- The lazy surfaces have a cost: an error that used to appear at import now
  appears at first use. That was checked — a blocked `numpy` still raises the same
  `ModuleNotFoundError` from `receipts.ingest.compute_phash` rather than being
  masked as an `AttributeError`, and no public name disappeared from
  `receipts.ingest.__all__`.
- Still open, recorded rather than fixed: `receipts eval` and `receipts
  calibrate` continue to traceback without the `pipeline` extra, because
  `eval.run_baseline` imports `receipts.pipeline` at *its* module top. Six of the
  eight commands degrade cleanly; these two do not, and `calibrate` only reads
  JSON so it needs nothing from the pipeline.
- The console script also needs the interpreter's `Scripts`/`bin` directory on
  `PATH`, which is not true on the current development machine.
  `python -m receipts.cli <command>` is the invocation that always works.

## References

`pyproject.toml` (the extras and `pythonpath`); ADR-0009 (lazy `receipts.persist`
surface, the same pattern for the same reason); ADR-0013 (the CLI contract);
`tests/test_cli_reports.py` and `tests/test_import_isolation.py` (the guards);
`.superpowers/sdd/2026-07-29-cli/progress.md` (both defects as found).
