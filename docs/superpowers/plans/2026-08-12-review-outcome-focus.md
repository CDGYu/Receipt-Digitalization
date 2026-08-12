# Review Outcome Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close browser-pass finding I5 — make the outcome of a submit reach the reviewer, instead of rendering ~300px below the fold where a 403 or 404 produces no visible change at all.

**Architecture:** One `<section>` gathers everything that tells the reviewer what happened — the backend-down explanation, the summary alert, and the terminal or held card. It carries `tabIndex={-1}` and no role, and takes focus whenever it appears. The browser scrolls a focused element into view, so the fix rides on focus rather than on `scrollIntoView`, which does not exist in jsdom. The action buttons stay outside the region.

**Tech Stack:** React 19 + TypeScript + Vite, CSS Modules, Vitest/jsdom, Playwright for the ungated browser check.

Design: `docs/superpowers/specs/2026-08-12-review-outcome-focus-design.md`. Read it first.

## Global Constraints

- **The outcome region MUST be a `<section>`, never a `<div>`.** `ReviewScreen.module.css` carries `.screen > div { grid-column: 1; grid-row: 2 / span 4; position: sticky; ... }` and its own comment says that selector is "the image pane. It is the ONLY direct `<div>` child of" the screen. A new top-level `<div>` child silently becomes the sticky image pane.
- **The region carries NO `role`.** ADR-0024 decision 4 is a user ruling: a second alert in that region makes `findByRole('alert')` match two elements and throw, breaking pre-existing tests. The region is a focus target, not an announcement.
- **Focus NEVER goes to a button.** `ReviewScreen.tsx` records that when Approve and *Next receipt* shared a slot, React reused the node and a bare Enter advanced the queue, dismissing the warning unread.
- **The summary alert still renders in every failure case** (ADR-0024 decision 5). Wrapping must not make it conditional.
- **Terminal states keep exactly one exit and no retry** (ADR-0024 decision 3); Approve must not render in `lost` or `held`.
- **Do not use `scrollIntoView` and do not stub it.** Measured 2026-08-12: it is `undefined` in this repo's jsdom.
- **Any CSS change must update `CENSUS` in `frontend/tests/stylesheets.test.ts` in the same commit**, or the gated census test fails. Format: a keyword value records as `property: value`, anything else as bare `property`.
- **`python scripts/verify.py` exceeds a 2-minute tool timeout.** Background it, and make no edits while it runs.
- Frontend gates: `npm test` (Vitest), `npm run typecheck`, `npm run build`. **Vitest sets `css: false`**, so class names are unpinnable by rendering tests — guard CSS by reading the stylesheet as text.
- **Stage by explicit path, never `git add -A`.** Verify with `git diff --cached --stat` before committing.
- **The destructive-commands hook false-positives on reading config files via `cat`/`sed`.** Use the Read tool.
- **This plan's claims about existing artefacts were probed at `d2fffc0`, not recalled.** They can still be wrong. Read the real file before trusting any line here that describes one, and **report the discrepancy rather than working around it** — every plan defect across the last eleven milestones was the controller's.

## File Structure

| file | responsibility | task |
|---|---|---|
| `frontend/src/review/ReviewScreen.tsx` | the outcome region, and the effect that focuses it | 1 |
| `frontend/src/review/ReviewScreen.module.css` | `.outcome` — restores the spacing the wrapper would otherwise collapse | 1 |
| `frontend/tests/stylesheets.test.ts` | the `CENSUS` entry for `.outcome` | 1 |
| `frontend/tests/review-screen.test.tsx` | the focus pin and the containment pin | 1 |
| `docs/adr/0041-the-review-outcome-takes-focus.md` | **new.** The decision | 2 |
| `docs/adr/README.md` | index row and prose paragraph | 2 |
| `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` | I5's dated verdict line | 2 |

**Why the CSS is not optional.** `.screen` is a grid with `gap: var(--space-2xl)`, and today the explanation, the alert and the terminal card are three separate grid items with that gap between them. Wrapping them makes them one grid item and the internal spacing disappears. `.outcome` restores it with its own flex column and gap. `display: contents` was considered and rejected: an element with no box is a poor scroll target, which is the whole mechanism this fix rides on.

