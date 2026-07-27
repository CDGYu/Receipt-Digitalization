# ADR 0005 — Tooling, src-layout, and offline test strategy

**Status:** Accepted

## Context

The repo was reconstructed from a flat dump into a proper package. It must be
reliably testable offline (no network, no heavy deps required for the core) on a
new interpreter (dev is Python 3.14), with fast CI.

## Decision

- **src-layout**: package `receipts` under `src/`; `eval/` and `config/` at the
  root. `pyproject.toml` sets `[tool.pytest.ini_options] pythonpath = ["src",
  "."]`, `testpaths = ["tests"]`, so `python -m pytest` just works (no
  `PYTHONPATH`).
- **Optional extras** keep the core light: `dev` (pytest/ruff/mypy), `pipeline`
  (pillow/opencv-python-headless/pillow-heif/pypdfium2/openpyxl), `anthropic`,
  `openai`, `postgres` (psycopg). Tests that need heavy deps guard with
  `pytest.importorskip(...)` so the core still collects without them.
- **CI** (`.github/workflows/ci.yml`, Python 3.11/3.12): installs
  `.[dev,pipeline]`; `pytest` and `ruff check` are **blocking**, `mypy src` is
  **informational** (`continue-on-error`).
- **ruff**: line-length 100, `select = E,F,I,B,UP`, with a few global ignores
  (UP035/UP037/UP042) + surgical per-file-ignores so existing source passes
  without churn.
- **Eval preserves `Decimal`**: `field_accuracy` flattens `model.model_dump()`
  (python mode) — **not** `model_dump(mode="json")`, which would stringify
  `Decimal` — so money is compared via `within_tolerance`, not text.

## Consequences

- New heavy-dep modules must add an `importorskip` guard and (if they add a
  runtime dep) a `pipeline`/provider extra + a CI install update.
- Do **not** commit `.kiro/settings/mcp.json` (a local working-tree edit that
  has persisted all session); stage files explicitly.

## References

`pyproject.toml`, `.github/workflows/ci.yml`, `eval/metrics.py`; ADR-0001.
