# Design — three browser-pass findings, and what verifying them changed

**Date:** 2026-08-13
**Status:** proposed
**Closes:** browser-pass findings **I6**, **I8**, **I9**
**Deliberately excluded:** **I7** (touches ADR-0024's contract; needs a user ruling)

---

## 1. What this closes

`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` §3 has carried
I6, I7, I8 and I9 as open since the pass. I5 was taken as its own milestone and
closed by ADR-0041. This closes the three of the remainder that need no ruling
about scope or contract, and leaves I7 alone.

Each finding was re-derived against the tree before anything was designed
(ADR-0030). **Two of the three came back different from their written form**,
and both differences change what gets built. That is recorded in §2 rather than
folded silently into the fix, because a finding is a claim.

---

## 2. What verification changed

### 2.1 I6 is not "delete the rule that spans the row"

The finding names `ReceiptForm.module.css`'s `.form > p { grid-column: 1 / -1 }`
as the cause, and it is still there. But that file's own docblock records the
rule as *deliberate*:

> `.form > p` -- an inline error. It is a *sibling* of its label rather than a
> child (ADR-0024 §5: nesting it would pollute the field's accessible name), so
> in a grid it would otherwise land in the **next column's cell** instead of
> under the field it blames.

So the rule is not the defect; it is a repair for a worse defect. Removing it
trades a three-column offset for a one-column offset. The grid is
`repeat(auto-fill, minmax(11rem, 1fr))`, so the column count is a function of
viewport width — four at 1440, one at 375 — and **no CSS available here can say
"the column my previous sibling occupied"** when that count is dynamic. The fix
therefore has to be structural, which is why this milestone is architectural
rather than a stylesheet edit.

### 2.2 I6 touches two components, and one of them is shared

The error paragraph is rendered in two places, not the one the finding's
*Owning file* line names: `TextField` in `ReceiptForm.tsx`, and `MoneyInput` in
`MoneyInput.tsx`. Both return a fragment of `<label>` plus an optional
`<p role="alert">`.

**`MoneyInput` is also consumed by `LineItemsTable`**, three times, inside table
cells. Wrapping the error and its label *inside `MoneyInput`* would inject a
wrapper element into every money cell of the line-items table — a layout this
milestone is not targeting, on the table whose money columns were finding C1.
That is the trap this design exists to route around, and §3 does.

### 2.3 I9's "near the top-left" is no longer true

The finding reads:

> The block is also unframed — two bare paragraphs and a button near the
> top-left of an otherwise blank screen, with no card and no vertical centring.

`.notice` currently declares `max-width: 40rem` and `margin: 0 auto`. The block
is horizontally centred in a narrow column, not at the left. `bdbfd03` **created
this stylesheet** — the file does not exist at that commit's parent — so
`.notice` has been centred since it first existed, and that commit is dated the
same day as the pass. The report and the tree disagreed from close to the moment
it was written.

*(Derived by checking the parent, not by `git log -G "margin: 0 auto"`, which
matches two rules in this file — `.screen` and `.notice` — and so cannot
attribute either on its own. Standard 23: state the anchor beside the number.)*

**What remains true of that sentence:** there is no card — `.notice` declares no
`border`, no `background` and no `border-radius` — and there is no vertical
centring. Those two are fixed. The "top-left" half is a finding correction, and
is recorded in the browser-pass report rather than silently dropped.

### 2.4 I9's two render sites say the same sentence, and should not

The explanation is rendered twice in `ReviewScreen`, with identical text:

> The database is unavailable — nothing can be saved right now.

The two sites are reached in different states:

| Site | Reached when | Is the sentence apt? |
|---|---|---|
| The `failed` phase's notice | the **load** failed; no receipt is on screen | No. Nothing was being saved. |
| The submit block, gated `openTaskId === null` | the **submit** failed; the reviewer has edits on screen | Yes, and it is the only place it is. |

I9's complaint is that the explanation adds no plain language against this
message. On the load path it is worse than redundant: it answers a question
nobody asked. The identical wording is what hides that, and §5 splits it.

### 2.5 I8 is exactly as written

`StatTiles` renders four tiles — `Open backlog`, `In progress`, `Done`,
`Auto-approval rate` — under `aria-label="Queue statistics"`, and none of them
names a scope. `TaskTable`'s empty state does: *"No open tasks, and none
assigned to you"*. `AdminScreen` already computes the distinction, passing
`scope={isAdmin ? 'all' : 'mine'}` to the table while rendering the tiles
unconditionally.

`GET /metrics` depends on `require_user`, not `require_role(ROLE_ADMIN)`. **A
reviewer is deliberately authorized to see global counts**, so this is a
labelling defect and not an authorization one. Nothing in `src/` changes.

---

## 3. I6 — the wrapper goes at the call site

`ReceiptForm` wraps each field component's output in a grid cell. `TextField`
and `MoneyInput` are **not** modified:

```jsx
{TEXT_FIELDS.map(([path, label]) => (
  <div className={styles.fieldCell} key={path}>
    <TextField label={label} … />
  </div>
))}

{MONEY_FIELDS.map(([path, label]) => (
  <div className={styles.fieldCell} key={path}>
    <MoneyInput label={label} … />
  </div>
))}
```

`.fieldCell` becomes the grid item and stacks its two children:

```css
.fieldCell {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  min-width: 0;
}
```

`min-width: 0` is not decoration — it is what `.field` already carries, and
without it a long server message makes the cell refuse to shrink below its
content and blows the column out.

### 3.1 Why this placement and not inside the components

Three properties fall out of wrapping at the call site rather than inside
`TextField` and `MoneyInput`:

1. **`LineItemsTable` is untouched.** `MoneyInput` keeps returning a fragment,
   so no wrapper enters a table cell (§2.2).
2. **ADR-0024 §5 is satisfied unchanged.** The error stays a *sibling* of the
   `<label>` and never a child, so name-from-content still walks only the
   label's subtree and the field keeps its short accessible name.
   `aria-describedby` is an IDREF and needs no containment, so the wrapper is
   invisible to the accessibility tree.
3. **The grid keeps one item per field at every width.** The error is inside its
   field's cell, so it is under the field that sent it whether the form is one
   column or four.

### 3.2 What is deleted, and what is rewritten

`.form > p { grid-column: 1 / -1 }` matches nothing after this change: the
select and the two checkboxes have no error slot, which `ReceiptForm` records
in place —

> No error slot on the three below: `_coerce_legibility` and `_coerce_bool`
> cannot be reached from a closed option list or a checkbox.

— so no `<p>` remains a direct child of `.form`. The rule is **deleted**, not
left dead. `.form > h2` stays; the heading is still a direct child and still
spans.

The docblock's "The layout is selector-driven, because there is nowhere to hang
a class" section is rewritten, because this milestone gives it somewhere. Its
closing sentence — *"That coupling is the price of `className`-only, and it is
written down rather than left to be discovered"* — is the coupling being paid
off, and the replacement says so rather than deleting the history.

---

## 4. I8 — the tiles name their scope

`StatTiles` gains the scope it is rendering and says so once, on the region,
rather than four times across the labels. The visible caption and the region's
accessible name move together, so a screen-reader user and a sighted user get
the same qualification.

> **Dated note — 2026-08-13, from the plan's probe. Two corrections to the
> paragraph above; read them before re-deriving anything from it.**
>
> **The accessible name does not move.** Four tests in
> `frontend/tests/admin-screen.test.tsx` address the tiles by
> `getByRole('region', { name: 'Queue statistics' })`. Changing the region's
> accessible name breaks all four and buys nothing: a visible caption *inside*
> the region is announced as its first content, so a screen-reader user gets the
> qualification either way. `aria-label="Queue statistics"` therefore stays, and
> the caption is an element within the region. This keeps the milestone inside
> the standing bound that existing tests pass unmodified.
>
> **There is no scope to plumb.** `GET /metrics` calls `queue_stats(session)`
> with no user filter, so the tiles are global for every role, always — not
> "whatever scope this render happens to have". `StatTiles` needs **no new
> prop**; the caption is static and says the counts are global. Simpler than
> this paragraph implies, and the simplification is the accurate one.

This mirrors what §5.6 already did for the empty state, and that symmetry is the
argument: the screen currently names a scope in one of the two places it shows
counts, and the unqualified one is the one that reads as broken.

**Not done:** scoping the tiles' data per role. That would mean a scoped
`/metrics`, which is a backend contract change touching ADR-0026's privacy
property, to fix a defect that is entirely about words. `require_user` on that
route is a deliberate decision and this milestone does not revisit it.

---

## 5. I9 — two messages, and a card on one phase

### 5.1 The copy

ADR-0024 decision 4 is **unamended**. A distinct sentence still renders, still
carries no `role="alert"`, still sits beside the server's words. What changes is
that the sentence does the job the ADR says it exists for — adding plain
language the raw message lacks — at each of the two sites, which means the two
stop being identical.

- **Load path.** The reviewer cannot start. The server's words already say the
  database is unavailable; what they do not say is that nothing is wrong with
  their work and the queue is not lost.
- **Submit path.** The reviewer has edits on screen. What the server's words do
  not say — and what this is the only place to say — is that those edits are
  still there and nothing has been discarded.

Exact wording is settled in the implementation plan and reviewed there; the
constraint recorded here is that neither sentence may restate
*"the database is unavailable"*, because restating it is the defect.

> **Dated note — 2026-08-13, from the plan's probe. One existing test goes
> vacuous under this change and must move with it.**
>
> `a 503 on the close does not also claim nothing could be saved` asserts
> `queryByText('The database is unavailable — nothing can be saved right now.')`
> is `null`. That is a real pin today, because the string renders elsewhere. The
> moment §5.1 reworders both sites, **the string exists nowhere**, and the
> assertion passes because nothing can match it rather than because the
> suppression works. It would be green with the suppression deleted.
>
> The test must be re-pointed at the *new* submit-path sentence, and the
> re-pointed version proven red by deleting the `openTaskId === null` gate.
> This is review standard 15: a test that passes for the wrong reason proves
> nothing, and standard 14: a pin never proven red is not a pin.

### 5.2 The framing

`.notice` gains a card — border, `--color-surface`, radius — and vertical
centring.

**Scoped to the `failed` phase only.** `.notice` is the `<main>` for three
phases: `failed`, `empty` and `loading`. A card around *"Loading…"* is a
different screen from the one I9 measured, and widening a fix past its finding
is how this project has previously shipped changes nobody asked for. The card is
applied as an additional class on the failure render, leaving `empty` and
`loading` byte-identical.

---

## 6. Testing

TDD throughout. Each guarantee is revertible on its own (review standard 3), and
each mutation must be driven red for the *right reason* (standard 15).

| Guarantee | Pinned by | The mutation that must go red |
|---|---|---|
| The error is inside its field's cell | a rendering test asserting the error's parent is the field's wrapper, not `.form` | removing the wrapper puts the `<p>` back as a direct child of the grid |
| `.fieldCell` exists and stacks | the stylesheet census in `frontend/tests/stylesheets.test.ts` | deleting the declaration changes the census entry |
| `.form > p` is gone | the census | re-adding it restores an entry that must not be there |
| The tiles name their scope | a rendering test on the caption and the region's accessible name | dropping the caption |
| The two 503 sentences differ | a test asserting the load-path and submit-path texts are not equal | making them identical again |
| The card is on `failed` only | the census plus a render assertion on `empty`/`loading` | applying the card class unconditionally |

**Vitest sets `css: false`**, so a `.module.css` import returns a key-echoing
proxy and class names are unpinnable by rendering tests — a renamed class ships
as `class="undefined"` with every gate green. Anything asserting *which* class
carries a declaration goes through the stylesheet census, read as text. This is
ADR-0029's territory and the census is the only gate that can see it.

**What no gate here can see:** whether the result looks right. jsdom renders no
colour and no geometry, so the card, the centring and the error's position are
asserted structurally and confirmed by a person in a browser. ADR-0029 §4 is the
list; this milestone adds nothing to it and escapes none of it.

---

## 7. What this does not decide

- **I7** — a 401 mid-review swaps the screen for the login form with no message,
  and repaints restored edits identically to stored data. It touches ADR-0024's
  contract and needs a ruling. Untouched.
- **m10–m16**, every Minor from the pass. Untouched.
- **Whether the tiles should show a reviewer global counts at all.** The backend
  says yes, deliberately. Revisiting that is an ADR-0026 question.
- **The exact replacement wording** for the two 503 sentences, and for the tiles'
  scope caption — constrained here, chosen and reviewed in the plan.
- **`.notice`'s card for the `empty` and `loading` phases.** Deliberately out of
  scope; raisable separately if those screens want framing too.

---

## 8. Scope of the change

| File | Change |
|---|---|
| `frontend/src/review/ReceiptForm.tsx` | wrap each field in `.fieldCell`; rewrite the layout docblock |
| `frontend/src/review/ReceiptForm.module.css` | add `.fieldCell`; delete `.form > p`; rewrite the selector-driven docblock |
| `frontend/src/admin/StatTiles.tsx` | the region names its scope |
| `frontend/src/admin/StatTiles.module.css` | the caption's style |
| `frontend/src/review/ReviewScreen.tsx` | two distinct 503 sentences; card class on the `failed` render |
| `frontend/src/review/ReviewScreen.module.css` | the card; vertical centring |
| `frontend/tests/*` | the pins in §6, and the four copy assertions that move with §5.1 |
| `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` | dated verdicts on I6, I8, I9; the §2.3 correction |

**`src/` is untouched.** No route, no schema, no coercer. `MoneyInput.tsx` and
`LineItemsTable.tsx` are untouched, which §3.1 exists to guarantee.

**No ADR.** Nothing here amends a decision: ADR-0024 decision 4 keeps its
sentence and its ruling, ADR-0024 §5 keeps its sibling rule, ADR-0026 keeps its
scope, ADR-0027's tokens are used rather than extended. If the plan finds it
cannot hold that line, the finding is reported rather than the line crossed.
