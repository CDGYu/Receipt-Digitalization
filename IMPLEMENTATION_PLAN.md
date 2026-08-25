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
- **Tests:** `python -m pytest` (pyproject sets `pythonpath=src`, `testpaths=tests`). **No count here — run it.** *(This read "Baseline: 103 passing" from the file's first commit until 2026-08-24, and was missed by the 2026-08-23 sweep that closed the same rot under **Current state** and again on Phase 0's acceptance line — in the block that says it binds every task.)*

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
the golden set (P0.T1 — three receipts of a documented 50), bounding-box
highlighting (P5.T1, gated on P2.T2), **two of P5.T2's four items — upload
drag-and-drop and the receipts list's status/confidence filters**,
self-consistency wiring (P7.T1), and all of Phases 8 and 9.

*(P2.T1, P2.T3 and P2.T4 stood in that list until 2026-08-25, when all three
were built at `aa65a2b`. **The `P5.T2 / ISSUE-026` entry said "the upload
screen" and that was wrong in both directions**, which is why it was flagged as
suspect rather than deleted and then derived on 2026-08-25: the upload screen
IS built and mounted, so ISSUE-026 is genuinely closed — and P5.T2 is still
unmet on two items nobody was tracking, because the entry named the wrong
thing. See its status note.)*

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
>
> **Done as of `19c3b22`, and "the hundreds" was optimistic.** The interval is
> now computed and printed on every run. Measured at *perfect* precision:
> 300-of-300 still gives [98.74%, 100%] and does not clear 99%; roughly a
> thousand does. **And the `corrections` table has supplied nothing so far —
> zero rows, counted 2026-08-25** — because it fills only when a reviewer
> corrects a real receipt, which needs P0.T1 first.

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

> **The property holds as of `aa65a2b`; the second name does not exist.**
> `consistency.diff_extractions` appears nowhere in code -- only in this line
> and `RECEIPT_SYSTEM_SPEC.md:1256`. The consistency-side consumer that was
> actually built is `_vote` in `src/receipts/extract/extractor.py`, which P2.T1's
> own Files line calls "(consistency diff)".
>
> Left as written rather than re-pointed at `_vote`: an acceptance line is the
> record of what was asked for, and this one asked for a module nobody built.
> **Calling the acceptance "fully met" would retire it by pointing at a symbol
> that is not there** -- which is what a first draft of ISSUE-023's resolution
> did say, and it was narrowed on review before it landed.

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

> **STATUS 2026-08-25 — DONE at `aa65a2b`.** Money agrees through
> `within_tolerance`, and line items are matched by description through
> `align_line_items` against the longest run. Both mechanisms proven red by
> mutation. *(This read NOT DONE from 2026-08-23: `_vote` compared by exact
> string equality over `json.dumps(...)`, so `949.20` and `949.21` disagreed and
> line items were compared by flattened index.)*
>
> **P0.T3's acceptance is now fully met**, having been half-met since: it named
> two consumers of `align_line_items` — `line_item_f1` and the consistency diff
> — and only the first existed.

**Files:** Modify `src/receipts/extract/extractor.py` (consistency diff) / `consistency` code; `tests/test_extractor.py`
- [x] Failing test: two runs whose totals differ by one cent agree; a difference
      beyond the floor still disputes. *(Driven at `224.00`/`224.01` against
      `224.50` rather than the `949.20`/`945.20` written here — the same two
      directions on the fixture this module already has.)*
- [x] Implement: numeric field agreement uses `within_tolerance`; `align_line_items`
      (P0.T3) does the line-item diffing. Commit.
**Acceptance:** consistency no longer flags cent-level rounding as disagreement, and no longer disputes all rows on a single count mismatch.

### Task P2.T2 — Resolve R060/R061 OCR-grounding gap (review fix — decision required)

> **STATUS 2026-08-25 — DONE.** `OCR_GROUNDING_ENABLED` runs a second reader over
> the same pixels the model was shown and puts what it read on
> `ctx.ocr_text`, which is the source R060 and R061 were written against.
> Built ahead of the recorded sequencing on the owner's instruction: waiting on
> Task 3 gates *validating* the benefit, not building the plumbing.
>
> *(This block read "DECIDED, not yet built" from 2026-08-23, above a first
> checkbox that still said "needs user input" — a box contradicting the status
> directly above it, which is how the task read as undecided for two days when
> it was not. The box is ticked below with what was decided.)*

