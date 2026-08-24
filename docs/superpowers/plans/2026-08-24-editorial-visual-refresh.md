# Editorial Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the app the Editorial visual system the owner chose — a cooled-neutral ground, real elevation, a generous spacing scale and a grotesque display face — and then have a person look at it in a browser, because no gate in this repo can.

**Architecture:** Almost all of this is **values on token names that already exist**, so it touches components barely. Four new token names are added (`--space-4xl`, `--space-5xl`, `--text-3xl`, `--font-display`), one new self-hosted font package is installed, and each screen adopts the new display face on its heading, the new spacing on its container, and the now-distinct raised surface on its panels. The last task is not code: it is the browser pass of design decision 14.

**Tech Stack:** CSS Modules over one `tokens.css`; `@fontsource` (self-hosted, never a CDN); Vitest + jsdom for the unit gates; Playwright for the browser pass.

**Spec:** `docs/superpowers/specs/2026-08-23-upload-and-visual-refresh-design.md` — §5 (decisions 12–14), §6, §7.

**Read before Task 1:** that document carries **four dated corrections** — under §0, §3, §4 and §7. The first three record things the design asserted that the tree does not contain: an invented timing figure, a drop zone and file list that were deliberately never built, and a narration sequence the pipeline never emits. None of those three governs this plan's work; read them so you inherit the caution, not the claims. **The fourth does govern it** — it was written on 2026-08-24 alongside this plan, and it is the gate correction summarised in the next section.

## Global Constraints

- **`@fontsource` only; never a CDN, never an `@import url(https://…)`.** ADR-0027 decision 3. `tokens.test.ts` pins both the absence of the CDN form and the presence of every weight's import in `src/main.tsx`.
- **Severity colours are reserved and do not move.** `--color-severity-error`, `--color-severity-warn`, `--color-severity-info` and `--color-positive` keep their exact current values. ADR-0027 decision 2 rejected an amber-primary palette on the ground that "if amber is the brand colour, a WARN finding has no colour left."
- **Every colour token must be a plain six-digit `#RRGGBB`.** No `rgb()`, no `color-mix()`, no `var()` alias. `stylesheets.test.ts` asserts this explicitly, because anything else makes its luminance arithmetic return `NaN` and `NaN >= 4.5` is false — the check would pass by accident.
- **The three theme blocks stay exactly three, with exactly those selectors**, and the two dark blocks stay **declaration-for-declaration identical**. `tokens.test.ts` pins both.
- **The 4.5:1 floor is a real gate, not a guideline.** See below.
- **Light default.** ADR-0027 decision 1. No theme toggle is added.
- **Stage by explicit path. Never `git add -A`.**
- **Do not touch** `eval/`, `src/receipts/`, or anything outside `frontend/` and `docs/`.

## What the design got wrong about its own gates, and what is actually true

Design §7 says `frontend/tests/stylesheets.test.ts` "pins declarations by name and is silent on values", and concludes that **every** colour in this refresh can change with all five gates green. **Measured against the file on 2026-08-24, that is half right, and the wrong half will bite an implementer who believes it.**

| what | gated? | by what |
|---|---|---|
| a token's **value** appearing in the census | **no** | custom properties are recorded by name only |
| a **new** declaration in any rule | **yes** | `censusFor(file)` must equal the `CENSUS` entry |
| a colour token that is not `#RRGGBB` | **yes** | `stylesheets.test.ts`, explicit assertion |
| `color` + `background` **in one rule**, below 4.5:1 | **yes**, in all three theme blocks | "clears the floor for every colour painted on a background in the same rule" |
| a `color` token with no background, on `--color-background` or `--color-surface` | **yes**, in all three theme blocks | `INHERITABLE_SURFACES` |
| the same token on `--color-surface-raised`, `--color-surface-active` or `--color-surface-sunken` | **NO** | those three are not in `INHERITABLE_SURFACES` |
| spacing, radii, type sizes, shadows — any quantity | **no** | nothing reads them |
| how any of it looks | **no** | `css: false`, jsdom lays nothing out |

