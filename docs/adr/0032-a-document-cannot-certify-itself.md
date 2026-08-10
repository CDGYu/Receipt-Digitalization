# ADR 0032 — A document cannot certify itself, and a derived claim can rot inside its own commit

**Status:** Accepted (2026-08-10)
**Builds on:** ADR-0028 (claims about the tree are re-derived, not restated),
ADR-0030 (a finding is a claim, and a fix wave verifies before it fixes)
**Relates to:** ADR-0019 (the handoff stamp, and why it hands over a *command*),
ADR-0017, ADR-0023, review standards 5, 19, 20, 21 and 23

Derived 2026-08-10 against `feat/corrections-read-route`. Every count below
names the query that produced it. **Re-derive rather than quote** (ADR-0028
rule 1).

## Context

The corrections-read-route milestone shipped one route, four tasks, and
**nine fix rounds** — one on Task 1, one on Task 2, two on Task 3, five on
Task 4 (`grep -cE "^Task [0-9]: fix round [0-9]/5 \(" progress.md` → 9).

Those rounds fixed real work as well as prose: Task 1's changed the route's
`ORDER BY` on a user ruling and added 80 lines of tests; Task 2's replaced a
fixture that could not discriminate what it claimed to pin. **Rounds are not the
unit this ADR is about.**

The unit is the **false-claim instance**. **Nine were found during execution**,
and more afterwards — count them rather than reading a number here, and mind the
anchor:

```
grep -oE "INSTANCES? [A-Z]+" progress.md      # the plural marker is load-bearing
```

Every instance was a sentence — a number, or a universal, that nobody had run a
command to check — and **not one was a defect in behaviour**: every gate passed
throughout. The ledger numbers them from SIX onward; the first five were counted
as they were found during Task 3.

> **The singular anchor `INSTANCE [A-Z]+` is wrong** and this ADR carried it.
> The ledger's post-close entry reads `INSTANCES TEN THROUGH THIRTEEN`, which
> the singular form silently drops — so the stated method returned the number
> the author expected. Corrected 2026-08-10 by the whole-branch review. Rule 3
> below, and ADR-0030 §6, in one line.

**Five of the nine instances were written *while fixing* one of the other
four**, in four consecutive rounds of one task. The process built to catch false
claims became the place they were produced.

> **Corrected 2026-08-10, before this ADR was a day old.** This section first
> read *"nine fix rounds fixed nine defects and not one was behaviour"* — which
> conflates two different nines (rounds and instances) and is false of the
> first. An audit ran `git show 9f44864 -- src/receipts/review/queue.py` and
> found the `ORDER BY` change. **That is rule 5 below, committed by the document
> that states it:** two counts matched, and a causal story got built on the
> coincidence.

ADR-0030 already says a finding is a claim. This ADR is about the *next* layer:
the prose a fix wave writes about the fix, and the prose a document writes
about itself.

### The four that mattered

**Instance seven** — a round fixed a false claim about a mutation's
consequence, and its replacement sentence asserted the resulting 500 was
"reachable by any signed-in caller". Measured afterwards: on *this* route a
reviewer holding nothing is refused at 403 before the offending value reaches
the database. True of the two sibling routes, false of the one the sentence
documented.

**Instance eight** — a round deleted a self-describing header and, in the same
commit, wrote *"The route's docstring says which callers reach it."* Nothing in
`src/` mentions that failure mode at all.

