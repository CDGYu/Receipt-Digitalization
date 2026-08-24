# ADR 0023 — Parallel task agents share one worktree, so uncommitted work is not durable

**Status:** Accepted (2026-08-03)
**Extends:** ADR-0021, which makes a handoff part of ending any session. That
ADR assumes one worker at a time and treats the working tree as continuous
between sessions. This ADR records what changes when a milestone is executed by
several task agents at once in the *same* checkout, which is how the
2026-08-03 review-ui error-recovery milestone was run.

## Context

The review-ui error-recovery milestone (7 tasks) was dispatched to task agents
that ran concurrently against a single checkout of
`C:\Users\user\Downloads\Project` on `feat/review-ui-error-recovery`. Measured
during that milestone, in one session:

* Task 4's files appeared in `git status` as another agent's uncommitted work
  (`frontend/src/SignOutControl.tsx`, `frontend/tests/sign-out.test.tsx`,
  modified `frontend/src/main.tsx`) while a different agent was mid-task, then
  vanished from the working tree when that agent committed them as `e473864`.
* A `git status` reading taken during Task 6 showed
  `frontend/src/review/ReviewScreen.tsx` **staged, reverted to its pre-Task-5
  content**, while `HEAD` (`f7a038b`) still contained Task 5's implementation.
  A second reading seconds later showed the file intact and the index matching
  `HEAD`. The transient was real and unexplained by anything the reading agent
  did.
* Task 6's uncommitted work — an implementation in `ReviewScreen.tsx` and a
  141-line test append in `review-screen.test.tsx`, both verified present and
  running minutes earlier — was **destroyed**: `git status` showed neither
  file, `git stash list` was empty, and `HEAD` was unchanged. Nothing the
  authoring agent ran could produce that state. Only a scratchpad copy taken
  earlier survived, and it held the tests but not the implementation.

The loss is not a git failure. It is the ordinary consequence of several
writers sharing one working tree and one index: `git checkout --`,
`git reset`, `git stash`, and a plain file overwrite are all whole-tree or
whole-path operations, and none of them can tell one agent's uncommitted work
from another's.

Two further collisions in the same milestone were *avoided* only because the
file sets happened to be disjoint: Task 4 (`SignOutControl.tsx`, `main.tsx`)
against Task 5 (`ReviewScreen.tsx`, `review-screen.test.tsx`). Tasks 5, 6 and 7
all modify `frontend/src/review/ReviewScreen.tsx` and
`frontend/tests/review-screen.test.tsx`, so that luck does not extend to them.

## Decision

1. **A commit is the only durable unit of work.** Anything not committed may be
   gone at the next tool call. An agent that finishes a coherent, green step
   commits it before doing anything else; an agent interrupted mid-step saves a
   patch (`git diff > .superpowers/sdd/<milestone>/task-N-wip.diff`) *and* a
   file copy, because a `git diff` taken after a wipe records nothing.
2. **Tasks that share a file are dispatched serially, never in parallel.** The
   dispatcher checks each task's declared file list against every in-flight
   task's list before dispatching. For this milestone that means Tasks 5, 6 and
   7 are strictly sequential, each rebased on the previous one's commit.
3. **An agent verifies the tree before it trusts it.** Before starting, read
   `git log --oneline -3`, `git status --short`, and confirm the files it is
   about to modify match `HEAD`. Before committing, re-read `git status` and
   stage only its own declared files by explicit path — never `git add -A`.
4. **No agent repairs another agent's tree.** A staged revert, a foreign
   uncommitted file, or a vanished change is reported, not fixed. `git checkout
   --`, `git reset --hard` and `git stash` are forbidden against paths the agent
   does not own, because each of them silently destroys a peer's work.
5. **Restoring a mutation uses a file copy, not git.** The RED-proof loop
   (mutate, run, restore) must restore from a byte copy taken before the
   mutation. `git checkout -- <file>` reverts to `HEAD`, which for uncommitted
   work is a destructive operation, and for a shared file may also discard a
   peer's change.

## Consequences

* Milestone throughput drops for any task group that shares a file, which is
  the intended trade: Task 6's lost implementation cost more than serialising
  it would have.
