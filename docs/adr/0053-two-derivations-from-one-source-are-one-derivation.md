# ADR 0053 — Two derivations from one source are one derivation

**Status:** Accepted (2026-08-24)
**Builds on:** ADR-0028 (claims about the tree are re-derived), ADR-0048 (a
rationale is a second claim), ADR-0051 (a guard must not share its derivation
with its subject), ADR-0029 (what the gates certify)
**Implements:** nothing. This is a standard, recorded because it was paid for
four times in one day.

## Context

On 2026-08-24 two independent sessions worked the same branch and checked each
other continuously. Both are careful. Both re-derive claims rather than relaying
them. **Four times, both were still wrong in the same way**, and the shape was
identical each time: *the instrument answered a question adjacent to the one
being asked.*

**1. A contrast figure, verified twice, belonging to nothing.**
`ui/Chip.module.css` recorded `neutral 7.6:1`. It was reported false. One
session computed `#78716C` on `#FFFFFF` = **4.80** and said so; the other
**independently recomputed it**, and also checked the pre-ramp value. Both were
right. Neither checked which token `.neutral` paints — it is
`--color-muted-foreground`, never `--color-null`. The original 7.6 was **true**
(7.58 before the refresh, 7.63 after). A correction of something unbroken went
into the tree, and the second verification is what gave it authority.

**2. A formula, derived twice, over the wrong model.** The eighth column of the
line-items table renders at zero. Both sessions independently derived
`0.15W − 48` from the same CSS and agreed to the digit. **Both were wrong**: the
formula models the *specified* widths, and `th` is `box-sizing: content-box`
with 8px padding each side, so every column renders 16px wider than its rule.
There is no remainder to take. A reproduction built to test the formula
**omitted `th` padding entirely** and so modelled a table this app does not
have — it returned 43px where the real one returns 0.

**3. A grep that could not tell using from mentioning.** `grep -rln "docs/"
tests/*.py` returned three files, and was one sentence from becoming "pytest
reads five docs". Two of the three only *cite* a document in a docstring or a
comment. Only checking for `read_text`/`open` separated them.

**4. A null result from a query that could not have matched.** Verifying (3),
`grep -rnE "read_text|open\(" tests/*.py | grep -iE "docs|MEMORY|..."` returned
**nothing** — and that null was one sentence from becoming "no gate reads
docs". The real code splits the two facts:
`PAIR = (...)` at `tests/test_freshness_check.py:84`, and
`for rel in PAIR: (REPO_ROOT / rel).read_text(...)` at `:137-138`. A query
requiring two facts on one line cannot see code that names them apart.

## Decision

**1. Independent derivation from the same source is not corroboration.** Two
people reading one file the same way produce one derivation with two names on
it. Agreement raises confidence in the *arithmetic* and says nothing about the
*subject*. When a second party confirms a claim, record **what they did
differently** — and if the answer is "nothing", the claim has been checked once.

**2. Only execution decides between candidates a query produced.** A stated
query — the discipline ADR-0028 already requires — finds things that *resemble*
the claim. It cannot distinguish a read from a mention, a specified width from a
rendered one, or a token a rule names from the token it paints. **Run the
mutation, load the page, print the computed value.**

**3. A null result is evidence only if the query could have matched.** Before
reporting an absence, construct the positive case and confirm the query finds
it. A query that cannot express the thing it is looking for returns silence
indistinguishable from success.

**4. A reproduction is a claim about fidelity.** Building a minimal repro to
test a hypothesis tests the repro as much as the hypothesis. State what was
copied and what was left out; the omission is where the defect hides.

## Consequences

- Confirmations get a method, not just an answer. "I get 4.80 too" is not a
  second check; "I grepped which token the rule paints" is.
- Absence claims cost more: one extra step to prove the query has teeth.
- This does not replace [[state-the-instrument-beside-the-observation]] — naming
  the instrument is still what catches wrong-cause claims *before* they are
  reported. This ADR is the next question after it: **not only what did you use,
  but what would it have missed.**
- ADR-0051 said a guard must not share its derivation with its subject. This is
  the same principle applied to people: **two checkers who share a derivation
  are one checker.**

## What this cost, so the next reader can price it

One false correction committed and re-corrected; one issue filed with a
prediction that was dead on measurement; one fix proposal drafted that would
have changed nothing; and roughly an hour across two sessions. Every one was
caught — by a reviewer, by a measurement, or by a peer — and **none was caught
by the second derivation that was supposed to be the check.**
