You are continuing work on the **Receipt Digitization System**, a VLM pipeline
that turns receipt photos into accounting-grade structured data. Pick up exactly
where the last session left off.

**Read these first, then confirm the state back to me — and verify the snapshot
below against the repo rather than trusting it.** It has been stale at the start
of several sessions: once by a whole milestone; once rewritten *mid-milestone*
by a subagent working outside its lane; once carrying two sentences that
contradicted each other about whether `main` was pushed; and on **2026-08-06 the
prompt handed to the session was a whole milestone out of date *and the same
stale text had been restored over the correct one in the working tree*** — the
tracked file was right and the working copy was wrong, the inverse of the
earlier failure. Only `git` settled it. ADR-0019 made the refresh part of closing
a milestone; **ADR-0021 makes it part of ending any session.** This verification
step is permanent.

---

# ⚠️ A BRANCH IS IN FLIGHT. This is a mid-milestone handoff.

**`feat/review-ui-styling`**, off `main@1314485`, **pushed**. `main` is untouched
by it and in sync with `origin/main`.

The tip was `5d91fb8` when this was last edited, and **the edit itself commits
on top of that**, so the real tip is at least one commit later — a document cannot name
the commit that writes it (ADR-0019). **Do not quote a count from this file;
run it** (ADR-0028 §1):

```
git rev-list --count main..feat/review-ui-styling
git log --oneline main..feat/review-ui-styling | head -5
```

**Tasks 1, 2, 3 and 4 of six are complete** (3 and 4 each took one fix round;
Task 4's first implementer stalled and was finished by a second). **Tasks 5 and
6 are not started — Task 5 is the browser pass, and it is the point of the whole
milestone.**

**First thing to run:**

```
git status --short          # dirty => a mutation may be mid-flight; do not "clean" it
git log --oneline -8
```

**If the tree is dirty, do not "clean" it** (ADR-0023). Restore from a byte copy
after checking the ledger, never with `git checkout --`.

---

## Reading order

1. **`docs/MEMORY.md`** — state, decisions already made, environment, blockers,
   deferred items, and **review standards 1–20**. Its "Review-UI styling — IN
   FLIGHT" section records this milestone.
2. **The in-flight ledger** —
   `.superpowers/sdd/2026-08-05-review-ui-styling/progress.md`. **Read before
   touching the branch.** Every plan defect, every mutation, every controller
   ruling. Completed milestone ledgers sit beside it. **`.superpowers/` is
   gitignored — open ledgers by path; nothing in them is findable by searching
   the tracked tree.**
3. **`docs/adr/README.md`, then the ADRs (0001–0028).** Mandatory before
   touching the matching area:
   - **0028** — *claims about the tree are re-derived, not restated.* **Read
     before writing any sentence that quantifies over this codebase.** Four
     such claims were found false in one day; three were written by someone who
     *had* checked and asked the wrong question. Carries the enumeration
     methods and why citations here have no line numbers.
   - **0027 + its `## Correction (2026-08-06)`** — the design system: light
     default, CSS Modules, `@fontsource` never a CDN, a pathname switch not
     React Router, and **`null` ≠ `0` ≠ empty**. The correction fixes its false
     "all 17 are `<input>`" claim. **Read before writing any CSS or rendering
     any extracted value.**
   - **0026** — `/auth/me` and `/review/tasks`. The privacy property is
     *derived, not structural*, and **not closed**.
   - **0025** — the admin release, which `/review/tasks` exists to feed.
     `close_task` deliberately leaves `assigned_to` set on a `DONE` task.
   - **0024** — the error-recovery contract. Inline field errors carry
     `role="alert"` and are additive; the summary always renders; the
     **backend-down sentence deliberately carries none.**
   - **0023 + its THREE dated corrections** — parallel agents share one
     worktree. **The 2026-08-06 correction widens rule 2: serialise on files
     _or_ on a shared global gate.**
   - **0015** money is a string, `/app/*` only · **0012** auth and roles ·
     **0022** failure-text egress · **0018 + 0020** PAN · **0007** money
     integrity · **0006** the ValueError boundary · **0017** the gate runner ·
     **0019 + 0021** session continuity.
4. **`docs/superpowers/specs/2026-08-05-review-ui-design-system.md`** — the
   design. §2's three overrides; §4 the null rule; **§5.1's dated note parking
   the currency prefix**; §9's rulings (and its note that §9 is *not* an index
   of every decision since).
