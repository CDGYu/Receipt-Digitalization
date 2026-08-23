# Receipt Digitization System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is a **master plan**: each Phase below is an independently shippable milestone and should be expanded into its own detailed, code-level plan (one `writing-plans` pass per phase) before that phase is executed.

**Goal:** Complete the receipt-digitization product — from image upload through extraction, deterministic validation, human review, and Excel export — around the already-built extraction/validation core.

**Architecture:** A staged pipeline (ingest -> preprocess -> triage -> extract -> normalize -> validate -> repair -> score -> route -> persist -> export), fronted by a FastAPI service with an async job queue and a keyboard-first review UI. The extraction/validation core exists and is tested offline via a fake VLM client; the surrounding service, persistence, API, frontend, and evaluation harness do not yet exist.

**Tech Stack:** Python 3.11+ (dev on 3.14.4), Pydantic v2, FastAPI, SQLAlchemy 2.0 + Alembic, PostgreSQL (prod) / SQLite (dev), RQ + Redis, Pillow + OpenCV + pillow-heif + pypdfium2, openpyxl, structlog, pytest. Frontend framework is an open decision (see Task P5.T0).

## Global Constraints

These apply to every task. Values copied from `RECEIPT_SYSTEM_SPEC.md` and `.kiro/steering/receipt-system.md`.

- **`Decimal` everywhere in the money path. Never `float`.** A schema-walk test asserts no field is typed `float`.
- **Validation is deterministic:** pure functions, no I/O, never mutates the record, never raises (a crashing rule becomes an INFO finding `"<id>.crashed"`).
- **Rule IDs (R001, R021, ...) are stable and never renumbered** — stored in the DB and shown in the UI.
- **Tolerance:** `within_tolerance(a, b, rel=0.0002, floor=0.02)`; the floor does the real work. Scale the floor with line count in R020/R024 (`floor = max(base, 0.01 * n_lines)`). Never inflate `rel`.
- **Repair keeps the *best* attempt** ranked `(error_count, warn_count, null_count)`; only ERROR findings trigger repair; an unparseable response triggers a re-extract, not a repair; never alter numbers to force arithmetic — set `meta.receipt_is_inconsistent` instead.
- **Structured output via tool-use**, not "reply in JSON". `json_io` flattens `$ref`/`$defs` and strips the `Decimal` string branch (both have regression tests).
- **Few-shot images go first, the target receipt goes last.**
- **Consistency runs are never cached** (the cache refuses non-zero temperature).
- **Merchant hints always end with "trust the image."**
- **Nothing is ever silently dropped:** `process_receipt` wraps every stage; any exception marks the receipt `needs_review` with the failing stage as reason.
- **Excel is output only; the database is the source of truth.**
- **Secrets via environment (`pydantic-settings`) only.** Tolerances and penalty weights live in `config/rules.yaml`. No secrets in `rules.yaml` or code.
- **Store `txn_date` as a naive date; system timestamps as `timestamptz`.** Store only `card_last4`; redact any full PAN before writing `extraction_runs.raw_response`.
- **Tests:** `python -m pytest` (pyproject sets `pythonpath=src`, `testpaths=tests`). Baseline: 103 passing.

---

## Current state

> **Rewritten 2026-08-23, after auditing this file against the tree.** What
> stood here described the repository as it was around 2026-07-28 and had not
> moved since: it listed fourteen things as "Specified but not built" that had
> all shipped, and quoted a test count that was wrong by an order of magnitude.
> **Every checkbox in this document was also unticked**, including for whole
> phases that had merged. Both are corrected; the boxes below now mean something.

**No test count is written here, and no rule count.** Both move with every
milestone and both of this line's predecessors rotted. Run `python -m pytest`,
and count `id = "R[0-9]{3}"` in `src/receipts/validate/rules.py` — it was 28
when this plan was written and is more now.

**Built, merged, and covered:** every module the "File structure to be created"
section below names. `extract/`, `validate/`, `ingest/`, `preprocess/`,
`normalize/`, `score/`, `merchants/`, `persist/` (+ Alembic), `review/` (+ the
FastAPI app and auth), `export/`, `pipeline.py`, `cli.py`, `asgi.py`,
`worker.py`, `config/settings.py`, `eval/harness.py` + `eval/metrics.py` +
`eval/run_repeats.py`, and a **React + Vite frontend** with login, review,
admin and receipts screens. Deployment is complete too — entry point
(ADR-0035), container (ADR-0036), CI (ADR-0037).

**What is genuinely NOT built**, each with its status note on the task below:
the golden set (P0.T1 — three receipts of a documented 50), consistency
tolerance and shared alignment (P2.T1 / ISSUE-023), the tall-receipt
cross-check (P2.T3 / ISSUE-024), the pipeline-level worse-repair pin (P2.T4 /
ISSUE-025), bounding-box highlighting (P5.T1, gated on P2.T2), the upload
screen (P5.T2 / ISSUE-026), self-consistency wiring (P7.T1), and all of
Phases 8 and 9.

