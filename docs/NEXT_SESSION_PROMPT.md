# Next-Session Kickoff Prompt

Paste the block between the `---` markers as the first message of the next
session, and fill in the "Today's goal" line.

---

You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first (in order), then confirm the state back to me:**
1. `docs/MEMORY.md` — current state, what's built/not built, env, blockers,
   deferred items, and the workflow to follow.
2. `.superpowers/sdd/progress.md` — the running task ledger (newest entries at
   the bottom are the live status).
3. `docs/adr/README.md` then the ADRs it indexes (**0001–0010**). Read **0001**
   (`Decimal` money path) and **0007** (PAN redaction + money integrity) before
   touching anything that writes money or card data.
4. `.kiro/steering/receipt-system.md` — the load-bearing rules (also auto-loaded).
5. `IMPLEMENTATION_PLAN.md` — the authoritative phased task list.
6. `RECEIPT_SYSTEM_SPEC.md` as needed — §6 data model, §12 confidence/routing,
   §13 Excel, §14 function inventory (§14.9 review API, §14.10 pipeline/CLI),
   §15 milestones, §16 eval, §17 config, §18 traps, §19 definition of done.

**Where we are:** `master @ 9bd4cd0`, **410 tests passing, ruff clean, no feature
branch open.** Merged: Phase 0 foundations, Phase 1 offline modules (normalize,
preprocess, ingest, export), the online wiring (config → client factory →
preprocess → triage → extract+repair → normalize → score → route → eval, plus
`python -m eval.run_baseline`), and **Phase 3 persistence** (7-table ORM,
`docker-compose.yml`, Alembic migrations, repository layer, DB-backed dedupe,
review queue, 4-sheet XLSX export).

**Non-negotiables:** `Decimal` on the money path (never `float`); deterministic,
pure validation; prefer `null` over a confident wrong value; a full PAN never
persisted (last 4 only); nothing silently dropped; keep the full suite green and
`ruff check .` clean; `python -m pytest` must stay offline (fake client, SQLite).
Do **not** stage `.kiro/settings/mcp.json`.

**Workflow:** subagent-driven — one fresh `general-task-execution` implementer per
task, briefed to read the real signatures first, work TDD, keep the suite green,
and stage only its own files. After each task: review the diff, run `pytest` +
`ruff`, commit (`feat(scope): …`), update `.superpowers/sdd/progress.md`. Work on
a feature branch per milestone; at the end run a `semantic_reviewer` whole-branch
review, fix what it blocks on, re-verify, then fast-forward merge to `master`.
(Last session that review caught two real bugs — take it seriously.)

**Remaining tasks, in order (full detail in `IMPLEMENTATION_PLAN.md`):**

*Phase 4 — the service (next milestone; suggested branch `feat/service`)*
- **P4.T2 — auth (DECISION NEEDED, do first):** the review API handles financial
  PII, so no route may be reachable unauthenticated. Options: session auth +
  role checks (`reviewer`/`admin`) with an API key for machine upload
  (recommended) / plain API key / OIDC. Ask me before implementing.
- **P4.T3 — `review/api.py` (FastAPI)** wiring the existing `review/queue.py` and
  repository: `POST /upload`, `GET /receipts`, `GET /receipts/{id}`,
  `PATCH /receipts/{id}`, `GET /receipts/{id}/image` (signed URL),
  `GET /review/next`, `POST /review/{id}/complete`, `GET /export/xlsx`,
  `GET /health`, `GET /metrics` (§14.9). Every non-`/health` route enforces auth.
  While here: make `enqueue_review` insert-safe (it is check-then-insert today)
  and consolidate the `0.85`/`0.60` thresholds onto `Settings`.
- **P4.T4 — `pipeline.process_receipt` + the RQ worker:** the only function the
  worker calls; wraps every stage so any exception marks the receipt
  `needs_review` with the failing stage as the reason (never loses a job). Add a
  global VLM concurrency cap and a per-run cost guard. Persist via the repository
  (`save_extraction` then `save_findings` — see the note in MEMORY) and reconcile
  the raw-report / normalized-extraction mismatch noted there.
