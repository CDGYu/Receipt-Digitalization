# The review UI's first browser pass

**Date:** 2026-08-06
**Branch:** `feat/review-ui-styling` (tip `c781f40` when this ran)
**Spec run by:** `frontend/e2e/visual.spec.ts` — `cd frontend && npx playwright test visual`
**Screenshots:** 97 PNGs in `var/e2e/visual/` (git-ignored, and they must stay
that way — they are pictures of receipt data). Measurements alongside them in
`var/e2e/visual/measurements.json`.

> **This document reports. It fixes nothing.** Every finding below names the
> file that owns it, for whoever picks it up. Nothing in `src/` was touched.
>
> **No pixel baseline was laid down.** No `toHaveScreenshot`, no snapshot
> assertion. Three UI milestones shipped without anybody looking at them, so a
> baseline captured here would pin whatever is currently broken. The
> screenshots are evidence a human read; the spec asserts only that each state
> was *reached* and that every route stub was *hit*.

---

## 0. What this was, and why it had never happened

`ReviewScreen`, the five ADR-0024 error states, the confidence rail, the
findings panel, the line-items table and the whole admin surface have been
verified entirely through Vitest against jsdom. That proves structure and
accessibility wiring. It cannot see a colour, a box, an overlap or a font, and
**every defect in section 3 below was invisible to it** — the suite was green
with all of them present.

**[Corrected 2026-08-07 — that sentence has a shelf life, and it has expired.**
It was written when nothing pinned a declaration. `8ede47e` added a gated
stylesheet declaration census, and the census *can* now see C1, C3 and I4: each
of the three reverts that used to leave the suite green now reds it. What jsdom
still cannot see is the layout half — `cellOverflow` lives in the ungated
Playwright run, and a width regression expressed as a *length* rather than a
keyword would still pass. **ADR-0029** states the boundary. The suite count that
stood here has been removed rather than repointed: it rots on every commit that
adds a test, and review standard 5 says it does not belong in the sentence.**]**

97 screenshots were taken at **375, 1024 and 1440px**, in **light and dark**,
across eleven surfaces. **Every one of them was opened and read.** Numbers that
are numbers rather than judgements — contrast ratios, hit-target boxes,
horizontal overflow, the focus outline the browser actually computes, whether
the money font's digits really are the same width — were measured in the page
and are in `measurements.json` (64 records).

### How the synthetic states were produced

The fixture cannot produce most of them, so `page.route()` interception did:

| State | Why the seed cannot |
|---|---|
| null fields | `scripts/seed_review_e2e.py` populates **every** column; there is no null in it |
| three severities | the seed writes one ERROR and one WARN; nothing seeds INFO |
| the five error states | 503/403/404/400/401 are not things a healthy server does |
| admin-as-admin | the seed calls `create_user(..., ROLE_REVIEWER)` once, only |
| a legible receipt image | the seeded blob is a 1×1 transparent PNG |

`scripts/seed_review_e2e.py` was **not** modified. The seeded login and the
seeded review screen went through the real API; everything else is stubbed, and
the spec fails loudly if a stub never matched (`expectHits`) — a glob that
silently misses produces a screenshot of the *real* page, which is
indistinguishable from success at review time. That failure mode was measured
while writing this: without a `**/auth/me` stub the app drops to the login form
and the "review screen" capture is a picture of the login page.

---

## 1. The nine questions, answered

