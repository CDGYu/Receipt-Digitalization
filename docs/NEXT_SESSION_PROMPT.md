# Next-Session Kickoff Prompt

Paste the block below as the first message of the next session (adjust the
"Today's goal" line to what you want done).

---

You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first (in order), then confirm you understand the state:**
1. `docs/MEMORY.md` — current state, what's built/not built, env, blockers,
   deferred items, and the workflow to follow.
2. `.superpowers/sdd/progress.md` — the running task ledger (most recent entries
   are the live status).
3. `docs/adr/` (0001–0005) — the implementation decisions to stay consistent with.
4. `.kiro/steering/receipt-system.md` — the load-bearing rules (also auto-loaded).
5. `IMPLEMENTATION_PLAN.md` — the authoritative phased task list.
6. `RECEIPT_SYSTEM_SPEC.md` as needed — §6 (data model), §12 (confidence), §14
   (function inventory), §15 (milestones), §16 (eval), §17 (config).

**Where we are:** `master` @ `8cbef5a`; active branch **`feat/db-layer`** (2
commits ahead, **292 tests passing, ruff clean**) with the 7-table SQLAlchemy
ORM + `docker-compose.yml`. The online pipeline (config → factory → preprocess →
triage → extract+repair → normalize → score → route → eval) is built and merged
to `master`.

**Non-negotiables:** `Decimal` on the money path (never `float`); deterministic,
pure validation; prefer `null` over a confident wrong value; keep the full suite
green and `ruff check .` clean; `python -m pytest` runs offline via the fake
client. Do **not** stage `.kiro/settings/mcp.json`.

**Workflow:** subagent-driven — one fresh `general-task-execution` implementer
per task (brief it to read real signatures first, work TDD, stage only its own
files). After each task: review the diff, run `pytest` + `ruff`, commit
(`feat(scope): …`), and update `.superpowers/sdd/progress.md`. When the branch's
milestone is complete, run a `semantic_reviewer` whole-branch review, then
fast-forward merge to `master`.

**Remaining tasks (continue in this order — full detail in `IMPLEMENTATION_PLAN.md`):**

Finish the DB layer (current branch `feat/db-layer`):
- **P3.T2 — Alembic migrations** generated against `persist/models.py`; test
  upgrade/downgrade on SQLite; wire `DATABASE_URL`.
- **P3.T3 — `persist/repository.py`**: `save_extraction`, `save_extraction_run`
  (**redact any full PAN before writing `raw_response`**), `save_findings`,
  `get_receipt`, `query_receipts`, and transactional `apply_corrections` (one
  `corrections` row per changed field path, sets `status='reviewed'`).
- **P3.T5 — dedupe wired to the repository** + review-queue claim with
  `SELECT … FOR UPDATE SKIP LOCKED`.
- **P3.T7 — XLSX `Needs Review` + `Summary` sheets** (§13.3–13.5).
- **P3.T6 — calibration** (`receipts calibrate` / sweep thresholds) — *blocked
  on the golden set*.

Then: Phase 4 (auth decision → `review/queue.py` + `review/api.py` FastAPI →
`pipeline.process_receipt` + worker → `cli.py`), Phase 5 (frontend review UI —
needs framework decision), Phase 6 (merchants + few-shot), Phase 7 (wire
self-consistency into `run_receipt`), Phase 8 (calibrate confidence weights; move
them to `config/rules.yaml`).

**Blocked on the user (surface these, don't guess):** label the golden set +
pick a tool-capable provider (for a real baseline/calibration); decide the auth
model (P4.T2), the frontend framework (P5.T0), and the R060/R061 grounding
approach (P2.T2). Note: `moondream` (their current local model) likely can't do
tool-use, so extraction may fail against it.

**Today's goal:** <e.g. "Do P3.T2 and P3.T3 (Alembic + repository), then stop for
review.">

---

## Quick status line (update each session)

- Branch: `feat/db-layer` (2 ahead of `master@8cbef5a`) · 292 passing · ruff clean
- Next task: **P3.T2 (Alembic migrations)**
- Blocked-on-user: golden set, provider choice, auth/frontend/grounding decisions
