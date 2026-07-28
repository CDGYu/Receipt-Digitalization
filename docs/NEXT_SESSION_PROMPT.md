# Next-Session Kickoff Prompt

Paste the block between the `---` markers as the first message of the next
session, and **fill in the "Today's goal" line** (it is the one thing the prompt
cannot infer — a placeholder left in place costs a round trip).

Last refreshed: **2026-07-29**, at `master @ 72de8ad` (644 tests, ruff clean).

---

You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first (in order), then confirm the state back to me:**
1. `docs/MEMORY.md` — current state, decisions already made, what's built/not
   built, environment, blockers, deferred and parked items, and the workflow.
2. `.superpowers/sdd/progress.md` — the running task ledger (newest entries at
   the bottom are the live status). Per-milestone detail, including every review
   finding and its ruling, is under `.superpowers/sdd/<plan-name>/progress.md`.
3. `docs/adr/README.md`, then the ADRs it indexes (**0001–0013**). Mandatory
   before touching the matching area:
   - **0001** `Decimal` money path — anything that touches money.
   - **0007** PAN redaction + money integrity — anything that writes card data.
   - **0006** repository conventions (injected session, **caller commits**,
     `ValueError` boundary) — anything that writes to the DB.
   - **0011** terminal-state contract + VLM concurrency/cost guards — anything
     touching `process_receipt`, the worker, or model-call limits.
   - **0012** review API: identity, the `pending` row, the persisted confidence
     breakdown, and **"a machine run never overwrites a `reviewed` row"** —
     anything touching auth, the routes, `save_extraction`, or reprocessing.
   - **0013** CLI contract — anything touching `cli.py`.
   - **0002** provider abstraction — anything touching clients/config.
   - **0008** review-queue concurrency — anything touching `review/queue.py`.
4. `.kiro/steering/receipt-system.md` — the load-bearing rules (also auto-loaded).
5. `IMPLEMENTATION_PLAN.md` — the authoritative phased task list.
6. `docs/KNOWN_ISSUES.md` — ISSUE-001 (the deferred baseline run), with its full
   diagnosis, the **2026-07-29 measured smoke run**, and exact resume steps.
   **Do not re-derive it.**
7. Design docs for work in flight:
   - `docs/superpowers/specs/2026-07-29-cli-design.md` — **the approved CLI
     design; the next task implements it.** No implementation plan written yet.
   - `docs/superpowers/specs/2026-07-28-review-api-design.md` — the shipped
     review API, for context on why it is shaped as it is.
8. `RECEIPT_SYSTEM_SPEC.md` as needed: §6 data model (now **eight** tables), §8.5
   repair, §9 normalization, §10 validation/tolerance, §12 confidence + routing,
   §13 Excel, §14 function inventory (**§14.8** repository, **§14.9** review API,
   **§14.10** pipeline/CLI), §15 milestones, §16 eval, §17 config, §18 traps,
   §19 DoD.

**Where we are:** `master @ 72de8ad`, **644 tests passing, ruff clean.** No git
remote is configured; nothing is pushed anywhere.

Merged on `master`: Phase 0 foundations; Phase 1 offline modules (normalize,
preprocess, ingest, export); the online wiring (config → client factory →
preprocess → triage → extract+repair → normalize → score → route → eval, plus
`python -m eval.run_baseline`); **Phase 3 persistence**; the R020/R024
VAT-inclusive fix; the currency default chain; **P4.T4** (`process_receipt`, the
RQ worker, the two VLM guards — ADR-0011); and **P4.T3** (the review API: the
`users` table + stdlib-scrypt auth, `receipts.confidence_reasons`, session auth
with `reviewer`/`admin`, a machine upload key, and eleven routes — ADR-0012).

**Phase 4 has one piece left: `cli.py` (P4.T5/T6).** Its design is approved and
committed; the implementation plan is not written yet.

**Non-negotiables:** `Decimal` on the money path (never `float`); deterministic,
pure validation that never mutates and never raises; stable rule IDs (never
renumber); prefer `null` over a confident wrong value; a full PAN never persisted
(last 4 only); nothing silently dropped (every receipt reaches a terminal state);
**a machine run never overwrites a `reviewed` row**; structured output via
tool-use; few-shot images first, target receipt last; consistency runs never
cached; keep the full suite green and `ruff check .` clean; `python -m pytest`
must stay **offline** (fake client, SQLite, no Redis, no network). Do **not**
stage `.kiro/settings/mcp.json`.