**Problem:** grounding rules check the "raw OCR text layer," but the stack is VLM-only and nothing produces that layer.
- [x] **Decision — taken 2026-08-23:** **(b), a cheap OCR pass.** (a) was refused
      because a model's own transcription is not independent of its own misread,
      and R060's whole value is that a *second* reader disagrees. (c) was not taken.
- [x] Implement the chosen option with tests. `rapidocr-onnxruntime` behind a new
      optional `ocr` extra, imported inside the function that uses it;
      `OCR_GROUNDING_ENABLED` defaults **off**, and the flag gates an injected
      reader too, so "off" is observable rather than indistinguishable from
      "grounded". Both directions pinned: a layer without the total makes R060
      fire, a layer with it leaves R060 silent.
- [x] Commit.
**Acceptance:** R060/R061 either have a real text source and tests, or are removed with their tests.

> **Measured while building, and worth more than the feature.** The engine reads
> `SUPERMART INC.` as `SUPERMARTTNC` on a clean rendered fixture — so R060
> grounds the total correctly and **R061 fires a false INFO on the merchant**,
> because its token-overlap comparison has no tolerance for a character error.
> That is R061's existing design meeting a real reader for the first time, and it
> is why the tests assert on digits rather than on a string.
>
> **The eval path is NOT grounded, and that is stated rather than left to be
> found.** `run_receipt` takes no settings, so `build_eval_pipeline` cannot turn
> the pass on; only `process_receipt` grounds. It is the same shape as ISSUE-034
> — a capability production has and eval does not — and adding an unread seam to
> `run_receipt` to pretend otherwise would be the unread-prop mistake this repo
> has already paid for once.
>
> **Word-level boxes are produced and nothing reads them yet.** `OcrLayer.words`
> carries normalised 0-1 boxes matching `LineItem.bbox`'s declared convention,
> which is what P5.T1's highlighting needs. Running OCR twice to get them
> separately would be the expensive mistake; they cost nothing here.

### Task P2.T3 — Tall-receipt line-count cross-check (spec §18 trap)

> **STATUS 2026-08-25 — DONE at `aa65a2b`.** R071 compares the triage estimate
> against `len(line_items)` and raises WARN when at most half survived and at
> least three rows are missing. *(This read NOT DONE from 2026-08-23, when both
> uses of `estimated_line_item_count` sat inside R013, which fires only when
> ZERO rows were extracted.)*
>
> **"Large" was the decision this task left open, and its blind spot is written
> into the rule:** 4 estimated against 2 extracted is half a receipt lost and
> does not fire. A test pins that, so lowering the floor is a decision rather
> than a tweak.

**Files:** new rule in `src/receipts/validate/rules.py` (next free ID after R070, never renumber), `tests/test_rules.py`
- [x] Failing test: the estimate against half as many extracted rows -> WARN, on
      the same boundary as the `12`/`6` written here.
- [x] Implement `applies` (triage estimate present, rows present) + `check`
      (large shortfall -> WARN). Commit.
**Acceptance:** the silent tall-receipt truncation failure now raises a finding even when no subtotal is printed.

### Task P2.T4 — Confirm repair loop + best-attempt wired end-to-end

> **STATUS 2026-08-25 — acceptance MET at `aa65a2b`.**
> `test_the_pipeline_keeps_the_best_attempt_when_the_repair_is_worse` drives a
> strictly worse repair through `process_receipt` and asserts the PERSISTED row
> carries the extract's values. Proven red by mutating the selection where it
> happens — `min(attempts, key=rank)` in `extract_with_repair` — not where the
> test states its expectation (ADR-0051).
>
> It also asserts the repair was attempted at all. Without that it passes on a
> pipeline that never repairs, where the extract's values survive for a reason
> that has nothing to do with selection.