5. **`docs/superpowers/plans/2026-08-05-review-ui-styling.md`** — the plan under
   execution. **Read its "Dated defect log" at the bottom FIRST.** Twenty
   defects; several are still wrong in the body above it.
6. **`.kiro/steering/receipt-system.md`** — always-on rules (gitignored,
   untracked, still on disk).
7. **`IMPLEMENTATION_PLAN.md`** · **`docs/KNOWN_ISSUES.md`** (ISSUE-001 — do not
   re-derive) · **`RECEIPT_SYSTEM_SPEC.md`** §§ as needed.

---

## Where we are

- **`main` @ `1314485`**, pushed, in sync with `origin/main`, untouched by the
  branch. Every `main` push needs a **fresh** ask.
- **All 13 merged `feat/*` branches are pushed**; `feat/review-ui-styling` is
  the fourteenth and is the one in flight.
- **Freshness check**, using the commit named in `docs/MEMORY.md`'s
  "Last updated" line:

  ```
  git log --oneline <STAMP>..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
  ```

  **Empty means this prompt is current.**
- Gates at `5d91fb8`, controller-run: `python scripts/verify.py` **all five
  PASS**; pytest **979**; Vitest **318 across 24 files**.
- **`src/` CHANGED on this frontend branch** (`bbb5366`). The whole-branch
  review has one Python file in scope, and the **outside-repo import check
  applies at the merge**.

---

# THE WORK, IN ORDER

## 1. FINISH THE IN-FLIGHT MILESTONE — `feat/review-ui-styling`

Lanes **1 → 2 → {3 ∥ 4} → 5 → 6**. Plan:
`docs/superpowers/plans/2026-08-05-review-ui-styling.md` (read its defect log
first).

### 1.1 Task 4 — the `/app/admin` surface — **DONE (`5d91fb8`)**

Shipped: `route.ts` (a pathname switch, not a router), `api/admin.ts`,
`admin/{AdminScreen,TaskTable,StatTiles}` + stylesheets, the `session.ts`
identity widening hydrated from `/auth/me`, and the `main.tsx` wiring. Vitest
**281 → 318 across 24 files**; all five gates PASS, controller-run.

**It found that `main.tsx`'s admin branch was deletable with all 316 tests
green** — `/app/admin` being reachable at all was unpinned — and closed it with
`tests/app-admin-route.test.tsx`. Controller-reproduced: deleting the branch
reds exactly that one test.

**`Button` and `Chip` are both adopted and `Chip`'s signature did not change** —
five hand-authored `aria-hidden` SVG glyphs, so runtime deps stay at four. Every
chip is `neutral` except `done` → `positive`: ADR-0027 §2 reserves error red,
warn amber and info blue, so a priority-0 row says the **word** "Urgent" rather
than borrowing red.

The plan's Task 4 text is still wrong in four places (defects #17–20, in the
plan's dated defect log). **They were all handled in the shipped code**; they
are recorded here only so nobody re-derives them from the plan:

- **Do NOT create `ReviewTaskSummary`.** `frontend/src/api/types.ts` already
  declares **`ReviewTask`** with exactly `_task_summary`'s eight fields. Reuse
  it. A second type is a second place to drift.
- **`releaseTask` returns the whole task summary plus `released_from`**, not
  `{released_from}` alone (`api.py`, the release handler). `request<T>` is an
  unchecked cast, so the plan's type silently discards the rest.
- **`GET /auth/me` answers 401 when signed out and `request()` throws on 401.**
  The side effect is wanted — `session.ts`'s module-scope handler flips
  `setSignedIn(false)` — but the throw must be caught deliberately.
  `ErrorBoundary` catches render throws, not async rejections.
- **`state`'s wire values are lowercase** — `open` / `in_progress` / `done`.
  Sending `"OPEN"` gets a **422**, not an empty list.
- **`vite.config.ts` is no longer Task 4's** — its stale route list was fixed
  at `2689635`, so the plan's Step 1 is already done.