**Workflow:** brainstorm → design doc → implementation plan → subagent-driven
execution. One fresh **`general-purpose`** implementer subagent per task, briefed
to read the real signatures first, work TDD, keep the suite green + ruff clean,
and stage only its own files. After each task: review the diff yourself, re-run
`pytest` + `ruff` **independently** (do not take the subagent's report on trust —
that check has caught real bugs repeatedly), then a task review, then commit
(`feat(scope): …`) and append to the ledger. At the end of a milestone run a
whole-branch review on the most capable model, one consolidated fix wave, one
scoped re-review, then fast-forward merge to `master`.

**Review standard, learned the hard way in P4.T3 — hold it:** reviewers must
**reproduce**, not reason; every new test must be **proven to fail** with its fix
reverted (three tests last milestone passed against the unfixed code); and the
whole-branch review is mandatory because per-task reviews structurally cannot see
defects in the seam between tasks — that is exactly where the one Critical lived.
Merged feature branches and the SDD workspaces are **kept**, not cleaned up.

**Remaining tasks, in order (full detail in `IMPLEMENTATION_PLAN.md`):**

*Phase 4 — finish the service*
- **P4.T5 / P4.T6 — `cli.py`.** Design approved in
  `docs/superpowers/specs/2026-07-29-cli-design.md`; contract in **ADR-0013**.
  Next step is an implementation plan, then subagent execution.
  `receipts ingest|process|export|eval|calibrate|merchants|reprocess|users`.
  Load-bearing points: `ingest` writes a `pending` row and does **not** enqueue —
  `process` drains the `pending` rows, so both entry points share one work list;
  `process` enqueues to RQ by default with `--inline` for a no-Redis box and a
  **hard failure** (never a silent fallback) when `REDIS_URL` is missing;
  `reprocess` always records the attempt but never overwrites a `reviewed` row,
  and `--force` extends only to `auto_approved`; `calibrate` **refuses a
  zero-receipt result set** instead of reporting precision `1.0`; no interactive
  prompts anywhere; a receipt routed to review does **not** change the exit code.
  When it lands: update §14.10 with the real flags, and repoint the
  re-enqueueing docstrings in `review/api.py` and `pipeline.process_receipt` at
  `receipts reprocess`.

*Phase 5 — frontend review UI*
- **P5.T0 — framework (DECISION NEEDED):** React+Vite (recommended) / Next.js /
  Jinja+HTMX.
- **P5.T1 — review screen:** image + bounding-box highlighting left, editable
  fields right, keyboard-first, shows the **persisted** `confidence_reasons`
  (they now provably sum to the stored score — ADR-0012), every edit writes a
  `corrections` row. Target: a full correction in under 60s.
- **P5.T2 —** upload, receipts list, queue, export pages. The API is built and
  auth is enforced; `GET /receipts/{id}/image` returns a short-lived signed URL
  and the blob sub-route needs no session, so it works in an `<img>` tag.

*Phase 6 — merchants & few-shot*
- **P6.T1 —** `merchants/{fingerprint,registry}.py`; inject verified few-shot
  examples with **images first, target receipt last**; hints always end with
  "trust the image". Measure top-10-merchant accuracy before/after.
  **Four things unblock here:** wire semantic merchant+date+total dedupe into
  `process_receipt`; pass the same hints/few-shot values into
  `_attempt_prompt_hash` or the stored hash drifts; set
  `merchant_default_currency` at the marked plug-in point; and fix the parked
  `image_phash` gap (below) before `reprocess` leans on dedupe. Merchant
  `VAT Reg. TIN` is the strongest fingerprint on this corpus.

*Phase 7 — self-consistency*
- **P7.T1 —** wire `run_consistency` into the pipeline for handwritten /
  low-legibility receipts and feed disputed fields into scoring. The extractor
  supports it; the runner does not call it yet. **Gate on
  `triage.is_handwritten`, never on `document_type`** — this corpus is
  `INVOICE` + `MIXED`. Consistency runs are never cached.

*Phase 8 — calibration & algorithm polish*
- **P3.T6 / P8.T1 —** sweep the confidence threshold to hold auto-approval
  precision ≥99%, then fit the penalty weights from data and move them into
  `config/rules.yaml`. **Blocked on ISSUE-001.** `receipts calibrate` builds the
  curve but cannot produce a trustworthy threshold until a real baseline exists.
- **P8.T2 —** grow the held-out set until a ≥99% claim has a credible confidence
  interval (it cannot be validated on three receipts).

*Still open from earlier phases*
- **P2.T2 — R060/R061 OCR grounding (DECISION NEEDED):** the two grounding rules
  need a raw text layer nothing currently produces. Options: have the model
  return the text it read / add a cheap OCR pass / drop the rules.
