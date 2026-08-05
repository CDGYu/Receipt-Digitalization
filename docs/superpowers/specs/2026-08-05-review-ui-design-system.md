# The review UI's design system

**Status:** design, drafted 2026-08-05 — **not yet approved, not yet planned into tasks**
**Applies to:** `frontend/` (React 19.2.7 + Vite 8.1.1 + TypeScript 6.0.2), served same-origin under `/app`
**Reference:** Qarin (free SaaS template, Framer Marketplace, by UIPark) — https://framer.link/GO0pupH
**Generated with:** the `ui-ux-pro-max` skill; machine output persisted at
`design-system/receipt-review/MASTER.md`

---

## 0. The measured starting point

**`frontend/` contains no stylesheet at all.** Verified:
`git ls-files frontend | grep -E '\.(css|scss|module\.css)$'` returns **nothing**.
Every surface — login, the review screen, all five ADR-0024 error states, the
confidence rail, the findings panel, the line-items table — is unstyled browser
default. And per the standing record, **nobody has opened any of it in a
browser.** This document is the first design pass over a UI that has shipped
twice.

That combination is the real risk here. Two milestones of behaviour were
verified entirely through Vitest against the DOM, which proves structure and
accessibility wiring but says nothing about whether a human can read the screen.

---

## 1. What actually transfers from the reference

**Qarin is a SaaS *marketing website* template.** Its section inventory, read
off the live preview: hero + CTAs, social proof, feature overviews, statistics
showcase, integration showcase, pricing comparison table, FAQ accordion, blog
feed, footer. Its navigation is Features / Pricing / Changelog / About / Blog.

This project needs the opposite: an internal, data-dense review tool where a
human compares a photograph against extracted numbers and decides whether to
trust them. **Most of Qarin's functions do not transfer**, and forcing them to
would be worse than ignoring them.

**Four patterns do transfer, and are worth taking:**

| Qarin pattern | Used here as |
|---|---|
| Statistics showcase (KPI tiles) | the admin surface's queue summary, fed by `GET /metrics` — `counts_by_status`, `auto_approval_rate`, backlog by priority |
| Pricing comparison table | the row rhythm for `GET /review/tasks` — aligned columns, one emphasised column, quiet zebra |
| FAQ accordion | the findings panel's progressive disclosure — rule id + one-line summary collapsed, context expanded |
| Card + section shell | the panel shell shared by the confidence rail, findings, and image pane |

**What is deliberately not taken:** the hero, the CTA bands, the oversized
display type, the marketing colour warmth, and the scroll-reveal motion. A
reviewer working a queue is not being converted; they are being asked to
concentrate.

---

## 2. Three deviations from the generated system, each with a reason

The `ui-ux-pro-max` output is in `design-system/receipt-review/MASTER.md`. Three
of its recommendations are overridden here, and this section is the record of
why so nobody "restores" them later.

