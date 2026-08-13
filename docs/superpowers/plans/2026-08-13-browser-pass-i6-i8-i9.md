# Browser-pass I6, I8, I9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close browser-pass findings I6, I8 and I9 — the inline field error that
renders three grid columns from the field it blames, the admin tiles that
contradict the table beneath them, and the 503 that says one sentence twice in
two states where only one of them makes it apt.

**Architecture:** Three independent surfaces, no shared code. I6 wraps each
field at its call site in `ReceiptForm` so the error lands in its own grid cell,
leaving the shared `MoneyInput` untouched. I8 adds a static caption to the tiles
region. I9 splits one duplicated sentence into two site-appropriate ones and
gives the failure notice a card. Nothing under `src/` is touched and no ADR is
amended.

**Tech Stack:** React 19, TypeScript, CSS Modules, Vitest + Testing Library,
jsdom.

**Spec:** `docs/superpowers/specs/2026-08-13-browser-pass-i6-i8-i9-design.md`
— **read its two dated notes before re-deriving anything from its body.** They
correct §4 (the accessible name does not move; there is no scope to plumb) and
§5.1 (one existing test goes vacuous under the reword).

---

## Global Constraints

Every task's requirements implicitly include all of these.

- **ADR-0024 §5 — the inline error is a *sibling* of the `<label>`, never a
  child.** Nesting it pollutes the field's accessible name, because
  name-from-content walks the label's subtree. No task may move the `<p>` inside
  a `<label>`.
- **ADR-0024 decision 4 — the 503 explanation carries no `role="alert"`.** A
  standing user ruling. A second alert in one region makes `findByRole('alert')`
  match two elements and throw. **No task may add a role to that sentence.**
- **ADR-0024 §5 — the summary alert always renders.** Inline errors are
  additive and never replace it.
- **ADR-0027 — tokens only.** No raw hex outside `tokens.css`. Severity colours
  (error red, warn amber, info blue) are reserved and a statistics tile is not a
  severity.
- **ADR-0015 — money is a string.** No `<input type="number">`, no
  `valueAsNumber`. No task here should touch a money control's type, but
  `MoneyInput` is in the blast radius of Task 1 and this is the rule it lives
  under.
- **`MoneyInput.tsx` and `LineItemsTable.tsx` are NOT to be modified.** The
  design turns on this. `MoneyInput` is consumed three times by `LineItemsTable`
  inside table cells; a wrapper added inside `MoneyInput` reaches every money
  cell of the line-items table.
- **`src/` is not to be modified.** No route, no schema, no coercer.
- **Existing tests pass unmodified**, with exactly three named exceptions —
  assertions (a), (b) and (c) in Task 3 Step 1, plus the two comments and the
  one e2e assertion in Task 3 Step 5, all of which are listed there by name.
  Anything else that needs a test changed is a **stop-and-report**, not a fix.
- **Vitest sets `css: false`.** A `.module.css` import returns a key-echoing
  proxy, so class names are unpinnable by rendering tests — a renamed class
  ships as `class="undefined"` with every gate green. Anything asserting *which*
  class carries a declaration goes through `frontend/tests/stylesheets.test.ts`,
  which reads the stylesheet as text.
- **No `path:NNN` citations in any prose you write** (ADR-0028 §5). Quote text
  or name a symbol.

### Commands

```bash
# one test file (run from frontend/)
cd frontend && npx vitest run tests/receipt-form.test.tsx

# the whole frontend suite
cd frontend && npm test          # vitest run

# type check -- npm test does NOT type-check
cd frontend && npm run typecheck

# every gate; exceeds a 2-minute tool timeout, so background it,
# and do NOT edit source or tests while it runs
python scripts/verify.py
```

### Dispatch discipline (ADR-0023, as corrected 2026-08-06)

