# Next-Session Kickoff Prompt

Paste the block between the `---` markers as the first message of the next
session, and **fill in the "Today's goal" line** — it is the one thing the
prompt cannot infer, and a placeholder left in place costs a round trip.

Last refreshed: **2026-07-31**, at `main @ 7deb3fb`. **The PAN hardening
milestone is complete and merged.** 864 Python + 170 Vitest, all five gates
green (`scripts/verify.py`), `main` and `feat/pan-hardening` both pushed and
identical to their origin refs.

---

You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone; ADR-0019 now makes the refresh
part of closing a milestone, and makes this verification step permanent.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, what is built,
   the environment, blockers, deferred and parked items.
2. **`.superpowers/sdd/2026-07-31-pan-hardening/progress.md`** — the PAN
   milestone ledger: every measurement, the user's rulings, and the
   **FOLLOW-UPS section at the end**, which is the source of tasks 1–3 below.
   The Phase 5 ledger (`.superpowers/sdd/2026-07-29-review-ui/progress.md`)
   still holds the parked items behind task 4. **Note: `.superpowers/` is
   gitignored, so nothing in it is findable by searching the tracked tree — you
   must open it by path.**
3. **`docs/adr/README.md`, then the ADRs it indexes (0001–0019).** Mandatory
   before touching the matching area:
   - **0001** `Decimal` money path — anything touching money.
   - **0018** the PAN masking policy — **anything touching `_PAN_RE`,
     `_mask_pan`, or `redact_pan`. Read it with task 1 below.** It supersedes
     0007 on the masking rule; 0007 still governs money integrity and bounded
     text, and carries a dated correction.
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
   - **0019** session continuity — where state lives, the promotion rule, and
     why this snapshot must be verified rather than trusted.
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
   `docs/superpowers/specs/2026-07-31-pan-hardening-design.md` (§1.2 the TIN
   constraint, §2.1 the ruling, §4 the measured battery),
   `docs/superpowers/specs/2026-07-29-review-ui-design.md`,
   `docs/superpowers/specs/2026-07-29-cli-design.md`,
   `docs/superpowers/specs/2026-07-28-review-api-design.md`.

## Where we are

**`main` @ `7deb3fb`, pushed — `origin/main` is identical. The PAN hardening
milestone merged 2026-07-31** as a true fast-forward from `ce98345`;
`feat/pan-hardening` is kept at its merge point and pushed, per the convention
that merged branches and SDD workspaces are never cleaned up.

**Phases 0–5 are complete, plus PAN hardening.** What that milestone shipped:
the detector's four-group alternative widened its trailing group `\d{1,4}` →
`\d{1,7}` — **one character, closing leak (a)**: a four-group PAN with a 5–7
digit tail (17–19 digits) is no longer stored whole. **Leak (b)** — more than
four groups leaves the remainder in the clear — **is accepted by the user's
ruling, not fixed**, and is pinned by test; both measured routes to closing it
were refused (the greedy rewrite swallowed a second adjacent card whole and ate
amounts; the scan loop was O(n²)). Redaction is now **default-on for every
extraction-sourced value `save_extraction` stores** — every scalar text column
plus the `modifiers` JSON — while system-minted values (`image_key`,
`image_phash`, `status`, `confidence`, `merchant_id`) are excluded
structurally, because masking an all-digit `image_phash` broke dedupe. Review
reasons are redacted at the sink (`enqueue_review`). The four corpus TINs are
pinned as silent cases; a two-table column walk with a fully-seeded fixture
(all 22 reachable extraction text fields) makes a new text column fail RED;
ADR-0018 records the policy and ADR-0007 carries a dated correction.

### Running it

- **There are two test suites.** `python -m pytest` (**864**, offline and
  Node-free) and **Vitest in `frontend/`** (**170**).
- **`npm test` does NOT type-check.** A TypeScript error ships green through it.
  That trap fired three times in one milestone. Run `npm run typecheck` too.
