# The review outcome takes focus — design (2026-08-12)

**Status:** approved 2026-08-12 by the user. Decision to be recorded in an ADR.

Derived against `main` at `6f29aa5`, working tree clean, five gates PASS
(pytest 1081). **Re-derive rather than quote** (ADR-0028 rule 1). Every number
below states the command or probe that produced it.

Closes browser-pass finding **I5**, re-triaged to Critical by user ruling on
2026-08-06 and never fixed.

## 1. The defect

`ReviewScreen.tsx` renders, in source order: the merchant heading, the image
pane, the findings panel, the confidence rail, the receipt form, the line-items
table, and **then** the failure explanation, the summary alert, and the terminal
card or the Approve button. The outcome of a submit is last in a long document.

The ⌘↵ chord is registered on **`window`**, so it fires while the reviewer is
typing in a field at the top of the form. The sequence that produces the defect:

> type in Total with the page scrolled to the top → ⌘↵ → the PATCH answers 403
> → the outcome renders far below the viewport → **nothing visibly changes.**

A 403 or 404 is the case where *the write landed and the task is gone*. The
reviewer's screen is identical to before they pressed the key.

### 1.1 The measurement, and why the original finding understated it

I5's own evidence was one screenshot, and the browser-pass report says so about
itself: *"The 'fold' claims rest on one capture… `review-real-fold--1440x900-light.png`
is the only capture at a realistic height and is the only evidence behind I5's
above/below-the-fold wording."* That capture predates the styling milestone,
which changed this screen, and it records no numbers.

Measured directly on 2026-08-12 against `main` at `6f29aa5`, by driving the real
seeded app through Playwright and reading `boundingBox()` on the Approve button:

| viewport | Approve's top | below the fold by |
|---|---|---|
| 1440×900 | y=1195 | **295px** |
| 1440×800 | y=1195 | **395px** |
| 1440×1080 | y=1195 | **115px** |

**The finding said 1440×900. It is below the fold at every desktop height
tested, including 1080** — and that is with the seeded receipt's **two** line
items. Measured row pitch is **73px**, so each additional item pushes the
outcome down by that much; the whole document is 1263px tall and Approve sits at
1195, essentially at the bottom.

**So the target is not "make it fit at 1440×900."** The fold position is not a
property of the screen, it is a property of the receipt. Any fix stated in
pixels is wrong on the next receipt.

The measurement was taken with a temporary spec that was deleted afterwards; the
tree is clean. Re-derive by driving the seeded app rather than by trusting this
table.

## 2. The rule

**An outcome element that appears takes focus.**

Not "focus on `failed`, `lost` and `held`". `Submit` has five states today —
`idle`, `busy`, `failed`, `lost`, `held` — and a rule that lists three of them is
an enumerated defence that a sixth state escapes silently (review standard 19).

The bounded, structural form:

- **There is one outcome region**, and everything that tells the reviewer what
  happened lives inside it: the backend-down explanation, the summary alert, and
  the terminal or held card.
- **The region exists exactly when there is an outcome**, and takes focus when
  it appears. Rendering it and focusing it are the same mechanism, so a state
  added later inherits the behaviour by construction rather than by someone
  remembering to add it to a list.
- **The Approve and Close-task buttons stay outside it.** They are the action,
  not the outcome. This also keeps ADR-0024 decision 3 intact: in a terminal
  state Approve does not render at all, and the single exit lives *inside* the
  terminal card.

**Enforced at both ends.** The property is not only "the region takes focus"
but also "an outcome is inside the region" — so a future outcome rendered as a
sibling is a test failure rather than a silently unfocused element.

### 2.1 Two things the rule has to be unambiguous about

**Every appearance moves focus, not only the first.** A reviewer who submits
again from a failed state goes `failed → busy → failed`: the region unmounts and
remounts, and focus moves again. That is intended — the second outcome deserves
attention as much as the first, and a rule that fired only once would leave the
retry silent, which is the defect over again.

**Focus never moves without the reviewer having acted.** The region appears only
as the resolution of a submit, and a submit happens only on ⌘↵ or a click on
Approve. So focus movement is always the answer to something the reviewer just
did, never an interruption of typing. This is the property that makes moving
focus acceptable at all; if a future state could render an outcome without a
reviewer action, it would need to be reconsidered rather than inherited.

## 3. Where focus lands, and where it must not

Focus goes to the **outcome region container**, which is non-interactive and
carries `tabIndex={-1}`.

**It must never go to the exit button.** `ReviewScreen.tsx` already carries the
record of why, and it is not hypothetical:

> `Next receipt` lives **inside** the notice, not in the Approve slot. Two
> buttons alternating in one slot are the same DOM node to React, so the relabel
> used to happen under the reviewer's finger: measured, after clicking Approve,
> `document.activeElement.textContent` was `"Next receipt"`, it was the
> identical node (`focused === approve`), and a bare Enter advanced the queue
> (1 -> 2 calls to /review/next). One keystroke of muscle memory dismissed the
> warning unread, which is the whole thing this state exists to prevent.

*(Quoted verbatim from `ReviewScreen.tsx`'s comment on the `held` branch,
including its ASCII arrow. Re-read it rather than trusting this block.)*

Focusing *Next receipt* would re-create that failure deliberately, having
engineered it away once. The container is focused; the button is not.