---

### Task 1: The outcome region takes focus

**Files:**
- Modify: `frontend/src/review/ReviewScreen.tsx`
- Modify: `frontend/src/review/ReviewScreen.module.css`
- Modify: `frontend/tests/stylesheets.test.ts` (the `CENSUS` entry only)
- Test: `frontend/tests/review-screen.test.tsx`

**Interfaces:**
- Consumes: the existing `Submit` state union in `ReviewScreen.tsx` — `{kind:'idle'} | {kind:'busy'} | {kind:'failed', message, openTaskId, failure} | {kind:'lost', flavor, message} | {kind:'held', outcome}`. Read it in the file rather than trusting this line.
- Produces: nothing other tasks import. Task 2 documents what this builds.

- [ ] **Step 1: Read the current render block**

Open `frontend/src/review/ReviewScreen.tsx` and find the `return (` whose first child is `<main className={styles.screen}>`. Today its tail renders, as five sibling expressions: the backend-down explanation, the summary alert, a three-way ternary (`lost` → terminal `<section>`, `held` → `<StoredDifferently>`, else → the Approve `<button>`), and the conditional `Close task` button.

**Confirm that shape before changing it.** If it differs, stop and report what you found.

- [ ] **Step 2: Write the failing tests**

Append to `frontend/tests/review-screen.test.tsx`. The harness below is the file's own — `stubApi`, `TASK`, `SUMMARY`, `RECEIPT`, `render(<StrictMode><ReviewScreen /></StrictMode>)`, `userEvent.keyboard('{Control>}{Enter}{/Control}')` — copied from the existing 403 and 400 tests rather than invented. **Confirm those names exist before relying on them.**

```tsx
// ---------------------------------------------------------------------------
// I5: the outcome reaches the reviewer
//
// Measured on `main` at 6f29aa5: Approve renders at y=1195, below the fold at
// 1440x900, 1440x800 and 1440x1080, with a two-line-item receipt and a 73px
// row pitch. The Ctrl/Cmd+Enter chord is a `window` listener, so it fires while
// the reviewer is typing at the top of the form -- and a 403 produced no
// visible change at all.
//
// jsdom performs no layout, so these pin the *mechanism*: focus moved, and the
// outcome is inside the thing that took focus. They cannot pin that anything
// was seen -- ADR-0029, and this task's Step 8.
// ---------------------------------------------------------------------------

describe('the outcome reaches the reviewer (I5)', () => {
  /** The region, by the two attributes the design fixes: a `<section>` because
   *  `.screen > div` is the image pane's positional selector, and `tabindex=-1`
   *  because it is a focus target rather than a control. */
  const regionOf = (): HTMLElement | null =>
    document.querySelector<HTMLElement>('section[tabindex="-1"]')

  /** A 403 on complete: the write landed and the task is gone. */
  const terminalRoutes = {
    '/review/next': [
      [200, { task: TASK, receipt: SUMMARY }],
      [200, { task: null }],
    ],
    'GET /receipts/a1': [200, RECEIPT],
    'PATCH /receipts/a1': [200, RECEIPT],
    '/review/t1/complete': [
      403,
      { error: { message: 'only the assignee or an admin may complete this task' } },
    ],
  } as const

  /** A 400 on the PATCH: the write was refused and the reviewer can retry. */
  const failedRoutes = {
    '/review/next': [[200, { task: TASK, receipt: SUMMARY }]],
    'GET /receipts/a1': [200, RECEIPT],
    'PATCH /receipts/a1': [400, { error: { message: "not a decimal amount: 'abc'" } }],
  } as const

  /** Render, then fire the chord from the form -- the path I5 describes. */
  async function arriveAt(routes: Parameters<typeof stubApi>[0]): Promise<void> {
    vi.stubGlobal('fetch', stubApi(routes))
    render(
      <StrictMode>
        <ReviewScreen />
      </StrictMode>,
    )
    await screen.findByLabelText('Total')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
  }

  it('takes focus when a submit resolves to a terminal state', async () => {
    await arriveAt(terminalRoutes)

    const notice = await screen.findByText('Saved, but this task was taken over by someone else')
    const region = regionOf()
    expect(region).not.toBeNull()
    expect(region!.contains(notice)).toBe(true)
    expect(document.activeElement).toBe(region)
  })

  it('takes focus when a submit fails', async () => {
    await arriveAt(failedRoutes)

    await screen.findByText(/not a decimal amount/)
    const region = regionOf()
    expect(region).not.toBeNull()
    expect(document.activeElement).toBe(region)
  })

  it('never lands focus on the exit button', async () => {
    // `Next receipt` sharing a slot with Approve is the failure
    // ReviewScreen.tsx already engineered away: a bare Enter advanced the queue
    // and dismissed the warning unread. Focusing it re-creates that on purpose.
    await arriveAt(terminalRoutes)

    const exit = await screen.findByRole('button', { name: 'Next receipt' })
    expect(document.activeElement).not.toBe(exit)
    // Asserted positively as well: `not.toBe(exit)` alone would also pass with
    // focus left on `body`, which is the defect.
    expect(document.activeElement).toBe(regionOf())
  })

  it('contains every outcome element, so a future one cannot render unfocused', async () => {
    await arriveAt(failedRoutes)

    const alert = await screen.findByRole('alert')
    const region = regionOf()
    expect(region).not.toBeNull()
    expect(region!.contains(alert)).toBe(true)
  })

  it('carries no role, so single-alert queries stay unambiguous', async () => {
    // ADR-0024 decision 4 is a user ruling: a second alert in this region makes
    // findByRole('alert') match two elements and throw.
    await arriveAt(failedRoutes)

    await screen.findByRole('alert')
    const region = regionOf()
    expect(region).not.toBeNull()
    expect(region!.getAttribute('role')).toBeNull()
  })
})
```

