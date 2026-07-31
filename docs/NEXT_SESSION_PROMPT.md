You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone. ADR-0019 made the refresh part of
closing a milestone; **ADR-0021 makes it part of ending any session**, because
the last one ended with a branch part-built. This verification step is permanent.

**There is a feature branch in flight. Do not start anything new until it is
finished and merged.** See task 0.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, what is built,
   the environment, blockers, deferred and parked items. Its **"PAN grouping —
   the branch in flight"** section is the one that matters most this session.
2. **`.superpowers/sdd/2026-07-31-pan-grouping/progress.md`** — the ledger for
   the branch you are finishing: every measurement, the user's ruling, both
   task entries with what the controller re-verified itself, and the three
   plan-versus-reality defects found so far.
   `.superpowers/sdd/2026-07-31-pan-hardening/progress.md` holds the previous
   milestone's follow-ups; `.superpowers/sdd/2026-07-29-review-ui/progress.md`
   holds the Phase 5 parked items behind task 3. **Note: `.superpowers/` is
   gitignored, so nothing in it is findable by searching the tracked tree — you
   must open it by path.**
3. **`docs/adr/README.md`, then the ADRs it indexes (0001–0021).** Mandatory
   before touching the matching area:
   - **0001** `Decimal` money path — anything touching money.
   - **0018 then 0020** — **anything touching `_PAN_RE`, `_mask_pan`, or
     `redact_pan`. Read both with task 0 below.** 0018 supersedes 0007 on the
     masking rule; **0020 supersedes 0018 on the detector shape** and is the
     current record of which groupings are covered and which residual is
     accepted. 0007 still governs money integrity and bounded text and carries a
     dated correction.
   - **0006** repository conventions (injected session, **caller commits**,
     `ValueError` boundary) — anything writing to the DB.
   - **0011** terminal-state contract + VLM concurrency/cost guards.
   - **0012** review API: identity, the `pending` row, the persisted confidence
     breakdown, and **"a machine run never overwrites a `reviewed` row"**.
   - **0013** CLI contract, including `calibrate`'s three gates.
   - **0014** optional-dependency import discipline — **anything adding an
     import to a module reachable from an entry point.**
   - **0015** the review UI: same-origin serving, the `/app` prefix, the guarded
     static mount, money as a string in the browser. **Read with task 0's
     Task 3.**
   - **0016** `GET /review/next` resumes the caller's own in-progress task —
     anything touching `review/queue.py` or the claim lifecycle.
   - **0017** two test suites and `scripts/verify.py` — **read before believing
     a green test run.**
   - **0019 + 0021** session continuity — where state lives, the promotion rule,
     the two-position stamp, and why this snapshot must be verified rather than
     trusted.
   - **0002** provider abstraction · **0008** review-queue concurrency.
4. **`.kiro/steering/receipt-system.md`** — the always-on load-bearing rules.
   Still auto-loads and is on disk, but **gitignored and untracked**.
5. **`docs/superpowers/plans/2026-07-31-pan-grouping.md`** — the plan you are
   finishing. **Tasks 1 and 2 are done; Tasks 3 and 4 are not started.** Its
   prose is reliable; **its claims about existing code have been wrong three
   times already** (see task 0).
6. **`docs/superpowers/specs/2026-07-31-pan-grouping-design.md`** — §2.1 the two
   refused generalisations and why, §4 the full measured battery, §5 the residual
   as a number, §7 the prose sites Tasks 3–4 still owe.
7. **`IMPLEMENTATION_PLAN.md`** — the authoritative phased task list.
8. **`docs/KNOWN_ISSUES.md`** — ISSUE-001 (the deferred baseline), with its full
   diagnosis and exact resume steps. **Do not re-derive it.**
9. **`RECEIPT_SYSTEM_SPEC.md`** as needed: §6 data model (**eight** tables),
   §8.5 repair, §9 normalization, §10 validation/tolerance, §12 confidence +
   routing, §13 Excel, §14 function inventory (§14.8 repository, §14.9 review
   API, §14.10 the CLI), §15 milestones, §16 eval, §17 config, §18 traps
   (**PAN handling**), §19 DoD.
