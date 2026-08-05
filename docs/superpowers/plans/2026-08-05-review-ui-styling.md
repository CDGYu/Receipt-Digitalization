# Review UI Styling & Admin Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the review UI its first stylesheet, add the `/app/admin` surface over the two backend routes that already exist, and put a human in front of both in a real browser.

**Architecture:** CSS Modules over one `tokens.css`, light default with a full dark theme, self-hosted Fira Sans/Fira Code. No new runtime dependency: routing is a pathname switch, not React Router. No backend change — every route this consumes already ships.

**Tech Stack:** React 19.2.7, Vite 8.1.1, TypeScript 6.0.2, Vitest 4.1.10, Playwright (installed). CSS Modules are native to Vite; nothing is added to `dependencies`.

**Design:** `docs/superpowers/specs/2026-08-05-review-ui-design-system.md` — read §2 (three overrides of the generated system), §4 (null ≠ zero ≠ empty) and §9 (the four rulings) before Task 1.

## Global Constraints

- **ADR-0015** — money is a string end to end. **`<input type="number">` and `valueAsNumber` are banned**; use `type="text"` + `inputMode="decimal"`. No `CORSMiddleware`. SPA pages stay under `/app/*` and **no API path moves**.
- **ADR-0024** — **exactly one `role="alert"` region on screen**: the summary alert, which always renders. The backend-down sentence deliberately has none — a second alert makes the suite's single-alert queries ambiguous, and that is a recorded user ruling. Inline field errors are **additive**, never a replacement. The stash never touches browser storage.
- **ADR-0026** — a reviewer and an admin get different row sets from one endpoint. **The empty state must name its scope**, or a reviewer reads a scoped-empty list as a broken queue.
- **ADR-0012** — the confidence breakdown is persisted, and `NULL` ("not recorded") ≠ `[]` ("nothing lowered the score").
- **ADR-0017** — `npm test` does **not** type-check. Every task runs `npm run typecheck` **and** `python scripts/verify.py`.
- **Design §4 is a hard rule:** `null` must never render as `0`, and neither may render as blank. Three distinct treatments, and it is pinned by test.
- **Never colour alone.** Severity, confidence band and task state each carry an icon **and** a word.
- **Contrast ≥ 4.5:1** for body text in both themes. `--color-muted-foreground` is `#475569` in light, not `#94A3B8` (~2.8:1, fails).
- **No CDN fonts.** Vendor woff2 into the repo — the service runs on a LAN and the suite is offline.
- **`prefers-reduced-motion: reduce` → no transitions.** Motion is 150ms `ease-out`, only for state a user caused.
- Vitest is **221 passing across 19 files** at `333a3f1`; pytest **979**. Styling must not change either count except by tests this plan adds.
- **The working tree is CRLF.** Confirm `git diff --stat` is non-empty *and lands where you meant* before believing any mutation.
- **`pyproject.toml:61` sets `addopts = "-q"`** — use bare `python -m pytest`. `scripts/verify.py` exceeds a 2-minute tool timeout; run it in the background.

---

## Task 1: Tokens, fonts, and the theme switch

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/assets/fonts/` (four vendored woff2 files)
- Modify: `frontend/src/main.tsx` (import `tokens.css` once)
- Create: `frontend/tests/tokens.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: every CSS custom property in design §3, available globally. Tasks 2-4 consume these names and **must not introduce raw hex**.

- [ ] **Step 1: Vendor the fonts**

Download the woff2 files for **Fira Sans** (400, 500, 600) and **Fira Code** (400, 500) into `frontend/src/assets/fonts/`. Latin subset is sufficient. Do **not** add a Google Fonts `@import` or `<link>` — design §2.3 records why: the service runs on a LAN and the suite is offline, so a CDN import renders fallback fonts exactly where the app is deployed.

- [ ] **Step 2: Write `tokens.css`**

