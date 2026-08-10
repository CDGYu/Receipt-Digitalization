# ADR 0033 — The handoff pair goes last and alone, and a correction goes to every copy

**Status:** Accepted (2026-08-10)
**Builds on:** ADR-0019 (session continuity: the handoff pair and its stamp),
ADR-0021 (every session end refreshes it), ADR-0032 (a document cannot certify
itself)
**Relates to:** ADR-0028, ADR-0030, review standards 20, 21, 23 and 24

Derived 2026-08-10 against `main` at the corrections-read-route merge.
**Re-derive rather than quote** (ADR-0028 rule 1).

## Context

ADR-0019 built the handoff pair and its freshness check: a stamp naming a
commit, and a `git log` invocation that must come out empty. ADR-0021 made
refreshing it part of ending any session. Neither said anything about **how the
refresh is committed**, or what happens when the same fact is written down more
than once.

The corrections-read-route session found out. Its close produced three separate
false-claim defects in the continuity documents *after* the branch's own work
was finished and reviewed, and every one of the three came from a mechanism the
existing ADRs do not name.

### 1. The freshness check false-alarmed three times, and each needed a repair commit

The check excludes exactly two paths — `docs/MEMORY.md` and
`docs/NEXT_SESSION_PROMPT.md` — and watches `docs` otherwise. So **any commit
carrying the pair *plus* anything else under `docs/`** lists itself in its own
freshness check. Three times in one session a commit bundled the pair with a new
ADR or an index row, and each time the next reader would have been told the pair
was stale when it had been written in that very commit. Each needed a follow-up
commit touching the pair alone to restore the invariant.

The fourth and last refresh of that session touched the pair and nothing else,
and needed no follow-up. That is the whole finding.

### 2. A correction was applied to one copy of a sentence and not another

`docs/MEMORY.md` carries the current milestone's scope summary **twice**, in the
snapshot near the top and again in the "Decisions the user has made" list — on
that day roughly 700 lines apart. Three separate corrections landed in one copy
and not the other:

* `"exactly one task row"` → `"at most one"` — the second copy read *"so a
  receipt has one task row"*, the same claim in different words, which a
  literal-string grep for the first phrasing cannot find;
* the unqualified `OPEN`-disclosure claim, limited in ADR-0031 and left standing
  in `MEMORY.md` and in `queue.py`'s docstring;
* `"the access is permanent once taken"`, corrected in ADR-0031 and left in the
  handoff.

The same shape appeared in the review standards: standard 24 was the **last
surviving copy** of a conflation that had already been fixed in the milestone
summary and in the handoff — and it is the copy that matters most, because the
reading order sends every session to the standards list.

### 3. A count anchored to a self-recording document invalidates itself

The deferred-minor count was written from the anchor `minor \(deferred\)`, which
misses an entry written `minor (deferred, found by …)`. The fix dropped the
closing `\)` — and that anchor then matched **the ledger's own record of the
finding about the anchor**, which quotes the phrase.

The corrected anchor was wrong **at the moment it was written**: file mtimes
show the ledger entry pre-dated the commit. Recording a finding about a count,
in the document the count is anchored to, is what falsifies the count.

## Decision

### 1. The handoff pair is committed last, and alone

Nothing else in the same commit. Not an ADR, not an index row, not a spec note —
even when they are part of the same piece of work. Write the substantive commits
first, then stamp the pair at the last of them in a commit that touches
`docs/MEMORY.md` and `docs/NEXT_SESSION_PROMPT.md` and nothing else.

This is not a style preference. It is the only commit shape for which ADR-0019's
freshness check is self-consistent, and three repair commits in one session are
the measurement.

### 2. A correction is applied to every copy, and finding the copies is part of the fix

**Before fixing a sentence, find out how many times it is written down.** Search
for the *claim*, not the *phrasing* — the copy that survives is the one worded
differently. Name the copies in the fix, so the re-review can check the list
rather than re-derive it.

`docs/MEMORY.md` in particular states the current milestone twice by design: a
snapshot at the top and a durable entry in the decisions list. A milestone-scoped
correction has at least two homes there, often a third in the handoff and a
fourth in a docstring.

### 3. Prefer no count to a count anchored to the ledger

ADR-0032 §3 already ranks *no number* above *a well-anchored number*. This is the
sharpest case: the ledger records findings **about** the counts it is the source
for, so any count drawn from it is falsified by the next honest entry. Point the
reader at the list; do not count it for them.

### 4. A decision that states a boundary names what enforces it

The whole-branch review found ADR-0031 decision 2 asserting that excluding
`OPEN` from a scope "would disclose every unclaimed receipt's attribution to
every reviewer" — as a reason for the exclusion. Measured, the exclusion raises
the *cost* of reaching that data and does not deny it: one route converts an
unclaimed task into a claimed one on request, and nothing the reviewer controls
gives it back.

The decision still stands on friction and an audit trail. But **a rationale that
sounds like a security boundary must say which code enforces it**, or say
plainly that it is friction. Write the mechanism beside the claim, the way
ADR-0028 rule 2 requires the method beside a number.

## Consequences

- **The refresh gets one more step and loses three.** Stamping last and alone
  costs a moment of sequencing and removes the repair commits entirely.
- **Fixes get slower in the search phase.** Locating every copy of a claim takes
  longer than editing the one you were handed, and it is where the last three
  defects of that session lived.
- **This ADR is subject to ADR-0032.** It states no count it has not run, makes
  no claim about how carefully it was checked, and should not acquire one.

## What this ADR does not decide

Whether `docs/MEMORY.md` should stop stating the current milestone twice. The
duplication is deliberate — a snapshot for the reader who needs state now, a
durable entry for the reader who needs the decision later — and collapsing it
would cost more than the duplication does. The remedy chosen is to know the
duplication exists and fix both copies, not to remove it.

Nor does it propose a check. No gate can read prose for truth, and an
enumeration of known shapes is the enumerated defence again (review standard 19).

## References

`docs/adr/0019-session-continuity-and-handoff.md` (the pair, the stamp, and why
a stamp cannot name the commit that writes it);
`docs/adr/0021-handing-off-mid-milestone.md`;
`docs/adr/0032-a-document-cannot-certify-itself.md`;
`docs/adr/0031-the-corrections-read-route.md` (decision 2's stated limit, the
worked example of §4);
`.superpowers/sdd/2026-08-10-corrections-read-route/progress.md` (the three
repair commits, the surviving copies, and the self-invalidating anchor).