So the honest statement is: **the ramp's brightness is gated and its hue is not.** A palette that breaks readability goes red; a palette that is ugly, incoherent, or the wrong temperature ships green. Task 6 is the only thing that can see the second kind.

**This constrains the design more than the design knew.** The reserved severity colours already sit near the floor: `--color-severity-error` `#DC2626` measures **4.62:1** on today's `--color-background` `#F8FAFC`, and `--color-null` measures **4.55:1**. That is 0.12 and 0.05 of headroom. **The background therefore cannot get darker** — it can only change hue at roughly constant luminance. Every value in Task 1 was chosen under that constraint and measured, not picked.

## File Structure

| file | what happens to it |
|---|---|
| `frontend/package.json`, `package-lock.json` | gain `@fontsource/archivo` |
| `frontend/src/styles/tokens.css` | the light ramp, warmer shadows, 4 new tokens |
| `frontend/src/main.tsx` | two new font-weight imports |
| `frontend/tests/tokens.test.ts` | `TOKENS` 35 → 39; the two new font imports pinned; a new pin that raised ≠ surface |
| `frontend/tests/stylesheets.test.ts` | `CENSUS` updated for every rule that gains a declaration |
| `frontend/src/upload/*.module.css` | hero path: display face, spacing, elevation |
| `frontend/src/review/*.module.css` | the review cluster |
| `frontend/src/login/`, `receipts/`, `admin/` | the remaining screens |
| `frontend/e2e/visual.spec.ts` | a fourth width for the browser pass |
| `docs/adr/0052-*.md` (new), `docs/adr/0027-*.md` | decision 13's ADR, and its dated correction |

---

### Task 1: The token layer and the display face

**Files:**
- Modify: `frontend/package.json` (add one dependency)
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/main.tsx:14-18` (the `@fontsource` import block)
- Modify: `frontend/tests/tokens.test.ts` (`TOKENS`, the font-weight pin, one new test)
- Modify: `frontend/tests/stylesheets.test.ts` (`CENSUS['styles/tokens.css'][':root']`)

**Interfaces:**
- Produces: `--font-display`, `--text-3xl`, `--space-4xl`, `--space-5xl`, and a light ramp in which `--color-surface-raised` is no longer equal to `--color-surface`. Tasks 2–5 consume all five facts and introduce no raw hex.

**Values, all measured. Use these verbatim.**

Light block (`:root`) — the ramp in full. **Eight of these nine values change**; `--color-surface` is already `#FFFFFF` and is listed only so the ramp reads as a whole. (This said "every changed line, and only these" until 2026-08-24, which made it a nine-change claim and was wrong by one.)

```css
  --color-background: #FAFAF9;
  --color-surface: #FFFFFF;
  --color-surface-raised: #FFFDF9;
  --color-surface-sunken: #F4F3F0;
  --color-foreground: #1C1B19;
  --color-muted-foreground: #57534E;
  --color-border: #E4E1DB;
  --color-primary: #1C1B19;
  --color-null: #78716C;
```

**Unchanged in the light block, deliberately:** `--color-surface-active` `#EFF6FF` (tied to `--color-ring`; ADR-0027 forbids amber here), `--color-ring` `#2563EB`, and all four reserved severity/positive colours.

**The dark blocks do not change at all.** Ruling, with its cost stated: every dark value is backed by a browser measurement, and one of them — `--color-null: #7C8CA2` at 5.43:1 — is the subject of a recorded correction and a pinned arithmetic control. Re-tinting dark would invalidate four recorded measurements to buy coherence in the theme the demo will not use. **Cost if wrong:** the two themes have different temperaments; Task 6 will show it, and the fix is one line per token.

New tokens and retuned shadows:

```css
  --text-3xl: 2.5rem;
  --space-4xl: 48px;
  --space-5xl: 64px;
  --font-display: 'Archivo', 'Fira Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --shadow-sm: 0 1px 2px rgba(28,27,25,.06);
  --shadow-md: 0 6px 16px rgba(28,27,25,.10);
```