**The single blocking fact:** nothing in Phases 8 or 9, and no acceptance
phrased as "measure X before and after", can start until the golden set grows.
`docs/KNOWN_ISSUES.md` ISSUE-001 is the record; `docs/NEXT_SESSION_PROMPT.md`
section 2 is the ordered task list. **Where this file and those two disagree,
they win** — this one is a phase/task reference, not a state register.

---

## File structure to be created

```
src/receipts/
  ingest/        ingest.py, dedupe.py, storage.py
  preprocess/    image_ops.py, bounds.py, quality.py
  normalize/     numbers.py, dates.py, text.py, __init__.py
  score/         confidence.py
  merchants/     fingerprint.py, registry.py
  persist/       models.py (SQLAlchemy ORM), repository.py
  review/        queue.py, api.py
  export/        xlsx.py
  pipeline.py    end-to-end orchestrator (only fn the worker calls)
  cli.py         ingest/process/export/eval/calibrate/merchants/reprocess
config/
  settings.py    pydantic-settings (env only)
eval/
  harness.py, metrics.py, golden/{images,labels}/, results/
alembic/         migrations
frontend/        review UI (framework: decision P5.T0)
tests/           one test module per new source module
```

---

## Phase 0 — Foundations & critical path (do first)

Rationale: nothing downstream can be measured without an evaluation harness and a labelled set, and two algorithm design bugs are cheapest to fix now while the core is small.

### Task P0.T1 — Golden set (M0) `[data]`

> **STATUS 2026-08-23 — NOT DONE, and it is the project's bottleneck.** Three
> labels on disk, all `handwritten`, against a 60% `printed_clean` target. This
> is ISSUE-001 step 7 Task 3; it needs a person and a camera and no code removes
> it. `eval/golden/README.md` is the procedure.


**Files:** `eval/golden/labels/{id}.json`, `eval/golden/images/{id}.*`

- [ ] Collect >= 50 real receipts at the target mix: 60% printed/clean, 15% printed/degraded, 20% handwritten, 5% adversarial.
- [ ] Hand-label each into the `ReceiptExtraction` schema (spec §7); save as `eval/golden/labels/{id}.json`.
- [ ] Hold out 20-30% as a calibration set; do not inspect it until Phase 3.
- [ ] Commit labels (images are git-ignored per `.gitignore`).

**Acceptance:** `eval/golden/labels/` contains >= 50 schema-valid JSON files (a loader test parses each into `ReceiptExtraction` with no error).

> Note (statistics): a >=99% precision target cannot be *validated* on a held-out set of ~20-30. Treat 99% as aspirational until the calibration set reaches the hundreds (the `corrections` table will supply this over time). Track the precision confidence interval, not just the point estimate.

### Task P0.T2 — Evaluation harness (M-critical, §16) `[algorithm][backend]`

**Files:** Create `eval/metrics.py`, `eval/harness.py`, `tests/test_eval_metrics.py`

**Interfaces — Produces:**
- `field_accuracy(predicted: ReceiptExtraction, truth: ReceiptExtraction) -> dict[str, bool]`
- `line_item_f1(predicted: list[LineItem], truth: list[LineItem]) -> tuple[float, float, float]`
- `critical_field_accuracy(predicted, truth) -> bool` (all of merchant.name, receipt.date, totals.total exact)
- `calibration_curve(results: list[EvalResult]) -> list[tuple[Decimal, float, float]]`
- `run_eval(golden_dir: Path, pipeline_fn: Callable) -> EvalReport`

**Interfaces — Consumes:** `receipts.extract.schema.{ReceiptExtraction, LineItem}`, `receipts.validate.rules.within_tolerance`, `receipts.normalize.text.clean_text` (P1.T4; until then inline a casefold+strip).

- [x] **Step 1 — failing test for `field_accuracy`:**

```python
from decimal import Decimal as D
from receipts.extract.schema import ReceiptExtraction
from eval.metrics import field_accuracy

def test_field_accuracy_money_uses_tolerance():
    truth = make_receipt(total=D("949.20"))
    pred  = make_receipt(total=D("949.21"))   # within floor 0.02
    assert field_accuracy(pred, truth)["totals.total"] is True

def test_field_accuracy_flags_misread():
    truth = make_receipt(total=D("949.20"))
    pred  = make_receipt(total=D("945.20"))   # 4.00 off -> wrong
    assert field_accuracy(pred, truth)["totals.total"] is False
```