| Question | Answer |
|---|---|
| **Is a null field visibly different from a zero?** | **In the form, yes — unmistakably, in both themes.** `0.0000` in `--color-foreground` against a grey `—` with a hairline left border. ~~**In the line-items table, no: a null amount is invisible** (finding C2).~~ **[Corrected 2026-08-07 — this half is no longer true. C2 was fixed in the pass's own fix round; the table's null amounts now show the right-aligned `—`. See the status note at the head of §3.]** |
| Is the money column aligned on the decimal at every width? | **Only at 375.** The form is a 1/2/4-column grid at 375/1024/1440, so the six amounts sit in different columns at the two larger widths (measured right edges at 1440: 826, 1017, 1208, 1399). Alignment holds *within* a column. Fira Code's tabular figures are real and measured: `1111111111`, `0000000000` and `9999999999` each measure **exactly 96px** at 16px. |
| Do severity colours survive dark mode at 4.5:1? | **Yes.** error 4.94:1, warn 8.66:1, info 7.31:1 on `--color-surface`. Light: 4.83 / 5.02 / 6.70. Each carries the word as well as the colour. |
| Does anything scroll horizontally at 375px? | **No.** `documentElement.scrollWidth` never exceeded `clientWidth` on any of the 64 records. The line-items table scrolls inside its own `overflow-x` wrapper, as §5.2 asks. |
| Are focus rings visible on every interactive element, in both themes? | **On every input, select and button: yes** — `2px solid var(--color-ring)` at 2px offset, `:focus-visible` matching under keyboard traversal (26 stops walked on the review screen). **`<summary>` is the exception** and keeps the browser's own ring (finding m10). |
| Do the five error states read as sentences a reviewer can act on? | **The words do; the placement does not.** Every message is the server's own and every state offers exactly one workable exit. But the terminal states, the summary alert and Approve are all below the fold at a real window height (finding I5), and the 503's two sentences say the same thing twice (finding I9). **[Corrected 2026-08-12 — the placement half no longer answers the question. I5 was fixed (`99f0207`, ADR-0041): the outcome takes focus when it appears and the browser scrolls it into view, so a 403, a 404 or a 400 no longer leaves the screen identical. The sentence stands as written — these elements do still render below the fold at rest; what changed is that the reviewer is taken to them. I9 is unaffected and still open.]** |
| Is the receipt image legible against its surround? | **Yes** — judged against an intercepted receipt-shaped image, because the seeded blob is one transparent pixel. White paper on `--color-surface-sunken`, paper edge clearly visible, nothing tinted or overlaid. §5.5 delivered. |
| Are touch targets 44×44 in practice? | **On the review and admin screens, yes.** Every input/select/button measured ≥44 tall. The two checkboxes are 20×20 **but their wrapping label measures 317×44 / 250×44 / 179×44**, so the row is the target, as `.check` claims. ~~**Not on login (21px controls) and not on the findings disclosure rows (21px).**~~ **[Corrected 2026-08-07 — the login half is no longer true: C3's fix took all three login controls past 44px in both themes at all three widths. The findings disclosure rows are still 21px (m10's neighbourhood) and are unfixed.]** |
| Does the light/dark switch work, and does explicit light beat an OS dark preference? | **Yes, both directions.** OS dark + `data-theme="light"` → light page *and* light UA widgets. OS light + `data-theme="dark"` → dark both. `:root:not([data-theme='light'])` behaves exactly as ADR-0027 says. **There is no theme control in the app**, so the only ways in are the OS preference and setting the attribute by hand. |

---

## 2. What is right

Recorded deliberately: three milestones shipped unseen, so "this part is fine"
is information nobody had.

* **The two-column shell lands where intended.** `.screen > div` really does
  select only the `ImagePane`: at 1024 and 1440 the photograph is the left
  column and the heading spans both, with findings / rail / form / table in the
  right column; below 1023px it collapses to one column in source order with
  sticky dropped. The controller's suspicion is unfounded in this tree.
* **`LineItemsTable` does have its `overflow-x` wrapper** and it works — the
  table scrolls, the page never does. (The brief says it does not. See §5.)
* **The findings panel is the best-realised component**: rule id in mono, the
  severity word in its own colour, the message inline, and the `context`
  payload behind a native `<details>` — legible in both themes.
* **The confidence rail's null distinctions render**: `—` for a null score,
  "Breakdown not recorded for this receipt." for `null` reasons, and "Nothing
  lowered the score." for `[]`.
* **The inline field error is genuinely additive** — the red border on the
  field, the server's sentence in the form, and the summary alert at the
  bottom, all three at once (ADR-0024 §5 honoured).
* **The admin surface is the most finished screen in the app**: stat tiles,
  chips carrying an icon *and* a word, `—` for an unassigned holder, an inline
  release confirm, and a table that scrolls rather than squeezes at 375.
* **The sign-out confirm reads as the interruption it is** — raised card, red
  destructive verb, cancel beside it.

---

## 3. Findings