- **P4.T5 / P4.T6 — `cli.py`:** `receipts ingest|process|export|eval|calibrate|
  merchants|reprocess` (§14.10), wiring `eval`/`calibrate` to the harness.

*Phase 5 — frontend review UI (needs a decision)*
- **P5.T0 — framework (DECISION NEEDED):** React+Vite (recommended) / Next.js /
  Jinja+HTMX.
- **P5.T1 — review screen:** image + bounding-box highlighting on the left,
  editable fields right, keyboard-first, shows `explain_confidence` reasons,
  every edit writes a `corrections` row. Target: a full correction in under 60s.
- **P5.T2 —** upload, receipts list, queue, export pages.

*Phase 6 — merchants & few-shot*
- **P6.T1 —** `merchants/{fingerprint,registry}.py`; inject verified few-shot
  examples with **images first, target receipt last**; hints always end with
  "trust the image". Measure top-10-merchant accuracy before/after.

*Phase 7 — self-consistency*
- **P7.T1 —** wire `run_consistency` into `run_receipt` for handwritten /
  low-legibility receipts and feed disputed fields into scoring. The extractor
  already supports it; the M1 runner does not call it yet. Consistency runs must
  never be cached.

*Phase 8 — calibration & algorithm polish*
- **P3.T6 / P8.T1 —** sweep the confidence threshold to hold auto-approval
  precision ≥99%, then fit the penalty weights from data and move them into
  `config/rules.yaml`. **Blocked on the golden set.**
- **P8.T2 —** grow the held-out set until a ≥99% claim has a credible confidence
  interval (it cannot be validated on a handful of receipts).

*LAST TASK — deferred by the user until the system is built*
- **ISSUE-001 — run the first real baseline.** See **`docs/KNOWN_ISSUES.md`** for
  the full diagnosis and exact resume steps; do not re-derive it. Everything is in
  place and the three golden labels validate with zero findings, but
  `python -m eval.run_baseline` has never completed: the local CPU model takes
  ~262s per call, so a run is 30–60 min and dies to any interruption. Recommended
  fix is to point the baseline at a hosted tool-capable model (the commented-out
  Gemini block in `.env` — **rotate that key first**, it was echoed in terminal
  output). Until this runs there are **no measured accuracy numbers**, so
  calibration (P3.T6 / P8.T1) stays blocked and no precision claim is real.

*Still open from earlier phases*
- **P2.T2 — R060/R061 OCR grounding (DECISION NEEDED):** the two grounding rules
  need a raw text layer nothing currently produces. Options: have the model
  return the text it read / add a cheap OCR pass / drop the rules.

**Blocked on me (the user) — surface these, don't guess:**
1. **Golden set** — I said I'd send sample receipts; until then no real baseline
   or calibration is possible (`eval/golden/labels|images` are empty).
2. **A tool-capable provider** — my `.env` points at a local `moondream`, which
   likely cannot do the tool-use the extractor needs for schema-constrained
   output.
3. **Decisions:** auth model (P4.T2), frontend framework (P5.T0), R060/R061
   grounding (P2.T2).

**Today's goal:** <e.g. "Start Phase 4: ask me about auth, then do P4.T4
(process_receipt + worker) which needs no decision." or "Wire up the golden set I
just sent and run a real baseline.">

---

## Quick status line (update each session)

- Branch: `master @ 9bd4cd0` (no feature branch open) · **410 passing** · ruff clean
- Phase 3 (persistence) complete and merged; only **P3.T6 calibration** remains
  from it, blocked on the golden set.
- Next task: **Phase 4** — auth decision (P4.T2), then P4.T3 API / P4.T4 worker.
- Golden set is **live**: 3 hand-verified real receipts (labels + images), all
  validating with zero findings.
- **Deferred to LAST: ISSUE-001, the first real baseline run** — see
  `docs/KNOWN_ISSUES.md`. No measured accuracy numbers exist until then.
- Blocked-on-user: a tool-capable provider (for ISSUE-001), and the auth /
  frontend / grounding decisions.