```css
@font-face {
  font-family: 'Fira Sans';
  src: url('../assets/fonts/FiraSans-Regular.woff2') format('woff2');
  font-weight: 400; font-style: normal; font-display: swap;
}
/* …repeat for FiraSans 500/600 and FiraCode 400/500… */

:root {
  --font-sans: 'Fira Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --font-mono: 'Fira Code', ui-monospace, 'Cascadia Mono', Consolas, monospace;

  --text-xs: 0.75rem;  --text-sm: 0.875rem; --text-base: 1rem;
  --text-lg: 1.125rem; --text-xl: 1.5rem;   --text-2xl: 2rem;

  --space-xs: 2px;  --space-sm: 4px;  --space-md: 8px;  --space-lg: 12px;
  --space-xl: 16px; --space-2xl: 24px; --space-3xl: 32px;

  --radius-sm: 4px; --radius-md: 8px; --radius-lg: 12px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,.05);
  --shadow-md: 0 4px 6px rgba(0,0,0,.1);

  /* Light is the default theme (design §2.2). */
  --color-background: #F8FAFC;
  --color-surface: #FFFFFF;
  --color-surface-raised: #FFFFFF;
  --color-foreground: #0F172A;
  --color-muted-foreground: #475569;
  --color-border: #E2E8F0;
  --color-primary: #0F172A;
  --color-ring: #2563EB;
  --color-severity-error: #DC2626;
  --color-severity-warn: #B45309;
  --color-severity-info: #1D4ED8;
  --color-positive: #15803D;
  --color-null: #64748B;
}

:root[data-theme='dark'] {
  --color-background: #020617;
  --color-surface: #0E1223;
  --color-surface-raised: #1A1E2F;
  --color-foreground: #F8FAFC;
  --color-muted-foreground: #94A3B8;
  --color-border: #334155;
  --color-primary: #F8FAFC;
  --color-ring: #60A5FA;
  --color-severity-error: #EF4444;
  --color-severity-warn: #F59E0B;
  --color-severity-info: #60A5FA;
  --color-positive: #22C55E;
  --color-null: #64748B;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme='light']) { /* …same dark block… */ }
}

body {
  margin: 0;
  background: var(--color-background);
  color: var(--color-foreground);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: 1.5;
}

:where(a, button, input, select, textarea):focus-visible {
  outline: 2px solid var(--color-ring);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}
```

`:root:not([data-theme='light'])` in the media query is load-bearing: it lets an explicit light choice win over an OS dark preference, while an unset preference still follows the OS.

- [ ] **Step 3: Import it once**

In `frontend/src/main.tsx`, add `import './styles/tokens.css'` above the app render. One import, at the entry — not per-component.

- [ ] **Step 4: Write the token test**

```ts
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8')

describe('tokens.css', () => {
  it('defines every token the design system names', () => {
    for (const token of [
      '--font-sans', '--font-mono', '--color-background', '--color-surface',
      '--color-foreground', '--color-muted-foreground', '--color-border',
      '--color-ring', '--color-severity-error', '--color-severity-warn',
      '--color-severity-info', '--color-positive', '--color-null',
    ]) {
      expect(css).toContain(token)
    }
  })

  it('ships a dark theme for every colour the light theme defines', () => {
    const light = [...css.matchAll(/^\s*(--color-[\w-]+):/gm)].map((m) => m[1])
    const darkBlock = css.slice(css.indexOf("[data-theme='dark']"))
    for (const token of new Set(light)) {
      expect(darkBlock, `${token} has no dark value`).toContain(token)
    }
  })

  it('never reaches the network for a font', () => {
    // A CDN @import renders fallback fonts exactly where this app is deployed
    // (LAN, offline suite) -- design section 2.3.
    expect(css).not.toMatch(/@import\s+url\(\s*['"]?https?:/)
    expect(css).not.toContain('fonts.googleapis.com')
  })

  it('respects prefers-reduced-motion', () => {
    expect(css).toContain('prefers-reduced-motion')
  })
})
```

- [ ] **Step 5: Run, then prove each test can fail**

```
cd frontend && npx vitest run tokens
```

Then three separate single-guarantee mutations, each reverted before the next (review standard 3): delete one `--color-*` from the dark block → test 2 red naming that token; add `@import url('https://fonts.googleapis.com/x')` → test 3 red; delete the `prefers-reduced-motion` block → test 4 red. **Read each failure** — if a test dies for a reason other than the one it exists for, the mutation changed more than one thing (standard 15).

- [ ] **Step 6: Gates and commit**

```
cd frontend && npm run typecheck && npm test
cd .. && python scripts/verify.py
```