> **Status note — 2026-08-07, added by the milestone's closing fix wave.**
> This section was written as a snapshot on the day of the pass and then shipped
> unchanged while its findings were being closed, so for a day it advertised four
> fixed defects as open. It is corrected in place rather than rewritten: the
> findings keep their original text, and each carries a dated verdict line.
>
> | Finding | Verdict |
> |---|---|
> | C1, C2 | **FIXED** — `205d77a`. `MoneyInput.module.css`'s `.field` went `inline-flex` → `flex`; `cellOverflow` 204 records → 0. |
> | C3 | **FIXED** — `205d77a`. `frontend/src/login/` got its first stylesheet; all three controls clear 44px. |
> | I4 | **FIXED** — `205d77a`. `--color-null` → `#7C8CA2` in both dark blocks; sub-4.5:1 records 35 → 0. |
> | **I5** | **RE-TRIAGED TO CRITICAL** (user ruling, 2026-08-06), then **FIXED 2026-08-12** — `99f0207`, recorded in **ADR-0041**. The outcome region takes focus when it appears, so the browser scrolls it into view. See its own entry. |
> | **I6** | **FIXED 2026-08-13 — MEASURED, NOT SEEN** — `e7e5d9e`; the guard that joins `.fieldCell` in the stylesheet to the reference in the component landed at `d4cbba2`. Every text and money field is wrapped in a `.fieldCell` at the call site in `ReceiptForm`, so the error is a child of a grid *item* rather than of the grid. See its own entry. |
> | I7 | **OPEN**, unchanged. It touches **ADR-0024**'s error-recovery contract, so it waits on a user ruling rather than on anyone's time. |
> | **I8** | **FIXED 2026-08-14 — MEASURED, NOT SEEN** — `3f552d1`, reworded at `7a770c3`. The tiles region opens with a caption naming the figures' scope, so the global counts no longer read against the role-scoped table below them. See its own entry. |
> | **I9** | **FIXED 2026-08-14 — MEASURED, NOT SEEN** — the copy at `1322932`, the frame at `fcfc627`. Two site-appropriate sentences replace the one that was said twice, and the failure notice is framed. Its entry also carries a dated correction: one half of the finding was never true. |
> | m10–m16 | **OPEN**, unchanged. |
>
> **The fixes were pinned only afterwards, and that is the milestone's headline
> lesson.** All three of `205d77a`'s changes were independently revertible with
> every gate green until `8ede47e` added a gated stylesheet declaration census.
> **ADR-0029** records what a green run now certifies and what it still cannot —
> read it before treating anything in this report as gate-protected.
>
> One defect in this list was found *after* the pass, by that census, because no
> capture puts it on screen: **`SignOutControl.module.css`'s `.error` renders
> inside `.confirm`, which paints `--color-surface-raised` — 4.39:1 in dark,
> below AA.** Recorded here with its measurement; not fixed, because it is a
> source change.
>
> **[Added 2026-08-14, with the I6/I8/I9 rows — what "MEASURED, NOT SEEN"
> means, once, for all three.** Nobody has opened a browser on any of that work.
> Every claim those three rows and their three entries make **about the result
> on screen** rests on jsdom, which lays out nothing and paints nothing; on
> `stylesheets.test.ts`, which reads a stylesheet as text and never asks what
> it computes to; on a class-name guard, which joins a name to a name and lives
> in a different test file for the admin surface than for the other two; and,
> for the one Playwright assertion this milestone touched, on a string compared
> against the code by eye. **ADR-0041** closed I5 on this same footing, and its
> acceptance bullet is where the distinction is stated: a person looking at it
> is the only thing that closes I5 as *seen*.
>
> Named rather than left to be inferred. **No browser, at any width, in either
> theme**, has rendered the field cell, the caption or the framed notice — so
> nothing here is evidence about a colour, a box or a column. **The Playwright
> visual run is not one of the five gates**; `scripts/verify.py` names it under
> *"Not a gate"* in its own docstring, so a green run after these three fixes
> certifies nothing about `frontend/e2e/`. And **the re-pointed assertion in
> `frontend/e2e/visual.spec.ts` was verified by static string comparison** —
> read against the JSX it has to match — **and not by running it.**
> **ADR-0029** is the standing list of what a green `verify.py` cannot see, and
> these three fixes escape none of it.**]**

> **[SUPERSEDED IN PART, 2026-08-14 — the three screens have now been SEEN.**
> The block above was true when written. The Playwright acceptance run was then
> executed against the merged tree — `npx playwright test visual`, **15/15
> passing**, 97 screenshots, 64 measurement records, 408 table cells checked —
> and the captures were read. **The re-pointed assertion is no longer verified
> only statically**: `ADR-0024 state 1 of 5: the distinct 503` passes against a
> running browser.
>
> **Invocation note, because the suite says so itself and it cost a run:** the
> whole suite consumes its single queued task in `review.spec.ts` by design, so
> `npx playwright test` leaves `visual.spec.ts` with an empty queue and a
> self-diagnosing failure. **Run `npx playwright test visual`, which re-seeds.**
>
> **What the captures show, at 1440 and 375, light:**
>
> * **I6 — correct, and unambiguously so.** `not a decimal amount: 'abc'` renders
>   directly beneath the Total field in the fourth column, with that input
>   outlined in the error colour. Before the fix the sentence sat at the far left,
>   under Subtotal.
> * **I8 — correct, and the `auto-fit` repair holds in a real browser.** The four
>   tiles span the row edge to edge with no blank remainder, and the caption heads
>   all four rather than labelling the first. This is the visual confirmation of a
>   fix that had only ever been verified by computing a track list.
> * **I9 — the frame is there and the finding is closed, but the result raises a
>   new question the fix did not.** The card renders with its border, radius and
>   surface, and its contents are vertically centred. **It is also mostly empty:**
>   at 1440, three small elements sit in a 60vh box with roughly 350px of blank
>   above and 370px below; at 375 the box fills the viewport width with the same
>   proportions. Whether `min-height: 60vh` is right for a block this small is a
>   judgement no measurement can make, and it is now a live question rather than a
>   hypothetical one.
> * **A parked finding is CONFIRMED by eye.** The 2026-08-14 milestone parked, for
>   the visual pass, that `.alert` and `.action` both paint `--color-surface` and
>   would lose their separation against a card of the same fill. They do: the
>   alert is distinguished only by its left border rule, and `Try again` reads as
>   a thin outline on the card's own white. Predicted, deferred, and now seen.
>
> **Still not seen:** dark theme at any width, 768, and every surface these three
> fixes did not touch. This note closes I6 and I8 as *seen at 1440 and 375 in
> light*, and closes I9's *frame* on the same footing while opening the question
> above.**]**