## 4. A positional selector this design must route around

`ReviewScreen.module.css` selects the image pane **by element type and
position**:

```css
.screen > div {
  grid-column: 1;
  grid-row: 2 / span 4;
  position: sticky;
  ...
}
```

**Any new top-level `<div>` child of `.screen` silently becomes the sticky image
pane.** The outcome region must therefore be a `<section>`, not a `<div>`.

This is the maintainability hazard recorded as residual 2 in the handoff's §1.3
("`.screen > div` is positional"), and this milestone is the first change to
actually come near it. The design routes around it rather than fixing it;
rewriting that selector is not in scope and would touch the layout the browser
pass validated.

## 5. What must not change

From **ADR-0024**, whose contract this extends rather than reopens:

- **No second live region.** Decision 4 records a *user ruling* that the
  backend-down sentence carries no `role="alert"`, because a second alert in
  that region makes every single-alert query in the suite ambiguous —
  `findByRole('alert')` matches two elements and throws. The outcome container
  gets **no role**: it is a focus target, not an announcement.
- **The summary alert still renders in every failure case** (decision 5).
  Wrapping it must not make it conditional.
- **Terminal states keep exactly one exit and no retry** (decision 3), and the
  ⌘↵ chord stays dead there because the submit guard stays armed.
- **The stash stays in memory** (decision 2) and **the classifier invents no
  copy** (decision 1). Neither is touched.

From **ADR-0027**: no raw hex outside `tokens.css`. If the region needs any
visual treatment at all it uses existing tokens — but the design's position is
that it needs **none**: this is a focus and structure change, not a styling one.

## 6. What the gates will certify, and what they cannot

Stated here rather than discovered at the close (ADR-0029).

**Measured on 2026-08-12 in this repo's Vitest/jsdom environment:**

| observable | jsdom |
|---|---|
| `element.scrollIntoView` | **`undefined`** |
| `element.focus()` / `document.activeElement` | **works; focus genuinely moves** |

**Certified by a green `verify.py`:** that focus moved to the outcome container
when the outcome appeared, and that the outcome elements are inside it.
`document.activeElement` is observable in jsdom and `review-screen.test.tsx`
already asserts it, so this is not a new capability.

**Not certified:** that anything became *visible*. jsdom performs no layout. The
scroll is the browser's own side effect of moving focus, and no gate can see it.
This is review standard 22's shape exactly — the complement of a universal pin
that still does not measure what you care about.

**Not certified at all:** how a screen reader behaves when focus lands on a
container that wraps a `role="alert"`. Some screen readers announce both the
focused container's contents and the live region. **This project has never
tested with a real screen reader** (the browser pass says so: *"No real touch
device and no real screen reader"*), so this claim ships unverified and is
recorded as such rather than asserted.

**Acceptance therefore has two halves**: the gates for the mechanism, and a
browser measurement — the same Playwright shape used to produce §1.1's table —
showing the outcome within the viewport after the chord. A person looking at it
is the only thing that closes I5 as *seen*.

## 7. Scope

**In:** `frontend/src/review/ReviewScreen.tsx` (the outcome region and the focus
move), `frontend/src/review/ReviewScreen.module.css` (a class for the region, if
one is needed at all), the review-screen tests, an ADR, and a dated verdict line
on I5 in the browser-pass report.

**Out, deliberately:**

- **I7** — the 401 that swaps in the login form with no message and repaints
  restored edits identically to stored data. A separate mechanism with no shared
  cause; user-scoped to I5 only.
- **Rewriting `.screen > div`.** §4 routes around it. Fixing the positional
  selector is its own change and would touch validated layout.
- **Any pinning or sticky treatment of the action region.** Considered and not
  taken: it would fix the everyday ergonomics of a 1195px-deep Approve, but it
  is a layout change against a screen the browser pass validated, and it is not
  what I5 describes.
- **Scroll-based fixes.** `scrollIntoView` is `undefined` in jsdom, so it breaks
  every rendering test that reaches the path unless stubbed, and a stubbed
  assertion proves only that a stub was called.

## 8. How it is pinned

The load-bearing test asserts that **after a submit resolves to an outcome,
`document.activeElement` is the outcome container** — and, separately, that the
alert and the terminal card are **inside** that container.

**The RED phase needs care.** A test written against a container that does not
exist yet fails by query-not-found, which is failure for the wrong reason and
proves nothing (review standard 15). The proof that these are pins is a
**mutation after the container exists**: remove the focus call and confirm the
focus assertion fails; move an outcome element outside the container and confirm
the containment assertion fails. Both mutations, their failure text, and their
reverts get recorded.

**A test that only asserts the container exists is not a pin for this defect.**
The defect is that the reviewer's attention never moves; the container's
existence is not the thing that was missing.

## 9. Open, and deliberately not decided here

- **Whether the container should also be the alert.** Focusing the existing
  terminal `<section role="alert">` directly is less DOM churn but more likely
  to double-announce. The design takes the wrapper; if a screen-reader test ever
  happens and contradicts this, the wrapper is the cheaper thing to change.
- **Whether the everyday 1195px-deep Approve is itself a defect.** Measured and
  recorded here; not this milestone's question.
- **`.screen > div`'s positional selector** stays as it is, now with one more
  reason on the record to replace it.
