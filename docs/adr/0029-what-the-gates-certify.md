# ADR 0029 — What the gates certify, and what they cannot

**Status:** Accepted (2026-08-06)
**Extends:** ADR-0017 (two suites and the gate runner — what "passing" means)
**Builds on:** ADR-0027 (the design system, and its ruling that a browser pass is
part of "done"), ADR-0028 (claims about the tree are re-derived)
**Relates to:** review standards 14, 19 and 22

## Context

ADR-0017 defines `python scripts/verify.py` as what "passing" means: five gates —
`pytest`, `ruff`, `typecheck`, `vitest`, `build`. The review-UI-styling
milestone found that definition has a blind spot large enough to lose the
milestone's entire point through.

**Measured at the close, three reverts, each with all five gates green:**

| Revert | Restores the defect |
|---|---|
| `MoneyInput.module.css`'s `.field` → `display: inline-flex` | money controls overflow their table cells; the null `—` is clipped out of sight |
| `tokens.css`'s `--color-null` → `#64748B` in both dark blocks | 3.91:1, below the WCAG AA floor, on the glyph carrying the prime directive |
| `LoginPage.module.css`'s rule bodies emptied to `{}`, class names kept | the login page reverts to browser default |

**Vitest 318/318. `tsc -b` exit 0. `oxlint` exit 0.** Those three reverts undo
*four* findings — three Critical and one WCAG failure — that a browser pass had
found and a fix round had repaired days earlier.

Two structural reasons, both measured:

1. **Vitest sets `css: false`.** A `.module.css` import returns a proxy whose
   keys echo back as strings. A rendering test can therefore assert that a
   component *references* a class, and cannot assert that the class *declares*
   anything. Class-name guards covered eleven files; **emptying every rule body
   in one of them left the suite green.**
2. **`frontend/e2e/visual.spec.ts` is not a gate**, and says so
   (`scripts/verify.py`: *"Not a gate: the Playwright acceptance run… A green run
   of this script says nothing about it"*). It computed `cellOverflow` per
   surface and 488 contrast ratios per run and **asserted neither, by design.**

So the only artefact in the tree that could observe any of the four fixes both
declined to assert them and was not executed by the thing called "passing".

**The bounded property, as measured — not the three instances:** across the
tree's sixteen stylesheets, exactly **three** rules had any declaration asserted
anywhere. Every other declaration was deletable in silence.

## Decision

### 1. A stylesheet declaration census joins the gated suite

`frontend/tests/stylesheets.test.ts` reads every tracked stylesheet as text and
pins, per rule, the declarations it carries. It runs under Vitest, so it is
inside `verify.py`. All three reverts above now turn it red, naming the file,
the selector and the lost declaration.

### 2. The census pins keywords by value and quantities by presence — deliberately

A declaration's value is one of two things. A **keyword** (`flex`, `auto`,
`border-box`) selects a *behaviour*, and a reader can judge a swap from the text
alone. A **quantity** — a length, a colour, a token reference, a shorthand —
selects an *appearance*, and text cannot tell you whether `0.75rem` is right.

Pinning every quantity by value would make the census a second copy of the
stylesheets: every deliberate change would edit two files, and the pin would
assert only that someone typed the same thing twice. **So keywords are pinned by
value; quantities are pinned by presence**, with colours the exception — those
carry a computed contrast assertion, because contrast has a floor that text can
be judged against.

### 3. The Playwright visual run remains NOT a gate

It stays evidence for a human, not an assertion. A first-ever visual pass has
nothing to diff against, and a pixel baseline captured from unreviewed output
pins whatever is broken (ADR-0027's dated note). **`cellOverflow` is therefore
only as good as the discipline that runs `npx playwright test visual`.**

### 4. Therefore, state plainly what a green `verify.py` now certifies

**It certifies:** the Python behaviour, lint, types, the DOM structure and
accessibility wiring of every component, and — new — that each stylesheet rule
still carries the declarations it carried, with colours meeting their contrast
floor on the surfaces they are used on.

**It does not certify:**

* **Layout.** Nothing gated observes overflow, position, or whether an element is
  on screen. `cellOverflow` lives in the ungated Playwright run. The first revert
  above is caught only because `display` happens to be a **keyword** — *a width
  regression expressed as a length would still pass.*
* **Cascade and specificity.** A per-rule census cannot see two rules fighting.
* **Contrast on the three narrower surfaces** (`raised`, `active`, `sunken`).
  The census bounds itself to the surfaces it can attribute with certainty.
* **Anything a person would call "does it look right".** That still needs a
  browser and a human, which is why ADR-0027's ruling stands unchanged.

## Consequences

* Vitest **318 → 346 across 25 files**; the pre-existing 318 all pass unmodified.
* **The census immediately found a defect the browser pass had missed**, because
  no capture put it on screen: `SignOutControl.module.css`'s `.error` renders
  inside `.confirm`, which paints `--color-surface-raised`; in dark that is
  **4.39:1**, below AA. Recorded, not fixed — it needs a source change.
* **A gate that pins text is a gate that can rot.** The census is a second place
  the stylesheets are described, and ADR-0028 applies to it: its own docblock
  states its bound, and the bound is what a reader should re-derive.
* **The honest limit must travel with the pin.** Wherever the census is cited,
  it must be cited with §4's second half. "All five gates PASS" is a stronger
  claim than it was and still not the claim "this screen is correct".

## What this ADR does not decide

Whether the Playwright visual run should become a sixth gate. It would need a
headless-stable configuration, a policy for the 43 recorded-but-unasserted
undersized hit targets, and a decision about how a first-ever baseline is
established without pinning current defects. None of those is settled, and
guessing at them inside a fix wave would have been the implementer's judgement
standing in for the design's.

## References

`frontend/tests/stylesheets.test.ts` (the census, its bound, and the 4.39:1
finding); `frontend/e2e/visual.spec.ts`; `scripts/verify.py` (the gate list and
its "not a gate" note); `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`;
`.superpowers/sdd/2026-08-05-review-ui-styling/progress.md` (the close's C-1 and
its three mutations); ADR-0017, ADR-0027, ADR-0028.