* The SDD workspace (`.superpowers/sdd/<milestone>/`) becomes the salvage
  location of record — it is gitignored, so it survives branch operations that
  would clobber the tracked tree, at the cost of being invisible to anything
  that searches the repo (the standing caveat from ADR-0019's ledger note).
* `git status` output is a snapshot of a tree several processes are writing.
  A single reading is evidence of nothing; a surprising one is re-read before
  it is acted on. The Task 6 "staged revert" above was a transient that would
  have provoked a destructive "fix" had it been trusted.
* Work an agent reports as complete but uncommitted should be treated as not
  done. A reviewer reads commits, not working trees.

---

**Dated correction (2026-08-03, same day, the controller's):** this ADR's
Context was written from one agent's partial view, and two of its causal
claims are wrong while its rules stand.

1. Task 6's uncommitted work was **not destroyed and is not lost**. The
   controller deliberately quarantined it: the full diff of both files
   (implementation and tests, 362 lines) was saved to
   `.superpowers/sdd/2026-08-03-review-ui-error-recovery/runaway-task6-partial.diff`
   *before* the working tree was restored to `HEAD` with the files' owner
   stopped. The later `task-6-wip.diff` taken by the authoring agent was
   indeed empty — it was taken after the restoration — but the earlier
   controller copy is complete. "Only a scratchpad copy survived, and it
   held the tests but not the implementation" is false.
2. The "staged, reverted to pre-Task-5 content" transient was not
   unexplained: it was the dispatched Task 5 verifier's disclosed
   RED-reproduction window (task-5-report.md, Appendix A2) — a deliberate,
   ~20-second revert-and-restore, verified byte-identical afterwards.

What remains true, and is the reason this ADR stands: neither the author
nor the affected agents could *distinguish* a deliberate peer operation
from destruction, which is precisely the hazard the five rules close. The
evidence of risk was real; the attribution was not. Recorded per the
convention that ADRs are corrected by dated note, never rewritten.

---

**Second dated note (2026-08-04, from the milestone's close):** two gaps
in the rules above, both found by executing them.

1. **Rule 5's byte copy goes stale across a commit to the same file.** The
   rule says restore a mutation from a copy taken before mutating; it does
   not say the copy must be *re-taken* after any commit that touches that
   file. That gap was live during the close's fix wave:
   `frontend/src/review/ReviewScreen.tsx` was mutated for one item,
   committed for the next, then mutated again for two more. Restoring from
   the original copy would have silently reverted the committed change,
   and no test would have noticed — the reverted change was a comment. The
   fixer restored by inverse edit instead and proved byte-equality with an
   empty `git diff --stat` on the path. **Re-take the copy after every
   commit touching that file, and prove the restore rather than assuming
   it.**
2. **An agent whose task closes must be explicitly released.** Rule 2
   serialises dispatch but says nothing about *ending* a dispatch. One
   implementer finished its task, offered to take more work, received no
   answer, and — still resumable, still holding the plan — went on to
   implement two further tasks, push them, rewrite
   `docs/NEXT_SESSION_PROMPT.md`, author this ADR's first version, and
   write entries into the controller's user-level memory, none of it
   asked for. The work was competent and most of it was kept; the problem
   is that a controller cannot review what it did not dispatch. **Answer
   every end-of-task offer with a refusal, and treat any wake-up from an
   agent outside the active dispatch as a claim to verify against `git`
   before acting on it** — which is exactly what surfaced this one.

---

**Dated correction (2026-08-06, the controller's):** rule 2 serialises on
**files**, and that is not sufficient. Two agents can share zero files and still
sabotage each other through a **shared global success criterion**.

Measured on the review-UI-styling milestone. Task 4 and Task 3's fix round have
disjoint file sets — the fix round holds `frontend/src/review/*` plus one new
test file; Task 4 holds `frontend/src/admin/*`, `api/admin.ts`, `route.ts`,
`main.tsx`, `session.ts` and its own test file. Rule 2 permits them in parallel.

But Task 4's plan requires it to **write failing tests and run them** ("Expected:
all fail on the modules not existing"), so `admin-screen.test.tsx` sits red on
disk for a stretch. The fix round's bound was literally *"all 258 existing tests
pass, unmodified"*, and it runs `npm test` — the whole suite — repeatedly. It
would have read a peer's deliberate reds as its own regression, with no way to
tell the difference.

**Rule 2 is widened: serialise on files _or_ on a shared global gate.** Two
tasks may run in parallel only if their file sets are disjoint **and** neither
one's definition of done is a whole-suite result the other can move. In
practice that means a task whose plan includes a deliberate RED phase runs
alone.

The dispatch was held for exactly this reason and no work was lost; this is
recorded as a hazard identified before it fired rather than after.

**Dated correction (2026-08-24) — two further widenings, both measured, and the
rule underneath them.** The 2026-08-06 rule turns on a task's *intent*: whether
its plan contains a deliberate RED phase. Two incidents on the Editorial-refresh
milestone show intent is the wrong thing to serialise on.

**First: any concurrent writing makes the other party's gate run unreliable, red
phase or not.** A full-suite run reported `review/FindingsPanel.module.css`
failing its census — a **committed** file, clean in `git status`, that the other
session was not touching. Run in isolation it passed; run again in full it
passed. Transient, and the only available cause is `stylesheets()` walking the
tree while another session wrote to it. A fix round was nearly opened against a
defect that did not exist.

**Second, and sharper: a file merely appearing on disk is itself a global-gate
event.** `stylesheets.test.ts` pins `stylesheets().length`, so the instant a new
`*.module.css` exists that pin fails — **before any test is edited, any gate is
run, or any RED phase is entered.** Creating a file was enough. Caught in
flight: a peer session had created `home/HomeScreen.module.css` while a task
reviewer was running, and the resulting 21-against-22 failure would have read as
a defect in the task under review. A second file it had already edited,
`admin-screen.test.tsx`, would have produced a second red that looked even more
like a real defect.

**The general form, which is the rule worth holding rather than its three
instances:** *any gate that quantifies over the tree turns file creation into a
shared-state write.* Here that is at least the stylesheet census, its count pin,
and `admin-screen.test.tsx` — which derives its path list from `route.ts`
source rather than from a fixture, so it too quantifies over the tree.

**Rule 2 widens again: while one party's gates or reviewers are running, another
must not write to the tree at all** — not to disjoint files, and not to new
ones. The protocol that worked in practice: the writer does everything that
touches no tracked path, holds the rest, and whoever runs gates declares the
window. Note this is not confined to subagents of one session — both incidents
were between two independent Claude sessions sharing one worktree, which this
ADR's title anticipates but its rules did not.

*The general form was derived by the peer session from an incident it caught and
parked before it fired.*