**One thing to expect and not to "fix":** these render inside `<StrictMode>`, which double-invokes effects in development. The focus effect will run twice. Focusing an already-focused element is a no-op, so this is harmless — but if you see a doubled call while debugging, that is why, and it is not a defect to engineer around.

- [ ] **Step 3: Run them to see them fail — and read WHY**

Run: `cd frontend && npx vitest run tests/review-screen.test.tsx`

Expected: the new tests FAIL because `section[tabindex="-1"]` does not exist yet — `region` is `null`.

**That is failure for the wrong reason.** It proves the selector matches nothing, not that focus is required. These become pins in Step 7, by mutation, and not before. Record the failure text.

- [ ] **Step 4: Add the outcome region**

In `ReviewScreen.tsx`, replace the five sibling expressions from Step 1 with the region plus the actions outside it.

Add the ref and the effect near the component's other hooks:

```tsx
  const outcomeRef = useRef<HTMLElement | null>(null)

  /** I5: the outcome renders at the end of a long document -- measured at
   *  y=1195, below the fold at 900, 800 and even 1080 -- and the Ctrl/Cmd+Enter
   *  chord is a `window` listener, so it fires while the reviewer is typing at
   *  the top of the form. Without this the reviewer's screen is identical
   *  before and after a 403, which is the case where the write landed and the
   *  task is gone.
   *
   *  Focus, not `scrollIntoView`: the browser scrolls a focused element into
   *  view by itself, and `scrollIntoView` is `undefined` in jsdom, so a scroll
   *  call would break every rendering test that reached this path.
   *
   *  Keyed on `submit.kind` so a resubmit that fails again (failed -> busy ->
   *  failed) moves focus a second time. An outcome the reviewer has already
   *  been shown is not the same as one they have not. */
  useEffect(() => {
    outcomeRef.current?.focus()
  }, [submit.kind])
```

Then the render tail:

```tsx
      {hasOutcome ? (
        // A <section>, never a <div>: `.screen > div` is the image pane's
        // positional selector and a new div child would become sticky.
        // No `role`: ADR-0024 decision 4 forbids a second alert here.
        <section ref={outcomeRef} tabIndex={-1} className={styles.outcome}>
          {submit.kind === 'failed' &&
          submit.failure.kind === 'backend-down' &&
          openTaskId === null ? (
            <p className={styles.explanation}>
              The database is unavailable — nothing can be saved right now.
            </p>
          ) : null}
          {submit.kind === 'failed' ? (
            <p className={styles.alert} role="alert">
              {submit.message}
            </p>
          ) : null}
          {submit.kind === 'lost' ? (
            <section className={styles.terminal} role="alert">
              <h2 className={styles.terminalHeading}>
                {submit.flavor === 'taken'
                  ? 'Saved, but this task was taken over by someone else'
                  : 'Saved, but this task no longer exists'}
              </h2>
              <p className={styles.message}>{submit.message}</p>
              <button
                type="button"
                className={styles.action}
                onClick={() => {
                  claimed.current = null
                  clearStash()
                  void load()
                }}
              >
                Next receipt
              </button>
            </section>
          ) : submit.kind === 'held' ? (
            <StoredDifferently outcome={submit.outcome} onAcknowledge={() => void load()} />
          ) : null}
        </section>
      ) : null}
      {submit.kind === 'lost' || submit.kind === 'held' ? null : (
        <button
          type="button"
          className={`${styles.action} ${styles.primary}`}
          onClick={() => void approve()}
          disabled={busy}
        >
          Approve (⌘↵)
        </button>
      )}
```

and define `hasOutcome` beside the other derived values:

```tsx
  /** The region exists when the reviewer has something to be told. Written as
   *  the *complement* of the two pending states rather than as a list of the
   *  three resolved ones, deliberately: a state added later defaults into the
   *  region and gets focus, so the failure mode is one focus move too many
   *  rather than an outcome that renders silently. */
  const hasOutcome = submit.kind !== 'idle' && submit.kind !== 'busy'
```

**Preserve the "different parent" property.** Approve is now a *sibling* of the region and *Next receipt* lives inside it, so the two are in different parents by construction — a stronger version of what the existing comment achieves with the ternary. Keep that comment, adjusting only what became inaccurate.

**No import change is needed.** Measured at `d2fffc0`: `ReviewScreen.tsx`'s first line is already `import { useCallback, useEffect, useRef, useState } from 'react'`. Re-read it rather than trusting this sentence; if it differs, that is a plan defect and I want it reported.

- [ ] **Step 5: Add the CSS and its census entry**

`ReviewScreen.module.css` — place `.outcome` beside the other outcome classes:

```css
/* The outcome region: everything that tells the reviewer what happened, in one
 * focusable box. It exists because `.screen` is a grid with a gap and these
 * were three separate grid items; collapsing them into one item would have
 * removed the spacing between them, so the gap is restored here.
 *
 * `display: contents` would have kept the children as grid items and needed no
 * gap at all, and was rejected: an element with no box is a poor scroll target,
 * and being scrolled to is the whole mechanism. */
.outcome {
  display: flex;
  flex-direction: column;
  gap: var(--space-2xl);
}
```

Then add the matching line to `CENSUS['review/ReviewScreen.module.css']` in `frontend/tests/stylesheets.test.ts`, in the same order the rule appears in the file:

```ts
    '.outcome': 'display: flex, flex-direction: column, gap',
```

**The format is not a guess:** a value matching `/^[a-z][a-z-]*$/` records as `property: value`, anything else as bare `property`. `flex` and `column` are keywords; `var(--space-2xl)` is not. `.terminal`'s existing entry is the worked example.

- [ ] **Step 6: Run the frontend gates**

```bash
cd frontend && npx vitest run && npm run typecheck && npm run build
```

Expected: all pass, including the five new tests and the census.

**If a pre-existing test fails, stop and report it rather than editing it.** The probe at `d2fffc0` found that the terminal card is queried by text and role, not by structure — so a wrapper should break nothing. `review-null-rule.test.tsx` is the file with structural queries (`parentElement`, `closest`, `querySelector`), but they target the form and the line-items table, not the outcome. If that probe was wrong, the plan is wrong and I want to know.