- [x] **Step 2 — run, verify FAIL** (`eval.metrics` not importable).
- [x] **Step 3 — implement `field_accuracy`:** flatten both via `receipts.extract.paths.flatten`, compare money paths with `within_tolerance`, strings after casefold+`clean_text`, everything else by `==`.
- [x] **Step 4 — run, verify PASS.**
- [x] **Step 5 — repeat Steps 1-4** for `line_item_f1` (greedy match — see P0.T3), `critical_field_accuracy`, `calibration_curve` (for each candidate threshold return `(threshold, auto_approve_rate, precision)`).
- [x] **Step 6 — implement `run_eval`:** iterate golden labels, run `pipeline_fn` (the `FakeVLMClient` for offline tests), assemble the six metrics (§16), write `eval/results/{date}-{prompt_version}.json`.
- [x] **Step 7 — commit.**

**Acceptance:** `python -m pytest tests/test_eval_metrics.py` passes; `receipts eval` (P4.T6) prints the six-metric table and writes a results file.

### Task P0.T3 — Shared greedy line-item alignment (review fix) `[algorithm]`

> **STATUS 2026-08-23 — BUILT; its acceptance is HALF MET.** The acceptance names
> two consumers and only `eval.metrics.line_item_f1` calls it. The consistency
> diff still aligns positionally — **ISSUE-023**.


**Problem:** consistency (§11) aligns line items *by position* ("differing count -> all disputed"), but eval (§16) aligns *greedily by description*. One missed row on one run then nukes confidence on every row. Unify on greedy alignment.

**Files:** Create `src/receipts/extract/lineitem_align.py`, `tests/test_lineitem_align.py`

**Interfaces — Produces:** `align_line_items(a: list[LineItem], b: list[LineItem]) -> list[tuple[int|None, int|None]]` (index pairs; `None` = unmatched).

- [x] **Step 1 — failing test:** 3 items vs the same 3 with one extra row -> 3 matched pairs + 1 `(i, None)`, not "all disputed".
- [x] **Step 2 — run, verify FAIL.**
- [x] **Step 3 — implement** greedy match on normalized-description similarity, then pair leftovers as unmatched.
- [x] **Step 4 — run, verify PASS.**
- [x] **Step 5 — commit.**

**Acceptance:** `eval.metrics.line_item_f1` and (in Phase 2) `consistency.diff_extractions` both call `align_line_items`.

### Task P0.T4 — Dev tooling & CI `[ops]`

**Files:** Modify `pyproject.toml`; Create `.github/workflows/ci.yml`, `tests/test_no_float_in_money_path.py`

- [x] Add `[tool.ruff]` and `[tool.mypy]` config; add `ruff`, `mypy` to `dev` extras.
- [x] Add the schema-walk test asserting no `float` in the money path (Global Constraint), if not already present.
- [x] CI: on push/PR, run `pip install -e .[dev]` then `python -m pytest`, `ruff check`, `mypy src`.
- [x] Commit.

**Acceptance:** CI is green on the whole suite plus the float-guard test. *(This line quoted "the current 103 tests" until 2026-08-23; a suite count in an acceptance is a number that rots without its sentence changing.)*

---

## Phase 1 — Straight-line extraction (M1) `[backend][algorithm]`

Ship `load -> preprocess -> triage -> extract -> normalize -> minimal XLSX` as one path, no DB/queue/repair. Record baseline accuracy against the golden set.

### Task P1.T1 — `preprocess/image_ops.py` `[backend/CV]`
**Files:** Create `src/receipts/preprocess/image_ops.py`, `tests/test_image_ops.py`
**Produces (spec §14.2):** `load_image`, `fix_orientation`, `to_rgb`, `resize_for_model(max_edge=2048, min_text_height_px=12)`, `split_tall_receipt(max_aspect=3.0, overlap_px=120)`, `to_base64`.
- [x] Tests: HEIC/PNG/JPEG load; EXIF rotation applied then stripped; a 5:1 image splits into overlapping strips whose overlap exceeds one line's height; `resize_for_model` warns below `min_text_height_px`.
- [x] Implement to pass; commit.
**Acceptance:** tests pass; splitting a tall fixture yields >1 strip with correct overlap.

### Task P1.T2 — `preprocess/bounds.py` + `quality.py` `[backend/CV]`
**Files:** Create `bounds.py`, `quality.py`, `tests/test_preprocess_bounds.py`, `tests/test_preprocess_quality.py`
**Produces:** `detect_document_bounds`, `deskew_perspective`, `auto_crop`, `estimate_rotation`; `assess_quality -> QualityReport`, `is_processable -> (bool, reason)`.
- [x] Tests on synthetic fixtures: a rotated rectangle deskews to axis-aligned; a blurred image scores low Laplacian variance and `is_processable` returns `(False, reason)`.
- [x] Implement; commit.
**Acceptance:** the quality gate rejects an obviously unusable fixture before any model call.