**2.1 — Discard the recommended pattern and style.** The tool returned
"Real-Time / Operations Landing" (hero → metrics → how-it-works → CTA) and the
style "Exaggerated Minimalism" (`font-size: clamp(3rem, 10vw, 12rem)`,
`font-weight: 900`, "massive whitespace", best for "fashion, architecture,
portfolios, agency landing pages"). Both of its style/pattern domains only
carry **landing-page** entries, so they misroute for an internal tool no matter
how the query is phrased — re-running with an explicit
`financial dashboard accounting admin audit` query returned the same style.
**Its product and colour domains did route correctly** to *Financial
Dashboard*, whose keywords literally include `accounting`, so those are kept.

**2.2 — Light default, dark available; not dark default.** The Financial
Dashboard palette is dark-first (`#020617` background). Rejected as the default
for one product-specific reason: **the reviewer's reference truth is a
photograph of white receipt paper.** A dark chrome around a bright scan raises
surround contrast, tires the eye across a queue-length session, and makes the
image's own contrast harder to judge — the one judgement this screen exists to
support. Dark mode ships as a full second theme, because operators do work at
night, but it is not what an unconfigured install renders. Both themes carry
the same semantic tokens, so no component knows which is active.

**2.3 — Self-host the fonts; do not use the Google Fonts CDN.** The tool emits
`@import url('https://fonts.googleapis.com/...')`. Not usable here. The service
is designed to run on a LAN, the entire test suite is offline and Node-free,
and `scripts/serve_review_e2e.py` runs against a local build. A CDN `@import`
means the app silently renders in fallback fonts exactly when it is deployed
where it is meant to run — so the styling nobody has ever seen would be *a
different styling again* in production. Vendor the woff2 files into
`frontend/src/assets/fonts/` and `@font-face` them locally, with
`font-display: swap` and a metric-compatible fallback stack.

---

## 3. Tokens

### 3.1 Typography

**Fira Sans** for prose and labels, **Fira Code** for every number. This came
from the tool's typography match ("dashboards, analytics, data visualization,
admin panels") and is the single most load-bearing choice in this document.

Fira Code is a monospace with **tabular figures**: digits occupy identical
advance widths, so a column of money aligns on the decimal without any
per-cell alignment hack, and a transposed digit is visible as a broken column.
On an accounting screen that is not decoration — it is the property that makes
a misread number *look* wrong.

```
--font-sans:  'Fira Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
--font-mono:  'Fira Code', ui-monospace, 'Cascadia Mono', Consolas, monospace;
```

Everything numeric — money, quantities, confidence scores, task ids, dates,
`card_last4` — uses `--font-mono` with `font-variant-numeric: tabular-nums`.
Prose, labels, buttons and findings text use `--font-sans`.

Type scale, 16px base (the tool's own guidance: consistent modular scale,
never arbitrary sizes):

| Token | Size | Use |
|---|---|---|
| `--text-xs` | 12px | table meta, timestamps, rule ids |
| `--text-sm` | 14px | labels, secondary text, dense table cells |
| `--text-base` | 16px | body, input values — **never below this for an editable value** |
| `--text-lg` | 18px | panel headings |
| `--text-xl` | 24px | the receipt total, stat-tile figures |
| `--text-2xl` | 32px | page title only |

Line-height 1.5 for prose, 1.3 for dense table rows. No display sizes; there is
no hero here.

### 3.2 Colour

Semantic tokens only — **no raw hex in components**. Light is the default;
`[data-theme="dark"]` and `prefers-color-scheme: dark` both resolve the dark
set.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--color-background` | `#F8FAFC` | `#020617` | page |
| `--color-surface` | `#FFFFFF` | `#0E1223` | panels, cards, table body |
| `--color-surface-raised` | `#FFFFFF` | `#1A1E2F` | popovers, sticky headers |
| `--color-foreground` | `#0F172A` | `#F8FAFC` | primary text |
| `--color-muted-foreground` | `#475569` | `#94A3B8` | labels, meta |
| `--color-border` | `#E2E8F0` | `#334155` | dividers, input borders |
| `--color-primary` | `#0F172A` | `#F8FAFC` | primary action |
| `--color-ring` | `#2563EB` | `#60A5FA` | focus ring — **its own token** |
| `--color-severity-error` | `#DC2626` | `#EF4444` | ERROR findings |
| `--color-severity-warn` | `#B45309` | `#F59E0B` | WARN findings |
| `--color-severity-info` | `#1D4ED8` | `#60A5FA` | INFO findings |
| `--color-positive` | `#15803D` | `#22C55E` | auto-approved, confirmed |
| `--color-null` | `#64748B` | `#64748B` | **the "not extracted" mark** |

`--color-muted-foreground` is `#475569` in light, not the generated `#94A3B8`:
`#94A3B8` on `#FFFFFF` measures ~2.8:1 and fails the 4.5:1 body-text rule the
tool itself flags as High severity. `#475569` on white is ~8:1.

**Severity colours are reserved.** Nothing decorative may use error red, warn
amber or info blue. This is why the earlier amber-primary palette was rejected
outright: if amber is the brand colour, a WARN finding has no colour left.

### 3.3 Spacing, radii, elevation

Dense scale (`--density 8`), taken from the generated system unchanged:

```
--space-xs 2px · --space-sm 4px · --space-md 8px · --space-lg 12px
--space-xl 16px · --space-2xl 24px · --space-3xl 32px
--radius-sm 4px (inputs, chips) · --radius-md 8px (buttons, panels) · --radius-lg 12px (cards)
--shadow-sm 0 1px 2px rgba(0,0,0,.05) · --shadow-md 0 4px 6px rgba(0,0,0,.1)
```

Elevation is used sparingly: panels are separated by border, not shadow.
`--shadow-md` and above are for things that genuinely float (the sign-out
confirm, any popover).

---

## 4. The rule this product has that no generic system supplies

> ### `null` must never look like `0`, and neither may look like "empty".

It follows directly from the prime directive — *prefer `null` over a confident
guess; a wrong number is far worse than a missing one*. If the UI renders an
unextracted total as `0.00`, the system's central safety property is destroyed
at the last inch, in the one place a human makes the decision.

**Three visually distinct states, everywhere a value can appear:**

| State | Display | Semantics |
|---|---|---|
| **null** — never extracted | `—` in `--color-null`, `--font-mono` | `<span aria-label="not extracted">`; input `value=""` with placeholder `—` |
| **zero** — extracted as zero | `0.00` in `--color-foreground` | a real, asserted number |
| **empty** — reviewer cleared it | `—` + a "cleared" chip beside the label | dirty state, distinct from both above |

A null field additionally carries a hairline left border in `--color-null` so a
scan down the form finds every gap without reading a single value.

**This rule is testable and must be pinned**, not left to review: a test that
renders a receipt whose `total` is `null` and asserts the accessible name is
*not* `"0"`, `"0.00"` or the empty string.

---

## 5. Components

### 5.1 MoneyField

The most constrained component in the app. **ADR-0015 bans `<input
type="number">` and `valueAsNumber`** — money is a string end to end, and a
number input silently reformats, strips leading zeros, and exposes a float
accessor. So:

```
<input type="text" inputMode="decimal" autoComplete="off"
       class="money" value={stringValue} />
```

`inputMode="decimal"` gets the numeric keypad on touch without any of
`type="number"`'s coercion. Right-aligned, `--font-mono`, tabular figures.
Currency symbol sits **outside** the input as a static prefix so it is never
part of the editable string.

Inline error renders **beside the input, `aria-describedby`-linked, additive to
the summary alert** (ADR-0024 — the summary always renders; the inline error
never replaces it).

### 5.2 LineItemsTable

Description left, numbers right, one row per line item. Column widths fixed so
the decimal column does not shift as the reviewer edits. `--text-sm`, row
height 32px, zebra at 2% foreground tint — enough to track a row across, not
enough to compete with severity colour.

Wrapped in `overflow-x: auto` (the tool's High-severity responsive rule); the
page body itself never scrolls horizontally.

### 5.3 ConfidenceRail

A vertical scale with the score and the persisted `(reason, penalty)`
breakdown. **Never colour alone** — every band carries an icon and a word
(`Auto-approve` / `Review` / `Low`), because the tool's Colour Only rule is
High severity and red/green is the exact failure case it names.

The breakdown is the persisted one (ADR-0012), and its `NULL`-vs-`[]`
distinction is visible: `NULL` renders "not recorded", `[]` renders "nothing
lowered the score". Collapsing those two would tell a reviewer "no reasons"
about a row that never captured any.

### 5.4 FindingsPanel

The accordion pattern, taken from Qarin. Collapsed row: severity icon +
`rule_id` + one-line message. Expanded: the `context` payload. Sorted by
severity then `created_at`, matching what `get_findings` returns.

Rule ids render in `--font-mono` — they are stable identifiers stored in the DB
and shown to humans, and monospacing marks them as such.

### 5.5 ImagePane

Neutral `#F1F5F9` surround (light) — never pure white, never the page colour —
so the receipt's own white edge is visible. Fit-to-width by default, click to
zoom. The image is the reference truth; nothing tints or overlays it.

### 5.6 TaskTable (new, admin surface)

Backed by `GET /review/tasks`. Columns: priority chip · reason · `assigned_to`
· `state` chip · age from `opened_at` · release action.

Two things the API's shape dictates:

- **`assigned_to` renders `—` when null**, by §4's rule — an unassigned open
  task must not read as assigned to nobody-in-particular.
- **A reviewer and an admin see different row sets from the same endpoint**
  (ADR-0026). The empty state must therefore say *which* scope is empty —
  "No open tasks, and none assigned to you" for a reviewer, "No tasks" for an
  admin — or a reviewer will read a scoped-empty list as a broken queue.

Release is a destructive-ish action on someone else's work: it confirms inline,
names the current holder, and after success the row moves to `OPEN` with
`assigned_to` cleared.

### 5.7 StatTiles (new, admin surface)

The Qarin statistics showcase, fed by `GET /metrics`. Four tiles: open backlog,
in progress, done, auto-approval rate. **`auto_approval_rate` is `str | None`
and its null is load-bearing** — an undefined rate renders `—`, never `0%`.
Same §4 rule, and the API was deliberately built to preserve that distinction.

### 5.8 The five error states (ADR-0024)

They exist and are wired; they have never been styled or seen. Styling must not
disturb their contract:

- **exactly one `role="alert"` region on screen** — the summary alert. The
  backend-down sentence deliberately has none, because a second alert makes the
  suite's single-alert queries ambiguous. That is a recorded user ruling.
- terminal `taken` / `gone` states offer one exit and keep ⌘↵ dead
- inline field errors are **additive** to the summary, never a replacement
- the classifier never invents copy; the UI renders what it was given

---

## 6. Accessibility contract

Non-negotiable, and every item is testable:

- **Contrast ≥ 4.5:1** for body text in both themes. `--color-muted-foreground`
  was darkened in light mode for exactly this.
- **Never colour alone** (High severity): severity, confidence band, and task
  state each carry an icon **and** a word.
- **Every input has a visible `<label>`** with `for` — placeholder-only is
  banned. All 17 correctable paths already have labels; keep them visible.
- **Focus is always visible**: 2px `--color-ring` outline with 2px offset.
  Never `outline: none`.
- **Targets ≥ 44×44px** with ≥8px separation. Today's controls are browser
  default and smaller than this.
- **SVG icons, never emoji.** Phosphor (outline, `size={20}`), self-hosted for
  the same reason as the fonts.
- **`prefers-reduced-motion: reduce` → no transitions.**

---

## 7. Motion

`--motion 2` (subtle). Transitions are 150ms `ease-out`, and only for state a
user caused: hover, focus, disclosure, row entry. **No scroll reveal, no
choreography, no animated width/height.** The generated system's GSAP
scroll-reveal preset is discarded along with the landing pattern that implied
it — and GSAP itself is not a dependency this app should take on.

A saving indicator is the one place motion is required rather than optional:
the tool's Submit Feedback rule is High severity, and the submit chain is
strictly sequential `PATCH → complete → next`, so each step needs a visible
pending state.

---

## 8. Constraints inherited from the ADRs

Any implementation must hold these; they are not style choices:

- **ADR-0015** — money is a string end to end; `<input type="number">` and
  `valueAsNumber` are banned; the browser stays same-origin so no
  `CORSMiddleware`; SPA pages live under `/app/*` and no API path moves.
- **ADR-0024** — one `role="alert"`; the stash never touches browser storage;
  the summary alert always renders; the classifier never invents copy.
- **ADR-0026** — a reviewer and an admin get different rows from one endpoint;
  the empty state must name its scope.
- **ADR-0012** — the confidence breakdown is persisted; `NULL` ≠ `[]`.
- **ADR-0017** — `npm test` does not type-check. Styling work still runs
  `npm run typecheck` and `python scripts/verify.py`.

---

## 9. Open questions for the user

1. **Light default with dark available, or dark default?** §2.2 argues light
   for image comparison; the generated system says dark. This is reversible but
   sets the tone.
2. **Plain CSS with custom properties, CSS Modules, or Tailwind?** This
   document is written in tokens so it survives any of the three. Tailwind is a
   new dependency and a build-config change; CSS Modules is zero new runtime
   deps and fits Vite natively. **Recommendation: CSS Modules + a single
   `tokens.css`.**
3. **Is a browser pass part of "done"?** Two UI milestones have shipped without
   one. Playwright is already installed and `scripts/seed_review_e2e.py` exists,
   so screenshots are cheap to produce.
4. **Does the admin surface need its own route shell**, or does it live as a
   tab inside the existing `/app` screen?
