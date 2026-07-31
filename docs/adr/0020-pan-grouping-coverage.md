# ADR 0020 — PAN detector: which groupings are covered, and why not more

**Status:** Accepted (2026-07-31)
**Supersedes:** ADR-0018 on the shape of `_PAN_RE` only. Everything else in
ADR-0018 — the redaction boundary, the review-reason sink, the accepted false
positives, the accepted leak (b), the load-bearing group-shape requirement —
stands unchanged.

## Context

ADR-0018 closed leak (a): a four-group card with a 5–7 digit tail used to be
stored whole. The whole-branch review that accepted it found a sibling defect it
did not close, and could not have, because no battery in the milestone's history
covered it: **a card grouped outside `4-4-4-N` and `4-6-5` matches neither
separated alternative and is stored entirely in the clear.** Diners Club prints
`4-6-4`. Maestro and legacy Visa print `4-4-5`. A hand-written slip is under no
grouping obligation at all, and this corpus is hand-filled. A second space
between groups defeats every separated alternative on its own, because the
separator class matches one character.

Full measurement, in both directions, is in
`docs/superpowers/specs/2026-07-31-pan-grouping-design.md`. This ADR records the
decision and the two rules that come out of it.

The constraint from ADR-0018 §Context is unchanged and still decides everything:
three of the four real merchant `VAT Reg. TIN` values on this corpus are
**fourteen digits**, inside the 13–19 window a PAN occupies, and they are silent
only because they print `3-3-3-N`. `merchant.tax_id` reaches `redact_pan`
through `save_extraction_run`'s payload pass, so a grouping-agnostic rule would
mask every merchant fingerprint Phase 6 depends on.

## Decision

**Five alternatives are added, each of a fixed shape, and the separator accepts
one or two characters instead of exactly one.** The added shapes are `4-6-4`
(Diners), `4-4-5` (Maestro / legacy Visa), `5-4-4-4`, `6-4-4-4` and `4-5-4-4`.
The pre-existing `4-4-4-N`, `4-6-5` and unseparated alternatives, the
lookbehinds, and the trailing `(?!\d)` are unchanged.

**Every new alternative has a fixed digit total inside 13–19** — 14, 13, 17, 18
and 17 respectively. `_mask_pan`'s length check therefore remains unreachable
from `_PAN_RE` by construction, which is the property ADR-0018 documents; the
enumeration that claim rests on grows from three alternatives to eight, and the
arithmetic still closes.

**The TIN constraint is now enforced structurally, not by sampling.** Every card
grouping begins with a group of at least four digits; every corpus TIN begins
with three. Across every group shape of two to five groups, no shape with a
leading three-digit group matches any alternative. That is a stronger guarantee
than "the four corpus TINs are silent," which would survive a change that
happened to miss those four, and it is pinned by a test over the shape space
rather than over the samples.

**The separator is capped at two characters rather than left open.** `+` covers
the doubled spelling too, but it additionally fires on amount columns aligned
with three or more spaces — measured. Four 4-digit amounts side by side already
mask when single-spaced, so this false-positive class is pre-existing and
accepted; the cap extends it by one spelling instead of by every gutter width a
printed form might use.

**Alternation order is not load-bearing.** Placing `4-6-4` ahead of `4-6-5` does
*not* truncate Amex, because the trailing `(?!\d)` rejects the truncated match
and the engine backtracks into the longer alternative. Three orderings were
measured and produce identical output on every covered shape. The committed
order is for readability, and this paragraph exists so a later reader does not
preserve it out of superstition.

### What was refused, and on what evidence

A generalised separated alternative — a leading group of 4–6 digits, then two or
three more — was built and measured in two forms.

**The first form required every group to be at least four digits.** Replaying the
committed battery in `tests/test_repository.py` **failed thirteen of its tests**:
it silently stopped masking the 13- and 15-digit `4-4-4-N` cards that already
ship masked, whose trailing groups are one and three digits. A pattern that
looked tighter than what it replaced was a leak, and only the *committed*
battery showed it — a battery written alongside the change would have agreed
with the change.