### Task P1.T3 — `ingest/` (storage, dedupe, ingest) `[backend]`
**Files:** Create `storage.py`, `dedupe.py`, `ingest.py`, matching tests.
**Produces (§14.1):** `StorageBackend` protocol + `LocalStorage`/`S3Storage`, `make_image_key`; `compute_phash`, `phash_distance`, `find_near_duplicate_image`, `find_semantic_duplicate`, `link_duplicate`; `ingest_file`, `ingest_bytes`, `expand_pdf`, `validate_upload`.
- [x] Tests: `LocalStorage` round-trips bytes; identical image -> phash distance 0; near-duplicate under threshold detected; PDF expands to one PNG per page; oversized/miswmimed upload rejected.
- [x] Implement; commit. (DB-backed dedupe queries are stubbed against an in-memory fake until Phase 3.)
**Acceptance:** tests pass with `StorageBackend=LocalStorage`.

### Task P1.T4 — `normalize/` (numbers, dates, text, `__init__`) `[algorithm]`
**Files:** Create `numbers.py`, `dates.py`, `text.py`, `__init__.py`, tests.
**Produces (§14.4):** `parse_money(convention)`, `detect_decimal_convention`, `quantize_money`; `parse_date -> (date|None, was_ambiguous)`, `parse_time`, `expand_two_digit_year`; `clean_text`, `normalize_merchant_name`, `normalize_currency`; top-level `normalize(raw) -> ReceiptExtraction` (pure copy).
- [x] Tests enforce the hard rules: `parse_money("O.50")` (letter O) -> `None`, not `0.50`; ambiguous `03/04/24` -> `(None, True)`; a null field in stays null out; currency resolves via explicit code -> merchant default -> system default -> `None` (never language-guessed).
- [x] **Review fix:** `detect_decimal_convention` takes `merchant_default_locale` as a prior; add a test for a comma-decimal (EU) receipt.
- [x] Implement; commit.
**Acceptance:** tests pass; `normalize` never invents a value.

### Task P1.T5 — `export/xlsx.py` (minimal) + M1 script `[backend]`
**Files:** Create `export/xlsx.py`, `tests/test_xlsx.py`; a temporary `scripts/m1_pipeline.py`.
**Produces:** `export_workbook(receipts, out_path)` producing the Receipts + LineItems sheets (§13.1-13.2); Needs-Review/Summary can be stubbed until Phase 3.
- [x] Test: exporting one known receipt yields a workbook whose cells match (open with openpyxl and assert).
- [x] M1 script: `load -> preprocess -> triage -> extract -> normalize -> export`, run against the golden set with the fake client (and optionally a real client behind an env flag).
- [x] Run `receipts eval` (P0.T2) to record baseline field accuracy; commit results.
**Acceptance:** M1 produces a workbook and a committed baseline eval result.

---

## Phase 2 — Validation & repair hardening (M2) `[algorithm polish]`

The rules and the repair loop exist. This phase wires them into the pipeline and fixes the review's algorithm issues. *(This line said "the 28 rules"; more have been added since and no count is written here now.)*

### Task P2.T1 — Consistency uses tolerance for money (review fix)

> **STATUS 2026-08-23 — NOT DONE. Filed as ISSUE-023.** `_vote` compares by exact
> string equality over `json.dumps(...)`, so `949.20` and `949.21` disagree and
> line items are compared by flattened index. Both bugs this task was written to
> fix are live. **Close it before P7.T1.**

**Files:** Modify `src/receipts/extract/extractor.py` (consistency diff) / `consistency` code; `tests/test_extractor.py`
- [ ] Failing test: two runs with totals `949.20` and `949.21` agree (within floor); `949.20` vs `945.20` disagree.
- [ ] Implement: numeric field agreement uses `within_tolerance`; reuse `align_line_items` (P0.T3) for line-item diffing. Commit.
**Acceptance:** consistency no longer flags cent-level rounding as disagreement, and no longer disputes all rows on a single count mismatch.

### Task P2.T2 — Resolve R060/R061 OCR-grounding gap (review fix — decision required)

> **STATUS 2026-08-23 — DECIDED, not yet built.** The user chose **(b), a cheap
> OCR pass, sequenced after Task 3** grows the golden set: option (a) was refused
> because a model's own transcription is not independent of its own misread, and
> R060's whole value is independence. Today `ctx.ocr_text` is written in two test
> files and nowhere else, so both rules are silently skipped on every real run —
> and `validator.py` makes a skipped rule indistinguishable from a passing one.
> The pass also yields the word-level boxes P5.T1's bbox highlighting needs.

**Problem:** grounding rules check the "raw OCR text layer," but the stack is VLM-only and nothing produces that layer.
- [ ] **Decision (needs user input):** (a) have the extraction model also return the verbatim text it read (add `meta.ocr_text`), (b) add a cheap OCR pass to populate `ctx.ocr_text`, or (c) drop R060/R061.
- [ ] Implement the chosen option with tests (if kept: total/merchant string found -> silent; absent -> WARN/INFO).
- [ ] Commit.
**Acceptance:** R060/R061 either have a real text source and tests, or are removed with their tests.