- **Score `is_handwritten` from triage too** — `score_confidence` reads only
  `receipt.meta.is_handwritten`; on these printed-template forms a model may say
  `False` while triage says `MIXED`, so the −0.15 is missed on exactly the
  receipts that need it.
- **`is_receipt` has no consumer** — the §3 "reject garbage before you pay for
  extraction" gate does not exist. It returned `False` for valid invoices on both
  receipts tried in the 2026-07-29 smoke run, so when the gate is built it must
  **not** hard-reject on it; route to review.
- **Blank pre-printed template rows** must not become line items (a sibling of
  R052) — Metro Oil's form pre-prints six fuel rows with one filled in.
- **`field_accuracy` counts fields the model cannot match** (from the smoke run):
  the flattened comparison includes `meta.*`, so a golden label's `meta.notes`
  annotator prose is scored against model output, and `meta.legibility` /
  `meta.is_handwritten` are self-reports. Consider excluding `meta.*` from the
  denominator; until then read per-field accuracy as pessimistic.

*Parked from the P4.T3 whole-branch review (real, adjudicated, not blocking)*
- `apply_corrections` redacts **any** coerced text, so confirming a 13–19-digit
  `receipt.number` masks it and writes a spurious `corrections` row, while
  `save_extraction` redacts only `merchant_name_raw` and `payment_method` — make
  the two sides agree.
- `_persist_failure` never writes `image_phash`, so a receipt whose stage failed
  keeps `""` and can never later serve as a dedupe **original**. Fix with the
  Phase 6 dedupe work, and before `receipts reprocess` depends on it.
- Closing a review task on an auto-approving reprocess also closes one a reviewer
  had already claimed. Revisit with the review UI (P5).
- **No login rate limiting**, and each attempt costs a full scrypt derivation
  (~16 MB, ~57 ms), so `POST /auth/login` is an unauthenticated CPU/memory
  amplifier as well as an enumeration surface. Address before this faces more
  than a LAN.

*LAST TASK — deferred by the user until the system is built*
- **ISSUE-001 — run the first real baseline.** Read `docs/KNOWN_ISSUES.md`; do not
  re-derive. The 2026-07-29 smoke run (`scripts/try_one_receipt.py`) proved the
  **pipeline works end to end and the safety machinery does not auto-approve
  garbage** — a bad extraction scored `0.000` and routed urgent. It also proved
  that `granite3.2-vision:2b` on CPU is both too slow and too weak: 314 s triage
  + 1057 s extract at `max_edge=768`, with the extraction effectively empty (at
  the 2048 default, triage alone takes 887 s, just under the 900 s timeout —
  which is why the earlier attempts died). Fix: point the baseline at a hosted
  tool-capable model (the commented-out Gemini block in `.env` — **rotate that
  key first**, it was echoed in terminal output). Until this runs there are **no
  measured accuracy numbers**, calibration stays blocked, and **no precision
  claim is real**.

**Blocked on me (the user) — surface these, don't guess:**
1. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001, and
   therefore for all calibration.
2. **Decisions:** frontend framework (P5.T0), R060/R061 grounding (P2.T2).

**Today's goal:** <FILL THIS IN — e.g. "P4.T5/T6: write the implementation plan
for the approved CLI design and execute it" or "Finish Phase 4, then P5.T0" or
"I've rotated the key — do ISSUE-001.">

---

## Quick status line (update each session)

- **`master` @ `72de8ad`** · **644 passing** · ruff clean · no git remote.
- Phase 4 is done except **`cli.py` (P4.T5/T6)** — design approved
  (`docs/superpowers/specs/2026-07-29-cli-design.md`, ADR-0013), plan not written.
- P4.T3 shipped the review API + auth (ADR-0012); P4.T4 shipped
  `process_receipt`, the worker and the VLM guards (ADR-0011).
- Golden set is **live**: 3 hand-verified real receipts, all validating with zero
  findings.
- **Deferred to LAST: ISSUE-001** — the 2026-07-29 smoke run validated the
  infrastructure and confirmed the local model is the blocker. No measured
  accuracy numbers exist until a hosted provider runs it.
- Blocked-on-user: a hosted tool-capable provider + rotated key (ISSUE-001), the
  frontend framework, and the R060/R061 grounding decision.
- Four findings are **parked with rulings** from the P4.T3 branch review — see the
  section above and `docs/MEMORY.md`.
- Harness note: the `developer-kit` `prevent-destructive-commands` hook was edited
  to stop blocking `git add`/`git commit`. A plugin update will revert it. It also
  mis-normalizes some relative paths — use absolute paths with `Remove-Item` if
  `rm` is wrongly refused.
