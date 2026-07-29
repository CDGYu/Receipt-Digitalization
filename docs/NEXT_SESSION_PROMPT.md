# Next-Session Kickoff Prompt

Paste the block between the `---` markers as the first message of the next
session, and **fill in the "Today's goal" line** (it is the one thing the prompt
cannot infer — a placeholder left in place costs a round trip).

Last refreshed: **2026-07-29**, at `master @ 4f088ed` (717 tests, ruff clean).
**Phase 4 is complete.**

---

You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first (in order), then confirm the state back to me** — and verify
the snapshot below against the repo rather than trusting it; it has been stale
before.

1. `docs/MEMORY.md` — current state, decisions already made, what's built/not
   built, environment, blockers, deferred and parked items, and the workflow.
2. `.superpowers/sdd/progress.md` — the running task ledger (newest entries at
   the bottom are the live status). Per-milestone detail, including every review
   finding and its ruling, is under `.superpowers/sdd/<plan-name>/progress.md`.
3. `docs/adr/README.md`, then the ADRs it indexes (**0001–0014**). Mandatory
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
   - **0013** CLI contract, including `calibrate`'s three gates — anything
     touching `cli.py` or the eval/calibrate reporting path.
   - **0014** optional-dependency import discipline — **anything adding an
     import to a module reachable from an entry point.** Read it before you add
     any import to `cli.py`, `worker.py`, `review/api.py`, or a package
     `__init__`.
   - **0002** provider abstraction — anything touching clients/config.
   - **0008** review-queue concurrency — anything touching `review/queue.py`.
4. `.kiro/steering/receipt-system.md` — the load-bearing rules (also auto-loaded).
5. `IMPLEMENTATION_PLAN.md` — the authoritative phased task list.
6. `docs/KNOWN_ISSUES.md` — ISSUE-001 (the deferred baseline run), with its full
   diagnosis, the 2026-07-29 measured smoke run, and exact resume steps.
   **Do not re-derive it.**
7. `RECEIPT_SYSTEM_SPEC.md` as needed: §6 data model (**eight** tables), §8.5
   repair, §9 normalization, §10 validation/tolerance, §12 confidence + routing,
   §13 Excel, §14 function inventory (**§14.8** repository, **§14.9** review API,
   **§14.10** the CLI as built), §15 milestones, §16 eval, §17 config, §18 traps,
   §19 DoD.
8. Design docs, only if you are touching what they cover:
   `docs/superpowers/specs/2026-07-29-cli-design.md` and
   `docs/superpowers/specs/2026-07-28-review-api-design.md`.

**Where we are:** `master @ 4f088ed`, **717 tests passing, ruff clean.** No git
remote is configured; nothing is pushed anywhere.

**Phases 0–4 are complete and merged.** Foundations; the offline modules
(normalize, preprocess, ingest, export); the online wiring (config → client
factory → preprocess → triage → extract+repair → normalize → score → route →
eval); persistence (8 tables, migrations, repository, review queue, 4-sheet
XLSX); `process_receipt` + the RQ worker + the VLM concurrency/cost guards
(ADR-0011); the review API with session auth, roles and a machine upload key
(ADR-0012); and the operator CLI (ADR-0013, ADR-0014).

**Running it:** `python -m receipts.cli <command>` — the console script needs the
interpreter's `Scripts`/`bin` directory on `PATH`, which it is **not** on this
machine. Commands: `ingest|process|export|eval|calibrate|merchants|reprocess|users`.

**Non-negotiables:** `Decimal` on the money path (never `float`); deterministic,
pure validation that never mutates and never raises; stable rule IDs (never
renumber); prefer `null` over a confident wrong value; a full PAN never persisted
(last 4 only); nothing silently dropped (every receipt reaches a terminal state);
**a machine run never overwrites a `reviewed` row**; **no module-top import of an
optional extra on any path reachable from an entry point** (ADR-0014); structured
output via tool-use; few-shot images first, target receipt last; consistency runs
never cached; keep the full suite green and `ruff check .` clean; `python -m
pytest` must stay **offline** (fake client, SQLite, no Redis, no network). Do
**not** stage `.kiro/settings/mcp.json`.

