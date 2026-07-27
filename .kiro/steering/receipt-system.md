---
inclusion: always
---

# Receipt Digitization System — Project Conventions

A VLM-based pipeline that turns receipt photos into structured, accounting-grade
data. Full detail lives in `README.md`, `RECEIPT_SYSTEM_SPEC.md` (build spec —
§14 function inventory, §15 milestones, §18 known traps), and `VLM_AND_DATA.md`.

## Prime directive

The system's value is knowing *which* extractions to doubt. Optimize for
**auto-approval precision (target >=99%)**, not raw extraction accuracy. A wrong
number is far worse than a missing one — prefer `null` over a confident guess.

## Architecture (three model passes)

1. **Triage** (cheap model): is this a receipt, printed or handwritten, legible?
   Returns no amounts.
2. **Extract** (strong model): schema-constrained tool-use call; injects up to
   two verified few-shot examples for known merchants.
3. **Repair** (only when validation finds errors): feeds the model back the
   *specific* numbers that do not reconcile.

Deterministic validation (28 pure-function rules) sits between extract and
repair. Handwritten receipts get self-consistency voting (3 runs). Every signal
folds into one confidence score that routes to auto-approve or review.

## Load-bearing rules — do not violate

- **`Decimal` everywhere in the money path. Never `float`.** A stray float
  creates tolerance failures that look like model errors. A schema test asserts
  no field is typed float.
- **Validation is deterministic code** — pure functions, no I/O. The validator
  never mutates its input, never raises, and is deterministic.
- **Rule IDs (R001, R021, ...) are stable and never renumbered** — they are
  stored in the DB and shown in the review UI.
- **Tolerance is bounded in cents, not proportional.** Use `rel = 0.0002`; scale
  the floor with line count where error genuinely accumulates. A safe-feeling
  large tolerance silently excuses misreads.
- **Rules must stay silent when they should.** Prefer exact match after
  normalization over substring match (a naive R052 would delete real products
  like "TOTAL WINE CO MERLOT"). Test the silent case, not just the firing case.
- **Repair keeps the *best* attempt**, ranked `(error_count, warn_count,
  null_count)` — not the last attempt.
- **Only errors trigger repair; warnings lower confidence instead.** An
  unparseable response triggers a re-extract, not a repair.
- **Repair must not alter numbers to force the arithmetic.** Real receipts do
  not always add up — keep the printed values and set a flag.
- **Structured output via tool-use**, not "reply in JSON". `json_io.py` flattens
  `$ref`/`$defs` and strips the `Decimal` string branch — both have tests
  because both silently reappear on a dependency upgrade.
- **Few-shot images go first, the target receipt goes last.**
- **Consistency runs are never cached** (the cache refuses non-zero temperature)
  — a cache hit would manufacture false agreement.
- **Merchant hints always end with "trust the image."**
- **Nothing is ever silently dropped.** Every receipt reaches a terminal state;
  on any stage exception, mark `needs_review` with the failing stage as reason.
- **Excel is an output format, never the source of truth** — exports read from
  the database.

## Structure & workflow

- Layout: `src/receipts/extract/` (schema, prompts, json_io, paths, extractor,
  `clients/`), `src/receipts/validate/` (rules, report, context, validator),
  `config/rules.yaml`, `tests/`.
- Run tests: `python -m pytest` (pyproject sets `pythonpath=src`,
  `testpaths=tests`). 103 tests pass offline via the fake client — no network.
- Build order (spec §15): golden set first (M0 — collect and label your own
  receipts), then extraction (M1), validation+repair (M2), persistence/routing
  (M3), review UI (M4), merchant few-shot (M5), self-consistency (M6). Build
  `eval/harness.py` early; re-run it on every prompt/model/rule change and commit
  results grouped by `prompt_bundle_hash()`.
- Change a prompt -> bump `PROMPT_VERSION` and re-run eval. Add or tune a rule ->
  `src/receipts/validate/rules.py` + `config/rules.yaml`.