Place `--font-display` beside `--font-sans`, `--text-3xl` after `--text-2xl`, and `--space-4xl`/`--space-5xl` after `--space-3xl`, so the census entry stays in readable source order.

- [ ] **Step 1: Install the display face**

```bash
cd frontend && npm install @fontsource/archivo
```

Verified 2026-08-24: the package is on the registry at 5.3.0 and ships `600.css` and `700.css` as separate weight entrypoints. Two subset weights is what design §5 asks for; do not import the variable package and do not import `index.css` (it pulls every weight).

- [ ] **Step 2: Write the failing pin for the thing decision 12 exists to fix**

Nothing in the tree would notice `--color-surface-raised` being reverted to `#FFFFFF` — which is the exact flatness this refresh is for. Add to `frontend/tests/tokens.test.ts`, inside the `describe('tokens.css', …)` block:

```ts
  it('gives the light theme a raised surface that is actually raised', () => {
    // The flatness this refresh removes was in the tokens, not the components:
    // --color-surface-raised and --color-surface were both #FFFFFF, so nothing
    // in light mode could sit above anything. Both values are read from the
    // file, so this cannot pass by agreeing with a constant it also supplies.
    const light = declarations(block(LIGHT))
    const raised = light.get('--color-surface-raised')
    const surface = light.get('--color-surface')
    expect(raised, '--color-surface-raised is not declared in the light block').toBeDefined()
    expect(surface, '--color-surface is not declared in the light block').toBeDefined()
    expect(raised).not.toBe(surface)
  })
```

- [ ] **Step 3: Run it and read why it fails**

Run: `cd frontend && npx vitest run tests/tokens.test.ts`

Expected: this one test FAILS, both values being `#FFFFFF`. **Two other tests in this file are expected to fail as well** once Step 4 lands, and one of them fails *now* if you reordered anything — `TOKENS.length` is pinned at 35. Read every failure reason rather than matching the count: a plan's RED prediction in this repo has been wrong more often than not.

- [ ] **Step 4: Apply the token changes**

Edit `frontend/src/styles/tokens.css` with the values above. Then:

- `frontend/src/main.tsx`, after the Fira imports:
  ```ts
  import '@fontsource/archivo/600.css'
  import '@fontsource/archivo/700.css'
  ```
- `frontend/tests/tokens.test.ts`: add `'--font-display'` to the typography group of `TOKENS`, `'--text-3xl'` after `'--text-2xl'`, `'--space-4xl'` and `'--space-5xl'` after `'--space-3xl'`; change `expect(TOKENS.length).toBe(35)` to `toBe(39)`; add both Archivo specifiers to the `self-hosts every weight` list.

- [ ] **Step 5: Re-derive the census entry mechanically**

Do **not** hand-transcribe it — the census header says so, and hand-transcription is how a census drifts from the file it guards. Print what the parser actually sees and paste that:

```bash
cd frontend && npx vitest run tests/stylesheets.test.ts -t 'declares exactly what the census records' 2>&1 | head -60
```

The failure message prints the received value for `styles/tokens.css`. Copy the `:root` string from the *received* side into `CENSUS`. Expect exactly four new names in it and no other difference; if anything else moved, stop and find out why before pasting.

- [ ] **Step 6: Run the frontend gates**

Run: `cd frontend && npx vitest run && npm run typecheck`