- [ ] **Step 7: Prove the pins red BY MUTATION — this step is the point of the task**

Step 3's failures proved nothing: a selector that matches nothing fails whatever the code does. Two single-variable mutations, each applied alone and reverted:

**Mutation A — remove the focus call.** Delete the body of the effect in `ReviewScreen.tsx`:

```tsx
  useEffect(() => {
    // MUTATION: focus call removed
  }, [submit.kind])
```

Run `npx vitest run tests/review-screen.test.tsx`. Expected: the two focus tests FAIL on `document.activeElement`, naming the region. Confirm the failure is an assertion about `activeElement` and **not** a null-region error — a null region means the mutation landed somewhere else (review standard 16). Revert; confirm green.

**Mutation B — move an outcome outside the region.** Move the summary alert `<p>` from inside the `<section>` to immediately after it, so it is a sibling rather than a child.

Run `npx vitest run tests/review-screen.test.tsx`. Expected: the containment test FAILS on `region.contains(alert)`. Revert; confirm green.

Record both mutations verbatim, their failure text, and confirmation of the reverts. Confirm the tree is clean afterwards with `git status --short`.

- [ ] **Step 8: Verify in a browser — the gates cannot see this defect**

jsdom performs no layout, so nothing above proves the reviewer sees anything. Measure it.

Create `frontend/e2e/_i5-check.spec.ts`, run it, record the numbers, then **delete it** — this is an acceptance measurement, not a permanent test. Playwright is not one of the five gates, and whether it should become one is an open backlog item nobody has ruled on.

```ts
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const MANIFEST = path.join(REPO_ROOT, 'var', 'e2e', 'seed.json')

test('I5: the outcome is in view after the chord', async ({ browser }) => {
  test.setTimeout(180_000)
  const seed = JSON.parse(fs.readFileSync(MANIFEST, 'utf8')) as {
    username: string
    password: string
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()

  await page.goto('/app/login')
  await page.getByLabel('Username').fill(seed.username)
  await page.getByLabel('Password').fill(seed.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('table')).toBeVisible({ timeout: 15_000 })

  // Type at the top of the form, then fire the chord from there -- the exact
  // path I5 describes.
  await page.getByLabel('Total', { exact: true }).fill('1234.56')
  await page.keyboard.press('Control+Enter')

  const region = page.locator('section[tabindex="-1"]')
  await expect(region).toBeVisible({ timeout: 15_000 })

  const box = await region.boundingBox()
  const view = await page.evaluate(() => ({ h: window.innerHeight, y: window.scrollY }))
  console.log(
    `\nI5-CHECK: regionTop=${box === null ? 'n/a' : Math.round(box.y)} ` +
      `viewportH=${view.h} scrollY=${Math.round(view.y)} ` +
      `inView=${box !== null && box.y >= 0 && box.y < view.h}`,
  )

  await context.close()
})
```

Run: `cd frontend && npx playwright test e2e/_i5-check.spec.ts`

**Expected: `inView=true`, and `regionTop` within the 900px viewport.** Before this task, the equivalent measurement put Approve at y=1195 with `scrollY=0`.

**If the outcome reached is not the one you expected** — the seeded receipt may resolve to `held` or a clean advance rather than a failure — report what state you reached and what it measured, rather than forcing the fixture. The measurement's job is to show the region comes into view, whichever outcome renders.

Then delete the file and confirm `git status --short` is clean.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/review/ReviewScreen.tsx frontend/src/review/ReviewScreen.module.css frontend/tests/review-screen.test.tsx frontend/tests/stylesheets.test.ts
git diff --cached --stat
git commit -m "fix: the review outcome takes focus, so a 403 is not invisible"
```

---

### Task 2: The decision, and I5's verdict

**Files:**
- Create: `docs/adr/0041-the-review-outcome-takes-focus.md`
- Modify: `docs/adr/README.md`
- Modify: `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`

**Interfaces:** none — documentation only. Depends on Task 1 shipping so the ADR describes what exists.

- [ ] **Step 1: Write ADR-0041**

Read `docs/adr/0040-what-field-accuracy-counts.md` for the house shape, which is (verified, not recalled):

```
# ADR 0041 — <title>