### Critical

**C1 — The line-items table's three money columns are unreadable, at every
width, in both themes.**
`MoneyInput.module.css`'s `.input` sets **no `width` and no `box-sizing`**,
unlike `ReceiptForm.module.css`'s `.input` and `LineItemsTable.module.css`'s
`.cell`, which both set `width: 100%; box-sizing: border-box`. So each money
control renders at the HTML default intrinsic width — **measured 246px** — in
cells measured **92px (Qty), 105–119px (Unit price), 106–119px (Line total)**.
Measured overflow per control: **127–155px, on every surface that renders the
table**. On screen: the Qty control paints under and past the Unit column's
`btl` box, the per-row `MoneyInput` labels ("Qty 0", "Unit price 0") show
*inside the cells* duplicating the column headers, the values land nowhere near
their headers, and Line total is clipped away entirely by `.scroller`. §5.2's
"column widths fixed so the decimal column does not shift" is destroyed:
there is no decimal column.
*Owning file:* `frontend/src/review/MoneyInput.module.css`. Co-owner for the
column widths: `frontend/src/review/LineItemsTable.module.css`.
*Evidence:* `review-real-table--*`, `review-null-table--*`,
`measurements.json` → `cellOverflow`.
***FIXED 2026-08-06 (`205d77a`).*** The diagnosis above is right about the
symptom and wrong about the cause: the missing `width` was measured inert, and
the real cause was `.field { display: inline-flex }` shrink-wrapping to the
input's `size="20"` intrinsic width. `display: flex` fixed it; `cellOverflow`
went 204 records → 0. **Pinned only at `8ede47e`** — see the status note above.

**C2 — A null amount in the line-items table is invisible.** A direct §4
failure, and a consequence of C1: the `—` placeholder is right-aligned inside a
246px control whose right edge is outside the clipped cell, so the null row's
Qty / Unit price / Line total read as **empty boxes** while the same row's
null *text* cells correctly show `—` with a hairline. On the one screen where a
human decides, a never-extracted amount and a box nobody has typed in yet look
identical.
*Owning file:* as C1.
*Evidence:* `review-null-table--1440-light.png`, `review-null-table--1024-light.png`.
***FIXED 2026-08-06 (`205d77a`), with C1.*** The null row's Qty / Unit price /
Line total now render the right-aligned `—` with its hairline border.

**C3 — The login page is entirely unstyled, and it is the first screen every
reviewer sees.** `frontend/src/login/LoginPage.tsx` has no stylesheet and no
`className` anywhere; no task in this milestone owned it. Rendered: the `<h1>`
is the UA's 2em bold, and both labels and both inputs sit **on one line with
the label text touching its box** — `Username[box]Password[box][Sign in]`.
Measured controls: inputs **177×21**, button **56.8×21** — every one under the
44×44 rule that design §6 calls non-negotiable. At 375 the row wraps mid-form,
so "Password" ends line 1 while its box starts line 2 and reads as belonging to
the username box. Only the page background, the body font and the focus ring
come from the design system, because they come from `body`/`:where(...)` in
`tokens.css`.
*Owning file:* `frontend/src/login/LoginPage.tsx` (there is no
`LoginPage.module.css` to fix).
*Evidence:* `login--375-light.png`, `login--1440-light.png`, `login--1440-dark.png`,
`login--1024-dark.png`, and the same page again at `error-401-login--*`.
***FIXED 2026-08-06 (`205d77a`).*** `LoginPage.module.css` now exists, built from
`ReceiptForm`'s and `ui/Button`'s rules; all three controls clear 44px in both
themes at all three widths. Its class names were guarded separately at `1bfacb4`
because the fix round was forbidden the test file — plan defect #15's shape,
third occurrence — and its *declarations* only at `8ede47e`.

### Important

**I4 — `--color-null` fails the 4.5:1 body-text rule in dark mode: measured
3.91:1** (`#64748B` on `--color-surface` `#0E1223`). It is spelled identically
in all three theme blocks. It paints the em-dash mark **and every
`::placeholder`** — that is, the single glyph carrying the prime directive
("prefer `null` over a confident guess"). Light measures 4.76:1: a pass with
almost no margin. Everything else on every surface measured ≥4.5:1; this is the
only failure in 64 records.
*Owning file:* `frontend/src/styles/tokens.css`.
***FIXED 2026-08-06 (`205d77a`).*** `--color-null` is `#7C8CA2` in both dark
blocks — **5.43:1**, browser-measured across 26 records. Sub-4.5:1 contrast
records went 35 → 0. (An earlier hand computation of `5.45` had a wrong green
luminance and propagated; `5.43` is the measured value.)

