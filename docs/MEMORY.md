# Agent Memory — Receipt Digitization System

Durable working memory for cross-session continuity. Read this first, then the
files in "Key references" below. Last updated: **2026-07-28**.

## Snapshot

- **`master` @ `8cbef5a`** — Phase 0 foundations + Phase 1 offline modules + the
  online wiring (config, client factory, M1 pipeline, confidence scoring,
  one-command baseline runner). 285 tests.
- **`master` @ `df528cb`** — Phase 3 (persistence) merged: the 7-table ORM +
  `docker-compose.yml`, Alembic migrations, the repository layer, DB-backed
  dedupe, the review queue, and the 4-sheet XLSX export.
  **410 tests passing, ruff clean.** No feature branch is open.
- Phase 3 is complete except **P3.T6 calibration** (blocked on the golden set).
  Next milestone is **Phase 4 (service)**, which starts with the auth decision.
- Dev interpreter **Python 3.14.4**; CI matrix 3.11/3.12.
- Plan of record: `IMPLEMENTATION_PLAN.md`. Running log: `.superpowers/sdd/progress.md`.

## What this project is

A VLM pipeline turning receipt photos into accounting-grade structured data.
**Prime directive: optimize auto-approval precision (target ≥99%), not raw
extraction accuracy. A wrong number is far worse than a missing one — prefer
`null` over a confident guess.** Three model passes (triage → extract → repair)
with deterministic validation between extract and repair, self-consistency for
handwriting, and one confidence score that routes to auto-approve or review.

## Invariants (never violate — see `.kiro/steering/receipt-system.md` + ADRs)

`Decimal` on the money path, never `float` (ADR-0001). Validation is
deterministic/pure, never mutates, never raises, stable rule IDs. Tolerance is
cents-bounded (`rel=0.0002`, floor scales with line count). Repair keeps the
**best** attempt `(errors, warns, nulls)`; only errors trigger repair;
unparseable → re-extract; never alter numbers to force arithmetic. Structured
output via tool-use. Few-shot images first, target last. Consistency runs are
never cached. Merchant hints end with "trust the image." Nothing is silently
dropped. Excel is output only; the DB is the source of truth.

## Built (on `master` unless noted)

- `extract/`: schema, prompts, json_io, paths, extractor (3-pass + repair +
  best-attempt + self-consistency), lineitem_align, clients/{base, fake,
  anthropic_client, openai_compat, **factory**}
- `validate/`: rules (28), report, context, validator
- `normalize/`: numbers, dates, text  ·  `preprocess/`: image_ops, bounds, quality
- `ingest/`: storage, dedupe, ingest  ·  `export/`: xlsx (Receipts + LineItems only)
- `score/`: confidence (score_confidence / explain_confidence / route / ReceiptStatus)
- `pipeline.py`: prepare_image, run_receipt, build_eval_pipeline
- `config/settings.py`; `eval/`: metrics, harness, golden_set, run_baseline
- Foundations: eval harness, golden-set on-ramp, CI, ruff/mypy, float-guard test
- **Phase 3 (persistence):** `persist/models.py` (7-table ORM) +
  `docker-compose.yml`; `alembic/` + `alembic.ini` (migration `b9342906a5a6`
  creates all 7 tables; a `compare_metadata` test guards ORM/migration drift —
  but it is SQLite-only, so it cannot see a new ENUM member);
  `persist/session.py` (`make_engine` / `make_session_factory`);
  `persist/repository.py` (§14.8 + DB-backed dedupe: `find_duplicate_by_phash`,
  `find_duplicate_by_content`, `mark_duplicate`); `review/queue.py` (§14.9:
  `enqueue_review`, `next_task`, `close_task`, `queue_stats`);
  `export/xlsx.py` now writes all four sheets with §13.5 formatting via the
  `ReceiptExportRow` metadata dataclass.
  - Alembic's console script is not on PATH — use `python -m alembic`.
  - `persist/__init__` is **lazy** (PEP 562 `__getattr__`): the models import
    eagerly, the repository/session names resolve on first access, so a base
    install (no `pipeline` extra) can still run migrations. Public API unchanged.
  - `next_task` applies `FOR UPDATE SKIP LOCKED` only on dialects that support
    it — **SQLite silently drops the clause instead of erroring**, which is why
    the guard lives in Python.
  - `redact_pan` is the §18 defence for `raw_response`; a review found it
    leaking on `CARD NO.<PAN>`, mixed separators, and dict keys — all fixed and
    regression-tested. Keep its silent-case tests intact when touching it.

## NOT built yet (remaining work)
- `review/{queue,api}.py` (FastAPI) + **auth** ; `pipeline.process_receipt`
  (full orchestrator) + worker ; `cli.py` (Phase 4)
- **Frontend** review UI — framework undecided (Phase 5)
- `merchants/{fingerprint,registry}.py` + few-shot injection (Phase 6)
- Self-consistency wired into `run_receipt` (extractor supports it; the M1
  runner does not call it yet) (Phase 7)