Expected: PASS. The contrast checks are the ones that matter here — if any pair reds, the message names the token, the surface and the theme block. Do not "fix" it by lightening the background further without re-measuring every reserved colour against the new value.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/styles/tokens.css frontend/src/main.tsx frontend/tests/tokens.test.ts frontend/tests/stylesheets.test.ts
git commit -m "feat(ui): the Editorial token layer, on a measured ramp"
```

---

### Task 2: The hero path — upload and processing

These two screens are what an audience sees first, and design §6 does not list them: it was written before they existed. They are in scope.

**Files:**
- Modify: `frontend/src/upload/UploadScreen.module.css`
- Modify: `frontend/src/upload/ProcessingView.module.css`
- Modify: `frontend/tests/stylesheets.test.ts` (both census entries)

**Interfaces:**
- Consumes: `--font-display`, `--text-3xl`, `--space-4xl`, `--color-surface-raised`, `--shadow-md` from Task 1.

- [ ] **Step 1: Apply the refresh to `UploadScreen.module.css`**

- `.screen` (line ~36): `padding: var(--space-2xl)` → `var(--space-4xl) var(--space-2xl)`
- `.heading` (line ~49): `font-size: var(--text-2xl)` → `var(--text-3xl)`, and add `font-family: var(--font-display);` immediately before `font-size`
- `.field` (line ~90): `background: var(--color-surface)` → `var(--color-surface-raised)`, and add `box-shadow: var(--shadow-md);` immediately after `background`
- `.alert` (line ~76): leave `--color-surface`. An alert is not a raised object; it is a message on the page.

- [ ] **Step 2: Apply the same three moves to `ProcessingView.module.css`**

- `.screen` (line ~43): `padding: var(--space-2xl)` → `var(--space-4xl) var(--space-2xl)`
- `.heading` (line ~56): `font-size` → `var(--text-3xl)`, add `font-family: var(--font-display);` before it
- `.receipt` (line ~79): `background: var(--color-surface)` → `var(--color-surface-raised)`, add `box-shadow: var(--shadow-md);` after `background`

- [ ] **Step 3: Re-derive both census entries**

As Task 1 Step 5, mechanically from the received value. Each rule that gained a declaration gains exactly that name, in source order.

- [ ] **Step 4: Run the gates**

Run: `cd frontend && npx vitest run && npm run typecheck`

Expected: PASS. If a contrast pair reds here it means `--color-surface-raised` now carries text that `--color-surface` did not — read the message, it names the rule.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/upload frontend/tests/stylesheets.test.ts
git commit -m "feat(ui): the hero path adopts the display face and real elevation"
```

---

### Task 3: The review cluster

**Files:**
- Modify: `frontend/src/review/ReviewScreen.module.css`
- Modify: `frontend/src/review/ReceiptForm.module.css`
- Modify: `frontend/src/review/FindingsPanel.module.css`
- Modify: `frontend/tests/stylesheets.test.ts`

- [ ] **Step 1: `ReviewScreen.module.css`**

- `.screen` (line ~48): `padding: var(--space-2xl)` → `var(--space-4xl) var(--space-2xl)`
- `.screen > h1` (line ~66): `font-size: var(--text-2xl)` → `var(--text-3xl)`, add `font-family: var(--font-display);` before it
- `.noticeFailed` (line ~111) and `.alert` (line ~145): leave `--color-surface`; both are messages, not objects.

- [ ] **Step 2: The two panels that are objects on the desk**

Exactly one rule per file, named — **not** "the outermost rule that sets `--color-surface`", because `ReceiptForm.module.css` sets that on three rules and two of them are form controls:

- `ReceiptForm.module.css` `.form` (line 47, `background` at line 54) → `var(--color-surface-raised)`, add `box-shadow: var(--shadow-md);` after it. **Leave `.input` (line 112) and `.select` (line 149) alone** — an input is not a raised panel, and raising it would tint every field on the form.
- `FindingsPanel.module.css` `.panel` (line 23, `background` at line 26) → same two changes.

`FindingsPanel`'s `--color-surface-sunken` rule (line ~126) is the JSON payload block and stays sunken.

- [ ] **Step 3: Re-derive the census entries, run the gates, commit**

```bash
cd frontend && npx vitest run && npm run typecheck
git add frontend/src/review frontend/tests/stylesheets.test.ts
git commit -m "feat(ui): the review cluster on the Editorial scale"
```

---

### Task 4: Login, receipts and admin

Three screens, one shape of edit each. This is a batch: one dispatch, one diff.