**Workflow:** brainstorm → design doc → ADR for anything load-bearing →
implementation plan → subagent-driven execution. One fresh **`general-purpose`**
implementer per task, briefed to read the real signatures first, work TDD, keep
the suite green + ruff clean, and stage only its own files. After each task:
review the diff yourself, re-run `pytest` + `ruff` **independently**, then a task
review, then commit and append to the ledger. At the end of a milestone: a
whole-branch review on the strongest model, **one** consolidated fix wave, one
scoped re-review, then fast-forward merge. Merged branches and SDD workspaces are
**kept**, not cleaned up.

**Three review standards this project learned the hard way — hold all of them:**
1. **Reviewers reproduce, they do not reason.** Every finding that mattered came
   from executing something.
2. **Every new test must be proven to fail** with its fix reverted. Several tests
   across these milestones passed against the unfixed code.
3. **Probe the existing code before dispatching, not after review.** Seven plan
   defects in the CLI milestone were caught this way, and every one was about
   what the code already does — an ADR claiming audit rows that were never
   written, tests asserting strings a function does not print, an ORM `.append()`
   that is silently never flushed. The plan's prose is reliable; its snippets
   against existing APIs are not.

And the environment lesson: **a green suite is not evidence that installed
software works.** The same defect shipped twice — a module-top import of an
optional extra broke every installed `receipts` command while all tests passed,
because pytest puts the repo root on `sys.path`. Anything with an entry point gets
run from outside the repository as part of verification.

**Remaining work, in order (full detail in `IMPLEMENTATION_PLAN.md`):**

*Phase 5 — frontend review UI*
- **P5.T0 — framework (DECISION NEEDED):** React+Vite (recommended) / Next.js /
  Jinja+HTMX.
- **P5.T1 — review screen:** image + bounding-box highlighting left, editable
  fields right, keyboard-first, shows the **persisted** `confidence_reasons`
  (they provably sum to the stored score — ADR-0012), every edit writes a
  `corrections` row. Target: a full correction in under 60s.
- **P5.T2 —** upload, receipts list, queue, export pages. The API is built and
  auth is enforced; `GET /receipts/{id}/image` returns a short-lived signed URL
  and the blob sub-route needs no session, so it works in an `<img>` tag.

*Phase 6 — merchants & few-shot*
- **P6.T1 —** `merchants/{fingerprint,registry}.py`; inject verified few-shot
  examples with **images first, target receipt last**; hints always end with
  "trust the image". Measure top-10-merchant accuracy before/after.
  **Five things unblock here:** wire semantic merchant+date+total dedupe into
  `process_receipt`; pass the same hints/few-shot values into
  `_attempt_prompt_hash` or the stored hash drifts; set
  `merchant_default_currency` at the marked plug-in point; fix the parked
  `image_phash` gap; and increment `Merchant.receipt_count`, which nothing writes
  today (`receipts merchants list` prints `-` rather than a confident `0`).
  Merchant `VAT Reg. TIN` is the strongest fingerprint on this corpus.

*Phase 7 — self-consistency*
- **P7.T1 —** wire `run_consistency` into the pipeline for handwritten /
  low-legibility receipts and feed disputed fields into scoring. The extractor
  supports it; the runner does not call it yet. **Gate on
  `triage.is_handwritten`, never on `document_type`** — this corpus is
  `INVOICE` + `MIXED`. Consistency runs are never cached.

*Phase 8 — calibration & eval-harness honesty*
- **P3.T6 / P8.T1 —** sweep the confidence threshold to hold auto-approval
  precision ≥99%, then fit the penalty weights from data into `config/rules.yaml`.
  **Blocked on ISSUE-001.**
- **P8.T2 —** grow the held-out set until a ≥99% claim has a credible confidence
  interval. Note `receipts calibrate` will not recommend from fewer than
  `_MIN_APPROVED_SAMPLE` (5) approved receipts, so with 3 golden labels it
  correctly refuses today.
- **P8.T3 — close the artifact ban properly.** An **all-failed** eval run still
  persists `"auto_approval_precision": 1.0` to the results JSON even though the
  terminal prints `n/a`. The ban is not closed until the file is honest too;
  widening the field ripples into `_report_to_dict`, the committed schema, and
  `calibration_curve`. Also consider excluding `meta.*` from `field_accuracy`'s
  denominator — a golden label's `meta.notes` prose is currently scored against
  model output, making per-field accuracy pessimistic.

