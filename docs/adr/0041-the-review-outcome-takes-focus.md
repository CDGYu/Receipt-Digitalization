# ADR 0041 — The review outcome takes focus, so a 403 is not invisible

**Status:** Accepted (2026-08-12)
**Relates to:** browser-pass finding **I5**
(`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` §3), ADR-0024
(the review UI's error-recovery contract — decisions 3, 4 and 5, which this
**extends rather than reopens**), ADR-0027 (the design system, and `.screen >
div`'s own record), ADR-0028 (claims about the tree are re-derived), ADR-0029
(what the gates certify and what they cannot), ADR-0033 (a correction goes to
every copy)

Derived 2026-08-12 on `feat/review-outcome-focus` at `5a7fc58`. **Re-derive
rather than quote** (ADR-0028 rule 1): the design this implements was written
before the code, and the finding it closes understated itself. Every number
below came out of one of the three probes described here on the day this was
written, or is a subtraction of two of their outputs. The third was run last,
at the close of the fix wave, and is the only one whose result contradicts
something the design assumed.

**The layout and the scroll.** A temporary spec under `frontend/e2e/`, run and
then deleted. `playwright.config.ts` chains build → seed → serve in one
`webServer.command`, so `npx playwright test` from `frontend/` drives that whole
chain; two of the three links shell `${PYTHON} scripts/seed_review_e2e.py` and
`${PYTHON} scripts/serve_review_e2e.py`, so a Python interpreter and those two
scripts are part of what a run needs. The spec reads
the seed manifest for credentials, signs in, waits for the line-items table,
and then, at each viewport height with `window.scrollTo(0, 0)`: `boundingBox()`
on the button named `/^Approve/`, `document.documentElement.scrollHeight`, and
`window.innerHeight`. Then it fills `Total` with `abc`, which
`apply_corrections` refuses with a 400, presses `ControlOrMeta+Enter`, and
reads the region's box,
`getBoundingClientRect().top` as a second opinion, `window.scrollY`,
`document.activeElement`, and `getAttribute('role')` on the region.

**The focus indicator.** A second temporary spec under `frontend/e2e/`, run and
then deleted. It signs in to the seeded app at 1440×900, routes
`**/review/*/complete` to a 403 so the real `lost` outcome renders, fills
`Total` with a valid amount, presses `ControlOrMeta+Enter`, waits for the
terminal heading, and then reads, off `document.activeElement`:
`getComputedStyle` for `outline`, `outline-style`, `outline-width`,
`outline-color`, `outline-offset`, `box-shadow`, `background-color` and
`border`; `matches(':focus')` and `matches(':focus-visible')`;
`getAttribute('role')`; and `--color-ring` off `documentElement`. Run once per
`colorScheme`, light and dark. Playwright's `getByRole('region')` count and
`locator.ariaSnapshot()` on the container come from the same run.

**The two jsdom facts**, against the `jsdom` that Vitest's
`environment: 'jsdom'` loads, from the repo root:

```bash
node -e "const {JSDOM}=require('./frontend/node_modules/jsdom');const w=new JSDOM('<section tabindex=\"-1\" id=r></section>').window;const el=w.document.getElementById('r');console.log('scrollIntoView:',typeof w.HTMLElement.prototype.scrollIntoView);el.focus();console.log('focus moved:',w.document.activeElement===el)"
```

## Context

`ReviewScreen` renders, in source order: the merchant heading, the image pane,
the findings panel, the confidence rail, the receipt form, the line-items
table, and **then** whatever the submit resolved to. The outcome of a submit is
last in a long document.

Measured in Chromium against the seeded fixture, with the reviewer at the top
of the page (`scrollY=0`) and before any submit:

| viewport | `Approve (⌘↵)` top | document height | in view |
|---|---|---|---|
| 1440×900 | y=1195 | 1263 | no |
| 1440×800 | y=1195 | 1263 | no |
| 1440×1080 | y=1195 | 1263 | no |

**y=1195 is measured at each height, not extrapolated from one.** At the three
heights measured the fold moved and the button did not, so the shortfall is a
subtraction: 295px at 900, 395px at 800, 115px at 1080. The
button's own 44px box puts its *bottom* edge 339 / 439 / 159px past the fold.

**It degrades with the receipt.** The fixture carries two line items and the
measured row pitch is **73px** (row tops at 1024 and 1097), so each additional
item pushes the outcome down by that much. The fold position is a property of
the receipt, not of the screen, and any fix stated in pixels is wrong on the
next receipt.

**The chord fires from the top of the form.** ⌘↵ is registered on `window` —
`window.addEventListener('keydown', onKeyDown)` — so it reaches a reviewer who
is typing, and measured, filling `Total` at 1440×900 leaves `scrollY` at 0. The
sequence:

> type in `Total` with the page at the top → ⌘↵ → the PATCH answers 403 → the
> outcome renders far below the viewport → **nothing visibly changes.**

A 403 or 404 is the case where *the write landed and the task is gone*. The
reviewer's screen is identical to before they pressed the key. The states carry
`role="alert"`, so a screen-reader user is told and a sighted one is not.

**I5 understated its own defect, and that is recorded rather than corrected in
place.** Its evidence was a single screenshot, and the browser-pass report says
so about itself: *"`review-real-fold--1440x900-light.png` is the only capture
at a realistic height and is the only evidence behind I5's above/below-the-fold
wording."* It records no numbers, and **it predates `205d77a` — not the styling
milestone**, which is a distinction worth getting right because it is what
licenses re-measuring. The pass ran on `feat/review-ui-styling` at tip
`c781f40`, and `bdbfd03` (*"feat(ui): style the review screen without touching
its error contract"*) is an ancestor of that tip, so the screen was already
styled when the capture was taken. What the capture predates is the pass's
**own fix round**, `205d77a`, which reshaped the money controls sitting above
Approve on this screen: `MoneyInput.module.css`'s `.field` went `inline-flex` →
`flex`, and `.input` gained `box-sizing: border-box`, which that stylesheet's
own comment records as the difference between a `min-height: 44px` control
painting 44px and painting **54px**. So the geometry did move after the
capture. Re-derive the ancestry rather than trusting this paragraph:

```bash
git merge-base --is-ancestor bdbfd03 c781f40 && echo "styled before the capture"
git merge-base --is-ancestor 205d77a c781f40 || echo "capture predates the fix round"
```

The finding's wording says 1440×900; it is below the fold at every desktop
height measured. The finding keeps its original text and carries a dated
verdict line, which is that report's own convention.

## Decision

### 1. One outcome region, and an outcome that appears takes focus

Three elements move into one region: the backend-down explanation, the summary
alert, and the terminal or held card. **The inline field error stays outside
it**, beside the input it blames and carrying its own `role="alert"`, because
ADR-0024 decision 5 puts it there and this ADR extends that contract rather than
reopening it. So on the commonest failure the server's sentence is on screen
twice — once in the region, once at the field — and focus moves to only one of
them. `frontend/e2e/visual.spec.ts` already asserts the pair, by filtering
`getByRole('alert')` on the message text.

Rendering the region and focusing it are **the same mechanism** — the effect
keys on the submit state and the region's ref is the only thing it reads — so
the rule is structural rather than a list of states somebody has to remember to
extend.

The condition is written as the **complement** of the pending states:

```tsx
const hasOutcome = submit.kind !== 'idle' && submit.kind !== 'busy'
```

Not "render on `failed`, `lost` and `held`". A rule that enumerates the
resolved states is an enumerated defence that the next state escapes silently
(review standard 19). Written as a complement, a state added later **defaults
into** the region and inherits the focus move by construction.

**The complement guarantees the region, not its contents.** What a later state
inherits is the focus move, not something to show: the region's three inner
conditionals are still enumerations of `failed`, `lost` and `held`, so a sixth
state renders the region with all three false — an empty box that takes focus,
which the browser scrolls to and in which the reviewer sees nothing. That is
this defect again with a green suite. Re-derive it rather than trusting this
paragraph: move the `lost`/`held` branch out of the region, and in the terminal
state the region renders empty and focused while exactly one test fails —
`takes focus when a submit resolves to a terminal state`, on its
`region.contains(notice)`, which names *this* state's notice. A state added
later would have no such test. The hazard is genuinely reduced — one focus move
too many beats an outcome that renders where nobody is looking — and it is not
removed: putting the new state's outcome inside the region stays the author's
job, enforced by nothing.

**Every appearance moves focus, not only the first.** A resubmit that fails
again goes `failed → busy → failed`, the effect's dependency changes, and focus
moves a second time. That is intended: a rule that fired once would leave the
retry silent, which is this defect over again.

**Focus never moves without the reviewer having acted.** The region appears
only as the resolution of a submit, and every path into a submit starts from a
reviewer action: ⌘↵, a click on Approve, or a click on `Close task`, which
drives the same `Submit` state through `closeTaskOnly`. So focus movement is
always the answer to something the reviewer just did. That is the property that
makes moving focus acceptable at all. A future state that could render an
outcome with no reviewer action would need this reconsidered rather than
inherited.

### 2. Focus lands on a non-interactive container, never on the exit button

The region is the focus target: a `<section>` carrying `tabIndex={-1}` and no
handlers. **Focus must never go to `Next receipt`.**

`ReviewScreen.tsx` already carries the measurement of why, in its comment on
the `held` branch, and it is not hypothetical: two buttons alternating in one
slot are the same DOM node to React, so the relabel used to happen under the
reviewer's finger — after clicking Approve, `document.activeElement.textContent`
was `"Next receipt"`, it was the identical node, and a bare Enter advanced the
queue. One keystroke of muscle memory dismissed the warning unread, which is
the whole thing that state exists to prevent. **Read that comment rather than
this paragraph.**

Focusing the exit would deliberately re-create a failure this screen has
already engineered away. The pin asserts the negative *and* the positive:
`not.toBe(exit)` alone would also pass with focus left on `body`, which is the
defect.

### 3. The region carries no role — ADR-0024 decision 4 extended, not reopened

The container gets **no `role`** — measured `null` in the browser as well as
asserted in the suite. Decision 4 is a user ruling: a second alert in this
region makes every single-alert query in the suite ambiguous, because
`findByRole('alert')` then matches two elements and throws.

That ruling is about **announcement**; this decision is about **attention**.
The region is a focus target, not an announcement, so it needs no role, and
adding one would reopen a ruling this milestone has no mandate to touch.
Decision 5 is likewise intact: wrapping the summary alert did not make it
conditional, and it still renders in every failure case. Decision 3 is intact
by construction: in a terminal state Approve does not render at all, and the
single exit lives *inside* the terminal card, which is inside this region.

The cost is stated rather than hidden, and it runs in **both** directions. How a
screen reader behaves when focus lands on a container wrapping a `role="alert"`
is **untested**. It may say *more*: some readers announce both the focused
container's contents and the live region. It may equally say *less* — moving
focus can preempt or drop a pending live-region announcement, so a reviewer who
would have been told about the 403 may now be told nothing. That second
direction is the one worth naming loudest, because the finding's own words are
that for I5 *"a screen-reader user is told; a sighted one is not"*:
screen-reader users are the one class this defect never harmed, and they now
carry a risk introduced to fix it for everyone else. This project has never
tested with a real screen reader; the browser pass says so about itself.
Neither direction is tested, and neither is claimed.

**"No role" and "no accessible name" are one decision, not two.** A `<section>`
carrying an accessible name is a `region` landmark; without one it maps to
`generic`. Declining the role therefore declines the name, and focus lands on
an unnamed generic node — measured in Chromium on the terminal state, where
Playwright's `getByRole('region')` finds nothing on this screen and the
accessibility tree under the container starts at the inner `alert`, with no
node for the container above it. That follows from extending ADR-0024 decision
4 rather than being an oversight, and it is written here because nothing else
writes it down.

### 4. Focus, not `scrollIntoView`, and the reason is measured

The browser scrolls a focused element into view by itself. Measured: after the
chord, the region's top is **768** in a 900px viewport and `window.scrollY` is
**460**, with `document.activeElement` on the region and no scroll call
anywhere in the component. `boundingBox().y` and `getBoundingClientRect().top`
agree, so that is the same verdict read twice.

Corroborated from a different state by a different spec: the focus-indicator
probe drove the `lost` outcome rather than the 400 and read `window.scrollY`
**460** again. The region's own top is not comparable across the two — a
`field` 400 also renders an inline error inside the form, above the region — and
it is the scroll figure that reproduced.

`scrollIntoView` was not merely passed over. In jsdom — the environment every
rendering test in this project runs in — `HTMLElement.prototype.scrollIntoView`
is **`undefined`**, while `element.focus()` works and `document.activeElement`
moves. A scroll call would break every rendering test that reached this path
unless stubbed, and a stubbed assertion proves only that a stub was called.
**Focus is the only mechanism here that a green `verify.py` can certify at
all**, and that is why the fix rides on it.

### 5. The region is a `<section>`, because `.screen > div` is positional

`ReviewScreen.module.css` selects the image pane by element type and position —
`.screen > div` sets `grid-column: 1`, `grid-row: 2 / span 4` and `position:
sticky` — and its own comment records that the pane is the only direct `<div>`
child of that `<main>`. **Any new top-level `<div>` child silently becomes the
sticky image pane.** The region is therefore a `<section>`, and the JSX says so
at the site rather than leaving the next reader to rediscover it.

This milestone routes around the selector rather than fixing it: rewriting it
would touch the layout the browser pass validated. **It is now a second reason
on the record to replace it**, beside the maintainability hazard the styling
milestone already recorded. The same positional style is why the stylesheet's
`grid-row: 2 / span 4` comment had to be re-derived over all five submit states
when the region landed — the change falsified what that comment said about
which children always render.

## Consequences

- **What a green `verify.py` now certifies**: that focus moved to the region
  when an outcome appeared, and that *today's* outcome elements are **inside**
  it. `document.activeElement` is observable in jsdom and the suite already
  asserted it elsewhere, so this is not a new capability.
- **The containment assertions do not reach a future sibling.** They pin where
  the three elements named in decision 1 sit; they are not a trap a later
  author's sibling springs. Re-derive rather than trust this: render one more
  element under `hasOutcome` — a `<p>` with no role, as a *sibling* of the
  region rather than a child — and `npx vitest run` from `frontend/` stays
  green: an outcome rendered where nobody is looking, with every gate passing,
  which is the shape this milestone exists to end. Give that same
  `<p>` a `role="alert"` and `review-screen.test.tsx` goes red, but through
  ADR-0024 decision 4's mechanism rather than through containment: a second
  alert makes `findByRole('alert')` match two elements and throw. A sibling
  with no role, or one rendering in a state no single-alert query reaches, is
  silent.
- **The design said the region needs no visual treatment. Measured, that means
  it gets none.** In **both** themes the focused container computes
  `outline-style: none` and `box-shadow: none`, with no border and no
  background, and it **does not match `:focus-visible`** — so the browser's own
  default ring is not a fallback here either. `tokens.css` scopes the ring to
  `:where(a, button, input, select, textarea):focus-visible` and a `<section>`
  is none of those, so `--color-ring` (`#2563eb` light, `#60a5fa` dark) exists
  and never paints on it. `stylesheets.test.ts`'s census pins `.outcome`'s
  declarations as exactly `display`, `flex-direction` and `gap`, which is the
  same fact from the stylesheet's side. Two measured things keep this from being
  the defect it sounds like: the **scroll** is the mechanism doing the work, not
  the indicator, and the `.terminal` card the reviewer is scrolled to carries
  its own surface and border, so there *is* a visible change on screen. What is
  missing is any mark on the focused element itself. Recorded as a known gap —
  see *What this ADR does not decide*.
- **What it still cannot certify**: that anything became *visible*. jsdom
  performs no layout. The scroll is the browser's own side effect of moving
  focus and no gate can see it. This is ADR-0029's boundary exactly — a
  universal pin that still does not measure the thing you care about.
- **Acceptance therefore has two halves, and the second is not a gate**: the
  suite for the mechanism, and a browser measurement showing the outcome within
  the viewport after the chord. The measurement in *Context* is that half, run
  by hand. A person looking at it is the only thing that closes I5 as *seen*.
- **The pins were proven by mutation, not by being green.** Removing the focus
  call fails the focus assertions with `document.activeElement` reading
  `<body>` against an expected `<section tabindex="-1">` — an assertion about
  focus, not a query that found nothing. Moving the summary alert out of the
  region fails the containment assertion alone. Run *before* the container
  existed, every one of them failed instead because `section[tabindex="-1"]`
  matched nothing — failure for the wrong reason, which proves nothing (review
  standard 15). The mutations are what make them pins.
- **A fixture that omits a route is not neutral, and the failure it produces
  does not name the thing under test.** The plan's test fixtures did not stub
  the receipt image; an unstubbed path 404s, and `ImagePane` answers a failed
  image link with a `role="alert"` paragraph of its own. So `findByRole('alert')`
  matched two elements and **threw**: two of the five new tests errored on the
  *fixture* rather than failing on their own assertion, and would have gone on
  erroring after the region existed. Neither alert contains the other —
  `ImagePane` is the second child of `.screen` and the region is the seventh,
  both inside the same `<main class="screen">` — so a query written to find
  *the* outcome alert was silently ambiguous about which screen element it
  meant. `review-screen.test.tsx` carries that measurement inline, beside the
  stub that fixes it. **The same ambiguity is one fixture away from returning.**
  Those tests reach the `failed` state through a helper that types nothing, so
  `buildPatch` returns `{}`, `classifyFailure` cannot match a field path, the
  400 is `other` rather than `field`, and no inline error renders. A fixture
  that typed a real field error would render a second `role="alert"` beside the
  input — deliberately, per ADR-0024 decision 5 — and `findByRole('alert')`
  would throw again, on a test that had nothing to do with the image.
- **The load-failure screen is untouched.** `phase.kind === 'failed'` renders a
  different `<main>`: a short, single-column page whose alert is near the top
  with nothing above it, so it has no below-the-fold problem to solve. Named
  here so its absence reads as a decision rather than an oversight.
- **I5's status is stated in one place, and other copies are dated records.**
  The verdict lives on the finding, in the browser-pass report.
  `git grep -n "I5" -- docs` is the list of everywhere else it is named; read
  it rather than trusting any summary of it, including this one. Some of those
  describe I5 as open and are correct as of their own dates: an Accepted ADR is
  immutable and its "still open" section is a snapshot, and the handoff prompt
  is refreshed at every session end and committed last and alone (ADR-0033).

## What this ADR does not decide

**I7** — the 401 that swaps in the login form with no message and repaints
restored edits identically to stored data. A separate mechanism with no shared
cause, user-scoped out of this milestone.

**Whether the everyday 1195px-deep Approve is itself a defect.** Measured and
recorded above; nothing here moves it. Pinning or sticking the action region
would fix the everyday ergonomics, and it is a layout change against a screen
the browser pass validated, and it is not what I5 describes.

**Whether the outcome region gets a focus indicator.** It has none, in either
theme, and the browser's default is not a fallback because the element does not
match `:focus-visible` — measured at the last gate before merge, and left
alone rather than fixed there. Adding one is an ADR-0027 question, not a
rendering one: the ring token is deliberately scoped to interactive elements,
so widening that scope, or giving `.outcome` a treatment of its own, changes the
design system. The case for leaving it is that this element is not tabbable, no
reviewer navigates to it, and the card it wraps is already visible; the case
against is that a focused element with no mark is a thing a keyboard user can
lose. Nobody has taken that decision, and this ADR does not.

**Whether Playwright becomes a sixth gate.** The browser measurement is the
half of acceptance no gate performs, and it is run by hand. Making it a gate is
a decision about CI time and flake budget that nobody has taken.

**Whether `.screen > div` gets rewritten.** It stays positional, now with one
more reason on the record to replace it. The wrapper element that would make
the right-hand column structural instead of positional is the single
restructure that stylesheet asks for, and it still does not get it.

**Whether the Approve gate should be a complement too.** It is not: Approve is
suppressed by an *enumeration* (`submit.kind === 'lost' || submit.kind ===
'held'`) while the region is rendered by a *complement*. So a terminal state
added later would default **into** rendering a retry beside its own outcome —
the retry that cannot work, which ADR-0024 decision 3 forbids — while correctly
defaulting into the region. Closing that asymmetry needs something to key on that the
`Submit` union does not carry: there is no `terminal` discriminator on it, and
inventing one is a change to the submit contract rather than to this render.
Recorded as an open question, not fixed.

**What the focus move costs the commonest failure.** A field error is not
terminal: the reviewer has to go back and fix the field. The server's message
renders both in the summary alert and beside the input it blames (ADR-0024
decision 5), and the measurement above is the page scrolling 460px *away* from
`Total` in order to show the alert. That is what I5 asks for, and it is right
for the case that motivated it — a 403, where there is nothing to go back to —
but the retry ergonomics of the most common failure are worse and nobody has
measured that cost.

## References

`docs/superpowers/specs/2026-08-12-review-outcome-focus-design.md` — the
approved design; `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`
— finding I5, the single capture behind it, and its dated verdict;
`docs/adr/0024-review-ui-error-recovery-contract.md` — decisions 3, 4 and 5,
which this extends; `docs/adr/0029-what-the-gates-certify.md` — the boundary
the Consequences restate; `docs/adr/0027-review-ui-design-system.md` — the
design system, and the positional selector recorded as a residual;
`frontend/src/review/ReviewScreen.tsx`,
`frontend/src/review/ReviewScreen.module.css`,
`frontend/tests/review-screen.test.tsx`, `frontend/tests/stylesheets.test.ts` —
what shipped.