10. Older design docs, only if touching what they cover:
    `docs/superpowers/specs/2026-07-31-pan-hardening-design.md` (§1.2 the TIN
    constraint, §2.1 the ruling, §4 the measured battery),
    `docs/superpowers/specs/2026-07-29-review-ui-design.md`,
    `docs/superpowers/specs/2026-07-29-cli-design.md`,
    `docs/superpowers/specs/2026-07-28-review-api-design.md`.

## Where we are

**Two positions, and they are different — do not conflate them (ADR-0021).**

- **`main` @ `1d9f3e3`.** `origin/main` is `7deb3fb`, so **`main` is one commit
  ahead and UNPUSHED**. That commit is docs only, so the *code* on `main` is
  identical to `7deb3fb`. **Ask me before pushing `main`.**
- **`feat/pan-grouping` @ `a883df6`, four commits ahead of `main`, PUSHED.**
  This is where the work is.

**Phases 0–5 are complete, plus PAN hardening (merged).** The PAN grouping
milestone is **half-built on the branch**:

| commit | what |
|---|---|
| `d529b0f` | design doc, **ADR-0020**, ADR README |
| `b8666f0` | the implementation plan, four tasks |
| `348b509` | **Task 1** — the detector, its behavioural tests, five falsified prose passages |
| `a883df6` | **Task 2** — two structural guards, the worked-example pin, the residual pin, `_mask_pan`'s docstring |

**Gates at `a883df6`, re-measured by the controller, not taken from a report:**
`python scripts/verify.py` **all five PASS**; pytest **914/0/0/0** read from
junitxml; Vitest **170**. On `main` the pytest count is **864**.

### What shipped, and what it does not claim

`_PAN_RE` gained five fixed-shape alternatives — Diners `4-6-4`, Maestro and
legacy Visa `4-4-5`, and the `5-4-4-4`, `6-4-4-4`, `4-5-4-4` forms a hand-filled
slip produces — and the separator class gained `{1,2}`, because it matched exactly
one character so a doubled space defeated every separated alternative. Each new
alternative has a **fixed** digit total inside 13–19, so `_mask_pan`'s length
check stays unreachable **by construction**.

**It did not close the class, and saying so would be false.** Against the
plausible band (every group 4–7 digits, totalling 13–19, 97 shapes) this went from
7 compliant / 90 storing a whole card to **15 compliant / 76 storing a whole
card**. `4-4-6`, `4-5-4`, `5-4-4`, `6-6-4`, `5-5-4-4` and others **still store a
card in the clear**, pinned by
`test_redact_pan_still_stores_some_groupings_whole` so the gap reads as a
decision. ADR-0020 carries the number.

**The load-bearing lesson, and the reason the residual was accepted: coverage and
cross-boundary risk move together.** A generalised alternative was built, passed
the committed battery, and covered 80 of 97 shapes — then **leaked a full second
card**: given two adjacent Amex numbers it matched a `4-6-5-4` span of 19 digits,
which is *inside* range so `_mask_pan` accepted it, and because `re.sub` never
rescans inside a match, eleven digits of the second card survived in the clear.
An earlier form of the same idea **failed 13 committed battery tests** by silently
dropping 13- and 15-digit `4-4-4-N` cards. **Any shape added to `_PAN_RE`
requires the two-instance check, every time.**

**Alternation order is NOT load-bearing**, measured against expectation: `4-6-4`
placed ahead of `4-6-5` does not truncate Amex, because the trailing `(?!\d)`
rejects the truncated match. Do not preserve the committed order out of
superstition.

### Running it

- **There are two test suites.** `python -m pytest` (**914** on the branch, **864**
  on `main`; offline and Node-free) and **Vitest in `frontend/`** (**170**).
- **`npm test` does NOT type-check.** A TypeScript error ships green through it.
  That trap fired three times in one milestone. Run `npm run typecheck` too.
- **`python scripts/verify.py` is the gate runner** — pytest, ruff, typecheck,
  vitest, build. It fails loudly naming the gate, and when `npm` is absent it
  prints a per-gate `SKIPPED` and still gates the Python half. **ADR-0017.**
- **Piped pytest output can lose its final summary line in this environment.**
  It did so again this session, twice. The `superclaude` plugin attribution
  remains **unproven** (stripping it did not reproduce the clipping). Workaround
  regardless: use `--junitxml` and read the counts from the XML.
- Lint is `python -m ruff check .` — bare `ruff` is not on PATH.
- CLI: `python -m receipts.cli <command>` — the console script needs the
  interpreter's `Scripts`/`bin` on `PATH`, which it is not on this machine.
