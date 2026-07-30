# Next-Session Kickoff Prompt

Paste the block between the `---` markers as the first message of the next
session, and **fill in the "Today's goal" line** — it is the one thing the
prompt cannot infer, and a placeholder left in place costs a round trip.

Last refreshed: **2026-07-31**, at `main @ cd464d5`. **Phase 5 is complete and
merged.** 844 Python + 170 Vitest, all gates green, everything pushed.

---

You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, what is built,
   the environment, blockers, deferred and parked items.
2. **`.superpowers/sdd/2026-07-29-review-ui/progress.md`** — the Phase 5 ledger.
   It carries every measurement, adjudication and parked ruling from that
   milestone, and the full scope of the next task. **Note: `.superpowers/` is
   gitignored, so nothing in it is findable by searching the tracked tree — you
   must open it by path.**
3. **`docs/adr/README.md`, then the ADRs it indexes (0001–0017).** Mandatory
   before touching the matching area:
   - **0001** `Decimal` money path — anything touching money.
   - **0007** PAN redaction + money integrity — anything writing card data.
     **Read this with the PAN task below.**
   - **0006** repository conventions (injected session, **caller commits**,
     `ValueError` boundary) — anything writing to the DB.
   - **0011** terminal-state contract + VLM concurrency/cost guards.
   - **0012** review API: identity, the `pending` row, the persisted confidence
     breakdown, and **"a machine run never overwrites a `reviewed` row"**.
   - **0013** CLI contract, including `calibrate`'s three gates.
   - **0014** optional-dependency import discipline — **anything adding an
     import to a module reachable from an entry point.**
   - **0015** the review UI: same-origin serving, the `/app` prefix, the guarded
     static mount, money as a string in the browser.
   - **0016** `GET /review/next` resumes the caller's own in-progress task —
     anything touching `review/queue.py` or the claim lifecycle.
   - **0017** two test suites and `scripts/verify.py` — **read before believing
     a green test run.**
   - **0002** provider abstraction · **0008** review-queue concurrency.
4. **`.kiro/steering/receipt-system.md`** — the always-on load-bearing rules.
   Still auto-loads and is on disk, but **gitignored and untracked**.
5. **`IMPLEMENTATION_PLAN.md`** — the authoritative phased task list.
6. **`docs/KNOWN_ISSUES.md`** — ISSUE-001 (the deferred baseline), with its full
   diagnosis and exact resume steps. **Do not re-derive it.**
7. **`RECEIPT_SYSTEM_SPEC.md`** as needed: §6 data model (**eight** tables),
   §8.5 repair, §9 normalization, §10 validation/tolerance, §12 confidence +
   routing, §13 Excel, §14 function inventory (§14.8 repository, §14.9 review
   API, §14.10 the CLI), §15 milestones, §16 eval, §17 config, §18 traps
   (**PAN handling**), §19 DoD.
8. Design docs, only if touching what they cover:
   `docs/superpowers/specs/2026-07-29-review-ui-design.md`,
   `docs/superpowers/specs/2026-07-29-cli-design.md`,
   `docs/superpowers/specs/2026-07-28-review-api-design.md`.

## Where we are

**`main` @ `cd464d5`. Phase 5 (the review UI) merged 2026-07-31** as a true
fast-forward from `5e4d708`. `feat/review-ui` is kept at its merge point
(`28f6c7a`), per the project convention that merged branches and SDD workspaces
are not cleaned up.

**Phases 0–5 are complete.** Foundations; the offline modules; the online wiring
(config → client factory → preprocess → triage → extract+repair → normalize →
score → route → eval); persistence (8 tables, migrations, repository, review
queue, 4-sheet XLSX); `process_receipt` + the RQ worker + the VLM guards; the
review API with session auth, roles and a machine upload key; the operator CLI;
and now the **review UI** — login, the review screen, editing across all 17
correctable paths, a strictly sequential `PATCH → complete → next`, a Playwright
acceptance test, and `scripts/verify.py`.

### Running it — this changed in Phase 5

- **There are two test suites.** `python -m pytest` (**844**, offline and
  Node-free — proven by running it with `node` stripped from `PATH`) and
  **Vitest in `frontend/`** (**170**).