- **The release route is guarded by `require_role`**, so a reviewer reaching it
  gets **403**, not an empty result. That is an error path, not an empty state.
- **The empty state must name its scope** (ADR-0026): reviewer → "No open
  tasks, and none assigned to you"; admin → "No tasks".

### 1.1b Task 4's residuals — reported, not fixed. Carry to the close.

1. **`getByText(/carol/)` in the release round-trip is vacuous** — it passes
   from the assignee cell alone, *before* the click. **Measured:** a visible
   "Release from carol" button makes it throw on 2 matches; with the name on
   `aria-label` there is exactly 1. So the test *forces* the holder-naming into
   the accessible name, and the assertion meant to check it checks nothing.
   **Consequence: making the confirm prompt name the holder *visibly* and
   keeping that test are mutually exclusive.**
2. **Nothing pins stylesheet *content* in `src/admin/`.** The guard checks only
   that referenced classes exist; both stylesheets could be emptied to `.x{}`
   stubs and stay green. **No test anywhere forbids raw hex outside
   `tokens.css`** — `tokens.test.ts` covers `tokens.css`, and
   `review-null-rule.test.tsx` scans `src/review` only.
3. **`has_more` is reported with no way to act on it.** `fetchTasks` accepts
   `limit`/`offset`; the screen never sends them. An operator past 50 tasks is
   told there are more and given no control. Contract-compliant, real gap.
4. **The metrics-failure branch and the multi-line alert region are untested** —
   every test stubs `/metrics` 200.
5. **`busyTaskId` locks every row's control**, not just the clicked one.
   Deliberate and documented; uncovered.

### 1.2 Task 5 — the browser pass nobody has ever done

**Nobody has opened any of this UI in a browser.** Build, seed, serve, and
capture every surface at **375 / 1024 / 1440px** in **both themes**: login; the
review screen with null fields; findings at all three severities; each of the
five ADR-0024 error states; the admin surface with tasks; and the admin surface
empty, as a reviewer.

**Report findings; do not fix them.** **Lay down no pixel baselines** — a
first-ever pass has nothing to diff against, and a baseline from unreviewed
output pins whatever is broken.

Check specifically: is a **null field visibly different from a zero**? Is the
money column aligned on the decimal at every width? Do severity colours survive
dark mode at 4.5:1? Does anything scroll horizontally at 375px? Are focus rings
visible in both themes? Is the receipt image legible against its surround?

### 1.3 Task 6 — absorb the findings

**ADR-0027 is already written, Accepted, and already carries one dated
correction.** Task 6 is therefore: **append a dated note recording what the
browser pass found.** Do **not** edit 0027's body.

### 1.4 Then close the milestone

Whole-branch review on the strongest model → **ONE** fix wave → one scoped
re-review → ff-merge → refresh this pair in the same session → **ask before
pushing `main`.**

**The close must explicitly cover:**
- **`41d01ab..e216af4`** — Task 2's round 5, whose scoped re-review was never
  run. The one diff on this branch no reviewer has seen.
- **`src/receipts/review/api.py`** — a Python file on a frontend branch.
- **The two carried residuals** in §1.5 below.
- **Candidate review standard 21**, if it earns it: *a citation is a claim
  too.* Closing a prose defect ages every sentence that cited it — this
  happened twice in one session, and twice the stale citations were inside the
  standard that names the defect.

### 1.5 Two residuals carried into the close — reported, not fixed

1. **§5.3's confidence band hardcodes `0.85` / `0.60`** while `GET /metrics`
   ships the authoritative `auto_approve_threshold` / `review_threshold`. A
   deployment overriding either gets a band that disagrees with its own
   routing. Documented at the constant.
2. **`ReviewScreen.module.css` places the image pane with `.screen > div`** — a
   *positional* selector that works only because the pane is the sole direct
   `<div>` child. A `<div>` scroll wrapper would have dropped the line-items
   table onto the photograph **with all gates green**; it was avoided with a
   `<section>` and pinned from both ends. One wrapper element fixes it
   structurally.

---

## 2. Phase 5 follow-ups — two left