- [x] Test (fake client): a repair that returns a strictly worse attempt -> the original survives; every attempt is recorded. Commit.
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
  > **HALF BUILT, and the halves fail for different reasons — audited
  > 2026-08-25.** The command exists: `cmd_calibrate` (`cli.py`), registered as
  > `calibrate` and dispatched, printing threshold / auto-approve rate /
  > precision from `calibration_curve` and recommending the lowest threshold
  > that reaches `--target`. **It recommends; it does not set.** And "over the
  > held-out set … commit results" needs a real eval run, which the box at
  > P8.T1 already records as impossible here (ADR-0039). *(The handoff pair
  > listed this as one of three boxes for work that is built. That reading
  > came from the symbol existing. The box asks for a number to be chosen from
  > data and written down, and no such number exists.)*
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
>
> **Four of the five boxes ticked 2026-08-25**, re-derived rather than taken
> from the notes below them: `serializers.py:287` -> `ReviewScreen.tsx:567`
> for the rail, `repository.py:1540` plus `test_api_write.py:348` for the
> `corrections` write, and `review.spec.ts`'s own assertions for the test box.
> The bbox box stays open, and a presence-grep is why it is not a close call:
> the only `bbox` in `src/review/` is a comment saying it is **absent**.

- [ ] Image pane on the left with **bounding-box highlighting** from `line_items[].bbox`; editable fields on the right; keyboard-first (Tab between fields, Enter to approve).
  > **THREE OF FOUR CLAUSES ARE BUILT; the highlighting is the only one that is
  > not — audited 2026-08-25.** `ImagePane` is mounted in `ReviewScreen`;
  > fields are editable through `LineItemsTable`; keyboard-first is deliberate
  > and *deviates from this box*: Tab order is native and plain Enter is left
  > to the browser, with **Ctrl/Cmd+Enter** to approve, because a bare Enter
  > moving focus through a form must keep working. That deviation is reasoned
  > at the call site and is better than what this box asks for.
  > **The highlighting is blocked on a step that appears in no plan.** A text
  > layer now exists (`preprocess/ocr.py`, P2.T2, `3b023a4`) and its `OcrWord`s
  > carry 0-1 boxes matching `LineItem.bbox`'s convention deliberately — but
  > `OcrLayer.words` has **zero consumers**, `_ground_in_ocr` keeps
  > `layer.text` and drops the geometry, and **nothing maps a word box onto a
  > line item.** `bbox` is omitted from the frontend types on purpose. There
  > are also **0 rows in `line_items`** to build against, and the model that
  > runs here does not ground. Whoever takes this: it is a design step and then
  > a feature, not the one-task green light the handoff called it.
- [x] Show the confidence explanation from `explain_confidence` so the reviewer sees *why* it was flagged.
  > **BUILT — audited 2026-08-25.** `ConfidenceRail` renders `confidence` and
  > `confidence_reasons`, mounted in `ReviewScreen`.
- [x] On approve/edit, `PATCH /receipts/{id}` -> writes to `corrections`.
  > **BUILT — audited 2026-08-25.** `@app.patch("/receipts/{receipt_id}")` in
  > `review/api.py`. *(Note the standing tension: **`corrections` is empty**,
  > which P8.T1 and P9.T1 are blocked on. The route exists; nobody has used
  > it.)*
- [x] Test (component + e2e via Playwright): editing a field and approving persists and advances to the next task; measure a scripted correction completes under 60s.
  > **BUILT, and it tightened this box rather than meeting it — audited
  > 2026-08-25.** `frontend/e2e/review.spec.ts`: "a reviewer corrects a receipt
  > and the correction is persisted". It asserts **under 10s, not 60**, with
  > the reason written down: a scripted run does it in about two seconds, so
  > **60s would pass even if the screen had become unusably slow**. The
  > acceptance line below still says 60 seconds; that is the number for a
  > *human*, and the two should not be conflated.
- [x] Commit.
  > **Done for everything above that is built.**
**Acceptance:** a full correction in under 60 seconds; every edit lands in `corrections`.
  > **Unmet, and not for want of code — audited 2026-08-25.** "A full correction
  > in under 60 seconds" is a claim about **a human**, and no human trial has
  > ever been run (see the note above this task). "Every edit lands in
  > `corrections`" is untested against reality because **`corrections` has zero
  > rows.** Both halves need a person, not a commit.

### Task P5.T2 — Upload, list, queue, export pages `[frontend]`