**Every task below has a deliberate RED phase, so tasks run strictly serially —
one at a time, never two in flight.** Two agents with disjoint file sets still
sabotage each other when one's plan has a RED phase and the other's definition
of done is a whole-suite result. Tasks 1, 2 and 4 additionally share
`frontend/tests/stylesheets.test.ts`, so they could not overlap regardless.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `frontend/src/review/ReceiptForm.tsx` | wraps each field in a grid cell; owns the layout docblock | 1 |
| `frontend/src/review/ReceiptForm.module.css` | adds `.fieldCell`; drops `.form > p` | 1 |
| `frontend/src/admin/StatTiles.tsx` | the tiles region and its scope caption | 2 |
| `frontend/src/admin/StatTiles.module.css` | the caption's style | 2 |
| `frontend/src/review/ReviewScreen.tsx` | two distinct 503 sentences; the card class on the failed render | 3, 4 |
| `frontend/src/review/ReviewScreen.module.css` | the card and vertical centring | 4 |
| `frontend/tests/receipt-form.test.tsx` | I6's behavioural pin | 1 |
| `frontend/tests/admin-screen.test.tsx` | I8's pin | 2 |
| `frontend/tests/review-screen.test.tsx` | I9's pins; the two re-pointed assertions | 3, 4 |
| `frontend/tests/stylesheets.test.ts` | the declaration census — the only gate that sees class names | 1, 2, 4 |
| `frontend/e2e/visual.spec.ts` | the Playwright scenario asserting the 503 sentence — **ungated**, `verify.py` does not run it | 3 |
| `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` | dated verdicts, and the §2.3 correction | 5 |

---

## Task 1: I6 — the error lands in its own field cell