### Task P2.T3 — Tall-receipt line-count cross-check (spec §18 trap)

> **STATUS 2026-08-23 — NOT DONE. Filed as ISSUE-024.** Highest rule id is R070
> and both uses of `estimated_line_item_count` sit inside R013, which fires only
> when *zero* rows were extracted. Nothing compares the estimate against
> `len(line_items)` when rows are present, so spec §18's silent truncation is
> undetected.

**Files:** new rule in `src/receipts/validate/rules.py` (next free ID after R070, never renumber), `tests/test_rules.py`
- [ ] Failing test: triage `estimated_line_item_count = 12` but 6 extracted -> WARN.
- [ ] Implement `applies` (triage estimate present) + `check` (large mismatch -> WARN). Commit.
**Acceptance:** the silent tall-receipt truncation failure now raises a finding even when no subtotal is printed.

### Task P2.T4 — Confirm repair loop + best-attempt wired end-to-end

> **STATUS 2026-08-23 — acceptance NOT MET. Filed as ISSUE-025.** The worse-repair
> direction is pinned only in isolation (`tests/test_extractor.py`). The
> pipeline-level repair test exercises the repair *improving* the extraction, and
> no test under `process_receipt` drives a worse one — which is the exact
> direction this acceptance names.

- [ ] Test (fake client): a repair that returns a strictly worse attempt -> the original survives; every attempt is recorded. (Confirm existing coverage; extend if missing.) Commit.
**Acceptance:** best-attempt selection proven under the pipeline, not just in isolation.

---

## Phase 3 — Persistence, scoring & routing (M3) `[database][algorithm]`

### Task P3.T1 — SQLAlchemy ORM for the 7 tables `[database]`
**Files:** Create `src/receipts/persist/models.py`, `tests/test_models.py`
**Produces:** ORM classes for `merchants`, `receipts`, `line_items`, `extraction_runs`, `validation_findings`, `corrections`, `review_tasks` (§6), with `numeric(14,4)` money, enums, `numeric(4,3)` confidence, indexes `(merchant_id, txn_date)`, `(status)`, `(image_phash)`, `(merchant_id, txn_date, total)`, `line_items` cascade + **`unique(receipt_id, position)`** (review fix), `txn_date` naive + timestamps `timestamptz`.
- [x] Tests (SQLite): create all tables; cascade delete removes line items; money columns preserve `Decimal` precision.
- [x] Commit.

### Task P3.T2 — Alembic migrations `[database]`
**Files:** `alembic/` init + first migration.
- [x] Autogenerate + hand-verify the initial migration; test upgrade/downgrade on SQLite. Commit.

### Task P3.T3 — `persist/repository.py` `[database][backend]`
**Produces (§14.8):** `save_extraction`, `save_extraction_run` (**redact PAN before writing `raw_response`** — Global Constraint), `save_findings`, `get_receipt`, `query_receipts`, `apply_corrections` (writes one `corrections` row per changed path, sets `status='reviewed'`, transactional).
- [x] Tests: round-trip a receipt+lines+findings; `apply_corrections` writes correct correction rows and is atomic; a raw response containing a full PAN is stored with only last-4.
- [x] Commit.

### Task P3.T4 — `score/confidence.py` `[algorithm]`
**Files:** Create `src/receipts/score/confidence.py`, `tests/test_confidence.py`
**Produces (§12, §14.6):** `score_confidence(...) -> Decimal`, `explain_confidence(...) -> list[(reason, penalty)]`, `route(confidence, report) -> (status, priority, reason)`. All weights from `config/rules.yaml`.
- [x] Failing tests: a clean printed receipt scores >= 0.85 -> `auto_approved`; an unresolved ERROR + null total -> priority-0 `needs_review`; penalties clamp to `[0,1]` and round to 3 dp; `explain_confidence` returns the contributing reasons.
- [x] Implement additive penalty model from the §12 table; commit.
**Acceptance:** routing thresholds behave per §12; `explain_confidence` is UI-ready.

### Task P3.T5 — Dedupe wired to DB + review-queue claim (review fix) `[database]`
- [x] Point `find_*_duplicate` at the repository.
- [x] Implement `next_task` with `SELECT ... FOR UPDATE SKIP LOCKED` so two reviewers never claim the same task; test with two concurrent sessions. Commit.

### Task P3.T6 — Calibration `[algorithm]`

> **STATUS 2026-08-23 — machinery BUILT, acceptance NOT MET.** `receipts calibrate`
> exists and is wired. **No calibration report is committed and none can be**:
> the threshold must be chosen from a held-out split, and the golden set is three
> receipts. Blocked on P0.T1 / ISSUE-001 step 7.

- [ ] Implement `receipts calibrate` using `calibration_curve` (P0.T2) over the held-out set; print the precision/throughput curve; set `AUTO_APPROVE_THRESHOLD` to the lowest threshold holding precision >= target. Commit results.
**Acceptance:** calibration report committed; threshold chosen from data (with the sample-size caveat noted).