> **STATUS 2026-08-25 (later) — DONE. All four.** The two below marked NOT built
> were built at `dc31af7`, and **neither of the "deliberately" notes forbade it**
> once read rather than summarised: the drop-zone note refused a box that *looks*
> droppable **and is not**, which handlers satisfy rather than overrule, and the
> filters note said "ruled out of **v1**" — a scope call whose load-bearing
> clause is *rows are not clickable*, which filters do not touch. The table below
> is kept as the record of how the gap was found.
>
> **STATUS 2026-08-25 — two of four, and NOT the two this row used to name.**
> Each item derived against the tree rather than inferred from ISSUE-026 being
> closed:
>
> | item | state | evidence |
> |---|---|---|
> | upload drag-and-drop | **NOT built, deliberately** | the only two matches for `drag` under `frontend/src` are comments; `UploadScreen.module.css` records the decision — "nothing here handles a drag, and a box that looks droppable and is not is a worse lie than a plain one" |
> | upload progress | built | `ProcessingView`, mounted in place by `UploadScreen` |
> | list status/confidence filters | **NOT built** | no control and no query param; `ReceiptsScreen.tsx` says so itself — "No filters, no sorting, no column choice" |
> | queue ordered by priority | built | `order_by(ReviewTask.priority, ReviewTask.opened_at, ReviewTask.id)`, `review/queue.py:92` and `:466` |
> | export trigger | built | `requestBlob('/export/xlsx')`, `frontend/src/api/receipts.ts:40` |
>
> **ISSUE-026 is closed and this task is not, and those were being confused.**
> The issue's claim was that no upload component existed and `main.tsx` mounted
> none; `main.tsx:151` mounts `<UploadScreen />`, so it is genuinely resolved.
> This task asks for four things and two of them have never been built.
>
> *(The earlier version of this note read "three of four" and named the upload
> screen as the missing one. That was true on 2026-08-23. What made it hard to
> correct is that the screen landing looked like the whole row landing.)*
>
> **Drag-and-drop is a decision, not a gap to fill silently.** Adding it means
> overturning a recorded refusal to make the chooser look droppable, and it
> needs the drop handler, not just the styling that was withheld.

- [x] Upload **drag-drop** — `dc31af7`. Handlers on the `<label>` that already
      wraps the input, feeding the **same `offer`** the picker uses.
      `onDragOver` calls `preventDefault`, without which the browser navigates
      to the dragged file and the drop handler never runs.
- [x] Upload **progress** — `ProcessingView`, replacing the chooser in place.
- [x] Receipts list with **status/confidence filters** — `dc31af7`. Server-side,
      through `GET /export/receipts`' existing `status` and `min_confidence`
      params; no backend change was needed. An unchosen filter is omitted, not
      sent empty.
- [x] Review queue **ordered by priority** — `review/queue.py:92`, `:466`.
- [x] Export trigger hitting `GET /export/xlsx` — `api/receipts.ts:40`.
- [x] Tests + commit — `dc31af7`. Ten tests: six on the filters (including that
      "Load more" keeps them, and that clearing one drops it from the query
      rather than sending it empty) and four on the drop (including that
      `dragover` is prevented, which nothing else on the screen can show).

*(One checkbox held all four items until 2026-08-25. It could not be ticked
while any item was missing and could not show which, so the two that shipped
and the two that never did were indistinguishable from outside.)*

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

> **STATUS 2026-08-25 — WIRED, default OFF. Acceptance NOT met.** `b3bc14e`.
> ISSUE-023 closed at `aa65a2b`, so the "two known defects on a live path"
> blocker is discharged: `_vote` now compares money through `within_tolerance`
> and line items through `align_line_items`.
>
> **The gate is `consistency_enabled` AND the receipt**, and neither half is
> sufficient — flag alone makes every printed receipt pay for a pass aimed at
> handwriting; receipt alone starts spending on every deployment that upgrades.
> Both proven red by mutation.
>
> **Two corrections to the boxes below, kept rather than silently satisfied.**
> The first box spells the trigger `document_type == "handwritten_receipt"`; the
> STATUS note it replaced said `is_handwritten`, **never** `document_type`. Those
> are not in conflict — `is_handwritten` is a property covering `document_type is
> HANDWRITTEN_RECEIPT` **or** `print_type in (HANDWRITTEN, MIXED)` — so the
> checkbox was strictly narrower and missed a hand-annotated thermal receipt.
> And the note dropped the *legibility* half that this task's own title carries;
> both are implemented, with `UNREADABLE` excluded deliberately.