- **`npm test` does NOT type-check.** A TypeScript error ships green through it.
  That trap fired three times in one milestone. Run `npm run typecheck` too.
- **`python scripts/verify.py` is the gate runner** — pytest, ruff, typecheck,
  vitest, build. It fails loudly naming the gate, and when `npm` is absent it
  prints a per-gate `SKIPPED` and still gates the Python half. **ADR-0017.**
- Lint is `python -m ruff check .` — bare `ruff` is not on PATH.
- CLI: `python -m receipts.cli <command>` — the console script needs the
  interpreter's `Scripts`/`bin` on `PATH`, which it is not on this machine.
- The e2e is run deliberately, not as part of the sweep:
  `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

### Git

- Default branch is **`main`**. Remote `origin` → `CDGYu/Receipt-Digitalization`,
  **private**.
- **Pushing `feat/*` branches is authorised.** **Ask before pushing `main`.**
- **`.kiro/` and `.github/workflows/` are gitignored and untracked.** GitHub
  Actions does not run; `scripts/verify.py` is the substitute, and **nothing
  runs the frontend gates on GitHub.**
- **`var/` is gitignored** — `STORAGE_ROOT` defaults to `var/blobs` and writes
  real receipt images there. Never stage one.

## Non-negotiables

`Decimal` on the money path (never `float`); deterministic, pure validation that
never mutates and never raises; stable rule IDs; prefer `null` over a confident
wrong value; **a full PAN never persisted**; nothing silently dropped (every
receipt reaches a terminal state); **a machine run never overwrites a `reviewed`
row**; no module-top import of an optional extra on any path reachable from an
entry point; structured output via tool-use; few-shot images first, target
receipt last; consistency runs never cached; `python -m pytest` stays **offline
and Node-free**.

**Frontend (ADR-0015):** money is a string end to end and
**`<input type="number">` and `valueAsNumber` are banned**; the browser stays
same-origin so **no `CORSMiddleware` is ever added**; SPA pages live under
`/app/*` and no API path moves.

## The work, in order

### 1. PAN hardening — the next task, already scoped

**Read the ledger's "NEXT TASK" section and ADR-0007 before touching
`_PAN_RE`.** It has produced a surprise on **both** of its last two widenings.

- **(a) Undocumented total leak.** A four-group PAN with a 5+ digit tail is
  stored **whole**: `'4111 1111 1111 11111'` (17), `'…111111'` (18),
  `'…1111111'` (19). The trailing group is `\d{1,4}`
  (`src/receipts/persist/repository.py`). Pre-existing and byte-identical under
  the old pattern. **Strictly worse than (b), and the only one the code's own
  comments do not record.**
- **(b) Documented partial leak.** More than four groups leaves seven digits
  clear: `'4111 1111 1111 1111 111'` → `'************1111 111'`. **The obvious
  fix is measured worse** — a fifth alternative lets
  `'4111 1111 1111 1111 9999 9999'` and `'4111.1111.1111.1111.1111'` through
  **whole**, because the long run is consumed and `_mask_pan` then rejects it
  for length. Any fix must be measured in **both** directions.
- **(c) A false sentence to fix in the same pass.** `ReceiptForm.tsx` asserts
  that a 13–19 digit PAN in four-group form with any of the six separators is
  masked. Falsified by (a). Bound it by the table it introduces, the way
  `serializers.py` already does.
- Also file alongside: a regression test binding the three recoverability
  properties the review UI's "Skip this receipt" button spends — a skipped
  receipt is still listed by `GET /receipts?status=needs_review`, still
  `PATCH`-able to `reviewed`, and still re-openable by `enqueue_review`. All
  three are true today; **none would go red if they stopped being.**

### 2. Phase 5 follow-ups, each a named piece of work

- **The five design §5 error-recovery behaviours that never shipped** — no
  logout control anywhere, no return-to-receipt after a 401, no inline
  field-level error on a 400 (one page-level alert instead), no distinct
  backend-down 503 state, no re-fetch-`next` on 403/404. The plan dropped design
  §5's error table wholesale, so no task owned any of them.
- **A read route for the `corrections` table.** The audit trail is write-only
  from the API's perspective — a reviewer cannot see the correction history of
  the receipt they are correcting, and an auditor needs database access.
  Additive; needs its own auth question.
- **An ASGI entry point and a deployment story.** `create_app` is a factory
  nothing calls, so this API has **no supported way to be served**.
  `scripts/serve_review_e2e.py` is deliberately e2e-scoped and says so — do not
  promote it without deciding the settings, session, storage and host policy on
  purpose.
- **An admin release for a claimed task** (`IN_PROGRESS` → `OPEN`). There is no
  inverse of a claim anywhere in the system.
- **The intermittent test.**
  `tests/test_cli_pipeline.py::test_inline_one_failing_receipt_does_not_abandon_the_others`
  failed twice in full runs and has not reproduced in ~20 since. **Test the
  hypothesis first:** this repo uses `pytest-randomly`, so order varies per run.
- Smaller parked items are listed in the ledger with rulings: `ReviewScreen.tsx`
  citing `queue.py:198-199` for writes at `:289-290`; no UI route reaching a
  skipped receipt; 405 responses under `/app` carrying no `Allow` header; two
  tabs of one reviewer silently overwriting each other; `ReviewScreen.tsx` past
  its size ceiling; `preventDefault()` firing on screens with no approve action.

### 3. Phase 6 — merchants & few-shot (P6.T1)

`merchants/{fingerprint,registry}.py`; inject verified few-shot examples with
**images first, target receipt last**; hints always end with "trust the image".
Measure top-10-merchant accuracy before/after. **Five things unblock here:**
wire semantic merchant+date+total dedupe into `process_receipt`; pass the same
hints/few-shot values into `_attempt_prompt_hash` or the stored hash drifts; set
`merchant_default_currency` at the marked plug-in point (`pipeline.py:227`); fix
the parked `image_phash` gap (`_persist_failure` never writes it, so a failed
receipt keeps `""` and can never serve as a dedupe **original**); and increment
`Merchant.receipt_count`, which nothing writes today. Merchant `VAT Reg. TIN` is
the strongest fingerprint on this corpus.

### 4. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (defined at `extract/extractor.py:295`, never called from
`pipeline.py`) into the pipeline for handwritten / low-legibility receipts, and
feed disputed fields into scoring. **Gate on `triage.is_handwritten`, never on
`document_type`** — this corpus is `INVOICE` + `MIXED`. Consistency runs are
never cached.

### 5. Phase 8 — calibration & eval-harness honesty

- **P3.T6 / P8.T1** — sweep the confidence threshold to hold auto-approval
  precision ≥99%, then fit the penalty weights from data into
  `config/rules.yaml`. **Blocked on ISSUE-001.**
- **P8.T2** — grow the held-out set until a ≥99% claim has a credible confidence
  interval. `receipts calibrate` refuses below `_MIN_APPROVED_SAMPLE` (5), so
  with 3 golden labels it correctly refuses today.
- **P8.T3 — close the artifact ban properly.** An **all-failed** eval run still
  persists `"auto_approval_precision": 1.0` to the results JSON even though the
  terminal prints `n/a`. Widening the field ripples into `_report_to_dict`, the
  committed schema, and `calibration_curve`. Also consider excluding `meta.*`
  from `field_accuracy`'s denominator.

### 6. Still open from earlier phases

- **P2.T2 — R060/R061 OCR grounding (DECISION NEEDED):** the two grounding rules
  need a raw text layer nothing produces. Options: have the model return the
  text it read / a cheap OCR pass / drop the rules. **This also gates bbox
  highlighting in the review UI** — an OCR pass would supply both.
- **Score `is_handwritten` from triage too** — `score_confidence` reads only
  `receipt.meta.is_handwritten`; on these printed-template forms a model may say
  `False` while triage says `MIXED`, so the −0.15 is missed on exactly the
  receipts that need it.
- **`is_receipt` has no consumer** — declared at `extract/schema.py:201`,
  referenced only in prompts. The §3 "reject garbage before you pay for
  extraction" gate does not exist. It returned `False` for valid invoices on
  both smoke-run receipts, so when the gate is built it must **not** hard-reject
  on it; route to review.
- **Blank pre-printed template rows** must not become line items (a sibling of
  R052) — Metro Oil's form pre-prints six fuel rows with one filled in.

### 7. Parked, with rulings (see the ledgers)

`apply_corrections` redacts **any** coerced text while `save_extraction` redacts
only two columns — the two sides should agree, and the review UI now makes this
reachable by a human. An auto-approving reprocess closes a review task a
reviewer had already claimed. **No login rate limiting**, and each attempt costs
a full scrypt derivation (~16 MB, ~57 ms), so `POST /auth/login` is an
unauthenticated CPU/memory amplifier as well as an enumeration surface.
`receipts eval`/`calibrate` still traceback without the `pipeline` extra while
the other six commands degrade cleanly. Reprocessing a `reviewed` receipt
records **no** `extraction_runs` — the transaction rolls back.

### 8. LAST — ISSUE-001, deferred by the user until the system is built

**Run the first real baseline.** Read `docs/KNOWN_ISSUES.md`; do not re-derive.
The smoke run proved the pipeline works end to end and that the safety machinery
does not auto-approve garbage — a bad extraction scored `0.000` and routed
urgent. It also proved `granite3.2-vision:2b` on CPU is too slow *and* too weak:
314 s triage + 1057 s extract at `max_edge=768`, extraction effectively empty.
Fix: point the baseline at a hosted tool-capable model (the commented-out Gemini
block in `.env` — **rotate that key first**, it was echoed in terminal output).
Until this runs there are **no measured accuracy numbers**, calibration stays
blocked, and **no precision claim is real**.

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation plan →
subagent-driven execution. One fresh **`general-purpose`** implementer per task,
briefed to read the real signatures first, work TDD, keep both suites green +
`python -m ruff` clean, and stage only its own files. After each task: review the
diff yourself, re-run the gates **independently**, then a task review, then
commit and append to the ledger. At the end of a milestone: a whole-branch review
on the strongest model, **one** consolidated fix wave, one scoped re-review, then
fast-forward merge. Merged branches and SDD workspaces are **kept**.

**Probe before dispatching.** Phase 5's plan was wrong about existing code
**eleven times** — including an acceptance test that would have failed against a
correct system, and a field set that did not match reality. The plan's prose is
reliable; its claims about existing APIs are not.

## Review standards this project learned the hard way — hold all of them

1. **Reviewers reproduce, they do not reason.** Every finding that mattered came
   from executing something.
2. **Every new test must be proven to fail** with its fix reverted.
3. **A test that asserts the absence of breakage cannot be proven by a RED run** —
   revert each guarantee separately instead.
4. **A mutation must change exactly one thing, or the result names the wrong
   cause.** A two-variable mutation reads exactly like evidence and points at
   the wrong variable.
5. **If a number can change without its sentence changing, it does not go in the
   comment.** One citation drifted `61 → 81 → 94 → 101`, once *inside the commit
   documenting the drift*; its replacement, a test count, rotted one commit
   later.
6. **A claim about what your own artefacts say is itself a claim requiring a
   command.** Grep for the word; do not recall it.
7. **Do not credit a tool with settling a question you have not put to it** —
   including `grep` and the float guard, which has no rule that can fire on
   arithmetic at all.
8. **A stub that does not reflect the write is a fixture bug that lies dormant
   until something reads the reply.**

And the environment lesson: **a green suite is not evidence that installed
software works.** Anything with an entry point gets run from outside the
repository as part of verification.

## Blocked on me (the user) — surface these, do not guess

1. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001,
   and therefore for all calibration.
2. **R060/R061 grounding (P2.T2)** — which also gates bbox highlighting.
3. **Whether GitHub Actions should run again** — `.github/workflows/ci.yml` is
   untracked, so nothing runs the frontend gates remotely. If yes, the workflow
   should call `scripts/verify.py` rather than re-listing the gates.

**Today's goal:** <FILL THIS IN — e.g. "PAN hardening", "the design §5 error
recovery rows", "start Phase 6", or "I've rotated the key — do ISSUE-001.">
