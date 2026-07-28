# Next-Session Kickoff Prompt

Paste the block between the `---` markers as the first message of the next
session, and **fill in the "Today's goal" line** (it is the one thing the prompt
cannot infer — a placeholder left in place costs a round trip).

---

You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first (in order), then confirm the state back to me:**
1. `docs/MEMORY.md` — current state, decisions already made, what's built/not
   built, environment, blockers, deferred items, and the workflow.
2. `.superpowers/sdd/progress.md` — the running task ledger (newest entries at
   the bottom are the live status).
3. `docs/adr/README.md`, then the ADRs it indexes (**0001–0011**). Mandatory
   before touching the matching area:
   - **0001** `Decimal` money path — anything that touches money.
   - **0007** PAN redaction + money integrity — anything that writes card data.
   - **0006** repository conventions (injected session, **caller commits**,
     `ValueError` boundary) — anything that writes to the DB.
   - **0011** terminal-state contract + VLM concurrency/cost guards — anything
     touching `process_receipt`, the worker, or model-call limits.
   - **0002** provider abstraction — anything touching clients/config.
   - **0008** review-queue concurrency — anything touching `review/queue.py`.
4. `.kiro/steering/receipt-system.md` — the load-bearing rules (also auto-loaded).
5. `IMPLEMENTATION_PLAN.md` — the authoritative phased task list.
6. `docs/KNOWN_ISSUES.md` — ISSUE-001 (the deferred baseline run), with its full
   diagnosis and exact resume steps. **Do not re-derive it.**
7. `RECEIPT_SYSTEM_SPEC.md` as needed — §6 data model, §8.5 repair, §9
   normalization, §10 validation/tolerance, §12 confidence + routing, §13 Excel,
   §14 function inventory (**§14.8** repository, **§14.9** review API, **§14.10**
   pipeline/CLI), §15 milestones, §16 eval, §17 config, §18 traps, §19 DoD.

**Where we are:** branch **`feat/service` @ `6d35575`** (1 ahead of
`master @ 9b823ea`), **488 tests passing, ruff clean.**
Merged on `master`: Phase 0 foundations; Phase 1 offline modules (normalize,
preprocess, ingest, export); the online wiring (config → client factory →
preprocess → triage → extract+repair → normalize → score → route → eval, plus
`python -m eval.run_baseline`); **Phase 3 persistence** (7-table ORM,
`docker-compose.yml`, Alembic migrations, repository layer, DB-backed dedupe,
review queue, 4-sheet XLSX export); the R020/R024 VAT-inclusive fix; and the
currency default chain.
On `feat/service`, **not yet merged**: **P4.T4** — `process_receipt`, the RQ
worker, and the two VLM guards (ADR-0011).

**Non-negotiables:** `Decimal` on the money path (never `float`); deterministic,
pure validation that never mutates and never raises; stable rule IDs (never
renumber); prefer `null` over a confident wrong value; a full PAN never persisted
(last 4 only); nothing silently dropped (every receipt reaches a terminal state);
structured output via tool-use; few-shot images first, target receipt last;
consistency runs never cached; keep the full suite green and `ruff check .` clean;
`python -m pytest` must stay **offline** (fake client, SQLite, no Redis, no
network). Do **not** stage `.kiro/settings/mcp.json`.