**Files:**
- Modify: `frontend/src/login/LoginPage.module.css`
- Modify: `frontend/src/receipts/ReceiptsScreen.module.css`
- Modify: `frontend/src/admin/AdminScreen.module.css`
- Modify: `frontend/tests/stylesheets.test.ts`

- [ ] **Step 1: The edits, per file**

`LoginPage.module.css` — the sign-in card is the one place elevation earns its keep:
- `.form` (line ~51): `padding: var(--space-2xl)` → `var(--space-4xl)`; `background: var(--color-surface)` → `var(--color-surface-raised)`; add `box-shadow: var(--shadow-md);` after `background`
- `.heading` (line ~71): `font-size` → `var(--text-3xl)`, add `font-family: var(--font-display);` before it

`ReceiptsScreen.module.css`:
- `.screen` (line ~38): `padding: var(--space-2xl)` → `var(--space-4xl) var(--space-2xl)`
- `.heading` (line ~51): `font-size` → `var(--text-3xl)`, add `font-family: var(--font-display);` before it

`AdminScreen.module.css`:
- `.screen` (line ~26): `padding: var(--space-2xl)` → `var(--space-4xl) var(--space-2xl)`
- `.heading` (line ~39): `font-size` → `var(--text-3xl)`, add `font-family: var(--font-display);` before it

Leave every `.alert` and `.waiting` on `--color-surface`.

- [ ] **Step 2: Re-derive the three census entries, run the gates, commit**

```bash
cd frontend && npx vitest run && npm run typecheck
git add frontend/src/login frontend/src/receipts frontend/src/admin frontend/tests/stylesheets.test.ts
git commit -m "feat(ui): login, receipts and admin adopt the scale"
```

---

### Task 5: ADR-0052 and the correction on ADR-0027

Design decision 13: this **extends** ADR-0027, so the correct form is a new ADR plus a dated correction on 0027 itself — the shape ADR-0043→0011 and ADR-0044→0040 already use here.

**Files:**
- Create: `docs/adr/0052-the-editorial-visual-system.md`
- Modify: `docs/adr/0027-review-ui-design-system.md` (a dated correction, not a rewrite)
- Modify: `docs/adr/README.md` (the index)

- [ ] **Step 1: Write ADR-0052**

Follow the house shape (`# ADR 0052 — …`, **Status:** Accepted (2026-08-24), **Builds on:** ADR-0027, **Implements:** the design path). It must record, at minimum: that all five of ADR-0027's decisions stand; the four new token names; that the ramp changed hue at constant luminance **because the reserved severity colours have 0.12 of headroom**, with the measured numbers; and that the dark blocks were deliberately left alone, with the cost.

- [ ] **Step 2: Add the dated correction to ADR-0027**

A dated paragraph, not an edit to its decisions. It says the palette values of decision 2 were superseded on 2026-08-24 by ADR-0052, that decision 2's *reasoning* — reserved severity colours — is what forced the new ramp's shape, and that the other four decisions are untouched.

- [ ] **Step 3: Commit**

```bash
git add docs/adr
git commit -m "docs(adr): ADR-0052, and 0027 corrected where its values moved"
```

---

### Task 6: The browser pass — decision 14

**This is the deliverable, not the follow-up.** Everything above can be entirely wrong with all five gates green: the census is silent on quantities, jsdom lays nothing out, and Vitest returns a proxy for class names. On this project a browser pass has never once failed to find something — the `auto-fit` regression shipped tiles 35% narrower with a third of the row blank at 1440, past five gates, five task reviews and five scoped re-reviews.

**Controller-run. Do not dispatch this to a subagent that cannot see the images.**

**Files:**
- Modify: `frontend/e2e/visual.spec.ts` (one viewport)

- [ ] **Step 1: Add 768 to the widths**

The spec captures 375, 1024 and 1440. Design decision 14 asks for 375, 768 and 1440. Both are right about something: 1024 and 1440 sit on the wide side of the layouts' only breakpoint (`max-width: 1023px`), and **768 is the collapsed layout at a width that is not the narrowest one** — which is precisely where a two-pane collapse goes wrong without looking broken at 375. Capture all four.