1. **A read route for `corrections`.** Nothing does `select(Correction)`, so a
   reviewer cannot see the correction history of the receipt they are
   correcting and an auditor needs database access. **Blocked on an auth
   ruling.** An answer was given 2026-08-05 — *"both, scoped differently:
   reviewers see corrections for the receipt they hold, admins see any
   receipt's"* — **but it arrived alongside a system notice disclaiming it as
   user input and has never been restated. Re-confirm it verbatim before
   designing the route.**
2. **An ASGI entry point / deployment story.** `create_app` is a factory
   nothing under `src/` calls. `scripts/serve_review_e2e.py` is deliberately
   e2e-scoped — inheriting a deployment policy from an e2e launcher is the
   mistake to avoid. **The only item that can start with no ruling.**

## 3. Phase 6 — merchants & few-shot (P6.T1)

`merchants/{fingerprint,registry}.py` is greenfield; few-shot images first,
target last; hints end "trust the image"; measure top-10-merchant accuracy
before/after — **blocked on ISSUE-001**, so Phase 6 can be built but not
validated. Five things unblock here: semantic dedupe into `process_receipt`;
the same hints into `_attempt_prompt_hash`; `merchant_default_currency` at its
plug-in point in `pipeline.py` (**re-verify the line — the file has grown**);
the `image_phash` gap; `Merchant.receipt_count` (nothing writes it).
`VAT Reg. TIN` is the strongest fingerprint on this corpus.

## 4. Phase 7 — self-consistency (P7.T1)

Wire `run_consistency` (`extract/extractor.py`, zero references in
`pipeline.py`) for handwritten/low-legibility; **gate on
`triage.is_handwritten`, never `document_type`**; consistency runs never cached.

## 5. Phase 8 — calibration & eval-harness honesty

P3.T6/P8.T1 threshold sweep + weights into `config/rules.yaml` (**blocked on
ISSUE-001**); P8.T2 grow the held-out set; P8.T3 the all-failed eval run still
persists `"auto_approval_precision": 1.0` to JSON.

## 6. Still open from earlier phases

R060/R061 grounding decision (also gates bbox); score `is_handwritten` from
triage too; `is_receipt` has no consumer (never hard-reject on it); blank
pre-printed template rows (sibling of R052).

## 7. Deferred, with rulings

- **From this branch:** the two residuals in §1.5; the class-name guard's three
  parked selector-axis leaks (harmless-but-inexact `:is`/`:where`,
  harmful-but-absurd self-contradictory `:not`, loud-and-safe `@import`);
  token *values* unpinned in the light block; `block()` assumes flat rule
  bodies; **`receipt-form.test.tsx` pins the row highlight through
  `rows[1].style.background`** — the *mechanism*, not the behaviour — which
  actively blocks moving it to a class.
- **From the admin-UI-routes milestone:** 20 Minor findings triaged as safe.
  `GET /receipts`' `has_more` is **unpinned in the `True` direction** — a
  constant `has_more: False` survives all 979 tests.
- **Layer-wide, measured:** nothing pins the queue's caller-commits rule.
- **ADR-0025's accepted residuals:** the re-claim, and the third race order.
- **Parked at the error-recovery close:** the `42/42` comment; `edit()` not
  resetting `submit`; no `aria-invalid`; the comment-only select/checkbox
  invariant; the sign-out confirm's wording; keystrokes during an in-flight
  submit not stashed.
- **Two queued PAN scoped decisions** — the grouping residual (76 of 97 band
  shapes) and the `{1,2}` separator surface (36 spellings, pinned).
- Plus MEMORY.md's "Deferred follow-ups".

## 8. LAST — ISSUE-001

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
green. **Egress (0022):** failure text goes through `redact_pan` at every
process exit. **Queue (0006):** explicit `Session` first, flush, **never
commit**, `ValueError` at the boundary; `list_tasks` is a pure read.
**Frontend (0015):** money is a string; no `<input type="number">`; no
`valueAsNumber`; no `CORSMiddleware`; `/app/*` only. **Error recovery (0024):**
the summary alert always renders; the classifier never invents copy; the stash
never touches browser storage; `PATCH /receipts/{id}` stays claim-unaware.
**Scope (0026):** the role mapping must not fail open. **UI (0027):** `null` ≠
`0` ≠ empty; severity colours are reserved; no raw hex outside `tokens.css`; no
CDN fonts. **Claims (0028):** a sentence that quantifies over the codebase is
derived at the moment of writing, with its method recorded.