*Still open from earlier phases*
- **P2.T2 — R060/R061 OCR grounding (DECISION NEEDED):** the two grounding rules
  need a raw text layer nothing produces. Options: have the model return the text
  it read / a cheap OCR pass / drop the rules.
- **Score `is_handwritten` from triage too** — `score_confidence` reads only
  `receipt.meta.is_handwritten`; on these printed-template forms a model may say
  `False` while triage says `MIXED`, so the −0.15 is missed on exactly the
  receipts that need it.
- **`is_receipt` has no consumer** — the §3 "reject garbage before you pay for
  extraction" gate does not exist. It returned `False` for valid invoices on both
  smoke-run receipts, so when the gate is built it must **not** hard-reject on it;
  route to review.
- **Blank pre-printed template rows** must not become line items (a sibling of
  R052) — Metro Oil's form pre-prints six fuel rows with one filled in.

*Parked, with rulings (see the per-milestone ledgers)*
- `apply_corrections` redacts **any** coerced text, so confirming a 13–19-digit
  `receipt.number` masks it and writes a spurious `corrections` row, while
  `save_extraction` redacts only two columns — make the two sides agree.
- `_persist_failure` never writes `image_phash`, so a receipt whose stage failed
  keeps `""` and can never serve as a dedupe **original**. Fix with Phase 6.
- An auto-approving reprocess closes a review task a reviewer had already claimed.
- **No login rate limiting**, and each attempt costs a full scrypt derivation
  (~16 MB, ~57 ms) — `POST /auth/login` is an unauthenticated CPU/memory amplifier
  as well as an enumeration surface.
- `receipts eval`/`calibrate` still traceback without the `pipeline` extra while
  the other six commands degrade cleanly; `calibrate` only reads JSON.
- Reprocessing a `reviewed` receipt records **no** `extraction_runs` — the
  transaction rolls back (ADR-0013's dated correction). Making the audit rows
  survive is real pipeline work and would give free model-versus-truth signal on
  exactly the receipts that carry human-verified values.

*LAST TASK — deferred by the user until the system is built*
- **ISSUE-001 — run the first real baseline.** Read `docs/KNOWN_ISSUES.md`; do not
  re-derive. The smoke run proved the **pipeline works end to end and the safety
  machinery does not auto-approve garbage** — a bad extraction scored `0.000` and
  routed urgent. It also proved `granite3.2-vision:2b` on CPU is too slow *and*
  too weak: 314 s triage + 1057 s extract at `max_edge=768`, extraction
  effectively empty. Fix: point the baseline at a hosted tool-capable model (the
  commented-out Gemini block in `.env` — **rotate that key first**, it was echoed
  in terminal output). Until this runs there are **no measured accuracy numbers**,
  calibration stays blocked, and **no precision claim is real**.

**Blocked on me (the user) — surface these, don't guess:**
1. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001, and
   therefore for all calibration.
2. **Decisions:** frontend framework (P5.T0), R060/R061 grounding (P2.T2).

**Today's goal:** <FILL THIS IN — e.g. "P5.T0 + P5.T1: pick the framework and
build the review screen" or "Clear the parked findings and close the artifact ban"
or "I've rotated the key — do ISSUE-001.">

---

## Quick status line (update each session)

- **`master` @ `4f088ed`** · **717 passing** · ruff clean · no git remote.
- **Phases 0–4 complete.** Next milestone is Phase 5 (frontend), gated on the
  P5.T0 framework decision.
- Run it with `python -m receipts.cli <command>`; the bare `receipts` script needs
  the interpreter's `Scripts` directory on `PATH`, which it is not on this box.
- Golden set is **live**: 3 hand-verified real receipts, all validating with zero
  findings.
- **Deferred to LAST: ISSUE-001** — the smoke run validated the infrastructure and
  confirmed the local model is the blocker. No measured accuracy numbers exist
  until a hosted provider runs it.
- Blocked-on-user: a hosted tool-capable provider + rotated key, the frontend
  framework, and the R060/R061 grounding decision.
- Six findings are **parked with rulings** — see the section above and
  `docs/MEMORY.md`.
- Harness notes: the `developer-kit` `prevent-destructive-commands` hook was
  edited to stop blocking `git add`/`git commit`; a plugin update will revert it.
  It also mis-normalizes some relative paths — use absolute paths with
  `Remove-Item` if `rm` is wrongly refused.