- [x] Gate `run_consistency` on the receipt — `is_handwritten` **or** `legibility in {poor, fair}`, `UNREADABLE` excluded — and feed disputed fields into scoring (§12). `b3bc14e`. **The cache clause was already true and already pinned** (`test_cache_only_stores_deterministic_calls`); the layer above it was not, and `run_consistency`'s "never cache these calls" promise is now pinned on the argument, proven red by threading a `ResponseCache` in.
- [ ] **Review fix option:** allow `n=5` for critical fields via config. **Not built, and `consistency_runs` is not it.** That setting takes the whole pass to `n=5`; this box asks for a *different* `n` on critical fields, which is a per-field policy nothing here expresses.
- [ ] Re-run `calibrate`; commit results. **Cannot be done on this box.** It needs a real model run, and ADR-0039 measures ~1896s/receipt CPU-only against a three-receipt golden set.

**Acceptance:** handwritten auto-approval rate/precision recorded before and after. **NOT MET, and it is the reason the flag defaults OFF.** Nobody has measured whether this improves precision. ISSUE-034's hermetic ruling means the eval path measures a different prompt than production sends, so the before/after would need that settled first, and ISSUE-001 step 7 needs the golden set to be more than three handwritten receipts before the number would mean anything.

---

## Phase 8 — Confidence calibration & algorithm polish `[algorithm]`

### Task P8.T1 — Fit confidence weights from data (review fix)

> **STATUS 2026-08-25 — NOT STARTED, and the blocker is measured rather than
> assumed: `corrections` has ZERO rows.** Counted against the local
> `receipts.db` on 2026-08-25: `corrections` 0, `extraction_runs` 0, `receipts`
> 1. There are no labelled outcomes to fit weights on — not few, none. A
> logistic model over an empty table is not a smaller version of this task.
>
> **No code removes this.** It is P0.T1 (the golden set, 3 of 50) plus reviewers
> actually correcting receipts, and the `corrections` table fills only when a
> human uses the review screen on real data.

- [ ] Once the `corrections` set is large enough, fit the penalty weights (or a logistic model) on labelled outcomes instead of hand-tuning; keep `explain_confidence` interpretable. Backtest against held-out data; update `config/rules.yaml`.
- [ ] Re-calibrate the threshold. Commit results.
**Acceptance:** calibrated weights beat the hand-tuned baseline on held-out precision at equal throughput.

### Task P8.T2 — Grow the calibration set toward statistical validity

> **STATUS 2026-08-25 — the second clause is DONE (`19c3b22`); the first is
> blocked on data that does not exist.** `corrections` has **zero rows**, so
> the set cannot be "expanded" by code. But "document the interval alongside the
> point estimate" needed no new data and was never done, so every report printed
> a bare percentage against a criterion that is a claim about evidence.
>
> **Measured at perfect precision, which is what makes this worth having:**
>
> | sample | precision | 95% Wilson CI | supports >= 99%? |
> |---|---|---|---|
> | **3 of 3** (today) | 100.00% | **[43.85%, 100%]** | no |
> | 100 of 100 | 100.00% | [96.30%, 100%] | no |
> | 300 of 300 | 100.00% | [98.74%, 100%] | no |
> | 1000 of 1000 | 100.00% | [99.62%, 100%] | **yes** |
>
> **So the spec's >= 99% criterion needs on the order of a THOUSAND clean
> receipts, not the 50 P0.T1 asks for.** That is the finding: 50 closes P0.T1
> and still cannot validate the headline number. Recorded here rather than
> quietly, because it re-scopes what "done" means for the acceptance criteria.

- [x] Document the interval alongside the point estimate — `19c3b22`. Wilson, not the normal approximation, which on 3-of-3 gives `1.0 +/- 1.96*sqrt(0/3)` = **[100%, 100%]** and would make a perfect run look like the criterion was met. Printed by `format_report` and committed in the results JSON.
- [ ] Expand the held-out set (from `corrections`) until a >= 99% precision claim has an acceptable confidence interval. **Blocked: `corrections` is empty and no code fills it** — it needs reviewers correcting real receipts.