---

## Running it

- Two suites: `python -m pytest` (**979**) and Vitest in `frontend/` (**318**
  across 24 files on the branch, 221 on `main`). `npm test` does **not**
  type-check — run `npm run typecheck` too. `python scripts/verify.py` is what
  "passing" means (ADR-0017).
- **`pyproject.toml` sets `addopts = "-q"`.** So `python -m pytest -q` is `-qq`
  and prints **no pass count**; `-v` nets to dot output. **Use bare
  `python -m pytest`,** or `--junitxml`.
- **`scripts/verify.py` exceeds a 2-minute tool timeout.** Background it — and
  **do not edit while it runs.** Backgrounded during an edit it caught a
  half-applied refactor and reported `FAIL build` on a `TS6133` that no longer
  existed. A phantom failure looks exactly like a real one.
- Lint: `python -m ruff check .`. The frontend linter is **oxlint**; there is
  **no formatter config anywhere** in the tracked tree.
- **`pytest -k` matches substrings, not words.** `-k tasks` does not match
  `test_an_admin_sees_a_task_assigned_to_someone_else`.
- **The working tree is CRLF.** A mutation anchored on `\n` matches nothing and
  still reports success. And a non-empty `git diff --stat` is not enough —
  `api.py` carries `limit=limit + 1` twice, and two runs landed on the **wrong
  route** and reported the suite passing. Confirm it landed **where you meant**.
- **Grep one distinctive word, never the phrase.** `git grep "one
  unauthenticated route"` returns nothing — the sentence wraps mid-phrase. The
  same trap defeated a `git log -S` pickaxe in the same session, and the
  residual was nearly recorded as already fixed on the strength of it.
- **PowerShell `Get-Content`/`Set-Content` mangles em dashes and `§`.** Three
  separate agents hit this in one day. `Get-Content` defaults to ANSI without a
  BOM, so corruption happens on the **read**. **Use the Read/Write/Edit tools
  for anything non-ASCII** — which is nearly every file here.
- **Vitest sets `css: false`** — a `.module.css` import returns a proxy whose
  keys echo back, so **class names are unpinnable by rendering tests**; a
  renamed class ships as `class="undefined"` with every gate green. Guard by
  reading the stylesheet as text (`frontend/tests/review-null-rule.test.tsx`
  has a working example).
- **Vitest's environment pragma is matched ANYWHERE in a file**, including
  inside a docblock that merely quotes it. It silently moved a suite to Node
  and killed 11 rendering tests.
- **`dirname(fileURLToPath(import.meta.url))` DOES work under jsdom.** It is
  the `new URL(specifier, import.meta.url)` *pattern* Vite rewrites.
  `no-float-in-money-path.test.ts`'s attribution is still wrong and still
  uncorrected — it has been outside every task's permitted set.
- **Enumerating routes:** build the app and walk `app.routes` **recursing
  through `.original_router.routes`** — a flat walk yields 13 routes with
  **zero** `/auth/*` paths, which is exactly how `vite.config.ts` came to list
  13 of 16. A transitively-called guard (`require_role` → `require_user`) is
  invisible at runtime too; detect it by qualname.
- **The Grep tool mangles `/` in content output** — verify slash-sensitive
  claims with Read, `git grep` via Bash, or by executing.
- The destructive-commands hook false-positives on: `rm` under the repo;
  read-only `git grep` whose *pattern* names a sensitive file (including
  `vite.config`); heredocs containing slash-separated config filenames; and
  reading `vite.config.ts` via `cat`/`sed`. Use the Read tool and rephrase
  patterns.
- CLI: `python -m receipts.cli <command>`. E2E: `python
  scripts/seed_review_e2e.py --reset` then `cd frontend && npx playwright test`.

## Git