**Status:** Accepted (2026-08-12)
**Relates to:** ...

Derived <date> by <how>. **Re-derive rather than quote** (ADR-0028 rule 1).

## Context
## Decision
### 1. ...
## Consequences
## What this ADR does not decide
## References
```

It must record:

- **Context:** the measurement. Approve at y=1195; below the fold at 1440×900, ×800 and ×1080; 73px row pitch so it degrades with receipt length; the chord is a `window` listener so it fires from the top of the form. And that I5's original evidence was a single screenshot predating the styling milestone, which understated it.
- **Decision 1:** one outcome region, and the rule is structural — an outcome that appears takes focus. Record that `hasOutcome` is written as the complement of the pending states so a new state defaults *into* the region.
- **Decision 2:** focus goes to a non-interactive container, never to the exit button, with the muscle-memory reason.
- **Decision 3:** the region carries no role, extending rather than reopening ADR-0024 decision 4.
- **Decision 4:** focus rather than `scrollIntoView`, and the measured reason — `scrollIntoView` is `undefined` in jsdom.
- **Decision 5:** the region is a `<section>` because `.screen > div` is positional. Record this as a second reason to eventually replace that selector.
- **Consequences:** what a green `verify.py` now certifies (focus moved, outcomes contained) and what it still cannot (that anything was seen; how a screen reader behaves). Name the browser measurement as the other half of acceptance.
- **What this ADR does not decide:** I7; whether the everyday 1195px-deep Approve is itself a defect; whether Playwright becomes a sixth gate; whether `.screen > div` gets rewritten.

**Do not state a count of anything you have not derived at the moment of writing**, and prefer a symbol or quoted text to a line number — a citation is a claim, and this branch's predecessor aged two of them into pointing at unrelated code.

- [ ] **Step 2: Add the index row and paragraph**

In `docs/adr/README.md`, append to the table, matching the existing row format exactly:

```markdown
| [0041](0041-the-review-outcome-takes-focus.md) | The review outcome takes focus, so a 403 is not invisible | Accepted |
```

Then add a prose paragraph below the table in the style of the `**0040**` paragraph that precedes it.

**Check the table is still complete before you add to it:** `ls docs/adr/*.md | grep -v README | wc -l` against `grep -cE '^\| \[00[0-9][0-9]\]' docs/adr/README.md`. They were 40 and 40 at `d2fffc0`; if they disagree, say so — that table has silently fallen behind before.

- [ ] **Step 3: Give I5 its verdict line**

In `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`, the §3 status-note table has a row reading:

```
> | **I5** | **RE-TRIAGED TO CRITICAL, NOT FIXED** (user ruling, 2026-08-06). See its own entry. |
```

Update that row to record the fix, and append a dated verdict line to I5's own entry in the same style the fixed findings use (`***FIXED 2026-08-06 (`205d77a`).***` is the pattern — read one before writing).

**Do not rewrite I5's original text.** The report's own status note says findings keep their original text and each carries a dated verdict line. That includes the "below the fold at 1440×900" wording, which the measurement showed understated the defect — **record the correction in the verdict line rather than editing history.**

- [ ] **Step 4: Check every copy of the claim**

I5 is referenced in more than one place. Search for the *claim*, not the phrasing (ADR-0033 §2):

```bash
git grep -n "I5" -- docs
git grep -n "below the fold" -- docs
```

For each hit decide: a **historical record** (leave it) or a **live claim about how the screen behaves** (correct it). Report the list and the decision for each rather than editing silently.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/0041-the-review-outcome-takes-focus.md docs/adr/README.md docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md
git diff --cached --stat
git commit -m "docs: ADR-0041, and I5 gets its verdict"
```

---

## Final gate

- [ ] **Run the full gate runner**

Background it — it exceeds a 2-minute tool timeout — and **make no edits while it runs**:

```bash
python scripts/verify.py
```

Expected: all five PASS. **No pytest count is written here** — this milestone touches no Python, so the count should not move, but the number moves with every milestone and a number in a plan is a claim about a tree that has since changed. Run it.

Vitest should rise by the tests Task 1 adds. If `pytest` moved, something was edited outside scope; stop and report.

- [ ] **Confirm the deliverable from the built artefact, not from this plan**

```bash
cd frontend && npx vitest run tests/review-screen.test.tsx tests/stylesheets.test.ts
```

and confirm by reading the built output that the region ships:

```bash
npm run build && grep -c 'tabindex="-1"' dist/assets/*.js || echo "not found as a literal - check the JSX compiles to a prop, which is expected"
```

The grep is a weak check by design: React sets `tabIndex` as a property, so the literal may not appear. **The authoritative confirmation is Task 1 Step 8's browser measurement**, which is the only thing that observes the fix doing its job.

---

## Notes for the implementer

**The plan's claims about existing artefacts are the part that has historically been wrong** — every plan defect across eleven milestones was the controller's, and each was caught by someone who executed instead of trusting. **"This step's premise is false" is a valid and expected outcome**; report it with what you measured.

**Task 1 Step 7 is not optional.** Tests that have only ever failed by "selector matched nothing" are not pins. The mutations are what make them pins, and the failure has to name the right thing (review standards 14, 15, 16).

**Existing tests pass unmodified.** This plan authorises no edits to existing tests — only additions, plus one `CENSUS` entry. If something appears to require changing an existing test, stop and report: that would mean the wrapper changed behaviour, which it must not.

---

## Dated defect log

This plan is a historical record and **does not self-amend**: the task text above
stays as written and is corrected only here. Read this section before applying
any task block literally. Every entry was found by an implementer or reviewer
executing rather than reading; every one was the controller's.

### 2026-08-12 — Task 1's test fixtures omitted a route the test file warns about

`terminalRoutes` and `failedRoutes` as written omit `/receipts/a1/image`.
`ImagePane` renders its **own** `role="alert"` when the image link fails, so
`findByRole('alert')` matched two elements and threw before any implementation
existed.

**`review-screen.test.tsx` already documents this trap inline** — *"an unstubbed
image route makes ImagePane render an alert of its own, and the query then
matches two elements and throws"* — and the plan was written without reading it.

**Resolution:** both fixtures spread an `IMAGE` constant. Do not remove it.

### 2026-08-12 — Task 1 Step 8's browser spec could not reach the region

Filling a valid `1234.56` clean-advances the seeded queue: the region never
appears and the page shows "The review queue is empty." Run verbatim, the spec
fails rather than producing numbers.

**Resolution:** type something the server refuses (`abc`) so the submit resolves
to `failed`. That changes what the *reviewer types*, not the fixture — a user
action, not a fixture edit.

### 2026-08-12 — two smaller miscounts in Task 1

Step 1 says the render tail is "five sibling expressions" and then enumerates
four. Step 7 predicts Mutation A fails "the two focus tests"; it fails **three** —
`never lands focus on the exit button` also asserts `activeElement` positively,
because the controller tightened it during the pre-flight scan.

### 2026-08-12 — the design's two false claims, both dated-noted at source

Both were inherited by this plan's briefs and are corrected in
`docs/superpowers/specs/2026-08-12-review-outcome-focus-design.md`'s dated notes
and in ADR-0041, which carries the corrected copies:

1. **"That capture predates the styling milestone"** — false. The browser pass
   ran on `feat/review-ui-styling` at tip `c781f40`, and `bdbfd03` ("style the
   review screen…") is an *ancestor* of it. What the capture predates is
   `205d77a`, that milestone's own fix round.
2. **"a future outcome rendered as a sibling is a test failure"** — false, and
   the milestone's Critical. Measured: a role-less `<p>` sibling under
   `hasOutcome` leaves the suite at **372/372**. The claim reached four
   documents, including a test's own name, before anyone falsified it.