### Task P3.T7 — Complete the XLSX workbook (all four sheets, §13) `[backend]`
**Files:** Modify `src/receipts/export/xlsx.py`; `tests/test_xlsx.py`
- [x] Add the `Needs Review` sheet (§13.3, driven by `status`/priority) and the `Summary` sheet (§13.4), plus the §13.5 formatting requirements (number formats, hyperlinks to source images, frozen headers).
- [x] Tests: a mixed batch produces all four sheets; a `needs_review` receipt appears on the Needs-Review sheet; Summary totals reconcile.
- [x] Commit.
**Acceptance:** `GET /export/xlsx` streams a workbook with all four correctly formatted sheets.

---

## Phase 4 — Service: API, worker, config, security (backend)

### Task P4.T1 — `config/settings.py` `[backend]`
- [x] `pydantic-settings` reading every env var in §17; test that missing required vars fail fast and no secret has a default. Commit.

### Task P4.T2 — Auth layer (review fix — security) `[backend]`
**Problem:** §14.9 exposes upload/export/patch with no authentication; the service handles financial PII.
- [x] **Decision (needs user input):** API-key, session, or OIDC. Default recommendation: session auth + role checks (`reviewer`, `admin`), API key for machine upload.
- [x] Implement auth dependency + role checks; tests assert every non-`/health` route returns 401 without credentials and 403 for insufficient role. Commit.
**Acceptance:** no financial-data route is reachable unauthenticated.

### Task P4.T3 — `review/queue.py` + `review/api.py` (FastAPI) `[backend]`
**Produces (§14.9):** routes `POST /upload`, `GET /receipts`, `GET /receipts/{id}`, `PATCH /receipts/{id}`, `GET /receipts/{id}/image` (signed URL), `GET /review/next`, `POST /review/{id}/complete`, `GET /export/xlsx`, `GET /health`, `GET /metrics`; queue fns `enqueue_review`, `next_task`, `close_task`, `queue_stats`.
- [x] Tests (httpx + pytest-asyncio): upload creates a job; PATCH applies corrections and writes to `corrections`; endpoints enforce auth (P4.T2). Commit.

### Task P4.T4 — Worker + `pipeline.process_receipt` `[backend]`
- [x] Implement `process_receipt` wrapping every stage; any exception -> `needs_review` with stage name (no silent drops). Add **global VLM concurrency cap + per-run cost guard** (review fix).
- [x] Wire RQ worker to call only `process_receipt`. Test: an injected stage failure yields `needs_review` with the correct reason, never a lost job. Commit.

### Task P4.T5 — `cli.py` `[backend]`
- [x] Implement `receipts ingest|process|export|eval|calibrate|merchants|reprocess` (§14.10). Smoke-test each subcommand. Commit.

### Task P4.T6 — Wire `receipts eval`/`calibrate` to the CLI `[backend]`
- [x] Connect P0.T2/P3.T6 to the CLI; test end-to-end on the golden set with the fake client. Commit.

---

## Phase 5 — Frontend: review UI (M4) `[frontend]`

The screen where the ongoing cost of the system lives. Optimise for time-per-receipt (< 60s per correction).

### Task P5.T0 — Choose the frontend stack (decision required)
**The spec names no frontend framework** (only "FastAPI ... review UI backend").
- [x] **Decision (needs user input):** options — (a) React + Vite SPA (richest bbox/image UX), (b) Next.js (SSR + API co-location), (c) server-rendered Jinja + HTMX (smallest footprint, no build step). Recommendation: React + Vite for the image/bbox interaction and keyboard flow.
- [x] Scaffold `frontend/` for the chosen stack; wire to the API base URL + auth. Commit.

### Task P5.T1 — Review screen `[frontend]`

> **STATUS 2026-08-23 — BUILT except bounding boxes.** The screen, the editable
> fields, the keyboard flow, `explain_confidence` and the `corrections` write all
> ship. **Bbox highlighting was never built** and is gated on P2.T2: nothing
> produces a text layer with coordinates. The `<60s` acceptance is pinned tighter
> than it asks — `review.spec.ts` rejects 60s as non-discriminating (a scripted
> run takes about two seconds) and pins 10s, while saying plainly that it claims
> nothing about a human reviewer. **No human trial has ever been run.**

- [ ] Image pane on the left with **bounding-box highlighting** from `line_items[].bbox`; editable fields on the right; keyboard-first (Tab between fields, Enter to approve).
- [ ] Show the confidence explanation from `explain_confidence` so the reviewer sees *why* it was flagged.
- [ ] On approve/edit, `PATCH /receipts/{id}` -> writes to `corrections`.
- [ ] Test (component + e2e via Playwright): editing a field and approving persists and advances to the next task; measure a scripted correction completes under 60s.
- [ ] Commit.
**Acceptance:** a full correction in under 60 seconds; every edit lands in `corrections`.