The file declares `WIDE` (1440), `MID` (1024) and `NARROW` (375) at lines 117–119, and **two** lists over them: `ALL_WIDTHS = [NARROW, MID, WIDE]` (line 121) and `ENDS = [NARROW, WIDE]` (line 125). Add beside them:

```ts
const TABLET: Viewport = { name: '768', width: 768, height: 1400 }
```

and add it to **`ALL_WIDTHS` only**, between `NARROW` and `MID`. `ENDS` is deliberately the two extremes and stays a pair; widening it would double captures that exist to compare the ends against each other.

Read the file's own counter machinery before running it — it asserts every route stub matched, because a stub that silently fails to match produces a screenshot of the *real* page, which is the failure it exists to catch.

- [ ] **Step 2: Capture**

Run the visual spec against all four widths in both themes. Record where the images land.

- [ ] **Step 3: Look at them. A person, reading.**

At minimum, answer each of these in writing:

1. Does the display face actually load, or is Archivo silently falling back to Fira? A fallback stack is invisible to every gate and looks like "the heading is a bit plain".
2. Is `--color-surface-raised` visibly raised at 1440 light, or does `#FFFDF9` on `#FAFAF9` read as flat? If it reads flat, the shadow is doing the work and the token is decoration — say so.
3. Does `--space-4xl` on `.screen` clip or scroll anything at 375 and 768?
4. Do the two themes now disagree in temperament — neutral-warm light against blue-slate dark? That was Task 1's stated ruling and this is where the cost lands.
5. Anything at all that looks wrong and is not on this list.

- [ ] **Step 4: Record the findings, and carry the three already owed**

Three findings were deferred to this pass by the previous milestone and must be answered here, not silently dropped:

- raw stage identifiers shown to an audience (`dedupe`, `persist` are operational vocabulary, not English)
- the production `setInterval` body is unexercised by any test
- `frontend/tests/app-admin-route.test.tsx` is misnamed for what it now covers

Write everything found to a defect log at the foot of this plan, dated. **A finding is a claim** — verify each before fixing it, and do not soften a correct document to match a wrong finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/visual.spec.ts docs/superpowers/plans/2026-08-24-editorial-visual-refresh.md
git commit -m "test(e2e): capture 768, and what the browser pass found"
```

---

## Self-review

**Spec coverage.** §5 decision 12 → Task 1 (the ramp, measured). Decision 13 → Task 5 (ADR-0052 + the 0027 correction). Decision 14 → Task 6. §5's `tokens.css` table: cooled ramp ✅, raised distinct ✅, warmer/longer shadows ✅, `--space-4xl`/`--space-5xl` ✅, `--text-3xl` ✅, a display face via `@fontsource` ✅. §6's screen list ✅ **plus the two §6 omits**, covered by Task 2.

**One gap, deliberately left.** §6 lists `--space-5xl` as new but no task consumes it — it is declared and unused. Declaring a token nothing paints is normally a defect. Kept because the census pins declarations and Task 6 may well want it once someone has seen the screens at 1440; if Task 6 does not use it, delete it there rather than leaving it as furniture.

**Type consistency.** `--font-display`, `--text-3xl`, `--space-4xl`, `--space-5xl` are spelled identically in Task 1 (where they are declared), Tasks 2–4 (where they are consumed), and the census instructions. `--color-surface-raised` is the existing name; no new colour token is introduced.

**Known-thin pair, un-gated, carried not introduced.** `--color-null` on `--color-surface-sunken` measures **4.34:1 today** and **4.32:1** after Task 1 — below the 4.5 floor in both cases. It is not gated, because `--color-surface-sunken` is not in `INHERITABLE_SURFACES` and no rule pairs the two directly. The refresh holds the existing margin rather than improving or worsening it. Flagged for Task 6 to look at; fixing it is a separate decision about a reserved token.

## Defect log

*(dated entries appended during execution)*