**Instance nine is the one that changed the rule.** A header read *"`src/` has
not moved since `bc67c31`."* It was **true when written** — `git log --oneline
bc67c31..ca22e6e -- src` is empty — and the commit that carried it forward
falsified it by editing `api.py`, in the same commit, without re-running the
check. The round before it had gated on exactly that derivation; the round that
needed it most had dropped the gate.

That is not a claim written carelessly. It is a claim **derived correctly and
then rotted by its own commit** — the shape ADR-0028's own Correction
identified, at the shortest possible timescale.

## Decision

### 1. A sentence whose subject is the document's own trustworthiness gets deleted, not corrected

Four consecutive rounds each fixed the finding in one such sentence and
produced a new false claim in the same place. That is review standard 19's
signature: the enumerated defence was *"describe the verification history
accurately"*, and every description is itself a fresh claim that can be wrong,
so the surface never closes.

**The bounded property: a sentence may stay only if its subject is the system —
the route, the tree, a decision — and a reader can check it without trusting
the author.** Anything whose subject is this document, its review, its
authorship, who found what, or how thoroughly it was checked comes out. Do not
replace it with a more careful version.

The history is not lost by deleting it. It is in the ledger and in `git log`,
which cannot rot because nobody has to maintain them.

**Headings are sentences.** The round that applied this to body prose left two
headings carrying the same claim, one of them two lines above the body sentence
it had just deleted.

### 2. A derived claim can rot inside the commit that carries it

Re-deriving a fact and then editing the tree in the same commit is enough to
falsify it. So a derivation is not a property of a sentence; it is a property
of a sentence *at a commit*, and the commit boundary is not a safe unit.

The practical rule: **a claim about what the tree currently contains does not
belong in a document that is edited alongside the tree**, unless the claim is
re-derived in the same act as the edit — and nothing enforces that.

### 3. Anchors are where rot lives — prefer no number to a well-anchored one

Every measurement needs an anchor, and the anchor is the part that ages. Two
kinds, and only one is safe:

* **Closed** — evaluated at a fixed commit (`at e2ec316, zero hits`). True
  forever. Safe.
* **Open** — anchored to a moving ref (`HEAD`), a growing range, or a milestone
  *name* rather than a SHA. Rots silently, and nothing goes red.

A sweep on this branch found a closing-time claim anchored at `HEAD` whose own
recorded follow-up would have falsified it: the document predicted its own
rotting.

**So the ordering is: no number > a number closed to a SHA > a number anchored
to a moving ref.** A count is worth its anchor's maintenance cost only where
the count is the point. A freshness stamp earns it. An ADR does not.

### 4. Where a stamp is genuinely needed, hand over the command, not the answer

ADR-0019 solved this and the solution was not reused. `docs/MEMORY.md`'s stamp
states plainly that *a stamp cannot name the commit that writes it*, and then
gives the reader **a command to run**. A command has no truth value to rot; it
has an anchor, and the anchor is stated.

### 5. Check membership, not cardinality — a second instance, and it was inherited

ADR-0030 rule 4 got a fresh instance, and this one travelled. A design document
enumerated the three `Correction` mentions in `repository.py` as *"the import,
the construction, and its `__all__` entry"*. The **count was right and the
third member was wrong**: `repository.py`'s `__all__` contains no `Correction`
at all, and the third hit is a comment referencing ADR-0020's dated
*Correction* about the PAN cap — a grep false positive on an English word.

ADR-0031 inherited the breakdown verbatim from the design. **A right count
launders a wrong membership**, and the error was found only when someone read
the lines the grep had printed instead of the symbol names they expected.

### 6. The fix wave's own prose needs the same review as its code

ADR-0030 §5 said this. This milestone measured how much: **five of nine
false-claim defects were introduced by fix rounds**, and each was caught only
because every round ended in a scoped re-review. A fix round that ends without
one ships its own prose unreviewed, and the prose is where the defects are.

## Consequences

- **Fix loops get longer, and that is the cost of catching this at all.** Task 4
  ran the full five rounds. Rounds 1–3 resumed the same implementer; rounds 4–5
  escalated to a fresh one on a stronger model, which is what produced the
  exhaustive heading sweep and the self-found `HEAD`-anchor.
- **The escalation worked, and the deletion is what converged it.** Round 5
  introduced no new claim — the first round of five that did not.
- **Documentation-only is not low-risk on a branch whose deliverable is
  documentation.** Most of this branch's commits are `docs:` — count them with
  `git log --oneline e2ec316..feat/corrections-read-route | grep -cE "docs:"`
  rather than reading a number here.

  > **Corrected 2026-08-10.** This bullet first read *"Nine of this branch's 18
  > commits are `docs:`"* with `e2ec316..HEAD` as its stated method. Both
  > numbers were right when derived and **were falsified by the commit that
  > carried them**, because `HEAD` is a moving ref — the exact defect §3 below
  > forbids, committed in the ADR that forbids it. The count is now a command,
  > and the command is anchored to the branch rather than to `HEAD`.
- **Minor findings were deferred rather than fixed**, under review standard 19's
  report-don't-fix. They are in the ledger with rulings, and the whole-branch
  review is where they get triaged, and it triaged every one as *ships*.

  **No count is given, after two anchors were tried and both were wrong.**
  `minor \(deferred\)` drops the entry written `minor (deferred, found by …)`;
  dropping the `\)` to fix that then matches the ledger's *own record of that
  finding*, which quotes the phrase. **A count anchored to a document that
  records findings about the count is falsified by the act of recording one** —
  measured here, where the second anchor was already wrong at the moment it was
  written. Read the ledger's list rather than counting it.
- **This ADR is subject to its own rules.** Its counts are closed to
  `feat/corrections-read-route` at 2026-08-10 with their queries named. It makes
  no claim about how carefully it was checked, and it should not acquire one.

## What this ADR does not decide

Whether any of this can be gated. It cannot, by the same argument ADR-0028 and
ADR-0030 both reached: no test can read prose for truth, and a check that
enumerates known shapes is the enumerated defence again. The obligation stays
with the reader of the sentence — which is where it can actually be discharged.

It also does not decide whether the nine defects say something about how plans
are written here. Every one of the nine plan-level defects on this milestone was
the controller's, which matches all nine previous milestones; whether that is a
fact about controllers or about the role is not settled by one branch.

## References

`.superpowers/sdd/2026-08-10-corrections-read-route/progress.md` (the ledger:
every instance, every fix round, every ruling, and the twelve deferred minors);
`docs/adr/0031-the-corrections-read-route.md`;
`docs/adr/0030-a-finding-is-a-claim.md`;
`docs/adr/0028-claims-about-the-tree-are-re-derived.md` and its
`## Correction (2026-08-07)`; `docs/adr/0019-session-continuity-and-handoff.md`
(the stamp that hands over a command); `docs/MEMORY.md` § "Review standards".
