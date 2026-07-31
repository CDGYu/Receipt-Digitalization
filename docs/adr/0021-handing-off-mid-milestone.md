# ADR 0021 — Handing off mid-milestone: the unfinished branch is a state that needs a record

**Status:** Accepted (2026-07-31)
**Extends:** ADR-0019, which governs the handoff pair at a *milestone close*.
This ADR covers the case 0019 does not: a session that ends with a feature branch
part-built.

## Context

ADR-0019 made the tracked pair `docs/MEMORY.md` + `docs/NEXT_SESSION_PROMPT.md`
the authoritative handoff and made refreshing it part of closing a milestone. It
records that commits `10166ec` and `395151b` "exist solely to mark it stale
mid-milestone" — so the mid-milestone case was already known to be a problem, and
0019 addressed only the clean case: merge, then refresh.

The situation 0019 leaves undefined then occurred immediately. A session ran the
PAN grouping milestone through design, ADR, plan and two of four implementation
tasks, and ended — by the user's call, on a context budget — with a branch
holding real, verified work and two tasks unstarted. Nothing in the protocol said
what that state should look like from the outside.

That matters more than an unfinished milestone normally would, because of what
was on the branch:

- **Two tasks were complete, gated and independently re-verified.** Losing or
  redoing them would be pure waste.
- **The remaining two tasks were fully specified** in a committed plan whose
  every expected value had been verified by execution.
- **Three defects in that plan's claims about existing code had already been
  found** by the implementers, each because the brief told them to read the code
  first. A fresh session that trusted the plan would hit the fourth.
- **The branch was unpushed**, so the work existed on one machine only.

A second, sharper problem: the handoff pair describes "where we are." Mid-branch,
there are two answers — where `main` is, and where the branch is — and a reader
who conflates them will either re-do finished work or merge an unfinished
detector change.

## Decision

1. **A session that ends mid-milestone refreshes the handoff pair, exactly as a
   close does.** The trigger for a refresh is the *session ending*, not the
   milestone ending. ADR-0019's decision 2 is widened accordingly.

2. **The stamp names both positions.** `main @ <sha>` and, when a feature branch
   is in flight, `<branch> @ <sha>, N commits ahead, pushed | UNPUSHED`. A single
   "where we are" line is ambiguous the moment a branch exists, and this project
   has already lost a whole milestone to an ambiguous stamp.

3. **Per-task state is recorded as done/verified, not as done.** For each
   completed task: its commit, that the controller re-ran the gates
   independently, and the measured result. "Task 2 complete" invites a fresh
   session to trust it; "Task 2 complete, `a883df6`, controller re-ran both
   mutations and reproduced 63 and 36,521" invites it to build on it.

4. **An in-flight branch is pushed before the session ends,** under the standing
   `feat/*` authorisation. Unpushed work on one machine is the one failure mode
   no document can repair.

5. **Plan defects found during execution are promoted into the tracked tree
   before the session ends,** not left in the gitignored ledger. A plan is a
   tracked artefact that a later session will follow literally; a correction that
   lives only in `.superpowers/` will not be seen, per ADR-0019's promotion rule.
   Either fix the plan or record the correction in the handoff prompt against the
   task it affects.

6. **Verification claims carry their method.** "Gates pass" is not a handoff
   fact; "`scripts/verify.py` all five PASS, pytest 914/0/0/0 read from
   junitxml at `<sha>`" is. The count and the sha travel together or neither
   travels, because a count without a position cannot be compared to anything.

## Consequences

- Ending a session costs a docs commit whenever a branch is open, not only at a
  merge. Accepted for the same reason 0019 accepted it: the alternative was
  measured.
- The handoff pair grows a branch-state section that is empty on a clean `main`
  and populated mid-flight. Empty is the signal that nothing is in flight.
- The pair can still be wrong if a session ends without running this protocol,
  which is why ADR-0019's decision 3 — the kickoff verifies rather than trusts —
  remains the load-bearing half. This ADR reduces how often verification finds a
  surprise; it does not remove the need for it.
- A reader now has to distinguish "verified by the implementer" from "re-verified
  by the controller." That distinction is the point: this project's review
  standard is that reviewers reproduce rather than reason, and a handoff that
  flattens the two loses the only signal that says which claims were checked
  twice.

## References

ADR-0019 (the handoff pair, the promotion rule, and the kickoff verification
this extends); ADR-0017 (what "passing" means, and why a count needs its
method); `docs/MEMORY.md`; `docs/NEXT_SESSION_PROMPT.md`;
`.superpowers/sdd/2026-07-31-pan-grouping/progress.md` (the ledger whose
mid-flight state prompted this); commits `10166ec` / `395151b` (the earlier
mid-milestone staleness markers ADR-0019 recorded but did not resolve).
