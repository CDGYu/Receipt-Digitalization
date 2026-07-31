# PAN grouping follow-up — cover the non-canonical groupings

**Date:** 2026-07-31
**Branch:** `feat/pan-grouping`
**Baseline:** `main @ 1d9f3e3` (code identical to `7deb3fb`; `1d9f3e3` is docs only)
**Predecessor:** `docs/superpowers/specs/2026-07-31-pan-hardening-design.md`
**Governing ADRs:** 0018 (the masking policy this amends), 0007 (money integrity
and bounded text, unaffected), 0001, 0006, 0017

---

## 1. The defect

`_PAN_RE` recognises a separated card number in exactly two group shapes:
`4-4-4-N` and `4-6-5`. A card printed or written in any other grouping matches
neither alternative, so `_PAN_RE.sub` never fires and `save_extraction` stores
the card number **entirely in the clear** — the same invariant violation as
leak (a), which the previous milestone closed for the four-group case.

The whole-branch review of `feat/pan-hardening` found the class and named five
members plus one separator spelling. All six reproduce at the baseline:

| grouping | example | stored today |
|---|---|---|
| 5-4-4-4 (17) | `41111 1111 1111 2345` | unchanged |
| 6-4-4-4 (18) | `411111 1111 1111 2345` | unchanged |
| 4-5-4-4 (17) | `4111 11111 1111 2345` | unchanged |
| 4-6-4 (14), Diners Club | `3055 930902 5904` | unchanged |
| 4-4-5 (13), Maestro / legacy Visa | `6759 4111 00005` | unchanged |
| doubled separator (16) | `4111  1111  1111  1111` | unchanged |

The doubled separator is a separator defect, not a grouping one: `[ .\-_/,]`
matches one character, so a second space between groups defeats every separated
alternative. It is the likeliest spelling in a handwritten corpus, which this
corpus is.

### 1.1 The class is larger than those six

Two shape populations are measured in this document, and they are not the same
number. Both cover 2–5 groups.

- **The plausible band** — every group 4–7 digits, totalling 13–19: **97
  shapes**. This is how a printed or typed card is actually grouped, and it is
  the band §5 scores against.
- **The permissive population** — leading group ≥4, any later group 1–7,
  totalling 13–19: **3,913 shapes**. It includes spellings nobody writes
  (`4-1-1-1-6`), so it overstates the gap and is used only where noted.

At the baseline, **90 of the 97 plausible shapes store a card entirely in the
clear**; 7 are compliant.

This design brings 8 of those 90 to compliant and improves 6 more without
reaching compliance. It is a reduction of the gap, not a closure of it, and §5
states the residual as a number rather than implying otherwise.

### 1.2 The constraint that shapes every option (unchanged from ADR-0018)

This corpus's merchant BIR `VAT Reg. TIN` values print `3-3-3-N`, and three of
the four are **fourteen digits** — inside the 13–19 window a PAN occupies.
`save_extraction_run` passes the whole extraction payload, `merchant.tax_id`
included, through `redact_pan`. Any rule as simple as "mask every run of 13+
digits" masks every merchant fingerprint Phase 6 depends on.

Every real card grouping begins with a group of **at least four** digits; every
corpus TIN begins with a group of **three**. That asymmetry, not the specific
list of groupings, is what keeps the TINs silent — and it is checkable
structurally rather than by sampling six values. See §4.2.

---

## 2. The decision

Add five alternatives, each of a fixed shape, and widen the separator to accept
one or two characters:

```
SEP = [ .\-_/,]{1,2}

(?<!\d)(?<!\d\.)
(?:
    \d{4}(?:SEP\d{4}){2}SEP\d{1,7}   # 4-4-4-N   13..19   unchanged
  | \d{4}SEP\d{6}SEP\d{5}            # 4-6-5     15       Amex, unchanged
  | \d{4}SEP\d{6}SEP\d{4}            # 4-6-4     14       Diners Club
  | \d{4}SEP\d{4}SEP\d{5}            # 4-4-5     13       Maestro / legacy Visa
  | \d{5}(?:SEP\d{4}){3}             # 5-4-4-4   17
  | \d{6}(?:SEP\d{4}){3}             # 6-4-4-4   18
  | \d{4}SEP\d{5}(?:SEP\d{4}){2}     # 4-5-4-4   17
  | \d{13,19}(?!\.\d)                # unseparated, unchanged
)
(?!\d)
```