> **I5 was re-triaged to Critical on 2026-08-06 (user ruling) and is NOT fixed.**
> It is left in this section under its original heading so its finding id keeps
> meaning what the captures and `measurements.json` call it. Severity, not
> position, is the ruling: a 403 or a 404 is the case where *the write landed and
> the task is gone*, and the reviewer sees nothing at all. Fixing it means
> reopening **ADR-0024**'s error-recovery contract — which is why it was not
> taken as a drive-by.
>
> **[Superseded 2026-08-12 — "is NOT fixed" was true when written and is not
> now.** I5 was fixed at `99f0207` and the decision is **ADR-0041**. The
> prediction in the last sentence above did not hold: fixing this **extended**
> ADR-0024 rather than reopening it — the outcome region carries no `role`, so
> decision 4's single-alert ruling is untouched, and in a terminal state
> Approve does not render while the single exit stays inside the terminal card,
> so decision 3 is untouched. The rest of that sentence held: it was still not
> a drive-by, and took a design, an ADR and a milestone of its own. The verdict
> line at the end of this entry is the record.**]**

**I5 — At a real window height the outcome of pressing ⌘↵ is off-screen.**
At 1440×900 the review screen's last visible element is the middle of the form:
the line-items table, the summary alert, the `taken` / `gone` terminal card and
the Approve button are all below the fold (the terminal card renders ~1240px
down at 1440, and far lower at 375). So a 403, a 404 or a 400 produces **no
visible change at all** for a sighted reviewer — the form stays exactly as it
was. The states carry `role="alert"`, so a screen-reader user is told; a
sighted one is not. This is the one finding that changes what a reviewer
*believes happened*.
*Owning file:* `frontend/src/review/ReviewScreen.module.css` (the outcome
region is a grid item in source order; nothing pins it near the action or
brings it into view).
*Evidence:* `review-real-fold--1440x900-light.png`, `error-403-taken--1440-light.png`,
`error-404-gone--375-light.png`, `error-400-field--1440-light.png`.
***FIXED 2026-08-12 (`99f0207`), recorded in ADR-0041.*** The backend-down
explanation, the summary alert and the terminal card are now one
`<section tabIndex={-1}>` that takes focus whenever it appears, and the browser
scrolls a focused element into view by itself.
**This finding understated the defect**, and the correction belongs here rather
than in the text above. Re-measured in Chromium against the seeded fixture with
the page at the top: Approve sits at **y=1195** at 1440×900, ×800 **and**
×1080 — measured at each height, so it is below the fold at every desktop
height tested, not only the one this entry names — in a 1263px document, and
the line-item row pitch is **73px**, so it degrades with the receipt.
**The placement is unchanged**: these elements still render at the end of the
document. What changed is that the reviewer is taken to them — measured,
`scrollY` 0 → 460 with the region in view and `document.activeElement` on it.
The *owning file* named above is not where the fix landed: it is
`ReviewScreen.tsx` (the region and the focus effect), with one class added to
the stylesheet.

**I6 — The inline field error does not sit under the field it blames.**
`ReceiptForm.module.css`'s `.form > p { grid-column: 1 / -1 }` starts the error
at the beginning of the grid row, so with `abc` in Total — the 4th of 4 columns
at 1440 — the red sentence renders at the far left, under Subtotal. Three
columns from its field. Correct at 375, where the form is one column.
ADR-0024 §5's "beside the input that sent it" holds in the DOM and in the
accessibility tree (`aria-describedby`), and not on screen.
*Owning file:* `frontend/src/review/ReceiptForm.module.css`.
*Evidence:* `error-400-field-form--1440-light.png`.
***FIXED 2026-08-13 (`e7e5d9e`) — MEASURED, NOT SEEN.*** Every text and money
field is now wrapped in a `.fieldCell` at the call site in `ReceiptForm`, and
the `.form > p` rule is gone. The wrapper is the grid item, so a label and the
error that belongs to it travel together into whatever column auto-fill puts
them in.
**The rule this entry names was a repair, not the defect.** The error is a
*sibling* of its label — ADR-0024 §5 forbids nesting it, because the sentence
would join the field's accessible name — so as a bare grid child it takes a cell
of its own: the next one auto-placement has free, which is the column after its
label, or the first column of the row below when the label sits in the last
column. `grid-column: 1 / -1` traded that for the start of a full-width row in
every case, which is the gap this entry measures at 1440. Deleting the rule on
its own would have exchanged one wrong position for another rather than
restoring the right one.
**The wrapper went at the call site, and that is what kept the fix inside this
form.** `MoneyInput` renders every money field in this form *and* three cells in
every row of `LineItemsTable`, so a wrapper inside `MoneyInput` would have
reached that table's money cells too. Neither `MoneyInput` nor `LineItemsTable`
was touched.
The *owning file* named above took half of it: the `.fieldCell` rule replaced
`.form > p` there, and the wrapper itself is in `ReceiptForm.tsx`.
*What is measured, and what is not:* `receipt-form.test.tsx` asserts that the
error and its label share a parent, that the parent is a `<div>` and not the
grid, and that the error is still not a child of the label — once for a text
field and once for a money field, one per `.map` block, because the first
version of that test reached only one of the two. `value.test.tsx` joins
`.fieldCell` in the stylesheet to the reference in the component, and
`stylesheets.test.ts` pins the rule's declarations. **No gate places anything in
a column.** jsdom performs no grid layout, so the column the sentence paints in
is exactly what stays unseen.

