# ADR 0027 — The review UI's design system

**Status:** Accepted (2026-08-05)
**Builds on:** ADR-0015 (same-origin, `/app`, money as a string), ADR-0024 (the
error-recovery contract), ADR-0017 (two suites and the gate runner)
**Implements:** `docs/superpowers/specs/2026-08-05-review-ui-design-system.md`

## Context

The review UI shipped twice — Phase 5 and the error-recovery milestone — and
until 2026-08-05 **`frontend/` contained no stylesheet at all.** Measured:
`git ls-files frontend | grep -E '\.(css|scss)$'` returned nothing. Every
surface (login, the review screen, all five ADR-0024 error states, the
confidence rail, the findings panel, the line-items table) was browser
default, and **nobody had opened any of it in a browser.** Two milestones of
behaviour had been verified entirely through Vitest against the DOM, which
proves structure and accessibility wiring and says nothing about whether a
human can read the screen.

A design system was drafted at the user's request from a Qarin SaaS template
reference plus the `ui-ux-pro-max` skill. Qarin is a **marketing website**
template — hero, pricing tiers, testimonials, blog feed — so four patterns
transferred (stat tiles, comparison-table row rhythm, accordion, card shell)
and the rest did not.

## Decision

### 1. Light default, dark available — not dark default

The generated system recommended a dark-first Financial Dashboard palette
(`#020617`). Rejected as the default for one product-specific reason: **the
reviewer's reference truth is a photograph of white receipt paper.** Dark
chrome around a bright scan raises surround contrast, tires the eye across a
queue-length session, and makes the image's own contrast harder to judge —
which is the one judgement this screen exists to support. Dark ships as a
full second theme; both carry the same semantic tokens, so no component knows
which is active.

`:root:not([data-theme='light'])` inside the `prefers-color-scheme` block is
**load-bearing**: an explicit light choice must beat an OS dark preference
while an unset preference still follows the OS. It has its own pin.

### 2. CSS Modules plus one `tokens.css` — no new runtime dependency

Chosen over Tailwind (a new dependency and a build-config change) and plain
global CSS. Native to Vite, component styles stay colocated, and the token
layer is one file with 35 custom properties in three blocks.

**`--color-muted-foreground` is `#475569` in light, not the generated
`#94A3B8`** — that value measures ~2.8:1 on white and fails the 4.5:1
body-text rule the tool itself flags as High severity.

**Severity colours are reserved.** Nothing decorative may use error red, warn
amber or info blue. This is why an amber-primary palette was rejected
outright: if amber is the brand colour, a WARN finding has no colour left.
It is also why the focused row is `--color-surface-active` (pale blue, tied
to `--color-ring`) rather than the `#fffbe6` yellow it replaces — a yellow
row reads as a warning on an accounting screen.

### 3. Fonts are self-hosted via `@fontsource`, never a CDN

The generated system emitted `@import url('https://fonts.googleapis.com/…')`.
Rejected: the service runs on a LAN, the whole test suite is offline, and
`serve_review_e2e.py` runs against a local build — so a CDN import renders
fallback fonts **exactly where the app is deployed**, meaning the styling
nobody has seen would be a different styling again in production.

The plan originally mandated hand-downloading woff2 binaries. Also rejected,
on the plan's own admission that no test could prove a vendored file is
actually Fira Sans rather than a renamed placeholder. `@fontsource/fira-sans`
and `@fontsource/fira-code` are self-hosted (Vite bundles the woff2 into
`dist`, so the no-network requirement still holds) **and** lockfile-pinned
with integrity hashes. Accepted cost: runtime dependencies go from two to
four in a project that hand-rolled scrypt rather than take passlib.

Verified on the shipping artefact rather than asserted: the built CSS carries
35 `@font-face` rules and 33 emitted woff2 files with **zero** `http(s)://`
references.

**Fira Code for every number** is the most load-bearing typographic choice
here. Its tabular figures give digits identical advance widths, so a money
column aligns on the decimal without per-cell hacks and a transposed digit is
visible as a broken column. On an accounting screen that is not decoration —
it is the property that makes a misread number *look* wrong.

### 4. A pathname switch, not React Router