### Task P5.T2 — Upload, list, queue, export pages `[frontend]`

> **STATUS 2026-08-23 — three of four. Filed as ISSUE-026.** The receipts list,
> the review queue and the export trigger all ship (ADR-0046). **There is no
> upload UI**: no component exists and `main.tsx` mounts none. `POST /upload` is
> complete, guarded and size-bounded, so today a receipt enters only through a
> shell. The user ruled 2026-08-23 that the screen **gets built**, as part of a
> wider UI/UX pass.

- [ ] Upload (drag-drop, progress); receipts list with status/confidence filters; review queue ordered by priority; export trigger hitting `GET /export/xlsx`.
- [ ] Tests + commit.

---

## Phase 6 — Merchant registry & few-shot (M5) `[backend][algorithm]`

### Task P6.T1 — `merchants/fingerprint.py` + `registry.py`

> **STATUS 2026-08-23 — BUILT (ADR-0043), acceptance NOT MET.** There is no
> `fingerprint.py` and that is a recorded decision, not an omission —
> `normalize_merchant_name` already existed. **The before/after top-10-merchant
> accuracy has never been measured**, because that needs a golden set; and
> `few_shots_for` is built, tested and deliberately never called.

**Produces (§14.7):** `fingerprint`, `match_merchant`, `name_similarity`; `get_or_create_merchant`, `add_name_variant`, `get_hints`/`set_hints`, `get_few_shots(limit=2)` (verified: `status='reviewed'` AND zero corrections), `suggest_hints` (from corrections; human-approved, never auto-applied).
- [x] Tests: exact `tax_id` match wins; fuzzy name match above threshold; few-shot selection returns only verified extractions; hints end with "trust the image" when injected.
- [x] Wire few-shot injection into `build_extraction_prompt` with **images ordered few-shot-first, target-last** (Global Constraint). Commit.
**Acceptance:** measure top-10-merchant accuracy before/after few-shot on the golden set.

---

## Phase 7 — Self-consistency & handwriting tuning (M6) `[algorithm]`

### Task P7.T1 — Enable consistency in the pipeline for handwritten/low-legibility

> **STATUS 2026-08-23 — NOT DONE.** `run_consistency` lives in
> `extract/extractor.py` with **zero callers**. Gate on `triage.is_handwritten`,
> never `document_type`. **Close ISSUE-023 first** — wiring this in now would put
> two known defects onto a live path.

- [ ] Gate `run_consistency` on `triage.document_type == "handwritten_receipt"` or `legibility in {poor, fair}`; feed disputed fields into scoring (§12). Ensure the cache still refuses non-zero temperature.
- [ ] **Review fix option:** allow `n=5` for critical fields via config.
- [ ] Re-run `calibrate`; commit results.
**Acceptance:** handwritten auto-approval rate/precision recorded before and after.

---

## Phase 8 — Confidence calibration & algorithm polish `[algorithm]`

### Task P8.T1 — Fit confidence weights from data (review fix)

> **STATUS 2026-08-23 — NOT STARTED, blocked on P0.T1.**

- [ ] Once the `corrections` set is large enough, fit the penalty weights (or a logistic model) on labelled outcomes instead of hand-tuning; keep `explain_confidence` interpretable. Backtest against held-out data; update `config/rules.yaml`.
- [ ] Re-calibrate the threshold. Commit results.
**Acceptance:** calibrated weights beat the hand-tuned baseline on held-out precision at equal throughput.

### Task P8.T2 — Grow the calibration set toward statistical validity

> **STATUS 2026-08-23 — NOT STARTED, blocked on P0.T1.**

- [ ] Expand the held-out set (from `corrections`) until a >= 99% precision claim has an acceptable confidence interval; document the interval alongside the point estimate.

---

## Phase 9 — Cost reduction (M7, optional) `[algorithm][ops]`

### Task P9.T1 — Self-hosted model benchmark + optional LoRA

> **STATUS 2026-08-23 — NOT STARTED, blocked on P0.T1.** Note the ground has
> shifted since this was written: the 2026-08-14 ruling is **Ollama only, no
> hosted APIs**, so this is no longer a cost comparison against a hosted baseline.

- [ ] Benchmark an open model via `openai_compat` on the golden set; if within a couple of points of hosted, evaluate switching. With enough `corrections`, evaluate a LoRA fine-tune. Commit the comparison.

---

## Cross-cutting / polish backlog

- **Security & PII:** auth (P4.T2), PAN redaction on the write path (P3.T3), image + `raw_response` retention policy, encryption at rest, signed image URLs only.
- **Observability:** `structlog` one event per stage; `GET /metrics` (counts by status, auto-approval rate); cost/latency dashboards from `extraction_runs`.
- **Testing coverage:** `preprocess/`, `persist/`, API, and frontend all need suites (currently only the extract/validate core is covered).
- **Non-determinism discipline:** never assert exact model equality in integration tests; rely on the consistency mechanism.

