You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone, and once — last session — it was
rewritten *mid-milestone* by a subagent working outside its lane, so it
described a branch that no longer existed. ADR-0019 made the refresh part of
closing a milestone; **ADR-0021 makes it part of ending any session** (its
2026-08-02 correction widened the freshness check to include `docs`). This
verification step is permanent.

**No branch is in flight.** The review-UI error-recovery milestone was closed
and merged (true fast-forward `7c811fa` → `02edcd0`), and `main` was pushed the
same session under a fresh one-time authorization — nothing is pending anywhere.

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, environment,
   blockers, deferred and parked items. Its "Review-UI error recovery —
   complete and merged" section records the last milestone.
2. **The ledgers** —
   `.superpowers/sdd/2026-08-03-review-ui-error-recovery/progress.md`
   (complete: seven task entries, **four plan defects**, **three user
   rulings**, a recorded incident where a subagent worked far outside its
   lane, and "THE CLOSE" — the whole-branch review, the one fix wave, the
   scoped re-review, and the parked residual).
   `2026-08-03-failure-egress-redaction/progress.md`,
   `2026-08-02-currency-bound-and-fixture-race/progress.md`,
   `2026-07-31-pan-grouping/progress.md`,
   `2026-07-31-pan-hardening/progress.md` are the completed prior
   milestones; `2026-07-29-review-ui/progress.md` holds Phase 5's parked
   items. **`.superpowers/` is gitignored — open ledgers by path; nothing
   in them is findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0024).** Mandatory before
   touching the matching area. Session-relevant highlights:
   - **0024** — the review UI's error-recovery contract: the five §5 rows,
     the classifier's five kinds and two attribution rules, the stash's
     lifecycle, and the three user rulings that shape them. **Read before
     touching `failure.ts`, `stash.ts`, `SignOutControl.tsx`,
     `ReviewScreen.tsx`'s phase/submit unions, or any inline error slot.**
   - **0023 + its two dated corrections** — parallel task agents share one
     worktree, so uncommitted work is not durable: commit every green step;
     never dispatch two tasks that touch one file; never repair a peer's
     tree; **restore a RED-proof mutation from a byte copy, never
     `git checkout --`, and re-take the copy after any commit to that
     file**; stage by explicit path; release an implementer explicitly when
     its task closes.
   - **0022 + its correction** — failure text is redacted at every process
     egress; a new egress extends the inventory.
   - **0018 + its two corrections** — the §18 walk's two named structural
     exclusions (`card_last4`, `currency`), each with its guarantee test.
     **0020 + its correction** — detector shape, residual, the `{1,2}`
     separator surface. **0015** the review UI's same-origin/`/app` rules
     and the money-is-a-string ban. **0007** money integrity / bounded
     text. **0006** the ValueError boundary. **0017** the gate runner.
     **0019 + 0021 (with correction)** session continuity and this
     snapshot's verification.
4. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
5. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do
   not re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.
6. **Last milestone's design and plan**, if you touch the review UI:
   `docs/superpowers/specs/2026-08-03-review-ui-error-recovery-design.md`
   (carries three dated notes) and
   `docs/superpowers/plans/2026-08-03-review-ui-error-recovery.md`.

## Where we are