```bash
git add frontend/src/styles frontend/src/assets/fonts frontend/src/main.tsx frontend/tests/tokens.test.ts
git commit -m "feat(ui): add design tokens, self-hosted fonts, and the light/dark themes"
```

---

## Task 2: Primitives — and the null rule

**Runs after Task 1** (consumes its tokens). **Tasks 3 and 4 both consume this task**, so it must land before either.

**Files:**
- Create: `frontend/src/ui/Value.tsx` + `Value.module.css`
- Create: `frontend/src/ui/Button.tsx` + `Button.module.css`
- Create: `frontend/src/ui/Chip.tsx` + `Chip.module.css`
- Modify: `frontend/src/review/MoneyInput.tsx` (+ new `MoneyInput.module.css`)
- Create: `frontend/tests/value.test.tsx`

**Interfaces:**
- Consumes: `tokens.css` custom properties.
- Produces:
  ```tsx
  // The null/zero/empty rule, in one place. Design §4.
  export function Value({ value, kind }: {
    value: string | null
    kind: 'money' | 'text' | 'count'
  }): JSX.Element

  export function Button(props: {
    variant: 'primary' | 'secondary' | 'danger'
    // …native button props
  }): JSX.Element

  export function Chip({ tone, icon, children }: {
    tone: 'error' | 'warn' | 'info' | 'positive' | 'neutral'
    icon: JSX.Element
    children: React.ReactNode
  }): JSX.Element
  ```

- [ ] **Step 1: Write the null-rule test first**

```tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Value } from '../src/ui/Value'

afterEach(cleanup)

describe('Value — null is not zero, and neither is empty', () => {
  it('renders a null money value as an em dash, never a number', () => {
    render(<Value value={null} kind="money" />)
    const el = screen.getByLabelText('not extracted')
    expect(el.textContent).toBe('—')
    // The prime directive reaching the last inch: a null total rendered as
    // 0.00 would destroy the system's central safety property on the one
    // screen where a human decides.
    expect(el.textContent).not.toBe('0')
    expect(el.textContent).not.toBe('0.00')
    expect(el.textContent).not.toBe('')
  })

  it('renders an extracted zero as a real number, distinct from null', () => {
    render(<Value value="0.00" kind="money" />)
    expect(screen.getByText('0.00')).toBeTruthy()
    expect(screen.queryByLabelText('not extracted')).toBeNull()
  })

  it('gives null and zero different accessible names', () => {
    const { container: a } = render(<Value value={null} kind="money" />)
    const { container: b } = render(<Value value="0.00" kind="money" />)
    expect(a.textContent).not.toBe(b.textContent)
  })
})
```

- [ ] **Step 2: Run it and confirm it fails for the right reason**

```
cd frontend && npx vitest run value
```

Expected: **3 failed**, all on the module not existing — not on an assertion.

- [ ] **Step 3: Implement `Value`**

```tsx
import styles from './Value.module.css'

export function Value({ value, kind }: {
  value: string | null
  kind: 'money' | 'text' | 'count'
}) {
  if (value === null) {
    return (
      <span className={styles.null} aria-label="not extracted">
        —
      </span>
    )
  }
  return <span className={kind === 'text' ? styles.text : styles.numeric}>{value}</span>
}
```

```css
/* Value.module.css */
.numeric {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.text { font-family: var(--font-sans); }
.null {
  font-family: var(--font-mono);
  color: var(--color-null);
  border-left: 2px solid var(--color-null);
  padding-left: var(--space-sm);
}
```

The hairline left border is the scannability half of design §4: a reviewer finds every gap in the form without reading a single value.

- [ ] **Step 4: Restyle `MoneyInput` without changing its contract**

Add `MoneyInput.module.css` and apply it. **Read the existing component first.** Do not change its props, its value handling, or its `type`. It must remain `type="text"` with `inputMode="decimal"` — ADR-0015 bans `type="number"` and `valueAsNumber`, and a number input silently reformats and strips leading zeros. Right-align, `--font-mono`, tabular figures. The currency symbol is a static prefix **outside** the input so it is never part of the editable string.

- [ ] **Step 5: Green, then prove the null pin fails**

```
cd frontend && npx vitest run
```