- Confidence-weight calibration against the golden set (Phase 8)

## How to run

- Tests: `python -m pytest` (pyproject sets `pythonpath=["src","."]`,
  `testpaths=["tests"]`). Lint: `python -m ruff check .`. Types: `mypy src`
  (informational).
- Baseline: `python -m eval.run_baseline` — needs a **real provider + a labeled
  golden set** (else it refuses the `fake` provider / scores an empty set).
- **Terminal quirk:** PowerShell sometimes clips piped Python output. Use
  `python -m pytest 2>&1 | Select-Object -Last 3` and capture summary lines
  explicitly.

## Environment / provider (user's `.env`, gitignored)

- Active config: `VLM_PROVIDER=openai`, `VLM_BASE_URL=http://localhost:11435/v1`,
  model `moondream` (a **local** OpenAI-compatible server). `openai` SDK installed.
- **Golden set is empty** (`eval/golden/labels|images`) — no real baseline
  possible until the user labels receipts.
- `moondream` likely lacks tool-use/function-calling, which the extractor needs
  for schema-constrained output → extraction may fail; a tool-capable model
  (Gemini/GPT-4o/Claude or a Qwen-VL-class local model) is safer.
- **Security:** a commented-out Gemini key was once echoed in output → user
  advised to rotate it. Never echo `.env` secret values; `.env` is gitignored.

## Blockers that need the user

1. Label the golden set (M0) — required for a baseline and calibration.
2. Choose a tool-capable provider + supply the key.
3. Decisions: **auth model** (P4.T2), **frontend framework** (P5.T0),
   **R060/R061 OCR-grounding** approach (P2.T2).

## Deferred follow-ups / known minors (non-blocking)

- Move confidence penalty weights into `config/rules.yaml` (calibration, P3.T6).
- Consolidate the `0.85`/`0.60` thresholds (duplicated in `route()`, `Settings`,
  `eval.metrics`) onto `Settings` at M3.
- `run_receipt` returns the raw-validated report but the normalized extraction
  (an ambiguous date is nulled) — reconcile when persistence lands (M3).
- Handwriting penalty reads only `receipt.meta.is_handwritten`; consider OR-ing
  `triage.is_handwritten`.
- `vllm`/`ollama` still require `VLM_API_KEY`; `VLM_BASE_URL` ignored for `anthropic`.
- Statistical caveat: ≥99% precision can't be validated on a tiny golden set —
  grow the held-out set before trusting that number.
- `save_extraction` takes `report` (per §14.8) but does **not** write findings —
  the pipeline must call `save_findings` separately (findings accumulate across
  passes via `resolved_by_repair`). Revisit if replace-semantics is wanted.
- `_build_line_items` falls back to list order when emitted positions aren't
  distinct, so `unique(receipt_id, position)` can't sink a whole receipt.
- ruff sorts `from alembic import command` as **first-party** in tests (the
  repo-root `alembic/` dir shadows the package) — don't "fix" that import order.
- `enqueue_review` is check-then-insert against a UNIQUE column: concurrent
  enqueues can still raise `IntegrityError`. Wrap it or use an upsert when the
  API lands (P4.T3).
- The migration drift guard runs on SQLite only, so a new ENUM member would pass
  locally and fail on Postgres.
- XLSX `write_only` streaming above 5000 rows is deferred (incompatible with the
  random-access §13.5 formatting pass).

## Workflow & conventions

- **subagent-driven-development**: one fresh implementer subagent
  (`general-task-execution`) per task. Its brief must tell it to read the real
  signatures first, work TDD, keep the full suite green + ruff clean, stage only
  its own files, and **never stage `.kiro/settings/mcp.json`** (a persistent
  local working-tree edit). The controller then reviews (read the diff + run
  `pytest`/`ruff`) and the task ends with a commit.
- **Per milestone**: work on a feature branch; when done, run a final
  whole-branch review (`semantic_reviewer`), then fast-forward merge to `master`.
  Review write-ups land under `semantic-review/` (untracked).
- Conventional commit messages (`feat(scope): …`, `chore: …`, `fix: …`).
- Global skills (`~/.kiro/skills`) and MCP (`~/.kiro/settings/mcp.json`) are
  configured; steering `.kiro/steering/receipt-system.md` auto-loads.

## Key references

- `RECEIPT_SYSTEM_SPEC.md` — build spec: §3 architecture, §6 data model, §9
  normalization, §10 validation, §12 confidence + routing, §14 function
  inventory, §15 milestones, §16 eval, §17 config, §18 traps, §19 DoD.
- `README.md` (overview, §5 design decisions), `VLM_AND_DATA.md` (model/data).
- `IMPLEMENTATION_PLAN.md` — the phased task list (authoritative).
- `docs/adr/` — implementation decisions (0001–0005).
- `.kiro/steering/receipt-system.md` — always-on load-bearing rules.
- `.superpowers/sdd/progress.md` — the running task ledger.