`_mask_pan`, `redact_pan`'s container walk, `_last4`, `_coerce_money`,
`_bounded_optional_text`, `_plan_change`, `save_extraction`'s redaction
boundary, `enqueue_review`'s sink and every API route are untouched.

### 2.1 Why enumerate rather than generalise

A generalised separated alternative was built and measured, in two forms. Both
were rejected on evidence:

**Form 1, `\d{4,6}(?:SEP\d{4,7}){2,3}`** — requiring every group to be at least
four digits. Replaying the committed battery (`tests/test_repository.py -k "pan
or redact"`, 110 tests) **failed 13 of them**: it stops masking the 13- and
15-digit `4-4-4-N` cards that ship masked today, because their trailing groups
are 1 and 3 digits. A leak, introduced by a pattern that looked tighter than
what it replaced, and visible only because the battery replayed was the
project's own and not one written alongside the change.

**Form 2, `\d{4,6}(?:SEP\d{4,7}){1,2}SEP\d{1,7}`** — the repair, letting only
the final group be short. It passes the committed battery 110/0 and covers 80 of
the 97 plausible shapes against the enumeration's 15. It was still rejected,
for two measured reasons:

1. **It leaks a full second card when two are adjacent.** Given
   `'3782 822463 10005 3782 822463 10005'` — two Amex cards — it matches the
   span `'3782 822463 10005 3782'`, which is `4-6-5-4` = 19 digits and therefore
   *inside* the accepted range, so `_mask_pan` accepts it. `re.sub` never
   rescans inside a match it has already made, so `'822463 10005'` — eleven
   digits of the second card — is left in the clear. The enumerated pattern
   masks both, and only because it has no `4-6-5-4` alternative. Diners pairs
   behave the same way. This is the failure ADR-0018 recorded for the greedy
   trailing group, in a new disguise.
2. **It makes `_mask_pan`'s length-reject branch reachable**, via 211 of the
   37,440 shapes measured. ADR-0018 documents that branch as unreachable from
   `_PAN_RE` by construction; the enumeration keeps it that way (§4.3).

The generalisation's coverage advantage is real and is recorded here rather than
buried: it closes 65 band shapes the enumeration leaves whole. It was refused
because every option that widened coverage in these measurements also widened
the **match span**, and a wider span is what let a second card through a green
suite twice in this project's history.

**The lesson that goes in the ADR: coverage and cross-boundary risk move
together.** A shape added to the enumeration can tile across the boundary
between two adjacent cards. Adding one is therefore not a local change — it
requires the two-instance check of §4.4, every time.

### 2.2 Why the separator is `{1,2}` and not `+`

Both cover the doubled-separator spelling. `+` additionally fires on
amount columns aligned with three or more spaces — measured,
`'1500   2000   2500   3000'` masks under `+` and stays silent under `{1,2}`.
Four 4-digit amounts side by side already mask when single-spaced
(`'1500 2000 2500 3000'` fires at the baseline), so this false-positive class is
pre-existing and accepted; `{1,2}` extends it to one more spelling, `+` extends
it to every gutter width a printed form might use. `{1,2}` is the spelling the
finding named, and it is where this stops.

### 2.3 Alternation order is immaterial, measured

The expectation going in was that `4-6-4` placed ahead of `4-6-5` would truncate
every Amex to 14 digits. It does not: the trailing `(?!\d)` rejects the
truncated match, so the engine backtracks into the longer alternative. Three
orderings — canonical-first, `4-6-4` before `4-6-5`, and `4-4-5` before
`4-4-4-N` — produce identical output on all six covered card shapes. The order
in §2 is chosen for readability, and the fact that it is not load-bearing is
recorded so a later reader does not preserve it out of superstition.

---

## 3. What must not change

Restated from ADR-0018 because this design touches the one function those
guarantees hang on:

- A full PAN is never persisted.
- `Decimal` on the money path; nothing here touches money.
- `redact_pan` stays pure and recursive, never mutating its input.
- The group-shape requirement stays load-bearing. This design **adds shapes**;
  it must never relax toward "any run of 13+ digits."