Then mutate `Value` to `return <span>{value ?? '0.00'}</span>` — the exact defect the rule exists to prevent. Expected: all three null tests red, the first on `'0.00' !== '—'`. Read the failures; restore from a byte copy.

- [ ] **Step 6: Gates and commit**

```
cd frontend && npm run typecheck && npm test
cd .. && python scripts/verify.py
```

```bash
git add frontend/src/ui frontend/src/review/MoneyInput.tsx frontend/src/review/MoneyInput.module.css frontend/tests/value.test.tsx
git commit -m "feat(ui): add Value, Button and Chip primitives, and pin null-is-not-zero"
```

---

## Task 3: Style the review screen

**Runs after Task 2.** Touches only `frontend/src/review/*` and its own stylesheet — **no file overlap with Task 4**, so the two may run in either order once Task 2 lands.

**Files:**
- Create: `*.module.css` beside each of `ReviewScreen`, `ReceiptForm`, `LineItemsTable`, `ConfidenceRail`, `FindingsPanel`, `ImagePane`
- Modify: those six `.tsx` files — **`className` only**
- Modify: `frontend/src/SignOutControl.tsx` (+ its module CSS)

**Interfaces:**
- Consumes: `Value`, `Button`, `Chip` from Task 2; tokens from Task 1.
- Produces: no new exports. This task adds no behaviour.

- [ ] **Step 1: Read the ADR-0024 contract before touching anything**

Read `docs/adr/0024-review-ui-error-recovery-contract.md` and `frontend/tests/review-screen.test.tsx`. **The single-`role="alert"` rule is the constraint most likely to be broken by styling**: adding `role="alert"` to a styled error box, or wrapping the summary in a live region, makes the suite's single-alert queries ambiguous and breaks six pre-existing tests. That happened once already, in the milestone that wrote this contract.

- [ ] **Step 2: Add stylesheets and `className`s, one component at a time**

Per design §5: two-column shell (image left, form right) collapsing to one column under 1024px; `LineItemsTable` with fixed column widths so the decimal column does not shift while editing, wrapped in `overflow-x: auto`; `ConfidenceRail` bands each carrying an icon **and** a word; `FindingsPanel` as a disclosure list with `rule_id` in `--font-mono`; `ImagePane` on a neutral `#F1F5F9` surround so the receipt's own white edge stays visible.

**Change no JSX except `className`.** If a component needs restructuring to be styleable, stop and report it rather than reshaping markup the tests assert against.

- [ ] **Step 3: Run the full frontend suite after each component**

```
cd frontend && npm test
```

Expected: **221 passing, unchanged**, after every component. A drop means the styling moved markup the tests depend on. Do not proceed past a red.

- [ ] **Step 4: Prove the alert contract is still intact**

```
cd frontend && npx vitest run review-screen
```

Then add a second `role="alert"` to the backend-down sentence — the exact violation ADR-0024 forbids. Expected: the single-alert queries go ambiguous and multiple tests fail. **Read them**: this confirms the contract is still load-bearing after restyling. Restore from a byte copy.

- [ ] **Step 5: Gates and commit**

```
cd frontend && npm run typecheck && npm test
cd .. && python scripts/verify.py
```

```bash
git add frontend/src/review frontend/src/SignOutControl.tsx frontend/src/SignOutControl.module.css
git commit -m "feat(ui): style the review screen without touching its error contract"
```

---

## Task 4: The `/app/admin` surface

**Runs after Task 2.** No file overlap with Task 3.

**Files:**
- Create: `frontend/src/admin/AdminScreen.tsx`, `TaskTable.tsx`, `StatTiles.tsx` (+ module CSS each)
- Create: `frontend/src/api/admin.ts`
- Create: `frontend/src/route.ts`
- Modify: `frontend/src/main.tsx`, `frontend/src/session.ts`
- Modify: `frontend/vite.config.ts` — **the stale route comment only**
- Create: `frontend/tests/admin-screen.test.tsx`

**Interfaces:**
- Consumes: `Value`, `Button`, `Chip`; `request` from `api/client.ts`.
- Produces:
  ```ts
  // api/admin.ts
  export async function fetchMe(): Promise<{ username: string; role: string }>
  export async function fetchTasks(params?: { state?: string; limit?: number; offset?: number }):
    Promise<{ items: ReviewTaskSummary[]; has_more: boolean }>
  export async function releaseTask(taskId: string):
    Promise<{ released_from: string | null }>
  // route.ts
  export function currentRoute(): 'login' | 'review' | 'admin'
  ```