---

## Per-area index (so nothing is missed)

**Frontend:** P5.T0 (stack decision), P5.T1 (review screen + bbox + keyboard + corrections), P5.T2 (upload/list/queue/export).

**Backend:** P0.T2 (eval harness), P1.T1-T3/T5 (preprocess, ingest, export, M1 wiring), P4.T1 (settings), P4.T2 (auth), P4.T3 (API/queue), P4.T4 (worker/pipeline + concurrency/cost guard), P4.T5-T6 (CLI), P6.T1 (merchant registry service side).

**Database:** P3.T1 (ORM, 7 tables, unique(receipt_id,position)), P3.T2 (Alembic), P3.T3 (repository + PAN redaction), P3.T5 (DB dedupe + FOR UPDATE SKIP LOCKED).

**Algorithm (build + polish):** P0.T3 (shared greedy alignment), P1.T4 (normalization), P2.T1 (consistency tolerance), P2.T2 (R060/R061 grounding decision), P2.T3 (tall-receipt cross-check), P2.T4 (best-attempt end-to-end), P3.T4 (confidence + routing), P3.T6/P8 (calibration + weight fitting), P7.T1 (self-consistency tuning).

**Data / eval:** P0.T1 (golden set), P0.T2 (harness), P8.T2 (grow calibration set).

**Ops / security:** P0.T4 (tooling + CI), P4.T2 (auth), cross-cutting backlog.

---

## Definition of done for v1 (spec §19 + review additions)

*(Ticked against the tree 2026-08-23. Two rows say plainly that they cannot be
ticked by inspection, because what they claim is a measurement nobody has taken
— that is the honest state, not an oversight.)*

- [ ] Golden set of >= 50 labelled receipts committed — **3 of 50** (P0.T1)
- [ ] `receipts ingest` handles JPEG, PNG, HEIC, PDF — **JPEG/PNG/HEIC yes;
      PDF no** (ISSUE-027). A PDF is accepted, stored and rowed, then fails
      every time at `preprocess`, because `expand_pdf` has no callers.
      *(This row was ticked in the 2026-08-23 audit and the tick was wrong;
      measured and corrected the same day.)*
- [ ] Every rule implemented and unit-tested + tall-receipt cross-check — the
      rules ship and are tested; **the cross-check does not exist** (P2.T3 /
      ISSUE-024). *(This row said "all 28 rules"; the count has moved and is not
      written down any more.)*
- [ ] Repair loop demonstrably improves golden-set accuracy — **unmeasurable
      today.** The loop ships and best-attempt selection is pinned, but
      "demonstrably improves" is a measurement over a golden set of three.
- [ ] Confidence threshold calibrated to >= 99% auto-approval precision (with a
      documented confidence interval) — blocked on the golden set (P3.T6 / P8).
- [x] Review UI allows a full correction in under 60 seconds — pinned at **10s**,
      tighter than asked, by a scripted run. **Never trialled with a human**, and
      the test says so.
- [x] Every correction writes to `corrections`
- [x] XLSX export produces all four sheets with correct formatting
- [x] `receipts eval` runs clean; results committed —
      `eval/results/2026-08-22-cloud-only/`, five repeats. **Read ISSUE-017
      before quoting the figure**: it is a spread across receipts, not repeats.
- [x] No receipt can reach a non-terminal state
- [x] No `float` anywhere in the money path
- [x] **(added) No financial-data API route is reachable unauthenticated**
- [ ] **(added) Consistency and eval share one line-item alignment strategy** —
      **they do not.** `align_line_items` has one consumer, `eval/metrics.py`
      (ISSUE-023).
- [x] **(added) Full PAN never persisted (last-4 only)**

---

## Open decisions requiring your input

**All four of the decisions this section was written to collect have been
taken.** It is kept as the record of what was chosen rather than deleted, and
the live list of what is still waiting on the user is
`docs/NEXT_SESSION_PROMPT.md` section 2g.

1. ~~**Frontend framework** (P5.T0)~~ — **React + Vite.** Built and shipped.
2. ~~**R060/R061 grounding** (P2.T2)~~ — **a cheap OCR pass, sequenced after the
   golden set grows** (2026-08-23). "Model returns the text it read" was refused:
   a model's own transcription is not independent of its own misread, and
   independence is the entire value of the check. See P2.T2's status note.
3. ~~**Auth model** (P4.T2)~~ — **session + roles**, with an API key for
   unattended upload. ADR-0012.
4. ~~**Provider**~~ — **Ollama only, no hosted APIs** (2026-08-14 ruling), which
   in practice means Ollama Cloud for anything that can read a receipt.
   `gemma4:cloud` produced the committed baseline. Note there are **two Ollama
   runtimes on the dev box** and the project reads the Docker one on `:11435`.