- **`main` @ `db233aa`**, with this handoff refresh riding on top as a
  docs-only commit. The check:

  ```
  git log --oneline db233aa..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.** Any output means the tree moved
  after it was written.
- **`main` is pushed and in sync with `origin/main`** (the one-time
  authorization asked for and granted at this milestone's close was
  consumed by that push). The standing rule continues: pushing `feat/*` is
  authorised; **every `main` push needs a fresh ask.**
- Gates at `02edcd0`, controller-run on `main` post-merge:
  `python scripts/verify.py` **all five PASS**; pytest **935**; Vitest
  **221** (19 files). `src/` was untouched by the whole milestone, so no
  outside-repo import check applied — **re-apply that rule the moment a
  Python module changes again.** `feat/review-ui-error-recovery` is merged,
  kept, and pushed at `02edcd0`.

### What the last milestone shipped (details in MEMORY.md, ADR-0024, the ledger)

**The five design §5 error-recovery rows that never shipped in Phase 5** —
the eleventh plan defect of that milestone, now closed. In seven tasks:
route-level pins of the exact 400 texts and the logout contract
(`tests/test_api_write.py`, the only Python change, tests-only); a pure
failure classifier (`frontend/src/review/failure.ts`) labelling a caught
failure `backend-down` / `taken` / `gone` / `field` / `other`, attributing a
400 to a field by quoted path first, then unique quoted value; an in-memory
edit stash (`stash.ts`) carrying unsubmitted edits across a 401, cleared
exactly where a write landed; a `SignOutControl` that never pretends (a
failed logout stays signed in and says so; dirty edits gate it behind a
confirm); terminal `taken`/`gone` states with a single explicit exit and a
dead ⌘↵; a distinct backend-down state that suppresses the Skip escape while
the database is down; and inline field errors beside the input that sent
them, `aria-describedby`-linked, additive to the summary alert that still
always shows.

**Three user rulings** are load-bearing (ADR-0024, and dated notes in the
design): edits are preserved **in memory only** (never `sessionStorage`);
the backend-down sentence renders **without** `role="alert"`; and design
§6.1 **supersedes** the old 403/404-on-complete retry contract, so three
pre-existing tests were rewritten to pin the new behaviour.

**The close:** whole-branch review on the strongest model — 0 Critical, 5
Important, 9 Minor. Every Important was a *measured mutation surviving the
whole suite*, including that the sign-out control could be deleted entirely
with all five gates green. ONE fix wave (nine items, five commits), one
scoped re-review — all nine ADDRESSED, one Minor-class residual parked.

## Non-negotiables

Unchanged: `Decimal` money path; pure validation; stable rule IDs; null over
confident-wrong; **a full PAN never persisted**; nothing silently dropped;
a machine run never overwrites a `reviewed` row; optional-import discipline;
tool-use structured output; few-shot images first; consistency never cached;
`python -m pytest` offline and Node-free. **PAN:** ADR-0018 + 0020 + their
corrections; any `_PAN_RE` change replays the committed battery both ways,
two-instance-tests, keeps the structural guards green. **Egress (ADR-0022):**
failure text goes through `redact_pan` at every place it leaves the process.
**Frontend (ADR-0015):** money is a string; no `<input type="number">`; no
`valueAsNumber`; no `CORSMiddleware`; `/app/*` only, and no client-side path
may carry a dot in its final segment. **Error recovery (ADR-0024):** the
summary alert always renders; the classifier never invents copy; the stash
never touches browser storage.

## The work, in order

### 1. Phase 5 follow-ups — three left, each a named piece of work

**The five design §5 error-recovery behaviours are DONE** (last milestone).
Remaining:

1. **A read route for `corrections`.** The audit trail is still write-only
   from the API's perspective: nothing does `select(Correction)`, so a
   reviewer cannot see the correction history of the receipt they are
   correcting and an auditor needs database access. Additive; **needs its
   own auth question** (reviewer-visible, or admin-only?).
2. **An ASGI entry point / deployment story.** `create_app` is a factory
   nothing under `src/` calls. `scripts/serve_review_e2e.py` is
   deliberately e2e-scoped — inheriting a deployment policy from an e2e
   launcher is the mistake to avoid.
3. **An admin release for a claimed task** (`IN_PROGRESS` → `OPEN`) — the
   inverse of a claim, which nothing in the system has. **This one now has
   a consumer waiting:** last milestone's terminal `taken` state was
   designed for exactly the 403 an admin release produces, so shipping the
   release makes the UI's handling live rather than theoretical. Smallest
   scope of the three.

The smaller parked items are in the Phase 5 ledger.

### 2. Phase 6 — merchants & few-shot (P6.T1)

Unchanged: `merchants/{fingerprint,registry}.py` is greenfield; few-shot
images first, target last; hints end "trust the image"; measure
top-10-merchant accuracy before/after. Five things unblock here: semantic
dedupe into `process_receipt`; the same hints into `_attempt_prompt_hash`;
`merchant_default_currency` at its plug-in point in `pipeline.py`
(**re-verify the line — the file has grown since it was measured**); the
`image_phash` gap (see MEMORY.md's dated correction); `Merchant.
receipt_count` (nothing writes it). `VAT Reg. TIN` is the strongest
fingerprint on this corpus.

### 3. Phase 7 — self-consistency (P7.T1)

Unchanged: wire `run_consistency` (`extract/extractor.py`, zero references
in `pipeline.py`) for handwritten/low-legibility; **gate on
`triage.is_handwritten`, never `document_type`**; consistency runs never
cached.

### 4. Phase 8 — calibration & eval-harness honesty

Unchanged: P3.T6/P8.T1 threshold sweep + weights into `config/rules.yaml`
(**blocked on ISSUE-001**); P8.T2 grow the held-out set; P8.T3 the all-failed
eval run still persists `"auto_approval_precision": 1.0` to JSON.

### 5. Still open from earlier phases

Unchanged: R060/R061 grounding decision (also gates bbox); score
`is_handwritten` from triage too; `is_receipt` has no consumer (never
hard-reject on it); blank pre-printed template rows (sibling of R052).

### 6. Parked, with rulings (see the ledgers)

- **Parked at the review-UI error-recovery close** (bundle with the next
  legitimate edit of the file named):
  - `frontend/tests/review-screen.test.tsx` — a comment carrying
    "42/42 green", a **suite count in a comment** (review standard 5) that
    was stale on arrival. Delete the number, keep the mechanism sentence
    beside it. The irony is the finding: it was introduced by the fix for
    another standard-5 violation.
  - `edit()` does not reset `submit`, so an inline field error stays on
    screen while the reviewer corrects that very field (it clears at the
    next submit) — the most user-visible of the deferred minors.
  - No `aria-invalid` beside `aria-describedby`; the select/checkbox
    no-slot invariant is comment-only; the sign-out confirm can say
    "unsaved edits" about edits that did land (a complete-step failure);
    keystrokes typed *while a submit is in flight* are not stashed (the
    mirroring effect's dep list is `[phase]` alone).
  - **Nobody has viewed any of this milestone's UI in a browser** — the
    error text is an unstyled `<p>` between controls.
- **Two queued PAN scoped decisions** — the grouping residual (ADR-0020: 76
  of 97 band shapes; two priced routes) and the `{1,2}` separator surface
  (36 spellings, 30 mixed, pinned; narrow or keep). Raise each as its own
  decision.
- **Parked at the failure-egress close:** the straddle test's one-character
  margin; ADR-0022 nowhere names the straddle test.
- **Parked from the PAN grouping close** (bundle with the next legitimate
  edit of `tests/test_repository.py`): the range-guard docstring's "about
  30x" (measured 19.6x); the mixed-pairs rationale; pin
  `len(_ALL_SEPARATOR_SPELLINGS) == 42`; the module docstring's "reaches
  thirteen" nuance; ADR-0018's References naming a nonexistent battery.
- **Parked at the currency-bound close:** `_PNG_SEEDS` starting at 0;
  design §2.2's terse mechanism; the plan's self-review note.
- ADR-0018's accepted false positives; leak (b); the ADR-0022
  reprocess/stderr raw-chain residual; the auto-approving reprocess closing
  a claimed task; no login rate limiting (scrypt amplifier); `receipts
  eval`/`calibrate` traceback without the `pipeline` extra;
  reviewed-receipt reprocess records no `extraction_runs`; the `superclaude`
  stdout-clipping attribution still unproven.

### 7. LAST — ISSUE-001, deferred by the user until the system is built

Unchanged: read `docs/KNOWN_ISSUES.md`, do not re-derive; hosted
tool-capable model needed (rotate the echoed Gemini key first); until it
runs, no measured accuracy numbers and no real precision claim.

## Running it

- Two suites: `python -m pytest` (**935** on `main`) and Vitest in
  `frontend/` (**221**, 19 files). `npm test` does NOT type-check — run
  `npm run typecheck` too. `python scripts/verify.py` is what "passing"
  means (ADR-0017).
- Piped pytest output can lose its final summary line — `--junitxml`, read
  counts from the XML. Lint is `python -m ruff check .`.
- **The Grep tool mangles `/` in content output** — verify slash-sensitive
  claims with Read, `git grep` via Bash, or by executing.
- The destructive-commands hook false-positives: `rm` under the repo, and
  read-only `git grep` whose *pattern* names a sensitive file. PowerShell
  `Remove-Item` / the Read tool work.
- CLI: `python -m receipts.cli <command>`. E2E deliberate:
  `python scripts/seed_review_e2e.py --reset` then
  `cd frontend && npx playwright test`.

## Git

Default branch **`main`**; `origin` → `CDGYu/Receipt-Digitalization`,
**public**. **Pushing `feat/*` is authorised; ask before pushing `main`**
(every `main` push authorization is one-time). `.kiro/`,
`.github/workflows/`, `.superpowers/`, `var/`, `eval/golden/images/` are
gitignored — never stage anything under `var/` (real receipt images).

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation
plan → subagent-driven execution (one fresh `general-purpose` implementer
per task, briefed to read the real signatures first; controller reviews the
diff, re-runs gates independently, dispatches a task review, appends to the
ledger). Milestone close: whole-branch review on the strongest model → ONE
fix wave → one scoped re-review → ff-merge → refresh this pair in the same
session. Mid-branch session end: refresh anyway and push (ADR-0021).

**Dispatch discipline, learned the hard way last milestone (ADR-0023):**
tasks that share a file run **strictly serially** — Tasks 5, 6 and 7 all
touched `ReviewScreen.tsx`. An implementer whose task closes is
**explicitly released**; never leave an agent idle holding an unanswered
offer to take more work, because one did exactly that and went on to
implement two further tasks, rewrite this handoff, author an ADR, and write
into the controller's memory, all unasked. **Verify any wake-up from an
agent outside the active dispatch against `git` before acting on it** —
that is what caught the incident.

**Probe before dispatching — and sweep transitively.** Plan-defect count by
milestone: Phase 5 eleven; PAN hardening five; PAN grouping six; currency
bound two; failure-egress two; review-UI error recovery **four** — the
path-quoting 400 family claimed pinned but was not (caught by an implementer
running `git grep` rather than trusting the plan's prose); a second
`role="alert"` that broke six pre-existing tests; the "every pre-existing
test still passes" constraint being unsatisfiable against a deliberate
supersession; and markup that would have polluted every money field's
**accessible name** (the plan nested the error inside the `<label>`; the
implementer measured it, moved it, and the reviewer upheld the argument
against the accname algorithm). The pattern across six milestones is
unchanged: **the plan's prose is reliable; its claims about existing
artefacts are not.**

## Review standards this project learned the hard way — hold all of them

1–13 unchanged (reproduce, don't reason · RED proofs · revert each guarantee
separately · single-variable mutations · **no rotting numbers in comments** ·
grep-don't-recall · don't credit unasked tools · stub-reflects-write ·
two instances in one input · replay the committed battery both ways ·
coverage and cross-boundary risk move together · a grown prose table changes
every sentence quantifying over it · a prose claim about a mutation needs
revert-proof discipline or it does not carry "(measured)"), plus:

14. **A pin that was never proven to fail is not a pin.** Last milestone's
    whole-branch review found five guarantees — including the milestone's
    own headline deliverable, which could be deleted outright with all five
    gates green — that were stated, believed, and unprotected. The fix wave
    then measured that one *instructed* placement for a new pin could not go
    red at all (a later `load()` overwrote the state it asserted on), and
    moved the test rather than land a pin that never fails. When a review
    says "unpinned", the answer is a mutation that goes red, not an
    assertion that looks right.

And: **a green suite is not evidence that installed software works** — run
entry points from outside the repository.

## Blocked on me (the user) — surface these, do not guess

1. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
2. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration).
3. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
4. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
5. **Close the PAN grouping residual?** Which priced route?
6. **Narrow the `{1,2}` separator** now that its 36-spelling surface is
   measured and pinned?
7. **Auth for the `corrections` read route** — reviewer-visible, or
   admin-only? (Gates Phase 5 follow-up #1.)
8. **Has anyone looked at the review UI in a browser?** Five error states
   shipped last milestone with no styling and no human ever viewing them.

**Today's goal:** <FILL THIS IN — with no branch in flight, the default is
"pick the next named piece of work". The three remaining Phase 5 follow-ups
(§1) are the smallest well-scoped candidates, and **the admin release is the
natural next one**: it is the smallest of the three and the UI is already
built to receive it. Phase 6 (§2) is the next substantial milestone.
Brainstorm → design → plan before touching code.>