**Workflow:** subagent-driven — one fresh **`general-purpose`** implementer
subagent per task, briefed to read the real signatures first, work TDD, keep the
suite green + ruff clean, and stage only its own files. After each task: review
the diff yourself, re-run `pytest` + `ruff` independently (do **not** take the
subagent's report on trust — that check has caught real bugs twice), commit
(`feat(scope): …`), and append to `.superpowers/sdd/progress.md`. Work on a
feature branch per milestone; at the end run a whole-branch review, fix what it
blocks on, re-verify, then fast-forward merge to `master`.

**Remaining tasks, in order (full detail in `IMPLEMENTATION_PLAN.md`):**

*Phase 4 — the service (in progress on `feat/service`)*
- **P4.T2 — auth. DECIDED, no need to ask: session auth + role checks
  (`reviewer` / `admin`), plus a separate API key for machine upload.** Rationale
  in `docs/MEMORY.md`: a shared key cannot attribute a correction to a reviewer,
  which hollows out the `corrections` audit trail. Tests must assert every
  non-`/health` route returns 401 without credentials and 403 for the wrong role.
- **P4.T3 — `review/api.py` (FastAPI)**, wiring the existing `review/queue.py`
  and repository (§14.9): `POST /upload`, `GET /receipts`, `GET /receipts/{id}`,
  `PATCH /receipts/{id}`, `GET /receipts/{id}/image` (signed URL),
  `GET /review/next`, `POST /review/{id}/complete`, `GET /export/xlsx`,
  `GET /health`, `GET /metrics`. Every non-`/health` route enforces auth.
  **While here:** make `enqueue_review` insert-safe (check-then-insert today, so
  concurrent enqueues can raise `IntegrityError` — see ADR-0008), and consolidate
  the `0.85`/`0.60` thresholds onto `Settings` (still triplicated across
  `route()`, `Settings`, `eval.metrics`).
- **P4.T5 / P4.T6 — `cli.py`:** `receipts ingest|process|export|eval|calibrate|
  merchants|reprocess` (§14.10), wiring `eval`/`calibrate` to the harness.
  `process` should drive the worker path; `reprocess` is the "re-run with current
  prompts, keep history" entry point ADR-0011 defers to.
- **Then:** whole-branch review of `feat/service`, fix blockers, fast-forward
  merge to `master`.

*Phase 5 — frontend review UI*
- **P5.T0 — framework (DECISION NEEDED):** React+Vite (recommended) / Next.js /
  Jinja+HTMX.
- **P5.T1 — review screen:** image + bounding-box highlighting left, editable
  fields right, keyboard-first, shows `explain_confidence` reasons, every edit
  writes a `corrections` row. Target: a full correction in under 60s.
- **P5.T2 —** upload, receipts list, queue, export pages.

*Phase 6 — merchants & few-shot*
- **P6.T1 —** `merchants/{fingerprint,registry}.py`; inject verified few-shot
  examples with **images first, target receipt last**; hints always end with
  "trust the image". Measure top-10-merchant accuracy before/after.
  **Three things unblock here** (all recorded in ADR-0011 / MEMORY): wire semantic
  merchant+date+total dedupe into `process_receipt`; pass the same hints/few-shot
  values into `_attempt_prompt_hash` or the stored hash drifts; set
  `merchant_default_currency` at the marked plug-in point. Merchant `VAT Reg. TIN`
  is the strongest fingerprint on this corpus.

*Phase 7 — self-consistency*
- **P7.T1 —** wire `run_consistency` into the pipeline for handwritten /
  low-legibility receipts and feed disputed fields into scoring. The extractor
  already supports it; the runner does not call it yet. **Gate on
  `triage.is_handwritten`, never on `document_type`** — this corpus is
  `INVOICE` + `MIXED`, not `handwritten_receipt`. Consistency runs are never
  cached.

*Phase 8 — calibration & algorithm polish*
- **P3.T6 / P8.T1 —** sweep the confidence threshold to hold auto-approval
  precision ≥99%, then fit the penalty weights from data and move them into
  `config/rules.yaml`. **Blocked on ISSUE-001.**
- **P8.T2 —** grow the held-out set until a ≥99% claim has a credible confidence
  interval (it cannot be validated on three receipts).

*Still open from earlier phases*
- **P2.T2 — R060/R061 OCR grounding (DECISION NEEDED):** the two grounding rules
  need a raw text layer nothing currently produces. Options: have the model return
  the text it read / add a cheap OCR pass / drop the rules.
- **Score `is_handwritten` from triage too** — `score_confidence` reads only
  `receipt.meta.is_handwritten`; on these printed-template forms a model may say
  `False` while triage says `MIXED`, so the −0.15 is missed on exactly the
  receipts that need it.
- **`is_receipt` has no consumer** — the §3 "reject garbage before you pay for
  extraction" gate does not exist. When built, do **not** hard-reject on a small
  model's `is_receipt` (it returned `False` for a valid invoice); route to review.
- **Blank pre-printed template rows** must not become line items (a sibling of
  R052) — Metro Oil's form pre-prints six fuel rows with one filled in.

*LAST TASK — deferred by the user until the system is built*
- **ISSUE-001 — run the first real baseline.** Read `docs/KNOWN_ISSUES.md`; do not
  re-derive. Everything is in place and the three golden labels validate with zero
  findings, but `python -m eval.run_baseline` has never completed: local CPU
  inference measured **262s–1205s per call**, so a run is 30–60 min and dies to any
  interruption, and Ollama runs JSON mode rather than the intended tool-use path.
  Fix: point the baseline at a hosted tool-capable model (the commented-out Gemini
  block in `.env` — **rotate that key first**, it was echoed in terminal output).
  Until this runs there are **no measured accuracy numbers**, calibration stays
  blocked, and **no precision claim is real**.

**Known small fixes worth folding into the next task that touches them:**
- `CostGuard._as_money` (`extract/clients/limits.py`) refuses `float` but has no
  `is_finite()` gate — a `Decimal("NaN")` cost makes the ceiling silently never
  fire (same shape as the ADR-0007 bug).
- `VLM_MAX_CONCURRENCY`, `MAX_COST_USD_PER_RECEIPT` and `STORAGE_ROOT` exist in
  `config/settings.py` but not in spec §17 — absorb them.
- `eval/results/2026-07-27-1.0.0.json` is an **empty-set artifact** reporting
  `auto_approval_precision: 1.0` on **zero** receipts. Untracked. Do not commit or
  cite it; delete it.

**Blocked on me (the user) — surface these, don't guess:**
1. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001, and
   therefore for all calibration.
2. **Decisions:** frontend framework (P5.T0), R060/R061 grounding (P2.T2).

**Today's goal:** <FILL THIS IN — e.g. "P4.T3: build review/api.py with the
decided session+role auth" or "Finish Phase 4 (CLI), review, and merge
feat/service to master" or "I've rotated the key — do ISSUE-001.">

---

## Quick status line (update each session)

- Branch: **`feat/service` @ `6d35575`** (1 ahead of `master @ 9b823ea`) ·
  **488 passing** · ruff clean
- P4.T4 done (`process_receipt` + worker + VLM guards, ADR-0011); **P4.T2 auth is
  decided but unimplemented**; P4.T3 API and P4.T5/T6 CLI remain, then review +
  merge.
- Golden set is **live**: 3 hand-verified real receipts (labels + images), all
  validating with zero findings.
- **Deferred to LAST: ISSUE-001, the first real baseline run** — see
  `docs/KNOWN_ISSUES.md`. No measured accuracy numbers exist until then.
- Blocked-on-user: a hosted tool-capable provider (ISSUE-001), plus the frontend
  and grounding decisions.
- Harness note: the `developer-kit` `prevent-destructive-commands` hook was edited
  to stop blocking `git add`/`git commit`. A plugin update will revert it.