**The second form let only the final group be short.** It passes the committed
battery and covers far more of the plausible shape band. It was refused for two
measured reasons:

1. **It leaks a full second card when two are adjacent.** On two Amex numbers in
   one value it matches across the boundary between them — a `4-6-5-4` span of
   nineteen digits, which is *inside* the accepted range, so `_mask_pan` accepts
   it — and because `re.sub` never rescans inside a match it has already made,
   eleven digits of the second card are left in the clear. The enumerated
   pattern masks both, and only because it has no `4-6-5-4` alternative. Diners
   pairs behave the same way. This is the failure ADR-0018 recorded for the
   greedy trailing group, wearing a different shape.
2. **It makes `_mask_pan`'s length-reject branch reachable**, contradicting the
   property above and reintroducing the no-rescan hazard that branch sits in
   front of.

**The rule this yields, and the reason it is in an ADR rather than a comment:
coverage and cross-boundary risk move together.** A shape added to the detector
can tile across the gap between two adjacent card numbers, and a wider match
span is precisely what let a second PAN through a green suite twice in this
project's history. Adding a shape to `_PAN_RE` is therefore never a local
change: it requires re-running the two-instance check — two instances of what
the guard guards, inside one input — for the new shape against every shape
already covered.

### The residual, accepted

Scored against the plausible band — every group four to seven digits, totalling
13–19, which is how a printed or typed card is actually grouped — this change
takes the detector from seven compliant shapes to fifteen, and from ninety
shapes storing a whole card to seventy-six. **It reduces the gap; it does not
close it.** Groupings including `4-4-6`, `4-5-4`, `5-4-4`, `6-6-4` and `5-5-4-4`
still store a card entirely in the clear. Six further shapes improve to a
partial mask that still leaves five or six digits visible.

This is accepted for now rather than fixed, because both measured routes to
closing the band cost more than they buy: enumerating it needs a shape table
with a two-instance gate per entry, and a candidate-then-validate scan loop that
controls its own resume position was priced in ADR-0018 at O(n²) — about 1715 ms
on a 40 KB adversarial input against about 4 ms. Neither is refused on principle;
both are a separate, scoped decision, and the number above is recorded so that
decision starts from a measurement instead of an impression.

## Consequences

- **`redact_pan` covers more spellings, and the claim about which is now
  enumerable rather than vague.** Every claim of the form "this masks a card
  however it is written" remains false and must stay out of the tree; what is
  true is the alternative list, and it belongs next to the pattern.
- **Two committed prose sites were falsified by this change and rewritten with
  it, not after it.** `repository.py`'s `_PAN_RE` comment showed a worked example
  returning a full 17-digit card in `5-4-4-4` grouping untouched; that example
  now masks. `frontend/src/review/ReceiptForm.tsx` named "the two shapes this
  masks" and carries a table it states was measured through the real `PATCH`
  route — new rows were measured that way, not copied from a probe. This project
  treats a knowingly-false comment as a defect class of its own; both sites are
  part of the change.
- **ADR-0018's pinned leak (b) cases are unchanged.** All four were re-measured
  under the new pattern and return exactly what they returned before, so the
  residual the user ruled on is the same residual.
- **The next person who widens this regex** replays the committed battery in both
  directions, tests two instances of what the guard guards in one input, and
  re-checks that no leading-three-digit shape matches. All three are pinned by
  tests; the third is new here.

## References

SPEC §18; ADR-0018 (superseded on the detector shape only); ADR-0007 (money
integrity and bounded text, unaffected; its Consequences bullet listing "a hash"
unqualified carries a dated correction);
`docs/superpowers/specs/2026-07-31-pan-grouping-design.md` (§2.1 the refused
generalisations, §4 the full measured battery, §5 the residual);
`src/receipts/persist/repository.py` (`_PAN_RE`, `_mask_pan`, `redact_pan`);
`tests/test_repository.py` (the `MUST_MASK`/`MUST_STAY_SILENT` battery and the
structural shape-space tests added here);
`frontend/src/review/ReceiptForm.tsx`; `eval/golden/labels/r001.json`,
`r002.json`, `r003.json` (the corpus TINs).