**I7 — A 401 mid-review swaps the whole screen for the login form and says
nothing.** Measured end to end: type into Total, ⌘↵, the PATCH answers 401, and
the app renders the (unstyled) login page with **no message that the session
expired and no indication that the edit is held**. Signing back in does restore
it — ADR-0016's resume plus the in-memory stash work exactly as designed, the
edit was back in the box — but the restored value is painted **identically to
stored data**, so a reviewer cannot tell which fields carry their unsaved work.
§4's third state (the "cleared"/dirty marker beside the label) is where this
would be answered and it is unimplemented.
*Owning files:* `frontend/src/login/LoginPage.tsx` (no message surface),
`frontend/src/review/ReceiptForm.tsx` + `.module.css` (no dirty marker).
*Evidence:* `error-401-login--1024-light.png`, `error-401-restored--1024-light.png`.

**I8 — The admin surface shows a reviewer a contradiction.** The tiles read
"Open backlog 9 / In progress 2 / Done 74" directly above "No open tasks, and
none assigned to you". Both are true: `/metrics` is global and `/review/tasks`
is scoped by role (ADR-0026 decision 2). §5.6 made the *empty state* name its
scope for exactly this reason; the *tiles* name no scope at all, so the screen
reads as broken.
*Owning files:* `frontend/src/admin/StatTiles.tsx` (the labels),
`frontend/src/admin/AdminScreen.tsx` (the composition).
*Evidence:* `admin-reviewer-empty--1024-light.png`.
***FIXED 2026-08-14 (`3f552d1`, reworded at `7a770c3`) — MEASURED, NOT SEEN.***
The tiles region's first child is now a caption reading "System-wide, not only
your tasks", declared to span the grid so that it heads every tile rather than
labelling the first.
**It claims scope and nothing else, which is narrower than it sounds.**
`queue_stats` groups review tasks by state and never reads `assigned_to`, and
`auto_approval_rate` is a ratio over receipt statuses with no task and no
reviewer in it — so a caption naming reviewers would be false of the rate tile,
and one calling every figure a count would be false of it too. The wording tried
first named reviewers; this milestone's plan carries how that was caught, in its
dated defect log.
`AdminScreen`, the co-owner named above, was not touched — the caption went
inside the region it qualifies, not above it.
*What is measured, and what is not:* `admin-screen.test.tsx` asserts the
sentence inside the `Queue statistics` region, and `stylesheets.test.ts` pins
`.caption`'s declarations. **Nothing measures where it sits**:
`grid-column: 1 / -1` is text to the census and geometry to nobody.
**[Corrected 2026-08-14 — "declared to span the grid" was this fix's own defect,
and it is undone.** `grid-column: 1 / -1` put the caption across every repeated
track, and `auto-fit` collapses only a track that no in-flow item occupies *or
spans* (CSS Grid §7.2.2.1) — so nothing collapsed and `auto-fit` sized exactly as
`auto-fill`. Measured in Chromium against the shipped declarations at a 1440px
viewport: six tracks of ~218.7px, the four tiles 219px wide, and 469px of the row
blank; the same row before the caption existed computes
`336px 336px 336px 336px 0px 0px`. At 1024 both shapes compute the same four
232px tracks. No gate could have, at any
width: none of the five lays a grid out. The caption is now a **sibling** of the
grid: `.tiles` is a flex column holding the caption and a new `.grid` element that
carries the grid declarations, and the measured track list is again
`336px 336px 336px 336px 0px 0px`. It is still the region's first child, still
inside `Queue statistics`, and still heads all four tiles rather than labelling
the first. `grid-column: 1 / 2` was rejected: it restores the row by the same
collapsing mechanism but makes the caption a label on the first tile. **The
`grid-column: 1 / -1` clause above is superseded with it; "nothing measures where
it sits" is not.** No gate computes a track list — the census reads `.grid`'s
declarations as text, the measurement above is a one-off Chromium run, and
nobody has looked at this screen.**]**

