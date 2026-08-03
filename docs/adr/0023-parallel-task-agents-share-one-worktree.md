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