Runtime dependencies are exactly `react` and `react-dom`; the only pathname
read in the app is `session.ts:21`; and the backend already serves a history
fallback (`_SpaFiles(..., html=True)`, `api.py`), so `/app/admin` survives a
reload without a router. Adding one would be the app's third runtime
dependency for a single route.

### 5. `null` must never look like `0`, and neither may look like "empty"

**This is the prime directive reaching the last inch of the UI.** *Prefer
`null` over a confident guess; a wrong number is far worse than a missing
one.* If the UI renders an unextracted total as `0.00`, the system's central
safety property is destroyed on the one screen where a human decides.

Three visually distinct states, and the rule lives in exactly one component
(`ui/Value.tsx`):

| State | Display |
|---|---|
| **null** — never extracted | `—` in `--color-null`, `--font-mono`, with a hairline left border and `role="img" aria-label="not extracted"` |
| **zero** — extracted as zero | `0.00` in `--color-foreground` |
| **empty** — cleared by a reviewer | the same mark; the distinguisher is a "cleared" chip **beside the label**, outside the value |

States 1 and 3 are **deliberately indistinguishable inside `Value`**, because
§4's own table puts the entire distinguisher outside the value, and `Value`
receives a `FieldMap` with no dirty flag — the distinction is not merely
unimplemented but unrepresentable there.

`role="img"` is load-bearing, not cosmetic. A bare `<span>` maps to
`role=generic`, for which ARIA 1.2 marks naming **prohibited**; and
`getByLabelText` reads the DOM attribute without consulting role, so a
label-only test passes whether or not a screen reader ever hears it.

The API already holds the same rule at its boundary — `auto_approval_rate` is
`str | None`, and the confidence breakdown distinguishes `NULL` ("not
recorded") from `[]` ("nothing lowered the score") per ADR-0012. The UI
honours a contract that already exists.

## Consequences

- **The rule is pinned at the primitive and not yet on any screen.**
  `git grep '<Value'` returns nothing: `Value` has no consumer. Every one of
  the 17 correctable paths is an `<input>`, and §4 specifies the input half
  separately as `value=""` **with `placeholder="—"`** — and `placeholder`
  appears **zero** times in `frontend/src`. A null total renders as a blank
  box today. Closing that is the first job of the review-screen task.
- `ConfidenceRail.tsx` already renders `{confidence ?? '—'}` with no
  accessible name, no `--color-null` and no border — an uncoordinated second
  copy of half the rule, predating this ADR.
- **The class-name guard is bounded, and the boundary is stated.** Under
  Vitest's `css: false`, a `.module.css` import returns a proxy whose keys
  echo back, so nothing detects a renamed or misspelled class. The guard
  therefore reads stylesheets as text. Its guarantee is: *the rule it reads is
  the unique top-level rule whose selector is exactly this string, or it
  throws.* **That property holds for stylesheets of the shape these four
  have — no functional selector lists, no statement at-rules.** Residual leaks
  are recorded as harmless-but-inexact (`:is`/`:where`), harmful-but-absurd
  (`:not(…, .mark) { color: … }` is self-contradictory CSS), and
  loud-and-safe (`@import` before the first rule throws misleadingly).
- **`text-align: right` belongs to the consuming cell, not to `Value`.**
  `text-align` applies to block containers and `Value` renders an inline
  `<span>`, so the declaration was inert and was removed.
- A browser pass is part of "done" for this system (user ruling). Nothing in
  the token or primitive work proves anything *renders* — `color-scheme` was
  added by reading, not by seeing.

## What this ADR does not decide

The five error states' appearance, the admin surface's layout, and whether
any of it is legible. Those need the browser pass, which had not run when
this was written.

## References

`docs/superpowers/specs/2026-08-05-review-ui-design-system.md` (the design,
with §2's three overrides of the generated system and §9's four rulings);
`docs/superpowers/plans/2026-08-05-review-ui-styling.md`;
`design-system/receipt-review/MASTER.md` (raw generated output);
`.superpowers/sdd/2026-08-05-review-ui-styling/progress.md` (the ledger —
every plan defect and every mutation);
ADR-0012 (the persisted breakdown's `NULL` vs `[]`), ADR-0015, ADR-0017,
ADR-0024, ADR-0026.