**I9 — The 503 state says the same thing twice, floating on an empty page.**
"The database is unavailable — nothing can be saved right now." sits directly
above the alert "the database is unavailable". They were measured as
indistinguishable while writing the spec:
`getByText('The database is unavailable')` matched both and threw a strict-mode
violation. The explanation exists to add plain language to the server's words;
against this message it adds none. The block is also unframed — two bare
paragraphs and a button near the top-left of an otherwise blank screen, with no
card and no vertical centring.
**[Corrected 2026-08-14 — "top-left" is half wrong, and the wrong half was never
true of the shipped stylesheet at any width past `max-width: 40rem` — though at
375 it was accurate, because 40rem is wider than that viewport, so the box fills
it and the contents sit at the left padding.** `.notice` sets `max-width: 40rem`
and `margin: 0 auto`, and has carried both in every revision of
`ReviewScreen.module.css` — including `bdbfd03`, the commit that created the
file, which is an ancestor of `c781f40`, the tip this pass ran against. The
element is a `<main>` in normal flow under an unstyled root, so at any viewport
wider than that box the block was already centred left to right; narrower, the
box fills the width, which is what a `max-width` does. Re-derive with
`git log --format=%h -- frontend/src/review/ReviewScreen.module.css` and read
the `.notice` rule at each. **What the rest of the sentence says — near the top,
no card, no vertical centring — was true**, and that is what the fix addressed.
The finding keeps its original text.**]**
*Owning files:* `frontend/src/review/ReviewScreen.tsx` (the copy),
`frontend/src/review/ReviewScreen.module.css` (`.notice`).
***FIXED 2026-08-14 — the copy at `1322932`, the frame at `fcfc627` — MEASURED,
NOT SEEN.*** Neither explanation restates the server's words any more. One
string served both sites; each now has its own sentence, saying what that site
can actually promise — on the load path, that the reviewer's assigned tasks are
unaffected; on the submit path, that their edits are still on the page and have
not been discarded. The submit path's sentence stays suppressed on the one path
where the write already landed.
The failure render composes `.noticeFailed` onto `.notice`: a border, a radius
and a surface background, with `min-height: 60vh` and `justify-content: center`
placing the notice's own contents in the middle of that taller box. **The frame
is on the failure render only** — `.notice` is the `<main>` for the loading and
empty phases too, and a card around "Loading…" is a screen this finding never
measured.
**What it does not do is centre the block in the window.** `main.tsx` renders a
`<header>` above the `<main>` and nothing centres the notice itself. The claim
that it did was written into the stylesheet while this was being fixed and
deleted from it in the round after — recorded because the same sentence still
stands in the plan step that prescribed it.
*What is measured, and what is not:* `review-screen.test.tsx` asserts both
sentences at their sites, the suppression on the path where the write already
landed, and that `.noticeFailed` is on the failure `<main>` and on neither the
empty nor the loading one; `value.test.tsx` joins the class to the component's
reference; `stylesheets.test.ts` pins its declarations. **The Playwright
scenario asserting the load-path sentence was re-pointed by reading the scenario
and comparing the string, not by running it** — `frontend/e2e` is not a gate.

### Minor

**m10 — `<summary>` keeps the browser's focus ring, not the design's.**
`tokens.css` styles `:where(a, button, input, select, textarea):focus-visible`
and `summary` is not in the list, so the findings rows compute
`outline: 1px auto rgb(16, 16, 16)`. **Looked at rather than inferred: Chromium
paints its adaptive ring and it is clearly visible in both themes** (black on
light, white on dark). So this is an inconsistency — a different ring from
every other control, and other engines paint different defaults — not an
invisible-focus defect.
*Owning file:* `frontend/src/styles/tokens.css`.
*Evidence:* `focus-finding-summary--1024-light.png`, `focus-finding-summary--1024-dark.png`.

**m11 — The findings disclosure rows are 21px tall** (43px when the message
wraps at 375), against §6's 44×44. Unlike the checkboxes there is no wrapping
label to enlarge them; the `<summary>` *is* the target.
*Owning file:* `frontend/src/review/FindingsPanel.module.css`.

**m12 — The `<header>` is unstyled.** The Sign out button sits flush in the
top-left corner at (0, 0) with no padding, out of line with the 24px gutter the
`<h1>` below it uses. `SignOutControl.module.css` already records that it was
written to survive this.
*Owning file:* `frontend/src/main.tsx` (the `<header>` carries no `className`).

**m13 — Text inputs clip their value with no ellipsis and no `title`.**
"BLUE RIDGE HARDWAR", "CABERNET SAUVIGN". At 1440 the form is a 4-column grid
of ~180px tracks and a merchant name is routinely longer than that; the reviewer
cannot read the value they are checking against the photograph without clicking
into the box.
*Owning file:* `frontend/src/review/ReceiptForm.module.css`.

**m14 — The money "column" is a column only at 375.** See §1. The property
Fira Code was chosen for is delivered at the narrowest width and not at the two
where a reviewer will actually work.
*Owning file:* `frontend/src/review/ReceiptForm.module.css`.