Default branch **`main`**; `origin` → `CDGYu/Receipt-Digitalization`, **public**.
**Pushing `feat/*` is authorised; ask before pushing `main`** (every `main` push
authorization is one-time). Merged `feat/*` branches and SDD workspaces are
**kept, never cleaned up** — this overrides the superpowers skills, which would
delete both. `.kiro/`, `.github/workflows/`, `.superpowers/`, `var/`,
`eval/golden/images/` are gitignored — never stage anything under `var/`.

**Stage by explicit path, never `git add -A`.** Several commits this session
were made while an implementer held the same worktree; each was verified with
`git diff --cached --stat` *before* committing.

## Workflow

brainstorm → design doc → ADR for anything load-bearing → implementation plan →
subagent-driven execution (one fresh implementer per task, briefed to read the
real signatures first; controller reviews the diff, **re-runs gates
independently**, **reproduces the headline mutation personally**, dispatches a
task review, appends to the ledger). Milestone close: whole-branch review on the
strongest model → ONE fix wave → one scoped re-review → ff-merge → refresh this
pair in the same session.

**Dispatch discipline (ADR-0023, as corrected 2026-08-06):** tasks that share a
file run strictly serially — **and so do tasks that share a global gate.** Two
agents with disjoint file sets can still sabotage each other if one's plan has a
deliberate RED phase and the other's definition of done is a whole-suite result.

**Brief the property, not the fix.** An enumerated list of permitted edits is an
enumerated defence and fails the same way: it produced defect #12, then its own
repair produced #16. Give a bound ("all N existing tests pass unmodified;
anything needing a test changed is a stop-and-report") and let the implementer
find the shape. Measured: the round briefed that way delivered three missing
design sections plus a hazard the controller had not thought of, in one pass.

**Never put test files outside an implementer's permitted set when the task's
deliverable needs pinning.** That was defect #15: the task that finally landed
§4 on the review screen was structurally unable to prove its own work, and the
implementer correctly refused to widen scope rather than edit a test.

**Probe before dispatching.** Plan-defect count by milestone: Phase 5 eleven;
PAN hardening five; PAN grouping six; currency bound two; failure-egress two;
review-UI error recovery four; admin release seven; admin UI backend routes
nine; **review-UI styling twenty so far**. Every one across nine milestones was
the controller's, and every one was caught by an implementer or reviewer who
checked instead of trusting. **The plan's prose is reliable; its claims about
existing artefacts are not.**

## Review standards — hold all of them

The full text is in **`docs/MEMORY.md` § "Review standards"**. In brief:

1–15 (reproduce don't reason · RED proofs · revert each guarantee separately ·
single-variable mutations · no rotting numbers in comments · grep-don't-recall ·
don't credit unasked tools · stub-reflects-write · two instances in one input ·
replay the committed battery both ways · coverage and cross-boundary risk move
together · a grown prose table changes every sentence quantifying over it · a
prose claim about a mutation needs revert-proof discipline · **a pin never
proven red is not a pin** · a mutation that kills the right test for the wrong
reason proves nothing), plus:

16. **Confirming a mutation landed is not confirming it landed where you meant.**
17. **A universal claim is answered by an enumeration, not an argument.**
18. **A substring can answer for a declaration.**
19. **An enumerated defence never converges.** State one bounded, checkable
    property, enforce it at both ends, move the enumerations into the tests as
    examples, and **report further shapes rather than fixing them**. A round has
    converged when it adds a *universally-quantified accept-side* assertion that
    fails on the previous round's defect without anyone having thought of it.
20. **A list in prose is read as complete, so writing one is a claim.** ADR-0028.
    Four instances found false in one day; all four now closed, each by
    **re-deriving** the claim rather than editing it in place.

And: **a green suite is not evidence that installed software works** — run entry
points from outside the repository.

---

## Blocked on me (the user) — surface these, do not guess

1. **Re-confirm the `corrections` auth ruling** — answered 2026-08-05, never
   confirmed (gates §2.1).
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
milestone** (§1). Start by checking what Task 4 landed (`git log --oneline
593e194..feat/review-ui-styling`), then Task 5 — the browser pass nobody has
ever done, and the point of the whole milestone — then Task 6 and the
whole-branch review. If you would rather pause the branch, it is committed,
pushed and green at every step; say so and I will stop.>