- `card_last4` keeps the stronger `_last4` guarantee.
- Leak (b) — a separated run of more than four groups leaving its remainder in
  the clear — remains **accepted by user ruling**, not fixed. All four of its
  pinned cases were re-measured under the new pattern and return exactly what
  they return today.

---

## 4. The measured battery

Every number below comes from executing `redact_pan` with `_PAN_RE` swapped for
the candidate, at baseline `1d9f3e3`.

### 4.1 The committed battery, replayed in both directions

`tests/test_repository.py -k "pan or redact"`, 110 tests, with the pattern
substituted by a pytest plugin:

| pattern | result |
|---|---|
| shipped (control) | 110 passed |
| enumerated + `{1,2}` | 110 passed |
| generalised form 1 | **13 failed** |
| generalised form 2 | 110 passed |

### 4.2 TIN safety, structurally

Over 37,440 group shapes (2–5 groups, widths 1–8, each with six single and two
doubled separators): **zero shapes with a leading 3-digit group match**, for
every candidate. The six corpus TIN spellings are silent, including the doubled
spelling `'TIN  221  193  789  09013'`.

This is the stronger claim. "Six samples are silent" would survive a change that
happens to miss those six; "no leading-3 shape matches at all" is the property
ADR-0018 calls load-bearing.

### 4.3 Match surface and reject-branch reachability

| pattern | shapes matched | added vs shipped | matches outside 13–19 digits |
|---|---|---|---|
| shipped | 8 | — | 0 |
| enumerated + `{1,2}` | 13 | +5 | **0** |
| generalised form 2 | 420 | +412 | 211 |

The five added shapes are exactly `(4,4,5)`, `(4,6,4)`, `(5,4,4,4)`,
`(6,4,4,4)`, `(4,5,4,4)`. Each new alternative has a **fixed** digit total —
14, 13, 17, 18, 17 — so `_mask_pan`'s length check remains unreachable by
construction and not merely by sampling.

### 4.4 Two instances of what the guard guards, in one input

Every pair of the nine covered card shapes across four joiners — 324 inputs.
The enumerated pattern leaves more than four consecutive digits clear in
**zero** of them. The generalised pattern leaks a full second card on the Amex
and Diners pairs (§2.1).

### 4.5 Monotonicity

The change must never leave *more* card digits in the clear than the baseline.
"Clear" here means the longest run of consecutive digits surviving in the output.

- 19,600 shapes (2–5 groups, widths 1–7) × 7 separators = 137,200 inputs:
  **15 regressions**, all of shape `(5,4,4,4,6)`, `(5,4,4,4,7)` or
  `(6,4,4,4,7)` — runs of 23–25 digits, which are not card numbers. In each the
  baseline leaves the 5- or 6-digit leading group clear and the new pattern
  leaves the 6- or 7-digit trailing group clear instead; both are inside the
  already-accepted leak (b).
- Restricted to runs totalling 13–19 digits — every real card length:
  **0 regressions**.
- The plausible band, 97 shapes × 7 separators = 679 inputs: **0 regressions**.
- 200,000 random receipt-shaped strings: **0 regressions**.

### 4.6 False positives

- The three real golden labels, all 56 string values, every candidate:
  **0 fire**.
- 29 hand-built silent controls: 1 fires, `'0000000000000000'` — the all-zero
  dHash, which the baseline also masks and which `save_extraction` excludes
  from redaction structurally. **No new false-positive class.**
- Random 16-character hex: 0.465%, unchanged from the baseline, reproducing
  ADR-0018's own measured ~1-in-200.

### 4.7 Cost

| input | shipped | enumerated + `{1,2}` |
|---|---|---|
| 8000 four-digit groups | 0.6 ms | 0.9 ms |
| 40 KB unbroken digit run | 0.5 ms | 0.6 ms |
| 4000 × `1111` + 20 dots | 6.2 ms | 13.2 ms |

No catastrophic backtracking: every quantifier is bounded, and the separator
repetition is capped at two.

---

## 5. The residual, as a number

On the plausible band of 97 shapes:

| pattern | compliant | >4 digits clear | entirely clear |
|---|---|---|---|
| shipped | 7 | 0 | 90 |
| **this design** | **15** | 6 | **76** |
| generalised form 2 | 80 | 0 | 17 |

Shapes still storing a whole card include `(4,4,6)`, `(4,4,7)`, `(4,5,4)`,
`(4,5,5)`, `(5,4,4)`, `(5,5,4)`, `(6,4,4)`, `(6,6,4)` and `(5,5,4,4)`. Six
shapes move from entirely-clear to partly-masked with 5–6 digits still clear —
better than the baseline on each, but not compliant.

Accepted for this change, for the reason in §2.1. Closing the band properly
needs either a shape table with a two-instance gate per entry, or a
candidate-then-validate scan loop that controls its own resume position —
ADR-0018 priced one such loop at O(n²), ~1715 ms on a 40 KB adversarial input
against ~4 ms. Both are out of scope here and are raised to the user as a
separate decision.

---

## 6. Tests

New, each to be proven failing with the fix reverted:

1. The five groupings masked, parametrised across all six separators.
2. The doubled-separator spelling masked.
3. Two instances of each new shape in one input, masked (review standard #9).
4. A doubled-separator TIN spelling staying silent.
5. **Structural:** no group shape with a leading 3-digit group matches — the
   property §4.2 measures, pinned so a future widening that breaks it fails.
6. **Structural:** no `_PAN_RE` match has a digit total outside 13–19 — pins
   §4.3 and keeps ADR-0018's unreachability claim honest.
7. ADR-0018's worked example `'4111 1111 1111 2345 678'` →
   `'************2345 678'`, pinned. This is ledger follow-up 5: the existing
   leak-(b) cases use uniform digits and cannot distinguish "the matched
   region's last four" from "the card's true last four", so the worked example
   could be falsified without failing a test.
8. The residual pinned: a representative shape from §5 documented as still
   whole, so the gap is a recorded decision rather than an oversight.

Tests 5 and 6 assert the *absence* of breakage, so per review standard 3 they
cannot be proven by a single RED run — each guarantee is reverted separately.

---

## 7. Prose this design falsifies

Three committed sites make measured claims that stop being true. This project
treats a knowingly-false comment as its own defect class, so each is part of the
change, not follow-up:

1. **`repository.py`, the `_PAN_RE` comment.** It shows
   `redact_pan('4111 1111 1111 1111 41111 1111 1111 2345')` returning
   `'************1111 41111 1111 1111 2345'` — "a full 17-digit PAN in 5-4-4-4
   grouping, untouched." Under this design it returns
   `'************1111 *************2345'`. The example must be re-measured; it is
   also the clearest single demonstration of what the change buys.
2. **The same comment's** "outside those two canonical shapes" and its
   enumeration of what `_mask_pan`'s bound rests on — two shapes becomes seven,
   and the arithmetic gains five fixed totals.
3. **`frontend/src/review/ReceiptForm.tsx`.** It names "the two shapes this
   masks (4-4-4-N, 4-6-5)" and carries a table it states was measured through
   the real `PATCH` route. The claim is bounded to that table on purpose,
   because the same claim has been wrong twice before. New rows must be
   **measured through `PATCH`**, not copied from a probe.

## 8. ADRs

- **ADR-0020, new.** ADR-0018 is Accepted and immutable, and this is a new
  decision rather than a correction, so it supersedes 0018 on the detector shape
  only. It records: the five shapes and the separator widening; the two refused
  generalisations with their measurements; the residual of §5 as a number; the
  structural TIN property; and the tiling lesson from §2.1 as a rule for the
  next person.
- **ADR-0007, dated correction.** Its Consequences section still lists "a hash"
  unqualified alongside money and `card_last4` as something `redact_pan` must
  stay silent on. The 2026-07-31 correction above it already says otherwise, but
  a reader jumping to Consequences misses it. Ledger follow-up 6.

## 9. Verification

`python scripts/verify.py` — all five gates. Plus, run independently by the
controller after the implementer reports: the committed-battery replay of §4.1,
the two-instance sweep of §4.4, and the structural checks of §4.2 and §4.3, from
outside the repository. Volatile numbers stay in this document and the handoff
pair, never in code comments (ADR-0019).