**m15 — `auto_approval_rate` renders as `0.598` under the label
"Auto-approval rate".** Showing the ratio rather than a percentage is a
deliberate ADR-0001 choice, but nothing on the tile says it is a ratio, and
`0.598` beside `9`, `2` and `74` invites reading it as a count.
*Owning file:* `frontend/src/admin/StatTiles.tsx`.

**m16 — The image pane has no minimum height.** With the seeded 1×1
transparent PNG it collapses to its toolbar plus a ~24px empty strip, and
nothing says "the image loaded and it is one pixel". A fixture artefact rather
than a defect — but the pane has no floor, and at 1440 it leaves a ~600px-wide
empty left column.
*Owning file:* `frontend/src/review/ImagePane.module.css`.

---

## 4. What could not be captured, and why

* **The seeded review screen cannot answer the image question.** Its blob is a
  1×1 transparent PNG by design. Every judgement about legibility against the
  surround comes from the **intercepted** image, which is a receipt-shaped SVG
  written for this pass. What a photograph of real paper does — JPEG noise, a
  skewed edge, a shadow — is still unmeasured.
* **The four ADR-0024 error states were captured at 375 and 1440 only, not at
  1024.** The grid has exactly one breakpoint (`max-width: 1023px`), so 1024 and
  1440 exercise the same layout; the four primary surfaces were captured at all
  three anyway to confirm the breakpoint's first pixel behaves.
* **`ImagePane`'s own failure states** (link 403, image `onError`, the spent
  retry) were not captured. They are outside the brief's shot list and remain
  the only wired states in the review screen nobody has seen.
* **Chromium only.** `playwright.config.ts` declares no `projects`, so this ran
  on one engine. m10 in particular is a Chromium observation; Firefox and
  Safari paint different default rings.
* **No real touch device and no real screen reader.** 44×44 is measured as CSS
  pixels in a desktop browser, and every accessibility claim here is about what
  is *painted*, not what is *announced*.
* **`prefers-reduced-motion` and `prefers-contrast` were not exercised.**
* **The "fold" claims rest on one capture.** Every other shot uses a 1400px-tall
  viewport that no window has, chosen so one image carries enough of a long
  screen to be worth reading; `review-real-fold--1440x900-light.png` is the only
  capture at a realistic height and is the only evidence behind I5's
  above/below-the-fold wording.

---

## 5. Where the brief disagreed with the tree

Reported rather than silently adapted to, per this project's standing rule.

1. **"`LineItemsTable` has no `overflow-x` wrapper, so check what a narrow
   viewport does to it" — false.** The wrapper exists and works:
   `LineItemsTable.tsx` renders `<section className={styles.scroller}>`,
   `LineItemsTable.module.css` has `.scroller { max-width: 100%; overflow-x:
   auto }` and `.table { min-width: 44rem }`, and the stylesheet's own comment
   says a previous round reported it as unimplemented before it landed. In the
   browser at 375 the table scrolls and the page does not.
2. **"Confirm the two-column shell actually lands where intended" — it does.**
   `.screen > div` selects only the image pane at 1024 and 1440, and the
   `max-width: 1023px` block resets `grid-row`, `position` and `max-height`
   correctly. No defect found in the positional layout at any width.
3. **"The five ADR-0024 error states"** are not enumerated as five *states* in
   ADR-0024 — its Context names five *design-§5 rows that had not shipped*: no
   logout control, no return-to-receipt after a 401, no inline field errors, no
   distinct 503, no re-fetch after a 403/404. Those map to **six** on-screen
   states, and all six were captured: 503-with-held-task, 403-taken, 404-gone,
   400-inline-field, 401-to-login **and** 401-restored, plus the logout control
   and its unsaved-edits confirm, plus the non-503 load failure that *does*
   offer the Skip escape.
4. Everything else in the brief matched: the tip was `c781f40` with a clean
   tree, `playwright.config.ts` chains build → seed → serve, `outputDir` is
   under the git-ignored `var/`, the seed really does have no null column, no
   admin user, two severities and one queued task.

---

## 6. Reproducing this

```
cd frontend && npx playwright test visual
```

Takes about 60s after the ~30s build/seed/serve chain. It re-seeds every run
(`reuseExistingServer: false`), writes 97 PNGs plus `measurements.json` and
`captured.txt` to `var/e2e/visual/`, and **wipes that directory first** so a
stale image can never be read as current evidence.

Two things to know before touching it:

* **Nothing here approves, skips or completes a task**, so the one queued task
  in the fixture survives. `e2e/review.spec.ts` closes it, so a full-suite run
  (`npx playwright test`) drains the queue before this file's seeded test
  reaches it — that test then fails with a sentence saying exactly that rather
  than photographing the empty state and calling it a review screen.
* **Every stub is counted and asserted.** If a `page.route` glob stops
  matching — a path changes, a route moves — the run fails on `expectHits`
  instead of quietly capturing the real page.
