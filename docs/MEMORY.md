# Agent Memory — Receipt Digitization System

Durable working memory for cross-session continuity. Read this first, then the
files in "Key references" below. Last updated: **2026-07-28**.

## Snapshot

- **`master` @ `9bd4cd0`** — **410 tests passing, ruff clean. No feature branch
  is open** (`feat/db-layer` is merged and can be deleted).
- Merged so far: Phase 0 foundations, Phase 1 offline modules, the online wiring
  (config, client factory, M1 pipeline, confidence scoring, one-command baseline
  runner), and **Phase 3 persistence** (7-table ORM + `docker-compose.yml`,
  Alembic migrations, repository layer, DB-backed dedupe, review queue, 4-sheet
  XLSX export).
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
- `ingest/`: storage, dedupe, ingest  ·  `export/`: xlsx (all four §13 sheets)
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

- **Phase 4 (service):** `review/api.py` (FastAPI) + **auth** (decision needed);
  `pipeline.process_receipt` (the full orchestrator that wraps every stage so a
  failure marks `needs_review` instead of losing the job) + the RQ worker, incl.
  a global VLM concurrency cap / cost guard; `cli.py`.
  (`review/queue.py` is already built.)
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

## The real receipt corpus (learned from the user's first 3 samples, 2026-07-28)

The user's actual documents are **Philippine BIR "SALES INVOICE" forms: a
machine-printed template with every value filled in by hand.** Three samples are
labelled in `eval/golden/labels/r001-r003.json` (Metro Oil Subic, Summit Fuel
OPC, Serv Central). Implications, all confirmed against the code:

- **They are `document_type=INVOICE` + `print_type=MIXED`, not `handwritten_receipt`.**
  `TriageResult.is_handwritten` already returns True for `MIXED`, so **gate
  self-consistency on `triage.is_handwritten`, never on `document_type`** (Phase 7).
- **The handwriting penalty must read triage too.** `score_confidence` currently
  reads only `receipt.meta.is_handwritten`; on these forms a model may report
  `False` (the template is printed) while triage says `MIXED`, so the −0.15 would
  be missed on exactly the receipts that need it. This promotes that deferred item
  to a real fix.
- **R020 FALSE-ERRORS ON 100% OF THESE RECEIPTS — see below.** Highest-priority
  open issue.
- **Blank pre-printed product rows.** Metro Oil's form pre-prints six fuel rows
  and only one is filled in; a VLM will likely emit all six. Needs a prompt
  instruction and/or a rule (sibling of R052) so empty template rows are dropped.
- **Buyer-vs-merchant trap.** Every form has `SOLD TO: Ideal Source` (the user's
  own company). `merchant.name` must be the ISSUER, never the buyer.
- **Printer-TIN trap.** The footer carries the *printing press's* TIN and
  accreditation (e.g. Midland Press `000-296-795-000`). `merchant.tax_id` must be
  the `VAT Reg. TIN` in the header.
- **Currency is never printed.** `normalize_currency` correctly refuses to guess,
  so **set `DEFAULT_CURRENCY=PHP`** or currency stays null.
- **Composition:** if this hybrid form is the whole corpus, the spec's §15 target
  mix (60% printed-clean / 20% handwritten) does not describe reality — the golden
  set should be dominated by this one type. Raise before scaling M0.
- Useful details: VAT is 12% and totals read `net + VAT = TOTAL AMOUNT DUE`;
  `Less: Withholding Tax` and the VATable / VAT-Exempt / Zero-Rated buckets appear
  on the forms but have no dedicated schema fields (withholding was blank on all
  three); merchant `VAT Reg. TIN` is printed, which is the strongest fingerprint
  for merchant matching (Phase 6).

### OPEN ISSUE — R020 vs VAT-inclusive line pricing

On these invoices the line-item **Amount column is VAT-INCLUSIVE**, so
`Σ line_total == total`, while `subtotal` is the net-of-VAT tax base. R020
(`Σ line_total ≈ subtotal`) therefore fails by exactly the VAT on all three
samples (verified: 1000 vs 892.86; 2000 vs 1785.71 ×2). R022 passes, so the
receipts are internally consistent — **the labels are right and the rule's
assumption is wrong.**

Consequences if unfixed: a false ERROR blocks auto-approval, burns a repair call,
costs −0.35 confidence, and hands the repair prompt a demand to reconcile numbers
that are already correct — pressuring the model to alter good values, which the
steering rules forbid.

Recommended fix (needs a decision; touches a stable rule ID): make R020/R024
**convention-aware** — add an explicit `prices_include_tax` flag the model reads
off the form (these say "Total Sales (VAT Inclusive)"), and when it is true (or
unknown) accept `Σ lines ≈ total` as well as `Σ lines ≈ subtotal`. Do **not**
widen the tolerance to paper over it. Never renumber R020.

## DEFERRED — do this LAST, after the system is built

**ISSUE-001: run the first real baseline.** Parked by the user on 2026-07-28 with
"I will do this after I build the system." Full diagnosis, the exact resume steps,
and what to expect are in **`docs/KNOWN_ISSUES.md`** — read that, do not
re-derive it.

One-line summary: everything needed is in place (labels, images, pipeline, scorer,
harness) and the three labels validate with zero findings, but
`python -m eval.run_baseline` has never completed. Two attempts failed — one to a
timeout bug (since fixed in `1f9f122`), one to the process being killed mid-run.
The open blocker is that `granite3.2-vision:2b` on CPU takes ~262s per call, so a
run is 30–60 min and dies to any interruption. **Recommended fix: point the
baseline at a hosted tool-capable model** (the commented-out Gemini block in
`.env`; rotate that key first, it was echoed in terminal output).

Until this is done there are **no real accuracy numbers**, and therefore no
threshold calibration (P3.T6 / P8.T1) and no way to judge a prompt or rule change.
Do not treat any precision claim as measured before it runs.

## Blockers that need the user

1. Label the golden set (M0) — required for a baseline and calibration.
2. Choose a tool-capable provider + supply the key.
3. Decisions: **auth model** (P4.T2), **frontend framework** (P5.T0),
   **R060/R061 OCR-grounding** approach (P2.T2).

## Deferred follow-ups / known minors (non-blocking)

- Move confidence penalty weights into `config/rules.yaml` (calibration, P3.T6).
- Consolidate the `0.85`/`0.60` thresholds (duplicated in `route()`, `Settings`,
  `eval.metrics`) onto `Settings` — do this while wiring Phase 4.
- `run_receipt` returns the raw-validated report but the normalized extraction
  (an ambiguous date is nulled), so a persisted score can carry a date-null
  penalty the stored report does not show — reconcile in `process_receipt`.
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
- **`docs/KNOWN_ISSUES.md`** — parked problems with their diagnosis and resume
  steps. ISSUE-001 (the baseline run) is the deferred final task.
- `docs/adr/` — implementation decisions (**0001–0010**; see `docs/adr/README.md`).
  0001 `Decimal` money path · 0002 provider abstraction/config · 0003 confidence
  penalties · 0004 portable persistence + Docker · 0005 tooling/offline tests ·
  0006 repository conventions · **0007 PAN redaction + money integrity (read
  before touching card/money writes)** · 0008 review-queue concurrency ·
  0009 lazy `persist` surface · 0010 export decoupling.
- `semantic-review/` — the whole-branch review write-ups (untracked). The
  `2026-07-28-…-feat-db-layer` one documents the PAN/NaN findings in detail.
- `.kiro/steering/receipt-system.md` — always-on load-bearing rules.
- `.superpowers/sdd/progress.md` — the running task ledger.