- **`python scripts/verify.py` is the gate runner** — pytest, ruff, typecheck,
  vitest, build. It fails loudly naming the gate, and when `npm` is absent it
  prints a per-gate `SKIPPED` and still gates the Python half. **ADR-0017.**
- **Piped pytest output can lose its final summary line in this environment.**
  The old "PowerShell clips it" attribution is unproven (a globally-installed
  `superclaude` pytest plugin is suspected, but stripping it did not reproduce
  the clipping). The workaround stands regardless: use `--junitxml` and read
  the counts from the XML.
- Lint is `python -m ruff check .` — bare `ruff` is not on PATH.
- CLI: `python -m receipts.cli <command>` — the console script needs the
  interpreter's `Scripts`/`bin` on `PATH`, which it is not on this machine.
- The e2e is run deliberately, not as part of the sweep:
  `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

### Git

- Default branch is **`main`**. Remote `origin` → `CDGYu/Receipt-Digitalization`,
  **private**. Everything is pushed and in sync as of the stamp above.
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

**PAN (ADR-0018):** the group-shape requirement in `_PAN_RE` is load-bearing —
three of the four real corpus TINs are 14 digits, inside the PAN window, and
are silent **only** because of the grouping. **Never relax it toward "any run
of 13+ digits."** Any change to `_PAN_RE` replays the committed battery in both
directions and tests **two instances of what it guards in one input**.

**Frontend (ADR-0015):** money is a string end to end and
**`<input type="number">` and `valueAsNumber` are banned**; the browser stays
same-origin so **no `CORSMiddleware` is ever added**; SPA pages live under
`/app/*` and no API path moves.

## The work, in order

### 1. PAN follow-up: the non-canonical grouping class — HIGH, already measured

The final whole-branch review found (pre-existing, never covered by any
battery): **a card grouped outside the two canonical shapes matches neither
alternative and is stored entirely in the clear** — 5-4-4-4, 6-4-4-4, 4-5-4-4,
Diners-style 4-6-4, Maestro 4-4-5. Measured: `'41111 1111 1111 2345'` (17
digits) → unchanged. Same class as leak (a). The **double-space separator**
(`'4111  1111  1111  1111'`) also stores whole — the likeliest spelling in a
handwritten corpus. Read the ledger's final-review entry and ADR-0018 first —
this regex has surprised on **three consecutive widenings**.

- The reviewer **measured a candidate fix** (enumerate the additional
  groupings as alternatives): 0 TIN regressions across all six TINs, 5/5 class
  members masked, 18 controls unchanged, both-instances cases masked, no ReDoS
  (7.1 ms @ 8000 groups). **Key insight: the TIN constraint blocks "any 13+
  digit run", NOT enumerating further specific groupings** — every real card
  grouping starts with a ≥4 group; every corpus TIN is 3-3-3-N.
- Fold into the same pass (both one-liners from the same ledger): pin
  ADR-0018's worked example `'4111 1111 1111 2345 678'` in the battery — the
  uniform-digit pinned cases cannot distinguish "matched region's last four"
  from "true card last four" — and qualify ADR-0007's Consequences bullet that
  still says "a hash" unqualified (dated-correction rules, ADR immutability).

### 2. Bound the machine-path `currency` write

`save_extraction` writes `currency=receipt_meta.currency` **directly** into a
`String(3)` column; `ReceiptMeta.currency` is an unconstrained `str | None`.
SQLite stores an over-long value silently; Postgres raises `DataError` — a
receipt-killing exception on the machine path. Same shape as leak (d): a guard
the human path has (`_bounded_optional_text`, wired only into
`_RECEIPT_FIELDS`) that the machine path lacks. Wire the bound into
`save_extraction`. Found during Task 3 pre-flight; recorded in the ledger.

### 3. Fix the intermittent test's fixtures — the diagnosis is done, stop re-deriving it

`tests/test_cli_pipeline.py::test_inline_one_failing_receipt_does_not_abandon_the_others`
is **NOT** flaky-by-ordering. **pytest-randomly is not installed** (pytest11
entry points on this machine: `anyio`, `superclaude` — re-verified 2026-07-31;
the old hypothesis in earlier handoffs is falsified). It is a **load-sensitive
thread race in the test's own fixtures**: three identical blobs + identical
extraction → whichever receipt commits first makes another a dedupe duplicate
→ `REJECTED` where the test expects `AUTO_APPROVED`. Reproduced 11/12 under six
CPU burners in isolation on the branch, 6/6 on `main` — pre-existing and
branch-neutral. **Fix: distinct blobs per receipt in the fixture.** Do not
chase test ordering.

### 4. Phase 5 follow-ups, each a named piece of work

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
- Smaller parked items are listed in the Phase 5 ledger with rulings:
  `ReviewScreen.tsx` citing `queue.py:198-199` for writes at `:289-290`; no UI
  route reaching a skipped receipt; 405 responses under `/app` carrying no
  `Allow` header; two tabs of one reviewer silently overwriting each other;
  `ReviewScreen.tsx` past its size ceiling; `preventDefault()` firing on
  screens with no approve action.

### 5. Phase 6 — merchants & few-shot (P6.T1)

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

### 6. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (defined at `extract/extractor.py:295`, never called from
`pipeline.py`) into the pipeline for handwritten / low-legibility receipts, and
feed disputed fields into scoring. **Gate on `triage.is_handwritten`, never on
`document_type`** — this corpus is `INVOICE` + `MIXED`. Consistency runs are
never cached.

### 7. Phase 8 — calibration & eval-harness honesty

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

### 8. Still open from earlier phases

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

### 9. Parked, with rulings (see the ledgers)

The old "the two redaction sides should agree" item is **closed** — that was
PAN hardening. What remains parked: ADR-0018's **accepted false positives**
(a 13–19 digit all-numeric identifier; two column-scale amounts in one
free-text value; ~1-in-200 random 16-char hex hashes, which is why **no hash
is ever routed through `redact_pan`**; a whole-number 13–19 digit modifier
amount) — a reviewer confirming a 13–19-digit `receipt.number` will see it
masked and a spurious `corrections` row minted, inherent to the policy. An
auto-approving reprocess closes a review task a reviewer had already claimed.
**No login rate limiting**, and each attempt costs a full scrypt derivation
(~16 MB, ~57 ms), so `POST /auth/login` is an unauthenticated CPU/memory
amplifier as well as an enumeration surface. `receipts eval`/`calibrate` still
traceback without the `pipeline` extra while the other six commands degrade
cleanly. Reprocessing a `reviewed` receipt records **no** `extraction_runs` —
the transaction rolls back. The `superclaude` stdout-clipping attribution is
**unproven** — re-measure before writing it anywhere as fact.

### 10. LAST — ISSUE-001, deferred by the user until the system is built

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
fast-forward merge — **and refresh `docs/MEMORY.md` + this prompt in the same
session (ADR-0019).** Merged branches and SDD workspaces are **kept**.

**Probe before dispatching.** Phase 5's plan was wrong about existing code
**eleven times**; the PAN plan repeated the pattern (a wrong enum name, a
missing required argument, two false "this path is protected" claims, a
mis-attributed TIN). The plan's prose is reliable; its claims about existing
APIs are not.

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
9. **Test a guard with two instances of what it guards in one input.** A
   scanner's failure mode lives at the boundary *between* two hits; a
   single-instance battery is blind to it by construction. That blind spot let
   a full second PAN through a green suite twice.
10. **A battery you write agrees with you.** Replay the *committed* battery in
    both directions before trusting a change — a 34-case hand-picked battery,
    passed in both directions, still missed a case the committed suite already
    had.

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

**Today's goal:** <FILL THIS IN — e.g. "the PAN grouping follow-up", "the
design §5 error rows", "fix the intermittent's fixtures", "start Phase 6", or
"I've rotated the key — do ISSUE-001.">
