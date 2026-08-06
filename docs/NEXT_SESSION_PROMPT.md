You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions, once by a whole milestone, once rewritten *mid-milestone*
by a subagent working outside its lane, and once carrying two sentences that
contradicted each other about whether `main` was pushed. On 2026-08-05 its own
verification step caught two further defects in it — a branch count wrong in
four places, and a heading that contradicted its own body. ADR-0019 made the
refresh part of closing a milestone; **ADR-0021 makes it part of ending any
session.** This verification step is permanent.

---

# ⚠️ A BRANCH IS IN FLIGHT. This is a mid-milestone handoff.

**`feat/review-ui-styling`**, seven commits off `main@1314485`. `main` itself is
untouched, pushed, and in sync with `origin/main`.

**Tasks 1 and 2 of six are done; 3, 4, 5 and 6 are not started.** Task 2 was in
**fix round 5 of 5** when the session ended — check whether it landed:

```
git log --oneline 41d01ab..feat/review-ui-styling
git status --short          # a modified Value.tsx may be a live mutation
```

**If the tree is dirty, do not "clean" it.** ADR-0023: never repair a peer's
tree. A modified `frontend/src/ui/Value.tsx` with no commit after `41d01ab`
means round 5's `className` deletion mutation was mid-flight. Restore from the
committed blob rather than guessing, and check the ledger first.

---

## Reading order

1. **`docs/MEMORY.md`** — current state, decisions already made, environment,
   blockers, deferred and parked items.
2. **The in-flight ledger** —
   `.superpowers/sdd/2026-08-05-review-ui-styling/progress.md`. **Read this
   before touching the branch.** It carries every plan defect, every mutation,
   the controller rulings, and the three carry-forwards Task 3 must honour.
   Completed milestone ledgers sit beside it (`2026-08-05-admin-ui-backend-routes`,
   `2026-08-04-admin-release`, `2026-08-03-*`, `2026-08-02-*`, `2026-07-31-*`,
   `2026-07-29-review-ui`). **`.superpowers/` is gitignored — open ledgers by
   path; nothing in them is findable by searching the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0027).** Mandatory before
   touching the matching area. Session-relevant:
   - **0027** — the review UI's design system: light default, CSS Modules,
     `@fontsource` never a CDN, a pathname switch not React Router, and
     **`null` ≠ `0` ≠ empty**. **Read before writing any CSS or rendering any
     extracted value.** Its Consequences section names what is still owed.
   - **0026** — `/auth/me` and `/review/tasks`; the privacy property is
     *derived, not structural*, and **not closed**.
   - **0024** — the error-recovery contract. **Exactly one `role="alert"` on
     screen.** Styling must not disturb it.
   - **0015** — money is a string; `<input type="number">` and `valueAsNumber`
     are banned; same-origin, `/app/*` only.
   - **0023 + its two dated corrections** — parallel agents share one worktree.
   - **0025** admin release · **0022** failure-text egress · **0018 + 0020**
     PAN · **0012** auth and the persisted breakdown's `NULL` vs `[]` ·
     **0006** the ValueError boundary · **0017** the gate runner ·
     **0019 + 0021** session continuity.
4. **`docs/superpowers/specs/2026-08-05-review-ui-design-system.md`** — the
   design. **§2** records three deliberate overrides of the generated system;
   **§4** is the null rule; **§9** the four settled rulings.
   `design-system/receipt-review/MASTER.md` is the raw generated output.
5. **`docs/superpowers/plans/2026-08-05-review-ui-styling.md`** — the plan
   under execution. Tasks 3–6 are there in full.
6. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
7. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do
   not re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.
8. **If you open `docs/superpowers/plans/2026-08-05-admin-ui-backend-routes.md`,
   read its "Dated defect log" at the bottom FIRST.** Five of that plan's nine
   defects are still in its body — plans are dated historical records here and
   do not self-amend. One reached the shipped tree once already, precisely
   because it was re-derived from the plan instead of checked against the code.

---

## Where we are

- **`main` @ `1314485`, pushed, in sync with `origin/main`.** Untouched by the
  in-flight branch. Every `main` push needs a fresh ask; the last was granted
  and consumed on 2026-08-05.