- [ ] **Step 1: Fix the stale route comment in `vite.config.ts`**

Its comment at `:14-23` claims to be "Cross-checked against every route `create_app` registers" and **is missing three**: `GET /auth/me`, `GET /review/tasks`, and `POST /review/{id}/release`. Verified by:

```bash
git grep -oh '@app\.\(get\|post\|patch\)("[^"]*"' -- src/receipts/review/api.py | sed 's/.*("//' | sort
git grep -oh '@router\.\(get\|post\)("[^"]*"' -- src/receipts/review/auth.py | sed 's/.*("//' | sort
```

The functional `API_PREFIXES` array is fine — it matches by prefix, and `/auth` and `/review` are both listed — so this is a false comment, not a broken proxy. Add the three missing lines. Re-run the two commands above and confirm every route now appears.

- [ ] **Step 2: Write the route switch**

```ts
// route.ts — a pathname switch, deliberately not React Router.
// Runtime deps are exactly react + react-dom; the backend already serves a
// history fallback (_SpaFiles(..., html=True), api.py:856), so /app/admin
// survives a reload without a router. Design §9 ruling 4.
export function currentRoute(): 'login' | 'review' | 'admin' {
  const path = window.location.pathname
  if (path === '/app/login') return 'login'
  if (path.startsWith('/app/admin')) return 'admin'
  return 'review'
}
```

- [ ] **Step 3: Write the failing admin tests**

Cover, with mocked `fetch`: an admin sees a task assigned to someone else and can release it; **the empty state names its scope** (a reviewer sees "No open tasks, and none assigned to you"; an admin sees "No tasks") — ADR-0026, because a reviewer must not read a scoped-empty list as a broken queue; `assigned_to: null` renders `—` and not blank; and `auto_approval_rate: null` renders `—` and not `0%`.

- [ ] **Step 4: Run them and read the failures**

```
cd frontend && npx vitest run admin
```

Expected: all fail on the modules not existing.

- [ ] **Step 5: Implement, widen `session.ts`, wire the switch**

`session.ts` gains an identity (`{username, role} | null`) alongside its boolean, hydrated from `GET /auth/me` on mount. **Keep its existing module-scope 401 handler registration** — the docstring at `session.ts:3-20` records why it cannot move into an effect. `main.tsx` renders by `currentRoute()`; the admin route renders nothing but a "not authorised" message for a non-admin, since the backend is the real gate.

- [ ] **Step 6: Green, then prove the scope-aware empty state fails**

Mutate the empty state to a single shared "No tasks" string. Expected: the reviewer-scope test goes red on its own assertion. Read it; restore from a byte copy.

- [ ] **Step 7: Gates and commit**

```
cd frontend && npm run typecheck && npm test
cd .. && python scripts/verify.py
```

```bash
git add frontend/src/admin frontend/src/api/admin.ts frontend/src/route.ts frontend/src/main.tsx frontend/src/session.ts frontend/vite.config.ts frontend/tests/admin-screen.test.tsx
git commit -m "feat(ui): add the /app/admin surface, and correct vite's stale route list"
```

---

## Task 5: The browser pass — the one nobody has ever done

**Runs last.** This is the task that closes the standing gap: **two UI milestones shipped without any human opening a browser.**

**Files:**
- Create: `frontend/e2e/visual.spec.ts`
- Create: `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` (the findings write-up)

- [ ] **Step 1: Build and serve against a real database**

```bash
python scripts/seed_review_e2e.py --reset
npm --prefix frontend run build
python scripts/serve_review_e2e.py
```

`serve_review_e2e.py` **fails loudly if the dist is missing** rather than silently skipping the SPA mount, so a missing build cannot be mistaken for a styling problem.

- [ ] **Step 2: Capture every surface, both themes, three widths**

Write `frontend/e2e/visual.spec.ts` capturing screenshots at **375, 1024, 1440px**, in light **and** dark, for: login; the review screen with a receipt that has null fields; the review screen with findings at all three severities; each of the five ADR-0024 error states; the admin surface with tasks; and the admin surface empty, as a reviewer.