---

## Phase 9 — Cost reduction (M7, optional) `[algorithm][ops]`

### Task P9.T1 — Self-hosted model benchmark + optional LoRA

> **STATUS 2026-08-25 — NOT STARTED, and BOTH of its halves are blocked, each
> for its own reason.** Note first that the ground shifted: the 2026-08-14
> ruling is **Ollama only, no hosted APIs**, so this is no longer a cost
> comparison against a hosted baseline — the box's "if within a couple of points
> of hosted" compares against a thing this project no longer has.
>
> **The benchmark half** needs the golden set: **3 of 50** (P0.T1), and a run
> costs ~1896s/receipt CPU-only on this box (ADR-0039). A comparison over three
> handwritten receipts would produce a number whose interval is [43.85%, 100%]
> — see P8.T2 — which cannot separate two models.
>
> **The LoRA half** says "with enough `corrections`": measured 2026-08-25, that
> table has **zero rows**.
>
> Neither is a code task today. Both are P0.T1 and a person with a camera.

- [ ] Benchmark an open model via `openai_compat` on the golden set. **Blocked on P0.T1 (3 of 50) and on the hosted baseline this comparison was written against no longer existing.**
- [ ] With enough `corrections`, evaluate a LoRA fine-tune. Commit the comparison. **Blocked: `corrections` has zero rows.**

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

- [ ] Golden set of >= 50 labelled receipts committed — **3 of 50** (P0.T1).
      **50 closes this box and still cannot validate the >= 99% precision
      criterion below.** Measured 2026-08-25 (P8.T2): at *perfect* precision the
      95% interval is [43.85%, 100%] on 3 receipts, [96.30%, 100%] on 100, and
      does not clear 99% until roughly a thousand. These two rows are a
      collection target and an evidence threshold, and they are two different
      numbers — ticking the first does not earn the second.
- [x] `receipts ingest` handles JPEG, PNG, HEIC, PDF — **all four, as of
      2026-08-25** at `55f9847`. A PDF becomes one receipt per page.
      *(This row was ticked in the 2026-08-23 audit and the tick was wrong --
      a PDF was accepted, stored and rowed, then failed every time at
      `preprocess`, because `expand_pdf` had no callers. It was measured and
      un-ticked the same day, and stayed un-ticked until the code caught up
      with it. This is the tick the audit should have been able to make.)*
- [x] Every rule implemented and unit-tested + tall-receipt cross-check — the
      cross-check is R071, added 2026-08-25 at `aa65a2b`. *(This row said "all 28
      rules"; the count has moved and is not written down here on purpose. It is
      asserted in `tests/test_rules.py`, which is where a count can be kept
      honest.)*
- [ ] Repair loop demonstrably improves golden-set accuracy — **unmeasurable
      today.** The loop ships and best-attempt selection is pinned, but
      "demonstrably improves" is a measurement over a golden set of three.
- [ ] Confidence threshold calibrated to >= 99% auto-approval precision (with a
      documented confidence interval) — blocked on the golden set (P3.T6 / P8).
      **The "documented confidence interval" half is DONE** at `19c3b22`: every
      report now prints the 95% Wilson interval beside the rate and commits it
      to the results JSON. **The calibration half is blocked on evidence, and
      the size needed is now known** — roughly a thousand clean receipts, not
      the 50 P0.T1 collects. Measured, at perfect precision: 3 receipts give
      [43.85%, 100%] and 300 give [98.74%, 100%].
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
- [x] **(added) Consistency and eval share one line-item alignment strategy** —
      as of `aa65a2b` they do. `align_line_items` has **two** call sites,
      derived rather than counted from memory: `eval/metrics.py:278` and
      `src/receipts/extract/extractor.py:486`, inside `_vote`.
      *(This row read "they do not", named one consumer, and cited ISSUE-023 as
      open. `aa65a2b` falsified all three parts at once and the row did not
      move -- it was found by the session that pasted ISSUE-023's resolution,
      not by the one that wrote the commit. A definition-of-done row is exactly
      the kind that goes stale green.)*
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