**Files:**
- Modify: `frontend/src/review/ReceiptForm.tsx` (the two `.map` blocks, and the docblock's "The layout is selector-driven" section)
- Modify: `frontend/src/review/ReceiptForm.module.css` (add `.fieldCell`, delete `.form > p`)
- Modify: `frontend/tests/receipt-form.test.tsx` (add one test to `describe('inline field errors')`)
- Modify: `frontend/tests/stylesheets.test.ts` (the `'review/ReceiptForm.module.css'` census entry)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `styles.fieldCell`, a CSS-module class on `ReceiptForm.module.css`.
  No exported symbol changes. `TextField`'s and `MoneyInput`'s signatures are
  untouched, and no later task depends on this one.

- [ ] **Step 1: Write the failing test**

Add to `frontend/tests/receipt-form.test.tsx`, inside the existing
`describe('inline field errors', () => {` block (it already defines `FIELDS`):

```tsx
  it('renders the error inside its own field cell, not as a child of the grid', () => {
    render(
      <ReceiptForm
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'totals.total': "not a decimal amount: 'abc'" }}
      />,
    )
    const input = screen.getByLabelText('Total') as HTMLInputElement
    const description = document.getElementById(input.getAttribute('aria-describedby')!)!
    const label = input.closest('label')!

    // The error and its label share a wrapper, and that wrapper is not the grid
    // itself -- which is what puts the sentence under the field that sent it at
    // every column count. Before this task both were direct children of
    // `<section class="form">`, so the shared parent was the grid and the error
    // began at column 1 while Total sat at column 4.
    expect(description.parentElement).toBe(label.parentElement)
    expect(description.parentElement!.tagName).toBe('DIV')

    // ADR-0024 §5, unchanged and re-asserted here because this task moves the
    // element that rule is about: a sibling, never a child.
    expect(label.contains(description)).toBe(false)
  })
```

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```bash
cd frontend && npx vitest run tests/receipt-form.test.tsx
```

Expected: FAIL on `expect(description.parentElement!.tagName).toBe('DIV')` with
**`expected 'SECTION' to be 'DIV'`**.

**If it fails on the line above it instead** (`toBe(label.parentElement)`),
stop and report — that would mean the two are already in different parents and
the defect is not the one this task describes.

- [ ] **Step 3: Add the `.fieldCell` rule**

In `frontend/src/review/ReceiptForm.module.css`, add after the `.form > h2`
rule:

```css
/* One grid cell per field: the `<label>` and, when the server refused it, the
 * error paragraph that is its sibling (ADR-0024 §5). The cell is the grid item,
 * so the error is under the field that sent it at every column count -- which
 * `grid-column: 1 / -1` on the paragraph could not do, because it put the
 * sentence at column 1 while its field sat wherever auto-fill had placed it.
 *
 * `min-width: 0` for the reason `.field` carries it: without it a long server
 * message refuses to shrink below its content and blows the column out. */
.fieldCell {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  min-width: 0;
}
```

- [ ] **Step 4: Delete the rule that spans the row**

Delete these three lines from the same file:

```css
.form > p {
  grid-column: 1 / -1;
}
```

Nothing matches it after Step 5: the select and the two checkboxes have no error
slot, which `ReceiptForm` records in place — *"No error slot on the three below:
`_coerce_legibility` and `_coerce_bool` cannot be reached from a closed option
list or a checkbox."* Leave `.form > h2` alone; the heading is still a direct
child and still spans.

- [ ] **Step 5: Wrap each field at its call site**

In `frontend/src/review/ReceiptForm.tsx`, replace the two `.map` blocks inside
`<section className={styles.form}>`:

```jsx
      {TEXT_FIELDS.map(([path, label]) => (
        <div className={styles.fieldCell} key={path}>
          <TextField
            label={label}
            value={fields[path]}
            error={errors?.[path]}
            onChange={(value) => onChange(path, value)}
          />
        </div>
      ))}

      {MONEY_FIELDS.map(([path, label]) => (
        <div className={styles.fieldCell} key={path}>
          <MoneyInput
            label={label}
            value={fields[path]}
            error={errors?.[path]}
            onChange={(value) => onChange(path, value)}
          />
        </div>
      ))}
```

The `key` moves to the wrapper, which is now the mapped element. **Do not touch
`TextField` or `MoneyInput`** — they keep returning a fragment, which is what
keeps `LineItemsTable` unchanged.

- [ ] **Step 6: Rewrite the docblock section that this task falsifies**

`ReceiptForm.module.css`'s docblock opens *"The layout is selector-driven,
because there is nowhere to hang a class"* and explains `.form > p` as the
consequence. That is no longer true. Replace that section with one that says
each field is wrapped in `.fieldCell`, that the heading is still reached by
element because it is genuinely the only `<h2>`, and that the error is still a
sibling of its label for ADR-0024 §5's reason. Keep the `## Every input keeps
its visible label` section as it is.

Do not delete the history — the old section ends *"That coupling is the price of
`className`-only, and it is written down rather than left to be discovered."*
Say that the coupling has been paid off, rather than removing the evidence it
ever existed.

- [ ] **Step 7: Run the test and confirm it passes**

```bash
cd frontend && npx vitest run tests/receipt-form.test.tsx
```

Expected: PASS, including the three pre-existing `inline field errors` tests and
the line-item test, which must be untouched.

- [ ] **Step 8: Update the declaration census**

The census now disagrees with the stylesheet in two ways: `.form > p` is gone
and `.fieldCell` is new.

```bash
cd frontend && npx vitest run tests/stylesheets.test.ts
```

Expected: FAIL on `review/ReceiptForm.module.css declares exactly what the
census records`.

**Read the actual value out of the failure message and copy it into `CENSUS`** —
do not hand-write the declaration string. The census format is derived by
`censusFor`, and guessing which properties keep their value and which do not is
how a wrong entry gets committed. Delete the `'.form > p': 'grid-column',` line
and add the `.fieldCell` entry the failure names.

- [ ] **Step 9: Run the whole frontend suite and the type check**

```bash
cd frontend && npm test && npm run typecheck
```

Expected: both clean. `npm test` does not type-check, which is why both run.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/review/ReceiptForm.tsx frontend/src/review/ReceiptForm.module.css frontend/tests/receipt-form.test.tsx frontend/tests/stylesheets.test.ts
git commit -m "fix(ui): the inline error sits in its field's cell, not the grid's first column"
```

---

## Task 2: I8 — the tiles say whose counts they are

**Files:**
- Modify: `frontend/src/admin/StatTiles.tsx`
- Modify: `frontend/src/admin/StatTiles.module.css`
- Modify: `frontend/tests/admin-screen.test.tsx`
- Modify: `frontend/tests/stylesheets.test.ts`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `styles.caption` on `StatTiles.module.css`. **`StatTiles`'s props are
  unchanged** — it still takes `{ metrics }: { metrics: Metrics }` and gains no
  scope prop, because `GET /metrics` calls `queue_stats(session)` with no user
  filter and the counts are global for every role, always.

- [ ] **Step 1: Write the failing test**

Add to `frontend/tests/admin-screen.test.tsx`, beside the existing tests that
address the region:

```tsx
  it('says the tile counts are global, so they do not contradict a scoped table', () => {
    // The tiles come from `GET /metrics`, which is global; the table below is
    // scoped by role. Both are true, and a reviewer holding nothing saw
    // "Open backlog 9" directly above "No open tasks, and none assigned to
    // you". The empty state already names its scope; this is the other half.
    render(<StatTiles metrics={METRICS} />)

    const tiles = screen.getByRole('region', { name: 'Queue statistics' })
    expect(tiles.textContent).toContain('Across all reviewers')
  })
```

Put it in the `describe('design section 5.7 -- a rate that was never defined is
not zero')` block, where the four existing `Queue statistics` tests live. **They
render `<StatTiles metrics={…} />` directly inside each `it` — there is no
`beforeEach`** — so this one carries its own `render` call, exactly as written
above. `METRICS` is the fixture those four already use.

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```bash
cd frontend && npx vitest run tests/admin-screen.test.tsx
```

Expected: FAIL on the `toContain` — the region renders four tiles and no
caption.

**If it fails on `getByRole`**, stop and report: the region's accessible name
has moved, and four other tests in this file depend on it being exactly
`Queue statistics`.

- [ ] **Step 3: Add the caption**

In `frontend/src/admin/StatTiles.tsx`, inside the `<section>` and before the
first `<Tile>`:

```jsx
      <p className={styles.caption}>Across all reviewers</p>
```

**Leave `aria-label="Queue statistics"` exactly as it is.** The caption is
announced as the region's first content, so a screen-reader user gets the
qualification without the accessible name moving — and four existing tests
address the region by that name.

- [ ] **Step 4: Style the caption**

In `frontend/src/admin/StatTiles.module.css`:

```css
/* The counts above are global -- `GET /metrics` has no user filter -- while the
 * table below is scoped by role, so a reviewer holding nothing reads a backlog
 * of nine directly above "No open tasks, and none assigned to you". The empty
 * state names its scope already; this is the other half of that symmetry.
 *
 * Muted and small: it qualifies the figures, it is not one of them. Spanning
 * the grid so it reads as a heading for all four tiles rather than a label
 * belonging to the first. */
.caption {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--color-muted-foreground);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: 1.5;
}
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd frontend && npx vitest run tests/admin-screen.test.tsx
```

Expected: PASS, **including all four pre-existing `Queue statistics` tests**. If
any of those four now fails, the accessible name moved — revert Step 3 and
report.

- [ ] **Step 6: Update the census**

```bash
cd frontend && npx vitest run tests/stylesheets.test.ts
```

Expected: FAIL on `admin/StatTiles.module.css`. Copy the actual value from the
failure message into `CENSUS`; do not hand-write it.

- [ ] **Step 7: Run the whole frontend suite and the type check**

```bash
cd frontend && npm test && npm run typecheck
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/admin/StatTiles.tsx frontend/src/admin/StatTiles.module.css frontend/tests/admin-screen.test.tsx frontend/tests/stylesheets.test.ts
git commit -m "fix(ui): the queue tiles say their counts are global"
```

---

## Task 3: I9a — two sites, two sentences

**This task changes three existing test assertions. That is authorised here and
nowhere else in this plan.** Both are named in Step 1 and both must be proven
red before the implementation lands.

**Files:**
- Modify: `frontend/src/review/ReviewScreen.tsx` (the two `styles.explanation` paragraphs, **and the comment that quotes the old sentence**)
- Modify: `frontend/tests/review-screen.test.tsx`
- Modify: `frontend/e2e/visual.spec.ts` — **this one is not covered by any gate.**
  `scripts/verify.py` does not run Playwright, and says so: *"Not a gate: the
  Playwright acceptance run (`frontend/e2e`)"*. A green `verify.py` after this
  task is **not** evidence that this file is consistent. Step 5 is where it is
  reached, and skipping it ships a broken acceptance suite invisibly.

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: two distinct sentence texts, relied on by no later task. Task 4
  touches the same component but a different concern (the card class) and does
  not read these strings.

### The two sentences

Proposed wording. **Neither may restate "the database is unavailable"**, because
restating it is the defect I9 reports:

| Site | Condition | Sentence |
|---|---|---|
| the `failed` phase's notice | `backendDown` | `Your assigned tasks are unaffected — this is a server problem, not a change to your queue.` |
| the submit block | `submit.failure.kind === 'backend-down' && openTaskId === null` | `Your edits are still on this page and have not been discarded.` |

- [ ] **Step 1: Re-point the two existing assertions, and add the new pin**

In `frontend/tests/review-screen.test.tsx`, three edits.

**(a)** In the test that reads
`const sentence = await screen.findByText('The database is unavailable — nothing can be saved right now.')`
**on the submit path** (the one that follows a `{Control>}{Enter}` keyboard
submit and then asserts `getByRole('button', { name: 'Approve (⌘↵)' })`), change
the searched text to:

```tsx
      'Your edits are still on this page and have not been discarded.',
```

Leave `expect(sentence.getAttribute('role')).toBeNull()` and its comment exactly
as they are — that is ADR-0024 decision 4's pin and it is not what this task
changes.

**(b)** In `a 503 on load is backend-down and does NOT offer Skip`, change the
searched text to:

```tsx
      'Your assigned tasks are unaffected — this is a server problem, not a change to your queue.',
```

Again leave the role assertion and its comment untouched.

**(c)** In `a 503 on the close does not also claim nothing could be saved`,
change the `queryByText` argument to the **submit-path** sentence:

```tsx
    expect(
      screen.queryByText('Your edits are still on this page and have not been discarded.'),
    ).toBeNull()
```

**This edit is the point of the whole step.** As written, that assertion names a
string that will exist nowhere once the reword lands, so it would pass because
nothing can match it — green even with the `openTaskId === null` gate deleted.
Re-pointed, it pins the suppression again.

**Add no fourth test.** An earlier draft of this plan added one asserting that
the two sentence constants differ and that neither contains the server's words.
It was **removed at the pre-flight scan**: it compares two literals declared in
its own body, so it cannot fail against the application — it would pass with
both render sites deleted. Three tests that could not fail shipped on the
2026-08-12 branch and review caught all three; this plan does not add a fourth,
and "but it is labelled as vacuous" is not a defence.

The constraint it was reaching for — neither sentence may restate *"the database
is unavailable"* — is enforced by (a) and (b), which assert the real rendered
text, and is recorded in the design doc. **If you find yourself wanting to pin
the constraint more directly, stop and report rather than inventing an assertion
over constants.**

- [ ] **Step 2: Run and confirm the two re-pointed assertions fail**

```bash
cd frontend && npx vitest run tests/review-screen.test.tsx
```

Expected: FAIL. **(a)** and **(b)** fail on `findByText` — *"Unable to find an
element with the text"* — because the new sentences do not render yet. **(c)**
**passes** at this point, and that is expected: the old string is gone from the
test but the app still renders it, so `queryByText` of the new string is
correctly null.

- [ ] **Step 3: Prove (c) can fail, before trusting it**

Temporarily change the submit-block condition in
`frontend/src/review/ReviewScreen.tsx` from

```jsx
          submit.failure.kind === 'backend-down' &&
          openTaskId === null ? (
```

to

```jsx
          submit.failure.kind === 'backend-down' ? (
```

and also apply Step 4's copy change, then run the file again. **(c) must fail.**
Restore the `openTaskId === null` gate immediately afterwards.

A pin never proven red is not a pin (review standard 14), and this one has just
been re-pointed at a string that did not exist a moment ago — exactly the shape
that passes for the wrong reason.

- [ ] **Step 4: Write the two sentences**

In `frontend/src/review/ReviewScreen.tsx`, replace the text of the `failed`
phase's explanation:

```jsx
        {backendDown ? (
          <p className={styles.explanation}>
            Your assigned tasks are unaffected — this is a server problem, not a
            change to your queue.
          </p>
        ) : null}
```

and the text of the submit block's explanation:

```jsx
            <p className={styles.explanation}>
              Your edits are still on this page and have not been discarded.
            </p>
```

**Change only the text.** Both keep `className={styles.explanation}`, both keep
their absence of `role`, both keep their surrounding conditions, and both keep
the comments above them — those comments record ADR-0024 decision 4's ruling and
the `openTaskId` reasoning, and neither has stopped being true.

Note the em dash in the load-path sentence is the same `—` used throughout this
codebase. Use the Read/Write/Edit tools rather than a PowerShell
`Get-Content`/`Set-Content` round-trip, which mangles em dashes on this machine.

- [ ] **Step 5: Reach the three sites no gate watches**

The sentence appears in **eight** places, and Steps 1 and 4 reach five of them.
Derive the list yourself rather than trusting this one — it was measured on
2026-08-13 with:

```bash
git grep -n "nothing can be saved right now" -- frontend/
```

The three remaining:

1. **`frontend/e2e/visual.spec.ts`** asserts
   `page.getByText('nothing can be saved right now')` is visible. Re-point it at
   whichever of the two new sentences that scenario actually reaches — read the
   surrounding scenario to find out which; do not guess. **No gate will tell you
   if you get this wrong**, so verify by reading the scenario's setup.
2. **The comment in `frontend/src/review/ReviewScreen.tsx`** above the submit
   block, which reads *"Unsuppressed, a 503 on the close renders 'nothing can be
   saved right now' directly above 'Saved, but the task is still open: database
   unavailable'"*. Its reasoning is still correct; only the quoted string is
   stale. Update the quotation.
3. **The comment in `frontend/tests/review-screen.test.tsx`** inside
   `a 503 on the close does not also claim nothing could be saved`, which quotes
   the same old sentence for the same reason. Update the quotation.

A citation is a claim (review standard 21): closing a prose defect ages every
sentence that quoted it, and a comment quoting a string the code no longer
contains is exactly that.

- [ ] **Step 6: Run and confirm all three pass**

```bash
cd frontend && npx vitest run tests/review-screen.test.tsx
```

Expected: PASS, all of (a), (b), (c) and the new test, plus every other test in
the file unmodified.

- [ ] **Step 7: Confirm the old sentence is gone everywhere**

```bash
git grep -n "nothing can be saved right now" -- frontend/
```

Expected: **no output.** A non-empty result names a site Steps 4 and 5 missed.

- [ ] **Step 8: Run the whole frontend suite and the type check**

```bash
cd frontend && npm test && npm run typecheck
```

Note this still says nothing about `frontend/e2e/`. Step 7's grep is the only
check in this task that covers it.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/review/ReviewScreen.tsx frontend/tests/review-screen.test.tsx frontend/e2e/visual.spec.ts
git commit -m "fix(ui): the 503 explanation says something the server's words do not"
```

---

## Task 4: I9b — a card on the failure notice, and only there

**Files:**
- Modify: `frontend/src/review/ReviewScreen.tsx` (the `failed` phase's `<main>`)
- Modify: `frontend/src/review/ReviewScreen.module.css`
- Modify: `frontend/tests/review-screen.test.tsx`
- Modify: `frontend/tests/stylesheets.test.ts`

**Interfaces:**
- Consumes: nothing from Task 3, though it edits the same component.
- Produces: `styles.noticeFailed`, applied only on the `failed` render.

- [ ] **Step 1: Write the failing test**

Add to `frontend/tests/review-screen.test.tsx`. Because Vitest sets
`css: false`, the class *names* echo back as their keys, which is exactly what
makes this assertable at the DOM level:

```tsx
  it('frames the failure notice, and leaves the loading and empty screens bare', async () => {
    // I9's second half: the failure block was two paragraphs and a button on an
    // otherwise blank page. `.notice` is the <main> for `failed`, `empty` and
    // `loading` alike, so the frame is an additional class on the failure
    // render -- a card around "Loading..." is a screen this finding never
    // measured, and widening a fix past its finding is its own defect.
    const fetchMock = stubApi({
      '/review/next': [200, { task: TASK, receipt: SUMMARY }],
      'GET /receipts/a1': [503, { error: { message: 'database unavailable' } }],
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
    await screen.findByRole('alert')
    const main = document.querySelector('main')!
    expect(main.className).toContain('noticeFailed')
  })
```

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```bash
cd frontend && npx vitest run tests/review-screen.test.tsx
```

Expected: FAIL — the `<main>` carries only `notice`.

- [ ] **Step 3: Add the card**

In `frontend/src/review/ReviewScreen.module.css`:

```css
/* The failure notice only. `.notice` is the <main> for the loading and empty
 * phases too, and a card around "Loading..." is a different screen from the one
 * finding I9 measured. Composed rather than overridden, so the loading and
 * empty renders keep exactly the declarations they had.
 *
 * `min-height` with `justify-content: center` is the vertical centring the
 * finding names; `.notice` already supplies the horizontal half via
 * `max-width` and `margin: 0 auto`. */
.noticeFailed {
  justify-content: center;
  min-height: 60vh;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}
```

- [ ] **Step 4: Apply it to the failure render only**

In `frontend/src/review/ReviewScreen.tsx`, in the `phase.kind === 'failed'`
branch:

```jsx
      <main className={`${styles.notice} ${styles.noticeFailed}`}>
```

**Leave the `empty` and `loading` renders exactly as they are** — both keep
`className={styles.notice}` alone.

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd frontend && npx vitest run tests/review-screen.test.tsx
```

Expected: PASS, and every other test in the file unchanged.

- [ ] **Step 6: Update the census**

```bash
cd frontend && npx vitest run tests/stylesheets.test.ts
```

Expected: FAIL on `review/ReviewScreen.module.css`. Copy the actual value from
the failure message into `CENSUS`.

- [ ] **Step 7: Run the whole frontend suite and the type check**

```bash
cd frontend && npm test && npm run typecheck
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/review/ReviewScreen.tsx frontend/src/review/ReviewScreen.module.css frontend/tests/review-screen.test.tsx frontend/tests/stylesheets.test.ts
git commit -m "fix(ui): frame the failure notice, and only the failure notice"
```

---

## Task 5: the browser-pass report gets its verdicts

**Files:**
- Modify: `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`

**Interfaces:** none. Documentation only.

- [ ] **Step 1: Add dated verdicts to the status-note table**

That table at the head of §3 already carries `| I6, I7, I8, I9 | **OPEN**,
unchanged. |`. Split it: I6, I8 and I9 get **FIXED 2026-08-13** with a one-line
statement of what changed, and I7 stays **OPEN**. Follow the form the C1/C2/C3
and I5 rows already use.

- [ ] **Step 2: Correct I9's stale half**

I9's body reads *"two bare paragraphs and a button near the top-left of an
otherwise blank screen, with no card and no vertical centring."* Add a dated
correction, in the style the report already uses for its other corrected
sentences: the block has been horizontally centred since `bdbfd03` created
`ReviewScreen.module.css`, which carries `max-width: 40rem` and `margin: 0 auto`
— so **"near the top-left" was never true of the shipped stylesheet**. The "no
card" and "no vertical centring" halves were true and are what Task 4 fixed.

Correct it **in place, keeping the original text**, exactly as the report's
other dated corrections do. Do not rewrite the finding.

- [ ] **Step 3: Note what I6's fix actually was**

I6's body names `.form > p { grid-column: 1 / -1 }` as the cause. Add a dated
line recording that the rule was a *repair* rather than the defect — without it
the error lands in the next column's cell — and that the fix was a per-field
wrapper at the call site in `ReceiptForm`, which left `MoneyInput` and
`LineItemsTable` untouched.

- [ ] **Step 4: Run every gate**

```bash
python scripts/verify.py
```

Background it; it exceeds a 2-minute tool timeout. **Do not edit source or tests
while it runs** — a backgrounded run during an edit once reported a `FAIL build`
on a `TS6133` that no longer existed, and a phantom failure looks exactly like a
real one.

Expected: all five PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md
git commit -m "docs: dated verdicts for I6, I8 and I9, and I9's stale half"
```

---

## What this plan does not do

- **I7.** It touches ADR-0024's contract and needs a user ruling. Untouched.
- **m10–m16**, every Minor from the pass. Untouched.
- **A browser pass.** jsdom renders no colour and no geometry, so nothing here
  is evidence that the result *looks* right. The card, the centring and the
  error's new position need a person at 1440×900 and 375. ADR-0029 §4 is the
  list of what a green `verify.py` cannot see, and this milestone escapes none
  of it.
- **The handoff pair.** `docs/MEMORY.md` and `docs/NEXT_SESSION_PROMPT.md` are
  refreshed at session end, in a commit touching nothing else (ADR-0033 §1).
  No task above may touch them.