**Screenshots are the deliverable, not an assertion.** Do not add pixel-diff baselines in this task — a first-ever visual pass has nothing to diff against, and a baseline captured from unreviewed output would pin whatever is wrong.

- [ ] **Step 3: Look at them. Actually look.**

Write up what is wrong in `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`. Check specifically:

- Is a **null field** visibly different from a zero? (design §4 — the whole point)
- Is the **money column** aligned on the decimal at every width?
- Do **severity colours** survive dark mode at 4.5:1?
- Does anything **scroll horizontally** at 375px?
- Are **focus rings** visible on every interactive element, in both themes?
- Do the five error states **read as sentences a reviewer can act on**?
- Is the **receipt image** legible against its surround?

- [ ] **Step 4: Report, do not silently fix**

Findings go in the write-up with severity. Anything Critical or Important comes back as a fix round on the task that owns the file. **Do not fix them inside this task** — the whole value of a browser pass is an independent look, and a pass that quietly repairs what it finds leaves no record of what was wrong.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/visual.spec.ts docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md
git commit -m "test(e2e): capture every surface in a browser, and record what it looks like"
```

---

## Task 6: ADR-0027 and the spec absorption

**Runs last, after Task 5's findings are known.**

**Files:**
- Create: `docs/adr/0027-review-ui-design-system.md`
- Modify: `docs/adr/README.md`

ADR-0027 records four load-bearing decisions: **light default with dark available** (and why — the reviewer's reference truth is a photograph of white paper); **CSS Modules + one `tokens.css`**, no new runtime dependency; **a pathname switch rather than React Router**, keeping runtime deps at two; and **`null` ≠ `0` ≠ empty as a rendering invariant**, with the test that pins it named.

It must also record what the browser pass found, because that is the first evidence this project has about how any of its UI actually looks.

Re-read the prose under `docs/adr/README.md`'s table — it quantifies over the ADR list (review standard 12).

---

## Plan self-review

**Spec coverage.** Design §3 tokens → Task 1. §4 null rule → Task 2 (implementation + pin) and Task 5 (visual confirmation). §5.1 MoneyField → Task 2 Step 4. §5.2-5.5 → Task 3. §5.6-5.7 → Task 4. §5.8 error states → Task 3 Step 4 (contract) and Task 5 (appearance). §6 accessibility → distributed, verified in Task 5. §7 motion → Task 1 Step 2. §9 rulings 1-4 → Tasks 1, 1, 5, 4 respectively.

**Placeholder scan.** No TBD. Task 1's `@font-face` block is abbreviated with an explicit "repeat for" rather than a placeholder. Task 3 deliberately does not enumerate every `className` — the design doc specifies the appearance and the task specifies the constraint (`className` only); enumerating them would be transcription, not instruction.

**Type consistency.** `Value`'s signature is identical in Task 2's Interfaces block and its Step 3 implementation. `currentRoute()`'s three return values match `main.tsx`'s switch. `fetchTasks`' return shape matches `ReviewTaskListResponse` (`items` + `has_more`) exactly.

**Dispatch lanes (ADR-0023).** Task 1 → Task 2 → {Task 3 ∥ Task 4} → Task 5 → Task 6. Tasks 3 and 4 share **no file**: Task 3 owns `frontend/src/review/*` and `SignOutControl`; Task 4 owns `frontend/src/admin/*`, `route.ts`, `api/admin.ts`, `main.tsx`, `session.ts`, `vite.config.ts`. They may run in either order, but **not in parallel unless a controller confirms that separation still holds at dispatch time** — `main.tsx` is the one file a careless Task 3 might reach for.

**Three things this plan cannot promise.**

- **Task 1's font files are a manual download.** No step can fetch them offline, and no test can prove the vendored file *is* Fira Sans rather than a renamed placeholder. The test proves only that no CDN is referenced.
- **Task 5's findings are unknown by construction.** Its budget is a guess, and if it returns Critical findings the milestone grows a fix round it has not planned for. That is the correct trade for a first look.
- **Vitest's 221 must not move in Task 3.** If styling forces a markup change that breaks a test, the plan is wrong and the task should stop and report rather than editing the test to match — those tests encode a contract two milestones paid for.
