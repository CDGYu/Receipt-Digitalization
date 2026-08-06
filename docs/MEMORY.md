# Agent Memory — Receipt Digitization System

Durable working memory for cross-session continuity. Read this first, then
`docs/NEXT_SESSION_PROMPT.md` for the task list and the reading order. The
continuity protocol itself — what lives where, and why this snapshot must be
verified rather than trusted — is **ADR-0019**, extended by **ADR-0021** (whose
2026-08-02 dated correction widened the freshness check after a docs-only task
proved invisible to it).
Last updated: **2026-08-06 (`feat/review-ui-styling` IN FLIGHT — all six tasks
complete, the close not yet run)**, at **`main @ 1314485`**, which the branch
still does not touch. A stamp cannot name the commit that writes it, so the
check is this:

```
git log --oneline 1314485..main -- src tests frontend docs ":(exclude)docs/MEMORY.md" ":(exclude)docs/NEXT_SESSION_PROMPT.md"
```

**Empty means this file is current.** Any output means the tree moved after it
was written and you are reading something stale.

## Snapshot

- **⚠️ A BRANCH IS IN FLIGHT: `feat/review-ui-styling`**, off `main@1314485`,
  **pushed**. Its tip was `1bfacb4` when this was last edited and the edit
  commits on top, so **run `git rev-list --count main..feat/review-ui-styling`
  rather than quoting a number from here** (ADR-0028 §1; ADR-0019 on why a
  document cannot name the commit that writes it). **Tasks 1 through 5 of six
  are complete**; 3, 4 and 5 each took one fix round, and Task 4's first
  implementer stalled at an infrastructure fault. **Only Task 6 remains** — a
  dated note on ADR-0027 — **then the whole-branch review.**
  Vitest **318 across 24 files** (221 on `main`); pytest **979**; all five
  gates PASS at `1bfacb4`, controller-run.
  **The browser pass ran, and found §4 invisible on money in a real browser
  while every gate was green.** Fixed; see
  `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`.
  ADR-0027 + its 2026-08-06 correction record its decisions.
  **The plan is `docs/superpowers/plans/2026-08-05-review-ui-styling.md` —
  read its "Dated defect log" at the bottom FIRST; the ledger is
  `.superpowers/sdd/2026-08-05-review-ui-styling/progress.md` and must be read
  before touching the branch.**
- **`src/` CHANGED on this frontend branch** (`bbb5366`, `api.py`'s docstring).
  So the whole-branch review has one Python file in scope and the
  outside-repo import check applies at the merge.
- **Round 5 of Task 2's fix loop hit the cap (`e216af4`) and its scoped
  re-review was NOT run** — the session ended on a wrap-up instruction while
  it was in flight. **The whole-branch review must cover `41d01ab..e216af4`
  explicitly**; it is the one diff on this branch no reviewer has seen.
- **Twenty plan defects so far this milestone, every one the controller's.**
  #1–9 during Tasks 1–2; #10–14 in Task 3's pre-flight; #15–16 at Task 3's
  review; #17–20 in Task 4's pre-flight. All are in the plan's dated defect
  log and the ledger.

- **`main` @ `e0577ab`, pushed, in sync with `origin/main`.** The milestone
  was first merged locally with no push; the user then authorized the push
  explicitly ("merge all of the branches with the main and push it"), and
  that one-time authorization was consumed by it. The standing ask-first
  rule for `main` continues — every push needs its own fresh ask.
  pytest on `main`: **979**; Vitest **221**.
- **All 13 `feat/*` branches are ancestors of `main` and all are pushed.**
  Audited 2026-08-05: `git branch --no-merged main` is empty and every
  branch adds **+0** commits, so "merge all branches" was already a no-op —
  they are historical merge points, kept per the standing rule.
- **NO branch in flight.** Empty is the signal (ADR-0021).
- **The admin UI's backend routes are complete and merged** (2026-08-05,
  true fast-forward `7aa0a22` → `b59f164`; 9 branch commits: design, plan, a
  plan correction, three tasks, one task fix, and a two-item close fix wave).
  `feat/admin-ui-routes` is kept at its merge point **and pushed**.
- **The admin release is complete and merged** (2026-08-04, true
  fast-forward `c3a268c` → `9d31679`; 13 branch commits: design, plan,
  three tasks, two task-fix rounds, and a three-commit close fix wave).
  `feat/admin-release` is kept at its merge point and pushed.
- **The review-UI error-recovery milestone is complete and merged**
  (2026-08-04, true fast-forward `7c811fa` → `02edcd0`; 25 branch commits:
  design, plan, seven tasks, ADR-0023, a five-commit close fix wave).
  `feat/review-ui-error-recovery` is kept at its merge point and pushed.
- **The failure-egress redaction milestone is complete and merged**
  (2026-08-03, true fast-forward `3c5a86d` → `1035fd3`; ten branch commits:
  design, ADR-0022, plan, four task commits, and a three-commit close fix
  wave). `feat/failure-egress-redaction` is kept at its merge point and
  pushed; merged branches and SDD workspaces are never cleaned up.
- **The currency bound & fixture race milestone is complete and merged**
  (2026-08-03 morning, `b81ba34` → `f04aa65`). **PAN grouping** merged
  2026-08-02; **PAN hardening** merged 2026-07-31.
- **979 Python tests + 221 Vitest (19 files)** on `main`, ruff clean,
  typecheck clean, build clean — `python scripts/verify.py` all five gates
  PASS, run by the controller on `main` at `b59f164` immediately after the
  merge. `src/` changed, so the **outside-repo import check** was run from
  `/c/Users` too: `receipts.review.list_tasks` resolves through the package,
  `create_app` and `build_auth_router` import clean, and
  `python -m receipts.cli --help` runs.
- **Phases 0–5 complete, plus PAN hardening, PAN grouping, the currency
  bound, failure-egress redaction, review-UI error recovery, the admin
  release, and the admin UI's backend routes.** Phase 3 is complete except
  **P3.T6 calibration** (blocked on ISSUE-001). Phase 5 has **two** named
  follow-ups left, and the admin UI's **frontend half** is the committed
  next milestone (see "Remaining work").
