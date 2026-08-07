# ADR 0030 — A finding is a claim, and a fix wave verifies before it fixes

**Status:** Accepted (2026-08-07)
**Builds on:** ADR-0028 (claims about the tree are re-derived, not restated)
**Relates to:** ADR-0017 (what "passing" means), ADR-0029 (what the gates
certify), review standards 1, 17, 19, 20 and 21

## Context

ADR-0028 legislated one direction: a sentence *in this codebase* that quantifies
over the codebase must be derived at the moment of writing. It did not consider
the sentences written *about* those sentences.

At the close of `feat/review-ui-styling`, a whole-branch review produced six
documentation findings. A fix wave was briefed to fix all six. **Two of the six
were false**, and both failed by the mechanism the review existed to find.

| Finding | Verdict | How it failed |
|---|---|---|
| "ADR-0027 says **35 custom properties**; measured **54 declarations / 24 unique**" | **The ADR was right.** 65 declarations, 35 unique names. | `grep -c "^\s*--[a-z]"` answers *"how many custom properties begin a line"*. Eleven share a line with a neighbour: 54 + 11 = 65, 24 + 11 = 35. The unique count also deduplicated names together with their leading whitespace. |
| "**35 is the `@font-face` count**, cited twelve lines below — borrowed from the wrong measurement" | **Two unrelated numbers.** `tokens.css` has **zero** `@font-face` rules; the other 35 counts the *built* CSS. | A causal story built on two counts matching. |

The second is the same shape as the finding the same review got **right** two
bullets earlier — that ADR-0028's motivating story read "the old route list
listed 13, and a flat walk returns 13" as cause and effect when the two 13s
share no members. **The reviewer committed the defect it was hunting, in the
same report, having just described it.**

The near-miss matters more than the errors. The wave was briefed to *fix* six
items. Fixing the first would have edited a correct sentence in an Accepted ADR
to match a wrong measurement — shipping the ADR-0028 defect into ADR-0027 on the
authority of a document written to prevent it. It was caught only because the
implementer re-ran the measurement before editing, and noticed that the method
it wrote into the correction did not reproduce the number the correction
claimed.

**Why a finding is the most trusted sentence in the process.** It arrives
looking like the output of a check; it carries a number; and its reader is
already braced to have been wrong. That is precisely the profile ADR-0028
identifies as never re-checked — *"an enumeration in prose inherits the
authority of the thing it enumerates"* — with the authority of a review added
on top.

## Decision

### 1. A finding is a claim about the tree, so ADR-0028 rule 1 binds it

A reviewer asserting "measured N" is making the same kind of sentence as the
code comment it attacks, and owes the same derivation. **Record the method
beside the finding**, not only the number. A finding that arrives without its
method is incomplete, and saying so is the first response to it.

### 2. A fix wave verifies each item before fixing it, and may return "this finding is wrong"

Fix waves are briefed with a bound, not a list of edits (ADR-0023's dispatch
rule and review standard 19). That bound is now explicit: **the deliverable is
"each item is resolved", and *falsified* is a resolution.** An implementer who
edits a correct document to match an incorrect finding has failed the task, not
completed it.

Re-derive by a method you chose rather than the one the finding came with, and
compare the two answers. Where they disagree, that disagreement is the finding.

### 3. Falsified findings are recorded in the tracked tree, with the measurement

Not dropped. A finding that quietly disappears is re-raised by the next reader
of the same document, and the second reviewer has no way to know the first was
answered. Record what was claimed, what was measured, how, and why the original
text stands. ADR-0027's `## Correction (2026-08-07)` is the worked example: it
corrects two real defects and, in the same section, records the third as
falsified.

### 4. Check membership, not cardinality

When two counts match and you are about to say one explains the other, **list
both sets and diff them**. Both instances in this codebase died in one line the
moment anyone asked *which* 13, or *which* 35. Cardinality is the weakest
possible evidence of a shared cause and it reads as the strongest.

### 5. The rule binds the fix wave's own prose, immediately

The scoped re-review of wave B found that **the wave's own commit message made
two false claims about the tree**, written in the act of closing four:

* *"comment-stripped HEAD and worktree are byte-identical for all **16** source
  and test files"* — there are **18**. The work was sound and the reviewer
  proved all 18 identical; only the count was invented. 16 is the number of
  stylesheets under `src/`, asserted twice elsewhere in the tree — **a true
  number borrowed for a different quantity, which is rule 4's failure, committed
  a third time in the commit adjudicating the first two.**
* *"~70 accurate-but-numbered citations remain in files this milestone never
  opened"* — **39 of the 71 are in files it did open**, and they are not all
  accurate: the re-review resolved fifteen and six were stale. One sat in
  `tokens.css`, which the wave had edited, and asserted in the present tense
  that a swap Task 3 had already made was still outstanding.

**Neither was measured. Both were plausible.** A bound stated rather than
derived is the same defect as a count stated rather than derived, and a
*residual* is exactly where it hides, because a residual is what nobody checks.

### 6. State a query's anchor beside its number

`^\s*--[a-z]` and `--[A-Za-z0-9-]+\s*:` are different questions and neither
announces what it excluded. A count produced by a grep carries the grep's
blind spots, so **write the anchor down with the count**, or produce the number
with a script whose exclusions are visible in its source. This is ADR-0028 rule
2 — record the method — sharpened: the method is not the tool, it is the tool
*plus its anchor*.

## Consequences

- **Fix waves get slower and shorter.** Every item is measured before it is
  edited. Wave B spent more time on the two findings it rejected than on the
  four it applied.
- **A fix wave needs a reviewer even when it changes no code.** Wave B touched
  24 files and not one line of behaviour, and the re-review still found six
  stale citations, two false claims in its commit message, and two test-docblock
  claims falsifiable by mutation. **"Documentation only" is not "low risk" on a
  branch whose deliverable is documentation.**
- **Reviews are not weakened by this.** The same review found a Critical
  (`8ede47e`'s subject) that no gate could see, and four documentation defects
  that were entirely real. The rule is not "distrust reviews"; it is "a review's
  numbers are numbers, and numbers are derived."
- **Two documents now carry a falsified finding on purpose.** ADR-0027's
  correction records the 35 as measured-and-correct; this ADR records both. A
  reader who re-derives them will get the same answer, which is the point.
- **This ADR is subject to its own rule 1.** Its two counts (65/35
  declarations/names, zero `@font-face` in `tokens.css`) were derived on
  2026-08-07 by the script quoted in ADR-0027's correction. Re-run it rather
  than quoting this table.

## What this ADR does not decide

Whether reviewers should be *required* to attach a runnable command to every
numeric finding. That would be enforceable only by the person reading the
report, no gate can check it, and a review that reports a real defect without a
tidy repro is still worth having. The obligation is placed on the reader of the
finding, where it can actually be discharged.

It also does not decide whether the citation sweep that produced wave B's
de-numbering becomes a script in the repository. ADR-0028 deliberately declined
to propose a CI check for prose, and that stands; ~70 accurate-but-numbered
citations remain in the tree as a recorded residual.

## References

`docs/adr/0028-claims-about-the-tree-are-re-derived.md` (its
`## Correction (2026-08-07)`, which withdraws the motivating story);
`docs/adr/0027-review-ui-design-system.md` (its `## Correction (2026-08-07)`,
which records the falsified finding beside the two real ones);
`docs/adr/0029-what-the-gates-certify.md`;
`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`;
`.superpowers/sdd/2026-08-05-review-ui-styling/progress.md` ("THE CLOSE");
`docs/MEMORY.md` (review standards).