- The e2e is run deliberately, not as part of the sweep:
  `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

### Git

- Default branch is **`main`**. Remote `origin` → `CDGYu/Receipt-Digitalization`,
  **public**.
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

**PAN (ADR-0018 + ADR-0020):** the group-shape requirement in `_PAN_RE` is
load-bearing. Three of the four real corpus TINs are 14 digits, inside the PAN
window, and what keeps them silent is the asymmetry that **every alternative opens
with a group of at least four digits while every corpus TIN opens with three** —
now pinned across the whole shape space by
`test_pan_re_never_starts_a_match_at_a_three_digit_group`, not by the four
samples. **Never relax it toward "any run of 13+ digits."** Any `_PAN_RE` change
replays the **committed** battery in both directions, tests **two instances of
what it guards in one input**, and keeps
`test_every_pan_re_match_holds_between_thirteen_and_nineteen_digits` green.

**Frontend (ADR-0015):** money is a string end to end and
**`<input type="number">` and `valueAsNumber` are banned**; the browser stays
same-origin so **no `CORSMiddleware` is ever added**; SPA pages live under
`/app/*` and no API path moves.

## The work, in order

### 0. FINISH `feat/pan-grouping` — do this before anything else

Two tasks remain in `docs/superpowers/plans/2026-07-31-pan-grouping.md`. Both are
fully specified there; both are documentation-only in effect, but Task 3 requires
real measurement, not editing.

**Probe before dispatching. The plan has been wrong about existing code three
times, all three the controller's error, all three caught by an implementer who
read the code first:** its pattern snippet broke the `E501` lint gate as written;
it named three falsified prose passages where there were **five**; and it claimed
`from receipts.persist.repository import _PAN_RE` already existed in
`tests/test_repository.py` when **no test file imported that module at all**.
Assume a fourth defect is waiting in Tasks 3–4.

- **Task 3 — `frontend/src/review/ReceiptForm.tsx`, header comment only.** It
  names "the two shapes this masks (4-4-4-N, 4-6-5)"; there are now seven
  separated shapes. It also carries a table of `sent -> read` pairs that it
  *states* was measured through the real `PATCH` route on `receipt.date_raw`, one
  fresh receipt per row, read back with `GET /receipts/{id}`. **The new rows must
  be measured that way, not copied from a `redact_pan` call or from the design
  doc.** That file's own header warns the claim has been wrong twice, both times
  by generalising past what was measured. Build the harness from
  `tests/test_api_write.py`'s fixtures (`app`, `session_factory`, `storage`,
  `settings`, `submitted`). Re-measure two rows already in the table as a control;
  if they disagree, stop and report rather than writing a new false table.
  Spellings to add: `4111  1111  1111  1111`, `3055 930902 5904`,
  `6759 4111 00005`, `41111 1111 1111 2345`, `411111 1111 1111 2345`,
  `4111 11111 1111 2345`. No code, no JSX, no behaviour. Gates: `npm run
  typecheck` **and** `npm test`.
- **Task 4 — `docs/adr/0007-pan-redaction-and-money-integrity.md`.** Its
  `## Consequences` bullet still lists "a hash" unqualified alongside money and
  `card_last4`, while the `## Correction (2026-07-31)` section above it already
  records that masking a hash is not a property this function can be asked to
  have (~1 in 200 random 16-char hex values mask). A reader who jumps to
  Consequences misses it. ADRs are immutable, so extend the existing dated
  correction and add a pointer in the bullet — do not rewrite history. Ledger
  follow-up 6.
- **Then close the milestone properly:** whole-branch review on the strongest
  model, **one** consolidated fix wave, one scoped re-review, fast-forward merge
  into `main`, **and refresh `docs/MEMORY.md` + this prompt in the same session
  (ADR-0019/0021).** Merged branches and SDD workspaces are **kept**.

### 1. Bound the machine-path `currency` write

`save_extraction` writes `currency=receipt_meta.currency` **directly** into a
`String(3)` column. **Reproduced by measurement:** `ReceiptMeta.currency` is
`str | None` with no constraints; `Receipt.currency` is `String(3)`; the human
path (`receipt.currency` → `_bounded_optional_text`) raises
`ValueError: currency holds at most 3 characters, got 16`; and
`repository.py:464` passes the value through unguarded. SQLite stores an
over-long value silently; Postgres raises `DataError` — a receipt-killing
exception on the machine path. Same shape as leak (d): a guard the human path has
and the machine path lacks. Wire the bound into `save_extraction`.

### 2. Fix the intermittent test's fixtures — the diagnosis is done, stop re-deriving it

`tests/test_cli_pipeline.py::test_inline_one_failing_receipt_does_not_abandon_the_others`
is **NOT** flaky-by-ordering. **pytest-randomly is not installed** (pytest11
entry points on this machine, re-verified again: `anyio`, `superclaude`). It is a
**load-sensitive thread race in the test's own fixtures**: `_job` calls
`_png_bytes()`, which returns a **byte-identical** uniform 900×1400 PNG every
time, so three receipts share a sha256 and a phash → whichever commits first
makes another a dedupe duplicate → `REJECTED` where the test expects
`AUTO_APPROVED`. Reproduced 11/12 under six CPU burners in isolation on the
branch, 6/6 on `main` — pre-existing and branch-neutral. **Independently
corroborated last session:** a subagent hit it once, unprompted, and two later
full runs were clean. **Fix: distinct blobs per receipt in the fixture.** Do not
chase test ordering.

### 3. Phase 5 follow-ups, each a named piece of work

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
  nothing calls — **verified: there is no `app = create_app(...)` anywhere under
  `src/`**, and the only callers are tests plus the deliberately e2e-scoped
  `scripts/serve_review_e2e.py`, which says so in its own docstring. Do not
  promote that script without deciding the settings, session, storage and host
  policy on purpose.
- **An admin release for a claimed task** (`IN_PROGRESS` → `OPEN`). There is no
  inverse of a claim anywhere in the system.
- Smaller parked items are listed in the Phase 5 ledger with rulings:
  `ReviewScreen.tsx` citing `queue.py:198-199` for writes at `:289-290`; no UI
  route reaching a skipped receipt; 405 responses under `/app` carrying no
  `Allow` header; two tabs of one reviewer silently overwriting each other;
  `ReviewScreen.tsx` past its size ceiling; `preventDefault()` firing on
  screens with no approve action.

### 4. Phase 6 — merchants & few-shot (P6.T1)

`merchants/{fingerprint,registry}.py` — **verified: `src/receipts/merchants/`
does not exist, this is greenfield.** Inject verified few-shot examples with
**images first, target receipt last**; hints always end with "trust the image".
Measure top-10-merchant accuracy before/after. **Five things unblock here:**
wire semantic merchant+date+total dedupe into `process_receipt`; pass the same
hints/few-shot values into `_attempt_prompt_hash` or the stored hash drifts; set
`merchant_default_currency` at the marked plug-in point (**verified at
`pipeline.py:227`**); address the `image_phash` gap (a receipt that fails after
ingest keeps `""` and can never serve as a dedupe **original** — see MEMORY.md's
dated correction for the precise mechanism, which is *not* what earlier handoffs
claimed); and increment `Merchant.receipt_count`, which **nothing in `src/`
writes today (verified)**. Merchant `VAT Reg. TIN` is the strongest fingerprint
on this corpus.

### 5. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (**verified at `extract/extractor.py:295`, and verified to
have zero references in `pipeline.py`**) into the pipeline for handwritten /
low-legibility receipts, and feed disputed fields into scoring. **Gate on
`triage.is_handwritten`, never on `document_type`** — this corpus is `INVOICE` +
`MIXED`. Consistency runs are never cached.

### 6. Phase 8 — calibration & eval-harness honesty

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

### 7. Still open from earlier phases

- **P2.T2 — R060/R061 OCR grounding (DECISION NEEDED):** the two grounding rules
  need a raw text layer nothing produces. Options: have the model return the
  text it read / a cheap OCR pass / drop the rules. **This also gates bbox
  highlighting in the review UI** — an OCR pass would supply both.
- **Score `is_handwritten` from triage too** — `score_confidence` reads only
  `receipt.meta.is_handwritten`; on these printed-template forms a model may say
  `False` while triage says `MIXED`, so the −0.15 is missed on exactly the
  receipts that need it.
- **`is_receipt` has no consumer** — declared at **`extract/schema.py:201`
  (verified)**, referenced only in prompts. The §3 "reject garbage before you pay
  for extraction" gate does not exist. It returned `False` for valid invoices on
  both smoke-run receipts, so when the gate is built it must **not** hard-reject
  on it; route to review.
- **Blank pre-printed template rows** must not become line items (a sibling of
  R052) — Metro Oil's form pre-prints six fuel rows with one filled in.

### 8. Parked, with rulings (see the ledgers)

**The PAN grouping residual** — the shapes still stored whole after ADR-0020,
and the two priced routes to closing them (a shape table with a per-entry
two-instance gate, or a candidate-then-validate scan loop at O(n²), ~1715 ms on
40 KB). **You have not been asked to decide this yet; raise it as its own scoped
decision, do not fold it into something else.**

ADR-0018's **accepted false positives** remain: a 13–19 digit all-numeric
identifier; two column-scale amounts in one free-text value (measured:
`'1500 2000 2500 3000'` already fires at single-space, so the doubled-space
spelling `{1,2}` added is the *same* accepted class, not a new one); ~1-in-200
random 16-char hex hashes, which is why **no hash is ever routed through
`redact_pan`**; a whole-number 13–19 digit modifier amount. A reviewer confirming
a 13–19-digit `receipt.number` will see it masked and a spurious `corrections`
row minted — inherent to the policy. Leak (b) — a run of more than four groups
leaving its remainder in the clear — stays **accepted by ruling**, and all four
of its pinned cases were re-measured under the new pattern and are unchanged.

Also parked: an auto-approving reprocess closes a review task a reviewer had
already claimed. **No login rate limiting**, and each attempt costs a full scrypt
derivation (~16 MB, ~57 ms), so `POST /auth/login` is an unauthenticated
CPU/memory amplifier as well as an enumeration surface. `receipts eval`/
`calibrate` still traceback without the `pipeline` extra while the other six
commands degrade cleanly. Reprocessing a `reviewed` receipt records **no**
`extraction_runs` — the transaction rolls back. The `superclaude`
stdout-clipping attribution is **unproven** — re-measure before writing it
anywhere as fact.

### 9. LAST — ISSUE-001, deferred by the user until the system is built

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
session (ADR-0019).** **If a session ends mid-branch, refresh the pair anyway and
push the branch (ADR-0021).** Merged branches and SDD workspaces are **kept**.

**Probe before dispatching.** Phase 5's plan was wrong about existing code
**eleven times**; the PAN hardening plan repeated it (a wrong enum name, a
missing required argument, two false "this path is protected" claims, a
mis-attributed TIN); the PAN grouping plan has done it **three** times so far. The
plan's prose is reliable; its claims about existing APIs are not.

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
   later. Applied again last session: `_mask_pan`'s docstring stopped enumerating
   the per-shape digit totals rather than growing a second copy of a table that
   already sits above the pattern.
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
   a full second PAN through a green suite twice — and last session it was the
   probe that killed an otherwise-superior generalisation.
10. **A battery you write agrees with you.** Replay the *committed* battery in
    both directions before trusting a change — last session a generalisation that
    looked strictly tighter failed **13 committed tests** by silently dropping
    13- and 15-digit cards.
11. **Coverage and cross-boundary risk move together** (ADR-0020). A pattern wide
    enough to cover a new case is wide enough to tile across the gap between two
    adjacent instances of what it guards.

And the environment lesson: **a green suite is not evidence that installed
software works.** Anything with an entry point gets run from outside the
repository as part of verification.

## Blocked on me (the user) — surface these, do not guess

1. **May `main` be pushed?** It is one docs commit ahead of `origin/main` and has
   been since before last session.
2. **Do the public golden labels need scrubbing?** The repo is public and
   `eval/golden/labels/r00*.json` carry real third-party business names, TINs and
   addresses — which are also the exact values the PAN silent-case tests pin, so
   scrubbing is not free.
3. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001,
   and therefore for all calibration.
4. **R060/R061 grounding (P2.T2)** — which also gates bbox highlighting.
5. **Whether GitHub Actions should run again** — `.github/workflows/ci.yml` is
   untracked, so nothing runs the frontend gates remotely. If yes, the workflow
   should call `scripts/verify.py` rather than re-listing the gates.
6. **Whether to close the PAN grouping residual**, and by which of the two priced
   routes — see task 8.

**Today's goal:** <FILL THIS IN — the default is "finish `feat/pan-grouping`:
Tasks 3 and 4, then review and merge.">