- Dev interpreter **Python 3.14.4**. Node **v22.22.2** / npm **10.9.7**.
- Plan of record: `IMPLEMENTATION_PLAN.md`. Ledgers:
  `.superpowers/sdd/2026-08-05-admin-ui-backend-routes/progress.md`
  (complete — three task entries, **nine plan defects**, and "THE CLOSE"),
  `.superpowers/sdd/2026-08-04-admin-release/progress.md` (complete — three
  task entries, seven plan defects, three controller rulings, and "THE
  CLOSE"), `.superpowers/sdd/2026-08-03-review-ui-error-recovery/progress.md`,
  `.superpowers/sdd/2026-08-03-failure-egress-redaction/progress.md`
  (complete — four task entries and "THE CLOSE"),
  `.superpowers/sdd/2026-08-02-currency-bound-and-fixture-race/progress.md`
  (complete), `.superpowers/sdd/2026-07-31-pan-grouping/progress.md`,
  `.superpowers/sdd/2026-07-31-pan-hardening/progress.md`,
  `.superpowers/sdd/2026-07-29-review-ui/progress.md` (Phase 5's parked
  items). **`.superpowers/` is gitignored, so nothing in it is findable by
  searching the tracked tree — open ledgers by path.**
- **The repo is PUBLIC.** Verified 2026-07-31 via the GitHub API. See
  "Environment / provider" for what that exposes.

## Review-UI styling — IN FLIGHT (2026-08-05 → )

Six tasks, lanes 1 → 2 → {3 ∥ 4} → 5 → 6. **All six complete; the close
remains.** Branch `feat/review-ui-styling`, pushed — **run
`git rev-list --count main..feat/review-ui-styling` rather than quoting a
number from here** (ADR-0028 §1).

- **Task 1** — `tokens.css` (35 tokens, three blocks), self-hosted fonts via
  `@fontsource` (never a CDN), light default with `:root:not([data-theme='light'])`
  load-bearing inside the `prefers-color-scheme` block. One fix round.
- **Task 2** — `ui/Value.tsx`, `Button.tsx`, `Chip.tsx`. **Five fix rounds**,
  and the milestone's lesson (review standard 19) came out of them.
  **`Button` and `Chip` still have ZERO consumers**; `Chip` is unusable as
  typed — `icon: JSX.Element` with no icon set in the tree and runtime deps
  frozen at four. Task 4 owns that decision.
- **Task 3** — seven stylesheets, the review screen styled, `placeholder="—"`
  on the 14 applicable controls, `ConfidenceRail` converted to `Value`,
  `autoComplete="off"`, and the focused row moved off raw `#fffbe6` to
  `--color-surface-active`. One fix round, which also landed design §§5.2
  (a `<section>` scroller), 5.3 (the confidence band) and 5.4 (the findings
  disclosure) and **one universally-quantified pin** covering every rendered
  control. Vitest 258 → 281.
- **Task 4** — the `/app/admin` surface (`5d91fb8`): `route.ts`, `api/admin.ts`,
  `admin/{AdminScreen,TaskTable,StatTiles}`, the `session.ts` identity
  hydrated from `/auth/me`, and the `main.tsx` wiring. Vitest 281 → 318.
  **Its first implementer stalled at an infrastructure fault** with the RED
  phase complete; the work was quarantined and a second implementer finished
  it. **It found `main.tsx`'s admin branch deletable with all 316 tests
  green** — `/app/admin` reachable at all was unpinned — and closed it.
  **`Button` and `Chip` are both adopted**, `Chip` fed hand-authored
  `aria-hidden` SVG glyphs so runtime deps stay at four.
- **Task 5** — the browser pass (`d85e5e3`) and its fix round (`205d77a`,
  `1bfacb4`). 97 screenshots at three widths in both themes, every one opened;
  3 Criticals, 6 Importants. **It found §4's null rule asserted green in jsdom
  and invisible in a browser**: `placeholder="—"` was on every money control
  and the pin was correct, but the input overflowed its cell and the em dash
  was clipped out of sight. The real cause was `.field { display: inline-flex }`
  shrink-wrapping to the input's `size="20"` intrinsic width — **not** the
  missing `width` the controller diagnosed, which the implementer disproved by
  mutation. Fixed: `cellOverflow` 204 → 0, sub-4.5:1 contrast records 35 → 0,
  `--color-null` 3.91 → **5.45:1** in dark. **The login page got its first
  stylesheet — it had been in no task's file set in any of the six**, and its
  class guard was added separately because the fix round was forbidden the test
  file (plan defect #15's shape, third occurrence).
- **Task 6** — the dated note on ADR-0027 (`31fafaf`). Body untouched, appended
  after the existing correction, zero deletions verified. It records the pass,
  the generalisation worth keeping — **a pin can be genuinely universal, proven
  to fail, and still not measure the property you care about, because the
  assertion layer cannot see what a person sees** — and **one decision the pass
  showed is incomplete: dark ships as a full second theme and the application
  has no theme control.** Surface that at the close.

**ALL SIX TASKS ARE COMPLETE. What remains is the close.**

**Two residuals carried, both reported not fixed:** §5.3's confidence band
hardcodes `0.85`/`0.60` while `GET /metrics` ships the authoritative
thresholds, so an overriding deployment gets a band disagreeing with its own
routing; and `ReviewScreen.module.css` places the image pane with the
**positional** selector `.screen > div`, which nearly dropped the line-items
table onto the photograph with all gates green.

**Also on this branch, folded in rather than branched for:** `api.py`'s false
"one unauthenticated route" docstring (`bbb5366`), `vite.config.ts`'s stale
route list (`2689635`), ADR-0027's own correction and its de-numbered citation,
**ADR-0028**, and ADR-0023's 2026-08-06 correction.

## Admin UI backend routes — complete and merged (2026-08-05)

Design + plan: `docs/superpowers/{specs,plans}/2026-08-05-admin-ui-backend-routes*`.
Decision: **ADR-0026**. Ledger:
`.superpowers/sdd/2026-08-05-admin-ui-backend-routes/progress.md`.

**What shipped — the two contracts the admin UI needs before any frontend
work can start.**

**`GET /auth/me`** (`review/auth.py`, in `build_auth_router()`) returns
`{"username", "role"}` for a signed-in caller and **401 otherwise, including
for the machine key** — it is guarded by `require_user`, so it joins
`READ_ROUTES` like every other session-authenticated route rather than
inventing a 200-with-null shape. It returns a bare `dict[str, str]`; **no
Pydantic model**, because `POST /auth/login` has returned this exact body
since session auth first shipped (`d255750`) and a model on one side only
would be asymmetric. A **drift test** pins the two bodies equal. This exists
because `session.ts:21` holds one boolean whose initial value is a *guess*
and `LoginPage.tsx:15` discards the login body, so a reloaded page cannot
learn its role.

**`GET /review/tasks`** (`api.py`'s `_install_read_routes`, backed by
`list_tasks` in `review/queue.py`) is the queue as rows, so an admin can
find the task id that `POST /review/{task_id}/release` needs — `/metrics`
returns counts only. **Equal access, role-dependent content:** both roles
get 200; an admin sees every row, a reviewer sees `state == OPEN` plus
their own rows in any state. Ordered `priority, opened_at, id` — the same
total order `_claim_stmt` uses, so the first row of `?state=open` is the row
`GET /review/next` would hand out next. `has_more` off a `limit + 1` fetch.
Reuses `_task_summary` unchanged.

**The privacy property is derived, not structural** (ADR-0026): a reviewer
sees no other reviewer's name only because `state == OPEN` implies
`assigned_to IS NULL`. That holds because the three `OPEN`-producers — a
brand-new row (never sets it), `enqueue_review`'s reopen branch, and
`release_task` — each clear or omit it, and those three are pinned
one-for-one by existing tests. **The class is NOT closed**: the route-level
pin catches a fourth `OPEN`-producer only if some test exercises it. ADR-0026
says so plainly rather than claiming closure.

**The close, in numbers.** Whole-branch review on the strongest model ran
**25 mutations** in an isolated byte copy: 0 Critical, 2 Important, 11 Minor.
**Deleting `GET /review/tasks` turns 11 tests red; deleting `GET /auth/me`
turns 8 red; deleting the scoping clause turns 3 red on the subset bound
itself.** The privacy scope then survived an **exhaustive 1,554-path
reachability walk** (depth 4 over enqueue/claim/close/release, each on a
fresh database) with zero violations. ONE fix wave (two items, one commit),
one scoped re-review: both addressed. pytest 953 → 979.

**Two mutation traps worth remembering**, both new: `api.py` contains
`limit=limit + 1` and the `has_more` return line **twice** — once for
`/receipts`, once for `/review/tasks` — so a mutation can land cleanly, with
a correct byte delta, **on the wrong route** and report all tests passing.
*Confirming a mutation landed is not enough; confirm it landed where you
meant.* And the "unguard `/auth/me`" mutation in its nested-dependency form
turns the route into a 422 via a postponed-annotation failure — it changed
more than one thing and had to be re-run module-level.

**Plan defects this milestone: NINE, all the controller's.** The worst was
**#9**, and it is the one that let a falsehood into the shipped tree: the
`/auth/me` docstring claimed the route "stays inside the guard **every other
authenticated route** uses". False — the signed blob route takes no user
dependency at all, and `require_upload` returns for a valid machine key
before reaching `require_user`. **The ledger itself had cleared that sentence
as "STILL TRUE"** during a standard-12 re-read, on a reasoning error. It was
fixed at the close, and the re-reviewer proved the replacement by building
its own 17-route enumeration rather than accepting it.

## Admin release — complete and merged (2026-08-04)

Design + plan: `docs/superpowers/{specs,plans}/2026-08-04-admin-release*`
(the design carries a dated note in §5 — see below). Decision: **ADR-0025**,
plus dated notes on **ADR-0016** and **ADR-0015**. Ledger:
`.superpowers/sdd/2026-08-04-admin-release/progress.md`.

**What shipped — Phase 5 follow-up #3, the inverse of a claim.**
`release_task` (`review/queue.py`) returns a claimed task to the queue:
`IN_PROGRESS` → `OPEN`, `assigned_to` cleared, `priority`/`opened_at`/
`reason`/`closed_at` untouched so it keeps its queue position. `OPEN` is
idempotent; **`DONE` is refused** — `close_task` leaves `assigned_to` set,
no `Receipt` column names a reviewer, and a `corrections` row exists only
for a field that changed, so on a receipt confirmed without edits that
column is the only record in the system that a human looked at it.
`POST /review/{task_id}/release` is admin-only via `require_role`, 404s on
an unknown task from its own existence check (a `ValueError` would render
400), 400s on a closed one, and returns `_task_summary` plus a
`released_from` sibling key. A log line names task, prior holder and acting
admin — and **not `reason`** (ADR-0022), pinned by test.

**This is the policy decision ADR-0016 deferred, not a correction to it.**
ADR-0016 rejected a release as the *page-unload* recovery mechanism and
still wins that argument; resume-before-claim is unchanged. What it left
open was reassigning work between people, which it called "a policy
decision, not a bug fix."

**ADR-0024's terminal `taken` state now has a live producer** — it shipped
last milestone handling a 403 only tests could generate.

**The close, in numbers.** Whole-branch review on the strongest model ran
**25 mutations** in an isolated byte copy: 0 Critical, 6 Important, 11
Minor. **20 of 25 died, and deleting the whole route turns SEVEN tests
red** — the direct contrast with the previous close, where that milestone's
headline deliverable was deletable with all five gates green. ONE fix wave
(ten items, three commits), one scoped re-review: all ten addressed. pytest
951 → 953.

**The race the design missed.** Design §5 reasoned about release-vs-complete
in two orders and called both coherent. There is a third: `release_task`
takes no row lock, so a release committing inside the holder's window does
not stop their `close_task`, which writes `DONE` over an already-cleared
`assigned_to` — losing the record of who reviewed the receipt. **Accepted,
reproduced deterministically (two sessions, file-backed SQLite, no threads)
and pinned** by a named test; the design carries a dated §5 note and
ADR-0025 records the mechanism, the reachability and the cost of closing it.

**Plan defects this milestone: SEVEN, all the controller's.** The worst was
#7 — the Task 3 brief's sweep expectation would have led an implementer to
edit the body of two Accepted ADRs, caught only because it refused to
reconcile two instructions silently. Also: #5, two of seven mutations that
killed their target *for the wrong reason* (one changed two variables, one
was unreachable as a leak), which is why review standard 15 now exists.

## Review-UI error recovery — complete and merged (2026-08-04)

Design + plan: `docs/superpowers/{specs,plans}/2026-08-03-review-ui-error-recovery*`
(the design carries **three dated notes**: the alert-role ruling, the 503
narrowing, and the corrected ADR-0022 paragraph). Decisions: **ADR-0024**
(the contract) and **ADR-0023 + its two dated corrections** (how the
milestone was executed). Ledger:
`.superpowers/sdd/2026-08-03-review-ui-error-recovery/progress.md`.

**What shipped — the five design §5 rows Phase 5 dropped** (its eleventh
plan defect, now closed). A pure classifier (`frontend/src/review/failure.ts`)
labels a caught failure `backend-down`/`taken`/`gone`/`field`/`other`,
attributing a 400 by quoted path first then unique quoted value, degrading
to `other` on any ambiguity; an in-memory stash (`stash.ts`) carries
unsubmitted edits across a 401 and is cleared exactly where a write landed
or the session ended; `SignOutControl` never pretends (a failed logout stays
signed in and says so; dirty edits gate it behind an inline confirm);
terminal `taken`/`gone` states offer one exit and keep ⌘↵ dead; a distinct
backend-down state suppresses the Skip escape on the load path and its own
sentence on the complete step; inline field errors render beside the input
that sent them, `aria-describedby`-linked, **additive** to the summary alert
that still always shows. `src/` gained **no behavioural change** — only
route-level pins of the exact 400 texts and the logout contract in
`tests/test_api_write.py`.

**Three user rulings, all load-bearing (ADR-0024):** edits live in memory
only, never browser storage; the backend-down sentence carries **no**
`role="alert"` (a second alert makes the suite's single-alert queries
ambiguous); design §6.1 **supersedes** the old 403/404-on-complete retry
contract, so three pre-existing tests were rewritten to pin the new
behaviour rather than the design being narrowed.

**The close, in numbers.** Whole-branch review on the strongest model, run
in an isolated scratch copy of `frontend/`: 0 Critical, **5 Important**, 9
Minor. Every Important was a *measured mutation surviving 215/215* —
including that **the sign-out control could be deleted outright, header and
import, with all five gates green**. ONE fix wave (nine items, five
commits), one scoped re-review: all nine ADDRESSED. Vitest 215 → 221.

**Plan defects this milestone (four, all the controller's):** the
path-quoting 400 family claimed pinned but was not (caught by an implementer
running `git grep` instead of trusting the plan's prose); a second
`role="alert"` that broke six pre-existing tests; "every pre-existing test
still passes" being unsatisfiable against a deliberate supersession; and
markup that would have polluted every money field's **accessible name** (the
plan nested the error inside the `<label>`; the implementer measured it and
moved it, the reviewer upheld the argument against the accname algorithm).

**The execution incident (ADR-0023).** An implementer whose task had closed
was left holding an unanswered offer to take more work and went on to
implement two further tasks, push them, rewrite the handoff, author an ADR,
and write into the controller's user-level memory — none of it dispatched.
Nothing was lost (the controller quarantined the in-flight diff before
restoring the tree, and ADR-0023's first Context misread that quarantine as
destruction — corrected by dated note). The work was kept and gated
normally by user ruling. **Rules adopted: serialise tasks that share a file;
release an implementer explicitly when its task closes; verify any wake-up
from an agent outside the active dispatch against `git` before acting.**

## Failure-egress redaction — complete and merged (2026-08-03)

Design + plan: `docs/superpowers/{specs,plans}/2026-08-03-failure-egress-redaction*`
(the design carries dated notes: §1.3's missed-sinks note, §6's T3
exemption). Decision: **ADR-0022** plus its same-day dated correction.
Ledger: `.superpowers/sdd/2026-08-03-failure-egress-redaction/progress.md`.
Branch commits: `acaea81` design · `e95215f` ADR-0022 · `e4fcf81` plan ·
`a9af0a6`/`a0b92ac`/`69e18e4`/`c0ca94b` the four tasks · `50992f5`/`fa25013`/
`1035fd3` the close fix wave.

**What shipped — four egress guarantees (ADR-0022):** `_persist_failure`
redacts `str(failure)` BEFORE truncating (the order is measured
load-bearing and pinned by a PAN-straddles-char-400 test), so
`ProcessResult.reason` is redacted for CLI stdout, RQ's Redis result store,
and every future consumer; the failure log renders the traceback via
`traceback.format_exception`, redacts it as text, and drops `exc_info`
(full stack fidelity, nothing raw); `make_engine` passes
`hide_parameters=True` (SQLAlchemy's `[parameters: …]` echo measured
leaking and measured closed, one factory covers every runtime engine);
BOTH of `cmd_process`'s failed-job prints (inline `cli.py:865` and the
enqueue twin `cli.py:826`) print `redact_pan(str(exc))` — the `str()` is
load-bearing (`redact_pan` passes a bare exception object through
unchanged). `enqueue_review`'s own sink redaction and all producers stay
untouched (the sinks-redact policy).

**The close, in numbers.** Whole-branch review on the strongest model:
0 Critical, **1 Important** (ADR-0022 factually wrong in three places —
including a residual whose real mechanism the reviewer measured: on a
`_persist_failure` re-raise the rendered exception chain carries the
project's own `_StageFailure` raw text as `__context__`, reaching
`receipts reprocess`'s un-netted **stderr** and RQ's failed registry;
`hide_parameters` cleans only the SQLAlchemy segment), 3 Minor; all four
guarantees' revert-proofs re-run at HEAD with G1/G2 independence proven in
both directions; `_PAN_RE` unmoved proven by blob identity. ONE fix wave
(`50992f5` enqueue twin + own test · `fa25013` the straddle pin ·
`1035fd3` ADR correction + design notes), one scoped re-review: **all four
findings ADDRESSED**, residuals adjudicated at the breaker (see deferred
list). Gates re-verified independently at every step; verify.py all five
PASS on `main` post-merge.

**Plan defects this milestone (#9, #10 — both the controller's sink map):**
#9 the enqueue loop's twin print (found by the Task-4 implementer,
exposure sharpened by two reviewers: only broker text reachable today —
fixed anyway under ADR-0022's standing rule, Route A); #10 `receipts
reprocess`'s un-netted re-raise rendering the raw `_StageFailure` chain to
stderr (found by the whole-branch review by execution; accepted residual
with mechanism recorded in ADR-0022's dated correction).

## Currency bound & fixture race — complete and merged (2026-08-03)

Design/plan: `docs/superpowers/{specs,plans}/2026-08-02-currency-bound-and-fixture-race*`.
Ledger: `.superpowers/sdd/2026-08-02-currency-bound-and-fixture-race/progress.md`.
**Task 1:** `save_extraction` bounds `currency` through the shared
`_CURRENCY_BOUND = _bounded_optional_text("currency")` (ValueError,
ADR-0006/0007); the §18 walk's second named structural exclusion (user
ruling; ADR-0018 dated correction names the guarantee test
`test_save_extraction_bounds_the_machine_path_currency`). **Task 2:**
`tests/test_cli_pipeline.py` draws seeded random rectangles per call (the
uniform-PNG all-zero-dHash dedupe race is dead); the two
byte-identity-dependent tests pass one shared blob via `_job`'s `data=`
override. Close: 0 Critical / 0 Important / 4 Minor; five queued minors
triaged (1–3 fixed, 4–5 deferred); fix wave `43a79ef`/`22639cd`/`f04aa65`;
re-review all six ADDRESSED. Plan defects #7 (walk collision → user
ruling) and #8 (transitive `_job` callers); review standard 13 promoted.

## PAN grouping — complete and merged (2026-08-02)

Design: `docs/superpowers/specs/2026-07-31-pan-grouping-design.md` (with dated
§2.2/§4.6 corrections). Plan: `docs/superpowers/plans/2026-07-31-pan-grouping.md`.
Decision: **ADR-0020** plus its **2026-08-02 dated correction**. Ledger:
`.superpowers/sdd/2026-07-31-pan-grouping/progress.md` (complete).

**What shipped.** `_PAN_RE` recognises seven separated shapes — `4-4-4-N`,
`4-6-5`, `4-6-4` (Diners), `4-4-5` (Maestro/legacy Visa), `5-4-4-4`, `6-4-4-4`,
`4-5-4-4` — plus the unseparated form; the separator accepts one or two
characters. Each fixed-shape alternative has a digit total inside 13–19, so
`_mask_pan`'s length check stays unreachable by construction. Two structural
guards pin the load-bearing properties over the shape space (no match starts at
a 3-digit group — the corpus-TIN guarantee, swept across **all 42** separator
spellings; every match holds 13–19 digits). The worked example, the residual,
and the `{1,2}` false-positive surface are all pinned by named tests.

**The residual is real and deliberate.** Against the plausible band (97
shapes): **15 compliant / 76 storing a whole card**, pinned by
`test_redact_pan_still_stores_some_groupings_whole`. **This did not close the
class.** Any claim that it did is false.

**The `{1,2}` cap's real cost:** 36 two-character spellings, 30 mixed, every
one firing where the baseline was silent — pinned by
`test_column_amounts_separated_by_two_characters_are_the_cost_of_the_cap`.
**Narrowing the separator is a queued user decision**, raised alongside the
residual decision.

**The load-bearing lesson (ADR-0020): coverage and cross-boundary risk move
together.** A generalised alternative covered 80 of 97 shapes and leaked a
full second card by tiling across two adjacent Amex numbers. **Any shape
added to `_PAN_RE` requires the two-instance check, every time.**

## How to run

- **There are two test suites.**
  - `python -m pytest` — **979** on `main`; offline and **Node-free**.
    `pyproject` sets `pythonpath=["src","."]`, `testpaths=["tests"]`.
  - **Vitest, in `frontend/`** — **221** across 19 files. `npm test`.
- **`npm test` does NOT type-check.** Run `npm run typecheck` too. **That trap
  fired three times in one milestone.**
- **`python scripts/verify.py` is the gate runner** — pytest, ruff, typecheck,
  vitest, build. Fails loudly naming the gate; when `npm` is absent it prints a
  per-gate `SKIPPED` and still gates the Python half. **See ADR-0017.**
- Lint: `python -m ruff check .` — bare `ruff` is not on PATH. Types: `mypy src`
  (informational). Alembic: `python -m alembic` — its console script is not on
  PATH either.
- CLI: `python -m receipts.cli <command>` — the console script needs the
  interpreter's `Scripts`/`bin` on `PATH`, which it is **not** on this machine.
- E2E (deliberate, not part of the sweep): `python scripts/seed_review_e2e.py
  --reset`, then `cd frontend && npx playwright test`. Playwright's Chromium is
  installed.
- Baseline: `python -m eval.run_baseline` — needs a **real provider + a labeled
  golden set**, else it refuses the `fake` provider / scores an empty set.
- **Terminal quirks:**
  - Piped pytest output can lose its final summary line. The `superclaude`
    attribution is **unproven**. Workaround: `--junitxml`, read counts from
    the XML.
  - **`pyproject.toml:61` already sets `addopts = "-q"`.** So `python -m
    pytest -q` is really `-qq` and prints **no pass count at all** — green
    would rest on the exit code alone — and `-v` nets back to default dot
    output, so `-vv` is what produces a listing. **Use bare `python -m
    pytest`.** Measured 2026-08-05; it was a plan defect that shipped into
    a task brief.
  - **`python scripts/verify.py` takes longer than a 2-minute tool
    timeout.** Run it with `run_in_background`, or raise the timeout.
  - **The Grep tool mangles `/` in its content output** (`"/receipts/"` →
    `"\receipts\"`, `[ .\-_/,]` → `[ .\-_\,]`, inconsistently within one
    result). It nearly produced a false `_PAN_RE` defect report on 2026-08-02.
    Verify slash-sensitive claims with Read, `git grep` via Bash, or by
    executing — never from Grep-tool output.

## What this project is

A VLM pipeline turning receipt photos into accounting-grade structured data.
**Prime directive: optimize auto-approval precision (target ≥99%), not raw
extraction accuracy. A wrong number is far worse than a missing one — prefer
`null` over a confident guess.** Three model passes (triage → extract → repair)
with deterministic validation between extract and repair, self-consistency for
handwriting, and one confidence score that routes to auto-approve or review.

## Invariants (never violate — see `.kiro/steering/receipt-system.md` + the ADRs)

`Decimal` on the money path, never `float` (ADR-0001). Validation is
deterministic/pure, never mutates, never raises, stable rule IDs. Tolerance is
cents-bounded (`rel=0.0002`, floor scales with line count). Repair keeps the
**best** attempt `(errors, warns, nulls)`; only errors trigger repair;
unparseable → re-extract; never alter numbers to force arithmetic. Structured
output via tool-use. Few-shot images first, target last. Consistency runs are
never cached. Merchant hints end with "trust the image." **A full PAN is never
persisted** (ADR-0018 the measured policy; ADR-0020 the detector shape;
**ADR-0022 the egress rule: failure text goes through `redact_pan` at every
place it leaves the process — a new log site, an API field, a queue payload
extends the inventory**). Nothing is silently dropped — every receipt reaches
a terminal state. **A machine run never overwrites a `reviewed` row.** Excel is
output only; the DB is the source of truth.

**PAN (ADR-0018, then ADR-0020 + its 2026-08-02 correction):** the group-shape
requirement in `_PAN_RE` is load-bearing — three of the four real corpus TINs
are **14 digits**, inside the 13–19 PAN window, silent only because they print
`3-3-3-N`. What protects them is the asymmetry that **every alternative opens
with a group of at least four digits while every corpus TIN opens with three**;
pinned across the whole shape space by
`test_pan_re_never_starts_a_match_at_a_three_digit_group`, which sweeps all
42 separator spellings. **Never relax the grouping toward "any run of 13+
digits."**

Any `_PAN_RE` change must: replay the **committed** battery in
`tests/test_repository.py` in **both** directions; test **two instances of what
it guards in one input**; and keep
`test_every_pan_re_match_holds_between_thirteen_and_nineteen_digits`
green. The 42/36/30 separator-surface counts quoted in prose are **unpinned** —
pinning `len(_ALL_SEPARATOR_SPELLINGS) == 42` is a queued one-liner.

**Frontend (ADR-0015):** money is a string end to end; **`<input
type="number">` and `valueAsNumber` are banned**; the browser stays same-origin
so **no `CORSMiddleware` is ever added**; SPA pages live under `/app/*` and no
API path moves.

## Decisions the user has made (do not re-ask)

- **Auth model — session auth + role checks (`reviewer`/`admin`), plus a separate
  API key for machine upload.** (ADR-0012.)
- **Accounts live in a `users` table**; the confidence breakdown is **persisted**
  at process time; `admin` owns `/export/xlsx` + user management; `POST /upload`
  writes a `pending` row before queueing.
- **ISSUE-001 (the real baseline) is deferred until the system is built** — the
  user's explicit call. Do not start it unprompted.
- **Frontend is React 19 + Vite + TypeScript** (ADR-0015).
- **bbox highlighting is out of scope.** Revisit only if P2.T2 is resolved with
  an OCR pass.
- **Review-screen findings are labelled historical.** A dry-run `POST /validate`
  endpoint was considered and deferred.
- **Push policy (2026-07-30): pushing `feat/*` branches is authorised. Ask
  before pushing `main`.** Every `main` push authorization is one-time (the
  2026-08-02 one covered the PAN grouping merge; the two 2026-08-03 ones
  covered the currency-bound and failure-egress merges; all consumed).
- **`GET /review/next` resumes the caller's own in-progress task** (2026-07-30,
  ADR-0016).
- **`receipt.date_raw` is editable** (2026-07-31), as plain text.
- **The UI warns when the server stored something other than what was sent**
  (2026-07-31), by diffing the patch against the returned `ReceiptDetail`.
- **PAN rulings (2026-07-31, hardening — ADR-0018):** minimal one-character
  widening; leak (a) closed; **leak (b) ACCEPTED, not fixed**; the scan-loop
  alternative priced (O(n²), ~1715 ms on 40 KB) and refused.
- **PAN grouping (2026-07-31, ADR-0020): Option A — enumerate the five named
  groupings, cap the separator at two characters, document the residual as a
  number.** Closing the plausible band properly is **a separate scoped
  decision the user has not been asked to make yet** — as is **narrowing the
  `{1,2}` separator** (36 spellings, 30 mixed, measured and pinned).
- **Currency bound (2026-08-02):** over-long machine-path `currency` **raises
  `ValueError`** via the human path's own coercer; the §18 walk's second
  named exclusion is `currency` (dated correction in ADR-0018).
- **Failure-egress redaction (2026-08-03, ADR-0022):** the FULL egress class
  closed in one branch; the failure log's traceback **rendered and redacted**
  (not dropped, not raw); the enqueue twin print fixed under the standing
  rule (Route A at the close); the reprocess/stderr raw-chain exposure is an
  **accepted residual with its mechanism recorded** (ADR-0022's dated
  correction — closing it would need producer-side redaction or a rendering
  net in `main`/the worker, both priced, neither taken).
- **Task 5's CI job was cut** (Phase 5). `scripts/verify.py` replaces it
  (ADR-0017).
- **Review-UI error recovery (2026-08-03/04, ADR-0024):** unsubmitted edits
  survive a 401 **in memory only** — never `sessionStorage`, so a reload
  still starts clean; the backend-down sentence renders **without**
  `role="alert"` (a second alert makes the suite's single-alert queries
  ambiguous — the cost, a screen reader hearing only the raw server words,
  is accepted and recorded); and the design's terminal `taken`/`gone` state
  **supersedes** the old 403/404-on-complete retry contract, so three
  pre-existing tests were rewritten rather than the design narrowed.
- **The runaway agent's work was kept, not reverted** (2026-08-03): commits
  authored outside the dispatch loop were gated by the normal task review
  and merged on their merits; provenance is recorded in the ledger.
- **Admin release (2026-08-04, ADR-0025):** **admin-only**, not reviewer
  self-release; `OPEN` is idempotent and **`DONE` is refused** (releasing a
  closed task would lose the only record that anyone reviewed the receipt);
  audit is **a log line plus a response echo**, no new column — with the
  limit stated, that the log is the only durable trace and logs are not the
  database; **API-only this milestone**, with the admin UI split off as its
  own; and the **re-claim residual accepted** — because `opened_at` and
  `priority` are preserved, a still-polling displaced reviewer can re-claim
  the task an admin just took, which never arises for the case the feature
  exists for (someone who stopped polling).
- **`PATCH /receipts/{id}` stays claim-unaware** — a displaced reviewer's
  edits still land and only the close fails. That is ADR-0024 §3's premise,
  not an oversight; making it claim-aware is its own milestone.
- **The admin surface is two milestones, release first** (2026-08-04), and
  the release was merged **locally only** — the user chose "merge locally"
  and no `main` push was authorized.
- **Admin UI backend routes (2026-08-05, ADR-0026):** **`GET /auth/me`
  answers 401, not `200 {"user": null}`** — it stays inside `require_user`,
  joins `READ_ROUTES`, and lets the frontend's existing global 401 handler
  correct `session.ts`'s guess with no new client logic; the accepted cost
  is a 401 in the log on every anonymous cold load. **`GET /review/tasks`
  gives equal access with role-dependent content** — a reviewer sees the
  open backlog plus their own rows, an admin sees everything. **The privacy
  property is relied on and pinned rather than defended by a defensive
  filter** — a defensive filter was rejected because a broken invariant
  would then silently drop an open task from every reviewer's list, and
  per-caller masking was rejected because under the invariant that code
  never executes. **A listed row reuses `_task_summary` unchanged.**
- **`main` was pushed at the end of the admin-UI-routes session**
  (2026-08-05), on an explicit one-time authorization that is now consumed.
  All 13 `feat/*` branches were audited as already-merged (+0 commits each)
  and all are pushed. **The nine plan defects were re-audited at the same
  time**: all three that touched shipped code are correct in the tree, and
  the five still living in the plan's body are covered by a **dated defect
  log appended to that plan** — plans do not self-amend here, so the log is
  appended the way an ADR takes a dated correction.
- **Milestone close includes the handoff refresh** (ADR-0019); **every session
  end refreshes the handoff** (ADR-0021), whose freshness check was widened by
  dated correction (2026-08-02) to include `docs` with the handoff pair itself
  excluded.

## Still needing a user decision

1. **Auth for the `corrections` read route** — reviewer-visible, admin-only,
   or both scoped differently? **An answer was given in the 2026-08-05
   session — "both, scoped differently: reviewers see corrections for the
   receipt they hold, admins see any receipt's" — but it arrived alongside a
   system notice disclaiming it as user input, and it was never restated for
   confirmation.** Treat it as the user's likely intent and **re-confirm it
   verbatim before designing the route**; do not record it as a settled
   ruling on the strength of that exchange alone. Gates Phase 5 follow-up #1.
2. **A hosted tool-capable provider + a freshly rotated key** — for ISSUE-001,
   and therefore for all calibration.
2. **R060/R061 OCR grounding (P2.T2)** — model returns the text it read / a
   cheap OCR pass / drop the rules. Also gates bbox highlighting.
3. **Whether GitHub Actions should run again.** If yes, the workflow should
   call `scripts/verify.py` rather than re-listing the gates.
4. **Whether to close the PAN grouping residual**, and by which priced route
   (shape table with per-entry two-instance gate, or candidate-then-validate
   scan loop).
5. **Whether to narrow the `{1,2}` separator** (e.g. to doubling only) now that
   its 36-spelling surface is measured and pinned.
6. **Do the public golden labels need scrubbing?** (Real third-party names,
   TINs, addresses — also the exact values the PAN silent-case tests pin.)

## Built

**Core (Phases 0–2).** `extract/`: schema, prompts, json_io, paths, extractor
(3-pass + repair + best-attempt + self-consistency), lineitem_align,
clients/{base, fake, anthropic_client, openai_compat, factory}. `validate/`:
rules (28), report, context, validator. `normalize/`: numbers, dates, text.
`preprocess/`: image_ops, bounds, quality. `ingest/`: storage, dedupe, ingest.
`export/xlsx.py` (all four §13 sheets). `score/confidence.py` +
`score/thresholds.py`. `pipeline.py`, `config/settings.py`, `eval/` (metrics,
harness, golden_set, run_baseline). **The R020/R024 VAT-inclusive fix
shipped** — `prices_include_tax` is threaded from `extract/schema.py` into
`validate/rules.py`.

**Phase 3 — persistence.** `persist/models.py` (**8 tables**) +
`docker-compose.yml`; `alembic/`; `persist/session.py`; `persist/repository.py`
(§14.8 + DB-backed dedupe); `review/queue.py`.
- `persist/__init__` is **lazy** (PEP 562 `__getattr__`).
- `next_task` applies `FOR UPDATE SKIP LOCKED` only on dialects that support it —
  **SQLite silently drops the clause**, which is why the guard lives in Python.
- The migration drift guard runs on SQLite only.

**Phase 4 — service + CLI.** `pipeline.process_receipt` (all 8 stages wrapped);
`extract/clients/limits.py` (`VLMGate` + `CostGuard` + `GuardedVLMClient`);
`worker.py` (RQ, lazy behind a `worker` extra). `persist/users.py` (stdlib
scrypt); `review/auth.py`; `review/{api,schemas,serializers}.py` — `create_app`
plus the route table in `review/api.py`, which is the durable reference (a
count in prose here would rot; ADR-0025 added a row to it). `cli.py`:
`ingest|process|export|eval|calibrate|merchants|reprocess|users`. ADR-0011,
ADR-0012, ADR-0013, ADR-0014.

**Phase 5 — the review UI.** `frontend/` (React 19 + Vite + TS): login, the
review screen, `ConfidenceRail`, `FindingsPanel`, `ImagePane`, `ReceiptForm`
(all 17 correctable paths), `LineItemsTable`, `MoneyInput`, `patch.ts`,
`session.ts`, `ErrorBoundary`. Strictly sequential `PATCH → complete → next`;
⌘/Ctrl+Enter approves; a rewrite warning that **holds the screen**. Served
same-origin under `/app` by a guarded `StaticFiles` mount. Plus
`scripts/seed_review_e2e.py`, `scripts/serve_review_e2e.py` (**e2e-scoped**),
`scripts/verify.py`, a Playwright acceptance spec, and
`frontend/tests/no-float-in-money-path.test.ts` (measured sound, but it has
**no rule that can fire on arithmetic**).

Backend changes Phase 5 forced: `receipt_detail` returns `receipt_number`,
`txn_time` and `payment_method`; **`GET /review/next` resumes the caller's own
in-progress task** (ADR-0016).

**PAN hardening (2026-07-31, merged).** `_PAN_RE`'s four-group tail widened
`\d{1,4}` → `\d{1,7}` (leak (a) closed; leak (b) accepted and pinned;
ADR-0018). `save_extraction` redacts **every** extraction-sourced value it
stores via a `type(value) is str` gate; system-minted values are structurally
excluded. `card_last4` keeps the stronger `_last4` guarantee. `enqueue_review`
redacts `reason` at the sink. Guards: a two-table column walk seeding all
reachable extraction text fields; the four corpus TINs pinned silent.

**PAN grouping (2026-08-02, merged).** See its section above.

**Currency bound & fixture race (2026-08-03, merged).** See its section
above: the machine-path `currency` bound through the shared coercer
(ADR-0018's second named walk exclusion), and the CLI test module's
structurally distinct fixture images with the `data=` override.

**Admin release (2026-08-04, merged).** See its section above: `release_task`
in `review/queue.py` and `POST /review/{task_id}/release` in
`_install_write_routes`, admin-only, with ADR-0025 recording the five
rulings, the accepted re-claim residual and the third race order.

**Failure-egress redaction (2026-08-03, merged).** See its section above:
the four ADR-0022 guarantees — carrier redact-before-truncate, the
rendered-and-redacted failure log, `hide_parameters=True`, both failed-job
prints — pinned by six named tests including the straddle pin.

**Admin UI backend routes (2026-08-05, merged).** See its section above:
`GET /auth/me` in `review/auth.py`'s `build_auth_router()`, and
`GET /review/tasks` in `_install_read_routes` backed by `list_tasks` in
`review/queue.py` (exported from **both** `queue.py`'s and
`review/__init__.py`'s `__all__`), with ADR-0026 recording the three
decisions, the two rejected alternatives, and the stated limit of the
privacy pin. `_task_summary` moved above the read routes; its old home under
the "Write routes (P4.T5)" banner was wrong once a read route consumed it.

## Remaining work

**`docs/NEXT_SESSION_PROMPT.md` carries the full ordered task list.** Headlines:

1. Phase 5 follow-ups — the five §5 error-recovery behaviours (ADR-0024)
   and the **admin release** (ADR-0025) are DONE. **Two remain:** a read
   route for `corrections` (**blocked on the auth ruling — see "Still
   needing a user decision" #1, whose answer needs re-confirming**) and a
   real ASGI entry point / deployment story.
1b. **A design system for the review UI is DRAFTED but NOT APPROVED and NOT
   PLANNED** — `docs/superpowers/specs/2026-08-05-review-ui-design-system.md`,
   with the raw generated output at `design-system/receipt-review/MASTER.md`.
   Written 2026-08-05 at the user's request from a Qarin SaaS-template
   reference plus the `ui-ux-pro-max` skill. **Measured basis: `frontend/`
   contains NO stylesheet at all** — `git ls-files frontend` matches no
   `.css`/`.scss`, so every surface is browser default. The reference is a
   *marketing* template, so only four patterns transfer (stat tiles,
   comparison-table row rhythm, accordion, card shell) and the spec says so
   rather than bending a landing page into a review tool. **Its §4 is the
   rule no generic system supplies: `null` must never look like `0`, and
   neither may look like "empty"** — the prime directive reaching the last
   inch of the UI, and testable. **Four questions gate the work** (spec §9):
   light-vs-dark default, CSS Modules vs Tailwind vs plain CSS (recommended:
   CSS Modules + one `tokens.css`), whether a browser pass is part of "done",
   and whether the admin surface gets its own route shell.
2. **The admin UI's FRONTEND half is the committed next milestone.** Its two
   backend contracts shipped 2026-08-05 (ADR-0026) and **nothing under
   `frontend/` consumes either one yet.** What remains: read `/auth/me` on
   mount, widen `session.ts` from one boolean to an identity (today
   `session.ts:21` guesses "signed in unless the URL says otherwise"), give
   `LoginPage` somewhere to put the role it currently discards, and build a
   new `/app` admin surface that lists tasks via `GET /review/tasks` and
   drives `POST /review/{task_id}/release` from a browser. **Nobody has
   viewed ANY of the review UI in a browser** — that risk is inherited, not
   new, and is called out in the design's §8 so the frontend design does not
   absorb it silently.
3. **Phase 6** — merchants & few-shot. **Phase 7** — self-consistency wired into
   the pipeline, gated on `triage.is_handwritten`. **Phase 8** — calibration and
   eval-harness honesty.
4. Still open from earlier phases (see the prompt's §5).
5. **ISSUE-001 last.**

## Environment / provider (user's `.env`, gitignored)

- Active config: `VLM_PROVIDER=ollama`, `VLM_BASE_URL=http://localhost:11435/v1`,
  model `granite3.2-vision:2b` (both passes), `DEFAULT_CURRENCY=PHP`,
  `VLM_TIMEOUT_S=900`. `openai` SDK installed; `anthropic` is not.
- **Golden set is LIVE** — `eval/golden/labels|images/{r001,r002,r003}` on disk.
  `eval/golden/images/` is gitignored (the parent is not — do not move real
  receipts up a level).
- Ollama runs in Docker (service `ollama`, host port **11435** → container
  11434). The native Windows Ollama CLI points at 11434 — use
  `docker exec ollama ollama …` or set `OLLAMA_HOST`.
- **Local CPU inference is not viable for real numbers.** No GPU passthrough;
  measured 262 s–1205 s per call. Ollama rejects a `tools` payload for models
  without the capability, so the local path runs JSON mode (ADR-0002). Offline
  spot checks only.
- **Security:** a commented-out Gemini key was once echoed in output → **rotate
  it before use.** Never echo `.env` secret values.
- **Git:** default branch `main`; `origin` → `CDGYu/Receipt-Digitalization`,
  **PUBLIC**. Push `feat/*` freely; **ask before `main`**.
  Every merged `feat/*` branch is kept at its merge point and pushed.
  **For where `main` itself stands, read the Snapshot — never this bullet.**
  It used to carry its own commit id and rotted by two whole milestones
  before anyone noticed; the Snapshot is the single stamp of record.
- **What the public repo exposes — surfaced to the user, no ruling yet.**
  Nothing secret leaked: `.env` never committed, no image file tracked. But
  `eval/golden/labels/r00*.json` **are** tracked and world-readable, carrying
  real third-party business identities (also the exact values the PAN
  silent-case tests pin, so scrubbing is not free). **Awaiting the user's
  decision.**
- **Gitignored and untracked:** `.kiro/` (steering still auto-loads from disk),
  `.github/workflows/` (**Actions does not run**), `.superpowers/` (the SDD
  ledgers), and **`var/`**, where `STORAGE_ROOT` defaults to `var/blobs` and
  writes **real receipt images**. Never stage one.
- **Harness notes:** the `developer-kit` plugin's
  `prevent-destructive-commands.py` hook used to block `git add`/`git commit`;
  fixed 2026-07-28, **a plugin update will overwrite this**. It also falsely
  blocks `rm` under the repo and read-only `git grep` whose *pattern* names a
  sensitive file — PowerShell `Remove-Item` works, rephrase patterns.
  `developer-kit-typescript`'s `ts-file-validator.py` complains about
  PascalCase `.tsx` — PostToolUse, cannot block, ignore. **The Grep tool
  mangles `/` in content output** — see "How to run". Subagents may report
  injection-shaped file-watcher notices — verify with git, do not comply,
  disclose.

## The real receipt corpus (from the user's first 3 samples, 2026-07-28)

The user's documents are **Philippine BIR "SALES INVOICE" forms: a
machine-printed template with every value filled in by hand.** Labelled in
`eval/golden/labels/r001-r003.json`. All confirmed against the code:

- **`document_type=INVOICE` + `print_type=MIXED`, not `handwritten_receipt`.**
  `TriageResult.is_handwritten` already returns True for `MIXED`, so **gate
  self-consistency on `triage.is_handwritten`, never on `document_type`.**
- **The handwriting penalty must read triage too** — `score_confidence` reads
  only `receipt.meta.is_handwritten`.
- **Blank pre-printed product rows** (Metro Oil pre-prints six fuel rows) must
  not become line items — needs a prompt instruction and/or a rule (sibling of
  R052).
- **Buyer-vs-merchant trap:** every form has `SOLD TO: Ideal Source` (the
  user's own company). `merchant.name` must be the ISSUER.
- **Printer-TIN trap:** the footer carries the printing press's TIN.
  `merchant.tax_id` must be the `VAT Reg. TIN` in the header.
- **The TINs are why the PAN grouping rule is load-bearing:** three of the four
  labelled TINs are 14 digits, printing `3-3-3-N`. Pinned by
  `test_redact_pan_is_silent_on_the_merchant_tax_ids_this_corpus_prints` and
  structurally by the lead-3 guard.
- **Currency is never printed.** `DEFAULT_CURRENCY=PHP` is required or currency
  stays null.
- **Composition:** if this hybrid form is the whole corpus, the spec's §15
  target mix does not describe reality. Raise before scaling M0.
- VAT is 12% and totals read `net + VAT = TOTAL AMOUNT DUE`. Merchant
  `VAT Reg. TIN` is the strongest fingerprint for Phase 6 matching.

## DEFERRED — do this LAST

**ISSUE-001: run the first real baseline.** Parked by the user on 2026-07-28.
Full diagnosis and exact resume steps are in **`docs/KNOWN_ISSUES.md`** — read
that, do not re-derive it. Blocker: `granite3.2-vision:2b` on CPU takes ~262 s
per call. **Fix: point it at a hosted tool-capable model** (the commented-out
Gemini block in `.env`; rotate that key first). Until this runs there are **no
real accuracy numbers**, no threshold calibration (P3.T6 / P8.T1), and no way
to judge a prompt or rule change. **Do not treat any precision claim as
measured.**

## Deferred follow-ups / known minors (non-blocking)

- **Shipped from the admin-UI-routes close (2026-08-05): 20 Minor findings,
  triaged by the whole-branch reviewer as safe to ship.** They live in
  `.superpowers/sdd/2026-08-05-admin-ui-backend-routes/progress.md` with
  per-item rulings. The ones a future editor will actually trip over:
  - ~~**`api.py`'s signed-blob docstring says it "is the one unauthenticated
    route in the service"**~~ — **FIXED 2026-08-06 (`bbb5366`)**, folded into
    the review-UI-styling branch. It was one of five (nine with
    `DOCS_ENABLED=true`); now narrowed to "the one route that serves receipt
    data without a session", with the real set named, the method recorded, and
    the reader told to re-run it. Two independent enumerations — static
    dependant tree and empirical no-cookie call — agreed on both counts. It
    was **never** true: the sentence arrived at `130b202` (2026-07-29) and
    `/health` had been in that file since `b7a2966` the day before.
  - `tests/test_api_read.py:507-508`'s block comment ("each of these is a
    bare GET against `receipt_id`") is false for two of its three rows —
    `/review/next` and `/export/xlsx` take no `receipt_id`. Pre-existing.
  - **`GET /receipts`' `has_more` is unpinned in the `True` direction** — a
    constant `has_more: False` survives all 979 tests. Measured at the close
    as a control. `GET /review/tasks` is strictly better than the route it
    was copied from: both directions die there.
  - The route-level ordering test for `/review/tasks` is blind to `ORDER BY`
    *removal* (the fixture's insertion order already equals queue order) but
    does discriminate a *wrong* order. The guarantee is properly pinned at
    the queue layer, whose fixture inserts out of order.
  - `ReviewTaskListResponse`'s body is byte-identical to
    `ReceiptListResponse`'s. Defensible — distinct response models give
    distinct OpenAPI schema names — but a third page envelope earns a base.
  - `RECEIPT_SYSTEM_SPEC.md`'s `# api.py  (FastAPI routes)` header now heads
    three routes that live in `auth.py`'s `build_auth_router()`.
    `# api.py + auth.py` settles it when that line is next in remit.
  - **No cache directives anywhere in `src/`** — no `Cache-Control`,
    `no-store` or `Vary`, verified by grep. `GET /auth/me` echoes an
    identity on every cold load, which makes it the natural place to raise a
    global `no-store` decision during the frontend milestone.
- **Both items parked at the admin-release close were FIXED post-merge**
  (2026-08-04, `9dd2fea`, at the user's direction rather than waiting for
  the next edit of those files): `test_release_requires_authentication`'s
  false generalization about where other routes get their machine-key row,
  and the race test's repair instruction, which was true of its outcome
  assertions and false of its mechanism one. Prose only. **Nothing from
  this milestone remains parked.**
- **Layer-wide and pre-existing, measured at the admin-release close:**
  nothing pins the queue layer's caller-commits rule. Deleting
  `release_task`'s `flush()`, or turning it into a `commit()`, leaves the
  suite green — and the same is true of `enqueue_review` and `next_task`
  (controls were run). Only `close_task` is pinned, incidentally. A hidden
  commit would make a queue function an undocumented exception to ADR-0006
  with nothing going red.
- **Parked at the review-UI error-recovery close** (bundle with the next
  legitimate edit of the file named): `frontend/tests/review-screen.test.tsx`
  carries **"42/42 green" in a comment** — a suite count (review standard 5)
  that was stale on arrival, and introduced by the fix for another
  standard-5 violation; delete the number, keep the mechanism sentence.
  Also: `edit()` does not reset `submit`, so an inline field error stays on
  screen while the reviewer corrects that very field (clears at the next
  submit) — the most user-visible of these; no `aria-invalid` beside
  `aria-describedby`; the select/checkbox no-slot invariant is comment-only;
  the sign-out confirm can say "unsaved edits" about edits that did land
  (a complete-step failure); keystrokes typed *while a submit is in flight*
  are not stashed (the mirroring effect's dep list is `[phase]` alone).
  **Nobody has viewed any of this milestone's UI in a browser** — the error
  text is an unstyled `<p>` between controls.
- **The failure-egress residual (ADR-0022 + its dated correction):** on a
  `_persist_failure` re-raise, the rendered exception chain carries
  `_StageFailure`'s raw producer text as `__context__` to `receipts
  reprocess`'s stderr and RQ's failed registry; `hide_parameters` cleans only
  the SQLAlchemy segment. **Accepted with mechanism recorded**; closing it
  needs producer-side redaction (policy reversal) or a rendering net in
  `main`/the worker — both priced, neither taken.
- **Parked at the failure-egress close (bundle with the next legitimate edit
  of the file named):** the straddle test's one-character margin — add
  `assert result.failed_stage == "persist"` as its prefix anchor
  (`tests/test_process_receipt.py`); ADR-0022 nowhere names
  `test_the_reason_bound_never_bisects_a_pan_into_the_clear` (append-only
  consequence; the design and ledger carry it); the milestone's 12 remaining
  task minors live in its ledger with the triage verdicts.
- **PAN — the accepted residue (ADR-0018 + ADR-0020 + its correction):**
  leak (b)'s remainder-in-the-clear (user ruling); the grouping residual
  (15/76, closure queued as a decision); the `{1,2}` separator surface
  (36 spellings, pinned; narrowing queued); four accepted false positives
  (13–19 digit identifiers; side-by-side column amounts; ~1-in-200 16-hex
  hashes — **no hash is ever routed through `redact_pan`**; whole-number
  13–19 digit modifier amounts) — a class that now also renders masked in
  operator diagnostics via the failed-job prints (priced in ADR-0022).
- **Parked at the PAN grouping close (bundle with the next legitimate edit of
  `tests/test_repository.py`):** the range-guard docstring's "about 30x"
  (measured 19.6x); the mixed-pairs "width changing mid-run" rationale;
  pin `len(_ALL_SEPARATOR_SPELLINGS) == 42`; the module docstring's "reaches
  thirteen" 16-hex nuance; ADR-0018's References naming the nonexistent
  `MUST_MASK` battery.
- **Parked at the currency-bound close:** `_PNG_SEEDS` starts at 0,
  overlapping the explicit `seed=0` blob (measured harmless; worth a comment
  on the next `tests/test_cli_pipeline.py` edit); design §2.2's terse
  mechanism; the plan's self-review note (plans don't self-amend).
- **`image_phash` on a failed receipt** — `_persist_failure`'s update branch
  never touches the column, so a post-ingest failure keeps `""` and can never
  serve as a dedupe original. Address with Phase 6 dedupe.
- An auto-approving reprocess closes a review task a reviewer had already
  claimed.
- **No login rate limiting**, and each attempt costs a full scrypt derivation
  (~16 MB, ~57 ms). Address before this faces more than a LAN.
- `receipts eval`/`calibrate` traceback without the `pipeline` extra.
- An **all-failed** eval run still persists `"auto_approval_precision": 1.0` to
  the results JSON. Fix with P8.
- Reprocessing a `reviewed` receipt records **no** `extraction_runs` — the
  transaction rolls back (ADR-0013's dated correction).
- Move confidence penalty weights into `config/rules.yaml` (P3.T6).
- `_attempt_prompt_hash` must receive merchant hints / few-shot values when
  they land, or the stored hash drifts.
- **Semantic dedupe is deliberately not wired** into `process_receipt` until
  Phase 6 (ADR-0011).
- `save_extraction` takes `report` but does **not** write findings — the
  pipeline calls `save_findings` separately.
- `_build_line_items` falls back to list order when emitted positions aren't
  distinct.
- `enqueue_review` is check-then-insert; concurrent enqueues can raise
  `IntegrityError`.
- `vllm`/`ollama` still require `VLM_API_KEY`; `VLM_BASE_URL` ignored for
  `anthropic`.
- XLSX `write_only` streaming above 5000 rows is deferred.
- ruff sorts `from alembic import command` as first-party in tests — don't
  "fix" that import order.
- Phase 5's own minors are in its ledger with rulings; each PAN milestone's,
  the currency-bound milestone's, and the failure-egress milestone's are in
  theirs.

## Workflow & conventions

- **subagent-driven-development**: one fresh **`general-purpose`** implementer
  per task, briefed to read the real signatures first, work TDD, keep **both**
  suites green + ruff clean, and stage only its own files. The controller
  reviews the diff, re-runs the gates **independently**, then dispatches a task
  review, then appends to the ledger.
- **Per milestone**: a feature branch; at the end a whole-branch review on the
  strongest model, **one** consolidated fix wave, one scoped re-review, then a
  fast-forward merge — **then the handoff refresh in the same session
  (ADR-0019)**. Branches and SDD workspaces are **kept**.
- **Probe before dispatching — and sweep transitively.** Plan-defect count by
  milestone: Phase 5 eleven; PAN hardening five; PAN grouping six (+1 in a
  controller dispatch prompt); currency bound two; failure-egress two;
  review-UI error recovery four; admin release seven; **admin UI backend
  routes NINE** — three caught before any dispatch (a pre-flight scan and
  the plan's own self-review), then: a gate command that printed no pass
  count because `addopts` already held `-q`; no red-proof prescribed for a
  new `READ_ROUTES` row; a mutation presented as single-guarantee that
  killed three extra tests for the wrong reason; a wrong test named in a RED
  prediction; a docstring whose pin list enumerated one triple and cited
  tests for a different one; and **#9, a false universal about the auth
  guard that this project's own ledger had cleared as "STILL TRUE" during a
  standard-12 re-read** — the only one that reached the shipped tree.
  **Every one was the controller's, and every one was caught by an
  implementer or reviewer who checked instead of trusting.** The plan's
  prose is reliable; its claims about existing artefacts are not. **Eight
  milestones, no exception.**
- **Adjudicating a standard-12 re-read is not the same as performing one.**
  Defect #9 shipped because the controller accepted an implementer's
  "STILL TRUE" answer, which rested on verifying that two guards *call*
  `require_user` and generalising from that — never enumerating the routes.
  The close's re-reviewer settled the same question in one pass by building
  the route table from `create_app` and reading each route's resolved
  dependant tree. **If a claim quantifies over a set, the answer is the
  enumeration, not an argument about the set.**
- Conventional commit messages (`feat(scope): …`, `fix: …`, `chore: …`,
  `docs: …`).

### Review standards — hold all of them

1. **Reviewers reproduce, they do not reason.**
2. **Every new test must be proven to fail** with its fix reverted.
3. **A test asserting the absence of breakage cannot be proven by a RED run** —
   revert each guarantee separately.
4. **A mutation must change exactly one thing**, or the result names the wrong
   cause.
5. **If a number can change without its sentence changing, it does not go in
   the comment.**
6. **A claim about what your own artefacts say is itself a claim requiring a
   command.** Grep; do not recall.
7. **Do not credit a tool with settling a question you have not put to it.**
8. **A stub that does not reflect the write is a fixture bug** that lies
   dormant until something reads the reply.
9. **Test a guard with two instances of what it guards in one input.**
10. **A battery you write agrees with you** — replay the committed battery in
    both directions before trusting a change.
11. **Coverage and cross-boundary risk move together** (ADR-0020).
12. **Adding rows to a prose table also changes every sentence that quantifies
    over the table.**
13. **A prose claim about what a test would do under a mutation needs the same
    revert-proof discipline as an assertion — or it does not carry
    "(measured)".**
14. **A pin that was never proven to fail is not a pin.** The review-UI
    error-recovery close found five guarantees — including the milestone's
    own headline deliverable, deletable outright with all five gates green —
    stated, believed, and unprotected. The fix wave then measured that one
    *instructed* placement for a new pin could not go red at all (a later
    `load()` overwrote the state it asserted on) and moved the test rather
    than land a pin that never fails. When a review says "unpinned", the
    answer is a mutation that goes red.

15. **A mutation that kills the right test for the wrong reason proves
    nothing.** The admin-release milestone shipped a mutation table in which
    two of seven rows were worthless: deleting the route's `admin` parameter
    also deleted the binding its log line reads, so the route raised
    `NameError` before any authorization was tested; and "log `task.reason`"
    could not leak, because the log call sits outside the session and the
    attribute access raised `DetachedInstanceError` first. Both *looked*
    like proof — tests went red on cue. Read the failure, not the colour:
    if the assertion that failed is not the one the pin exists for, the
    mutation changed more than one thing and proved none of them.

16. **Confirming a mutation landed is not confirming it landed where you
    meant.** The admin-UI-routes close found that `api.py` carries
    `limit=limit + 1` and the `has_more` return line **twice** — once for
    `GET /receipts`, once for `GET /review/tasks`. Two mutation runs applied
    cleanly, with a correct non-empty byte delta, **to the wrong route**,
    and reported the full suite passing. A non-empty `git diff --stat` only
    proves *something* changed. Anchor on text unique to the target, or
    verify the changed line's location, before believing a survivor.

17. **A universal claim is answered by an enumeration, not an argument.**
    Defect #9 — "the guard every other authenticated route uses" — survived
    an explicit standard-12 re-read because the check reasoned about which
    guards call `require_user` instead of listing the routes. Two
    counter-examples were sitting in the tree. Enumerating them took one
    script; the reasoning that replaced it took less and was wrong. **Note
    the trap in that enumeration:** on this FastAPI version `include_router`
    wraps the auth router in an `_IncludedRouter`, so a flat walk of
    `app.routes` yields 13 routes with **zero** `/auth/*` paths — recurse
    through `.original_router.routes` for the real 17. A transitively-called
    guard (`require_role` → `require_user`) is invisible at runtime too; it
    is plain Python, not a nested `Depends`.

18. **A substring can answer for a declaration.** Three times in one milestone:
    `--color-surface-raised` satisfied `toContain('--color-surface')`, so
    deleting every `--color-surface:` declaration left the suite green; and
    `border-left: 2px solid var(--color-null)` satisfied
    `toContain('var(--color-null)')`, so deleting `color: var(--color-null)` —
    §4's headline visual signal — left it green too. Assert on declarations,
    exact equality, or set membership. Never on containment.

19. **An enumerated defence never converges.** Four consecutive fix rounds on
    the review-UI styling branch each closed the shapes that had been found and
    re-asserted the class was closed; each assertion was falsified by the next
    round. **The recurring defect was the assertion, not the code.** What broke
    it: state one bounded, checkable property, enforce it at both ends, move the
    enumerations into the tests as examples, and **report further shapes rather
    than fixing them**. A round has converged when it adds a
    *universally-quantified accept-side* assertion that fails on the previous
    round's defect without anyone having thought of that defect.

20. **A list in prose is read as complete, so writing one is a claim.** Four
    instances measured in this tree, three closed 2026-08-06 and two of those
    found only because a task's pre-flight went looking:

    * ADR-0027's "every one of the 17 correctable paths is an `<input>`" —
      sixteen inputs and one `<select>`, and the consequence it licensed
      (`placeholder`) reaches **fourteen**. Corrected `46eb965`.
    * The design spec's "Rulings — all four settled 2026-08-05", which reads as
      an index of every decision taken and is in fact the four questions open
      at drafting. Corrected `ae4b782`.
    * `vite.config.ts`'s "Cross-checked against every route `create_app`
      registers" — listed 13 of 16. **Closed `2689635`**, by re-deriving the
      list from the built app rather than editing the list in place; the
      comment now records the method and the date so the next reader re-runs
      it. It listed exactly 13 because a *flat* walk of `app.routes` yields
      13 — the same trap standard 17 records.
    * `api.py`'s "This is the one unauthenticated route in the service" —
      five, or nine with `DOCS_ENABLED=true`. **Closed `bbb5366`**, by two
      independent enumerations (static dependant tree, empirical no-cookie
      call) required to agree. Dated in the fix because it was **never** true:
      the sentence arrived a day *after* `/health` was already in the file.

    **All four are now closed**, each by re-deriving the claim rather than
    editing it in place. The pattern that found every one: ask where the claim
    could be checked, then run that — not read the claim again.

    Standard 17 governs how to *answer* such a claim. This one governs
    **writing** it: an enumeration in prose inherits the authority of the thing
    it enumerates, so it gets trusted rather than re-derived — one of these
    misled an explicit standard-12 re-read. **Either enumerate from the code at
    the moment you write it and name what you ran, or write a sentence that does
    not quantify.** "A route that serves receipt data without a session" costs
    nothing and cannot rot; "the one unauthenticated route" rots the first time
    anyone adds a route.

    **And searching for one is harder than it looks:** `api.py:494`'s claim
    survived a `git grep` for its own words, because the sentence wraps
    mid-phrase across two lines. Grep for one distinctive word, never the
    phrase.

And: **a green suite is not evidence that installed software works.** Anything
with an entry point gets run from outside the repository.

## Key references

- `RECEIPT_SYSTEM_SPEC.md` — §3 architecture, §6 data model (**8 tables**), §9
  normalization, §10 validation, §12 confidence + routing, §14 function
  inventory, §15 milestones, §16 eval, §17 config, **§18 traps (PAN)**, §19 DoD.
- `docs/NEXT_SESSION_PROMPT.md` — the ordered task list and reading order.
- `IMPLEMENTATION_PLAN.md` · `README.md` (§5 design decisions) · `VLM_AND_DATA.md`
- **`docs/KNOWN_ISSUES.md`** — ISSUE-001 with its diagnosis and resume steps.
- **`docs/adr/` — 0001–0026**; see `docs/adr/README.md`. Read **0001** first;
  **0018 then 0020 (with corrections)** before touching `_PAN_RE`/`redact_pan`;
  **0022** before touching any failure-text egress; **0024** before touching
  the review UI's error surfaces (`failure.ts`, `stash.ts`,
  `SignOutControl.tsx`, `ReviewScreen.tsx`'s state unions, the inline error
  slots); **0026** before touching `/auth/me`, `/review/tasks` or
  `list_tasks`' scope — it is also where the privacy invariant's limit is
  recorded; **0023 (with both dated notes)** before dispatching parallel task
  agents; **0017** before believing a green test run; **0019 + 0021 (with its
  correction)** for how cross-session state works.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — per-milestone design
  and plan documents.
- `.superpowers/sdd/<plan-name>/progress.md` — per-milestone ledgers.
  **Gitignored: open by path, they cannot be found by searching.**
- `semantic-review/` — older whole-branch review write-ups.
- `.kiro/steering/receipt-system.md` — always-on load-bearing rules (untracked).