- **All 13 merged `feat/*` branches are pushed** (audited:
  `git branch --no-merged main` was empty, every branch +0 commits).
  `feat/review-ui-styling` is the fourteenth and is the one in flight.
- **Freshness check** — run it before trusting anything above, using the commit
  named in `docs/MEMORY.md`'s "Last updated" line:

  ```
  git log --oneline <STAMP>..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.**
- Gates on the branch at `41d01ab`: `python scripts/verify.py` **all five
  PASS**; pytest **979** (unchanged — no Python touched); Vitest **258** across
  21 files, up from 221 on `main`.

---

# THE WORK, IN ORDER

## 1. FINISH THE IN-FLIGHT MILESTONE — `feat/review-ui-styling`

Plan: `docs/superpowers/plans/2026-08-05-review-ui-styling.md`.
Lanes: **1 → 2 → {3 ∥ 4} → 5 → 6.** Tasks 1 and 2 are done.

### 1.1 Close out Task 2 (fix round 5 of 5)

If round 5 has not landed, resume or re-dispatch with exactly two items —
**do not widen the scope**:

- **IMPORTANT: `className={styles.notExtracted}` is deletable with every test
  green.** Deleting it at `Value.tsx:59` leaves the whole suite passing with
  §4's paint entirely gone. One token, zero contrivance. Rendering tests read
  `textContent`, role and accessible name; the class guard only checks
  `referenced ⊆ declared`, so *dropping* a reference is invisible. Fix is one
  source-text assertion —
  `referencedClasses(read('ui/Value.tsx')).has('notExtracted')` — symmetric
  with the existing `declaredClasses` check. **It does not need a browser
  pass**, contrary to what the task report says.
- **MINOR: the property docblock is orphaned from its function.** Two JSDoc
  blocks sit back to back with no code between, so tooling binds the nearer one
  and `declarationsIn`'s 60-line guarantee is attached to no declaration.

**Round 5 is the cap.** Anything still open after it gets a ruling in the
ledger, not another dispatch.

### 1.2 Task 3 — style the review screen

`frontend/src/review/*` + `SignOutControl`. **`className` only — change no
other JSX.** If a component needs restructuring to be styleable, stop and
report rather than reshaping markup the tests assert against.

**Three carry-forwards this task MUST honour** (all in the ledger):

1. **`Value` has no consumer, and structurally cannot deliver §4 on this
   screen** — every one of the 17 correctable paths is a form *control*, never
   a `Value`. §4 specifies the input half separately as `value=""` **with
   `placeholder="—"`**, and `placeholder` appears **zero** times in
   `frontend/src`. **A null total renders as a blank box today.** Closing this
   is the first job of the task.
   **The 17 are sixteen `<input>`s and one `<select>`** — 8 text, 6 money, one
   `<select>` (Legibility), two checkboxes — so `placeholder` reaches **14** of
   them: a closed option list and a checkbox have no empty state. ADR-0027's
   body says "is an `<input>`" and is **wrong**; it carries a dated correction
   (2026-08-06). `ReceiptForm.tsx:175` had it right all along — "seventeen
   *controls*".
2. **`ConfidenceRail.tsx:62` already renders `{confidence ?? '—'}`** with no
   accessible name, no `--color-null` and no border — an uncoordinated second
   copy of half the rule. Convert it to `Value` first.
3. **The currency prefix and `autoComplete` (design §5.1) are UNOWNED.**
   Task 2 was forbidden prop changes and refused correctly, reasoning that
   `receipt.currency` is a per-receipt correctable field so a hardcoded symbol
   would mislabel. **Controller ruling: assigned to Task 3, widening its file
   list to include `MoneyInput.tsx`.**

Also: `LineItemsTable.tsx:109` still paints the focused row raw `#fffbe6`;
`--color-surface-active` now exists for it (pale blue, deliberately not yellow
— amber is reserved for WARN). And **Task 3 sets `text-align: right` on the
`<td>`**; `Value` deliberately does not, because `text-align` is inert on an
inline span.

**Do not disturb ADR-0024's single-`role="alert"` contract.** A second alert
broke six tests once already, in the milestone that wrote the contract.

### 1.3 Task 4 — the `/app/admin` surface

`frontend/src/admin/*`, `api/admin.ts`, `route.ts`, `main.tsx`, `session.ts`.

**`vite.config.ts` is NO LONGER Task 4's** — the plan's Step 1 is already done
(`2689635`, 2026-08-06). Its comment did claim to be "cross-checked against
every route `create_app` registers" while listing 13 of 16; the three missing
were `GET /auth/me`, `GET /review/tasks` and `POST /review/{id}/release`. The
functional `API_PREFIXES` array was always fine — it matches by prefix — so the
claim was the defect, never the proxy. **Drop the file from Task 4's permitted
set**; that also removes the only overlap Task 4 had with anything else.

**The empty state must name its scope** (ADR-0026): a reviewer sees a filtered
list, so a bare "No tasks" would read as a broken queue. Reviewer → "No open
tasks, and none assigned to you"; admin → "No tasks".

Tasks 3 and 4 **share no file** and may run in either order, but `main.tsx`
belongs to 4 and is the one file a careless 3 might reach for.

### 1.4 Task 5 — the browser pass nobody has ever done

**This closes a two-milestone-old gap: no human has opened any of this UI.**
Build, seed a real database, serve, and capture every surface at **375, 1024,
1440px** in **both themes**: login; the review screen with null fields;
findings at all three severities; each of the five ADR-0024 error states; the
admin surface with tasks; and the admin surface empty, as a reviewer.

**Report findings; do not fix them.** A pass that quietly repairs leaves no
record of what was wrong. **Lay down no pixel baselines** — a first-ever visual
pass has nothing to diff against, and a baseline from unreviewed output pins
whatever is broken.

Check specifically: is a **null field visibly different from a zero**? Is the
money column aligned on the decimal at every width? Do severity colours survive
dark mode at 4.5:1? Does anything scroll horizontally at 375px? Are focus rings
visible in both themes? Is the receipt image legible against its surround?

### 1.5 Task 6 — absorb the findings

**ADR-0027 is already written and Accepted.** Task 6 therefore becomes:
**append a dated note recording what the browser pass found**, since that is
the first evidence this project has about how any of its UI actually looks. Do
**not** edit 0027's body — ADRs are immutable here.

### 1.6 Then close the milestone

Whole-branch review on the strongest model → **ONE** fix wave → one scoped
re-review → ff-merge → refresh this pair in the same session → **ask before
pushing `main`.**

---

## 2. Phase 5 follow-ups — two left

1. **A read route for `corrections`.** Nothing does `select(Correction)`, so a
   reviewer cannot see the correction history of the receipt they are
   correcting and an auditor needs database access. **Blocked on an auth
   ruling.** An answer was given on 2026-08-05 — *"both, scoped differently:
   reviewers see corrections for the receipt they hold, admins see any
   receipt's"* — **but it arrived alongside a system notice disclaiming it as
   user input and was never restated. Re-confirm it verbatim before designing
   the route.**
2. **An ASGI entry point / deployment story.** `create_app` is a factory
   nothing under `src/` calls. `scripts/serve_review_e2e.py` is deliberately
   e2e-scoped — inheriting a deployment policy from an e2e launcher is the
   mistake to avoid. **The only item that can start with no ruling.**

## 3. THE ONE RESIDUAL — pre-existing, known false, NOT fixed

**`src/receipts/review/api.py`'s signed-blob handler claims: "This is the one
unauthenticated route in the service."** False. Measured by building the route
table from `create_app` and reading each route's resolved dependant tree:
`GET /health`, `POST /auth/login`, `POST /auth/logout` and the `/app` mount are
also reachable with no session — **five**, or **nine** with `DOCS_ENABLED=true`.

Same defect class as ADR-0026's own Important #9, in the very file that finding
cited. Pre-existing on `main` since `130b202`. **Fix with the next legitimate
edit of `api.py`; do not open a branch for it.** Apply review standard 17 when
you do — answer the universal by enumerating, not by arguing.

## 4. Phase 6 — merchants & few-shot (P6.T1)

`merchants/{fingerprint,registry}.py` is greenfield; few-shot images first,
target last; hints end "trust the image"; measure top-10-merchant accuracy
before/after — **blocked on ISSUE-001**, so Phase 6 can be built but not
validated. Five things unblock here: semantic dedupe into `process_receipt`;
the same hints into `_attempt_prompt_hash`; `merchant_default_currency` at its
plug-in point in `pipeline.py` (**re-verify the line — the file has grown**);
the `image_phash` gap; `Merchant.receipt_count` (nothing writes it).
`VAT Reg. TIN` is the strongest fingerprint on this corpus.

## 5. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (`extract/extractor.py`, zero references in
`pipeline.py`) for handwritten/low-legibility; **gate on
`triage.is_handwritten`, never `document_type`**; consistency runs never cached.

## 6. Phase 8 — calibration & eval-harness honesty

P3.T6/P8.T1 threshold sweep + weights into `config/rules.yaml` (**blocked on
ISSUE-001**); P8.T2 grow the held-out set; P8.T3 the all-failed eval run still
persists `"auto_approval_precision": 1.0` to JSON.

## 7. Still open from earlier phases

R060/R061 grounding decision (also gates bbox); score `is_handwritten` from
triage too; `is_receipt` has no consumer (never hard-reject on it); blank
pre-printed template rows (sibling of R052).

## 8. Deferred, with rulings

- **From the styling branch** (full list in its ledger): the class-name guard's
  bounded property and its three residual leaks — harmless-but-inexact
  (`:is`/`:where`), harmful-but-absurd (`:not(…, .mark) { color: … }` is
  self-contradictory CSS), loud-and-safe (`@import` before the first rule).
  **Parked with a ruling; do not spend a round on them.** Also: token *values*
  are unpinned in the light block; `declaredClasses` matches `.name` outside
  selector position; `block()` assumes flat rule bodies.
- **From the admin-UI-routes milestone:** 20 Minor findings, triaged as safe.
  `GET /receipts`' `has_more` is **unpinned in the `True` direction** — a
  constant `has_more: False` survives all 979 tests.
- **Layer-wide, measured:** nothing pins the queue's caller-commits rule.
- **ADR-0025's accepted residuals:** the re-claim, and the third race order.
- **Parked at the review-UI error-recovery close:** the `42/42` comment;
  `edit()` not resetting `submit`; no `aria-invalid`; the comment-only
  select/checkbox invariant; the sign-out confirm's wording; keystrokes during
  an in-flight submit not stashed.
- **Two queued PAN scoped decisions** — the grouping residual (76 of 97 band
  shapes) and the `{1,2}` separator surface (36 spellings, pinned).
- Plus MEMORY.md's "Deferred follow-ups".

## 9. LAST — ISSUE-001

Read `docs/KNOWN_ISSUES.md`, do not re-derive; hosted tool-capable model needed
(rotate the echoed Gemini key first); until it runs, no measured accuracy
numbers and no real precision claim.

---

## Non-negotiables

`Decimal` money path; pure validation; stable rule IDs; null over
confident-wrong; **a full PAN never persisted**; nothing silently dropped; a
machine run never overwrites a `reviewed` row; optional-import discipline;
tool-use structured output; few-shot images first; consistency never cached;
`python -m pytest` offline and Node-free.

**PAN:** ADR-0018 + 0020 + corrections; any `_PAN_RE` change replays the
committed battery both ways, two-instance-tests, keeps the structural guards
green. **Egress (ADR-0022):** failure text goes through `redact_pan` at every
process exit. **Queue (ADR-0006):** explicit `Session` first, flush, **never
commit**, `ValueError` at the boundary; `list_tasks` is a pure read.
**Frontend (ADR-0015):** money is a string; no `<input type="number">`; no
`valueAsNumber`; no `CORSMiddleware`; `/app/*` only. **Error recovery
(ADR-0024):** exactly one `role="alert"`; the classifier never invents copy;
the stash never touches browser storage; `PATCH /receipts/{id}` stays
claim-unaware. **Scope (ADR-0026):** the role mapping must not fail open.
**UI (ADR-0027):** `null` ≠ `0` ≠ empty; severity colours are reserved; no raw
hex outside `tokens.css`; no CDN fonts.

---

## Running it

- Two suites: `python -m pytest` (**979**) and Vitest in `frontend/` (**258**
  on the branch, 221 on `main`). `npm test` does NOT type-check — run
  `npm run typecheck` too. `python scripts/verify.py` is what "passing" means.
- **`pyproject.toml:61` sets `addopts = "-q"`.** So `python -m pytest -q` is
  `-qq` and prints **no pass count**; `-v` nets to dot output (`-vv` gives a
  listing). **Use bare `python -m pytest`,** or `--junitxml`.
- **`scripts/verify.py` exceeds a 2-minute tool timeout.** Background it.
- Lint: `python -m ruff check .`. The frontend linter is **oxlint**; there is
  no formatter config anywhere in the tracked tree.
- **`pytest -k` matches substrings, not words.** `-k tasks` does not match
  `test_an_admin_sees_a_task_assigned_to_someone_else`.
- **The working tree is CRLF.** A mutation anchored on `\n` matches nothing and
  still reports success. **And a non-empty `git diff --stat` is not enough** —
  `api.py` carries `limit=limit + 1` and the `has_more` return line twice, and
  two runs landed on the *wrong route* and reported the suite passing. Confirm
  it landed **where you meant**. `git diff --stat` is also **silent on
  untracked files**; use an md5 landed-check.
- **Vitest's environment pragma is matched ANYWHERE in a file** — including
  inside a docblock that merely quotes it. Verified at source: the matcher is
  unanchored against the whole file. It silently moved the suite to Node and
  killed 11 rendering tests on `document is not defined`.
- **Vitest sets `css: false`**, so a `.module.css` import returns a proxy whose
  keys echo back. **Class names are unpinnable by rendering tests** — guard
  them by reading the stylesheet as text.
- **`dirname(fileURLToPath(import.meta.url))` DOES work under jsdom.** It is
  the `new URL(specifier, import.meta.url)` *pattern* Vite rewrites into an
  asset URL. `tokens.test.ts`'s attribution is right;
  **`no-float-in-money-path.test.ts:3-5`'s is wrong** and still uncorrected —
  it has been outside every task's permitted file set so far.
- **Enumerating routes:** `include_router` wraps the auth router in an
  `_IncludedRouter`, so a flat walk of `app.routes` yields 13 routes with
  **zero** `/auth/*` paths — recurse through `.original_router.routes` for the
  real 17. A transitively-called guard (`require_role` → `require_user`) is
  invisible at runtime; it is plain Python, not a nested `Depends`.
- **The Grep tool mangles `/` in content output** — verify slash-sensitive
  claims with Read, `git grep` via Bash, or by executing.
- The destructive-commands hook false-positives on: `rm` under the repo;
  read-only `git grep` whose *pattern* names a sensitive file; **any heredoc
  containing slash-separated config filenames**; and reading `vite.config.ts`
  via `cat`. Use the Read tool and rephrase patterns.
- CLI: `python -m receipts.cli <command>`. E2E: `python scripts/seed_review_e2e.py
  --reset` then `cd frontend && npx playwright test`.

## Git

Default branch **`main`**; `origin` → `CDGYu/Receipt-Digitalization`, **public**.
**Pushing `feat/*` is authorised; ask before pushing `main`** (every `main` push
authorization is one-time). Merged `feat/*` branches and SDD workspaces are
**kept, never cleaned up** — this overrides the superpowers skills, which would
delete both. `.kiro/`, `.github/workflows/`, `.superpowers/`, `var/`,
`eval/golden/images/` are gitignored — never stage anything under `var/`.

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation plan →
subagent-driven execution (one fresh implementer per task, briefed to read the
real signatures first; controller reviews the diff, re-runs gates independently,
dispatches a task review, appends to the ledger). Milestone close: whole-branch
review on the strongest model → ONE fix wave → one scoped re-review → ff-merge →
refresh this pair in the same session.

**Dispatch discipline (ADR-0023):** tasks that share a file run **strictly
serially**. Draw boundaries so no two tasks share a file.

**Probe before dispatching.** Plan-defect count by milestone: Phase 5 eleven;
PAN hardening five; PAN grouping six; currency bound two; failure-egress two;
review-UI error recovery four; admin release seven; admin UI backend routes
nine; **review-UI styling nine so far**. Every one across nine milestones was
the controller's, and every one was caught by an implementer or reviewer who
checked instead of trusting. **The plan's prose is reliable; its claims about
existing artefacts are not.**

## Review standards — hold all of them

1–15 unchanged (reproduce don't reason · RED proofs · revert each guarantee
separately · single-variable mutations · no rotting numbers in comments ·
grep-don't-recall · don't credit unasked tools · stub-reflects-write · two
instances in one input · replay the committed battery both ways · coverage and
cross-boundary risk move together · a grown prose table changes every sentence
quantifying over it · a prose claim about a mutation needs revert-proof
discipline · a pin never proven red is not a pin · a mutation that kills the
right test for the wrong reason proves nothing), plus:

16. **Confirming a mutation landed is not confirming it landed where you
    meant.** Two runs applied cleanly with a correct byte delta to the wrong
    route and reported the suite passing.

17. **A universal claim is answered by an enumeration, not an argument.** A
    false universal about the auth surface survived an explicit standard-12
    re-read because the check reasoned about which guards call `require_user`
    instead of listing the routes.

18. **A substring can answer for a declaration.** Three times in one milestone:
    `--color-surface-raised` satisfied `toContain('--color-surface')`;
    `border-left: 2px solid var(--color-null)` satisfied
    `toContain('var(--color-null)')`. Assert on declarations, exact equality,
    or set membership — never on containment.

19. **An enumerated defence never converges.** Four consecutive fix rounds each
    closed the shapes that had been found and re-asserted the class was closed;
    each assertion was falsified by the next round. **The recurring defect was
    the assertion, not the code.** What broke it: state one bounded, checkable
    property, enforce it at both ends, move the enumerations into the tests as
    examples, and **report further shapes rather than fixing them**. A round has
    converged when it adds a *universally-quantified accept-side* assertion that
    fails on the previous round's defect without anyone having thought of it.

20. **A list in prose is read as complete, so writing one is a claim.** Four
    instances measured in this tree, three closed 2026-08-06:
    ADR-0027's "every one of the 17 correctable paths is an `<input>`" (sixteen
    inputs and one `<select>`; `placeholder` reaches **fourteen**) — corrected
    `46eb965`; the design spec's "Rulings — all four settled" (an index of every
    decision, it reads; the four open at drafting, it is) — corrected `ae4b782`;
    `vite.config.ts`'s "Cross-checked against every route `create_app`
    registers" (13 of 16) — closed `2689635` by re-deriving from the built app,
    not by editing the list; and **`api.py:494`'s "This is the one
    unauthenticated route in the service"** — five, or nine with
    `DOCS_ENABLED=true` — **still open** (§3), the last of the four.
    Standard 17 governs how to *answer* such a claim; this one governs
    **writing** it. An enumeration in prose inherits the authority of what it
    enumerates, so it is trusted rather than re-derived — one of these misled an
    explicit standard-12 re-read. **Either enumerate from the code as you write
    it and name what you ran, or write a sentence that does not quantify.**
    And searching for one is harder than it looks: `api.py:494` survived a
    `git grep` for its own words because the sentence wraps mid-phrase. **Grep
    one distinctive word, never the phrase.**

And: **a green suite is not evidence that installed software works** — run entry
points from outside the repository.

---

## Blocked on me (the user) — surface these, do not guess

1. **Re-confirm the `corrections` auth ruling** — "both, scoped differently"
   was answered 2026-08-05 but never confirmed. (Gates §2.1.)
2. **A hosted tool-capable provider + freshly rotated key** (ISSUE-001 → all
   calibration, and Phase 6's success metric).
3. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the values the PAN silent-case tests pin.)
4. **R060/R061 grounding (P2.T2)** — also gates bbox highlighting.
5. **GitHub Actions again?** If yes, the workflow calls `scripts/verify.py`.
6. **Close the PAN grouping residual?** Which priced route?
7. **Narrow the `{1,2}` separator** now that its surface is measured?
8. **`main` push** — the next one needs a fresh ask.

**Today's goal:** <FILL THIS IN — the default is **finish the in-flight
milestone** (§1). Check whether Task 2's round 5 landed, close it out, then
Tasks 3 → 4 → 5 → 6 and the whole-branch review. Task 3 is the biggest and
carries three must-honour items from the ledger; Task 5 is the browser pass
nobody has ever done and is the point of the whole milestone. If you would
rather pause the branch, it is committed and green at every step — say so and
I will push it and stop.>
