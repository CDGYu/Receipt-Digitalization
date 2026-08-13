# ADR 0038 — The theme control, and one key in browser storage

**Status:** Accepted (2026-08-11)
**Closes:** ADR-0027's "one decision this ADR made that the pass showed is
incomplete" — dark shipped as a full second theme with no way for a user to
choose it
**Narrows:** ADR-0024's "nothing enters browser storage"
**Relates to:** ADR-0015 (same origin), ADR-0029 (what the gates certify)

Derived 2026-08-11 against `feat/theme-control`. **Re-derive rather than quote**
(ADR-0028 rule 1).

## Context

ADR-0027 decision 1 ships light as the default and dark as a **full** second
theme: same semantic tokens, every contrast ratio checked, and a precedence rule
(`:root:not([data-theme='light'])` inside the `prefers-color-scheme` block) so
an explicit light choice beats an OS dark preference.

Its browser pass then recorded what nobody had built:

> **Decision 1 ships dark as a full second theme, and there is no theme control
> in the application.** … a second theme a user cannot choose is a
> half-delivered decision. **Not fixed here, and deliberately not decided
> here**: it needs a home for the control, which is a design question this ADR
> did not open.

This opens it.

## Decision

### 1. Three states, not two

`light`, `dark`, and `system`. They map onto exactly one DOM fact:

| preference | `data-theme` |
|---|---|
| `system` | **absent** — the media query applies |
| `light` | `light` |
| `dark` | `dark` |

**Two states would have made ADR-0027's precedence rule a one-way door.** That
rule exists so an explicit light choice beats an OS dark preference; with only
light and dark on offer, a reviewer who touched the control could never get back
to following the OS. `system` is the state everybody starts in, so it has to
remain reachable.

**`system` removes the attribute rather than setting `data-theme="system"`.**
There is no such block in `tokens.css`, and adding one would mean a third copy
of both palettes.

### 2. A `<select>`, in the header, beside sign-out

Three mutually exclusive named options is what a `<select>` is. It carries its
own label association and keyboard handling, and it stays one control at any
width — the shell was already tight at 1440×900 in ADR-0027's pass.

The `<header>` renders only when signed in, so **the login page has no control**.
It is still themed: it honours the OS preference like everything else. Giving it
one would mean giving `LoginPage` a shell it does not have.

No `appearance: none`. The native chevron is the affordance, and replacing it
means redrawing focus, open state and the chevron per platform — none of which
has been through a browser pass in either theme. `color-scheme` on `:root` is
what makes the native widget render dark when the theme is dark.

### 3. One key in `localStorage`, and ADR-0024 is narrowed to say so

ADR-0024 carries a user ruling: *"nothing enters browser storage. Not
`sessionStorage`, not `localStorage`."* Its stated reason is the sentence after
it — *"no receipt-adjacent text is written to disk by the browser"* — and the
stash it governs holds edited receipt values.

**A theme preference is not receipt-adjacent text.** The user narrowed the
ruling on 2026-08-11: this application may write **one key**, `receipts.theme`,
holding **one of three known words**. Nothing else may write to storage, and
`review/stash.ts` still holds its edits in memory and always will. ADR-0024
carries the dated note.

The alternatives were considered and rejected: a column on the user row is a
migration, an endpoint and a round trip for a colour, and it flickers until
`/auth/me` returns; no persistence at all turns *"the app has no way to choose
dark"* into *"the app has no way to keep dark"*, which is not obviously better
than shipping nothing.

Anything unrecognised in that key reads as `system`. It is a shared-origin key
another tab or a person can set to anything, and the honest answer to
`receipts.theme = "purple"` is the default rather than a broken header.
`localStorage` access is guarded at both ends: a browser that refuses to store
gets a control that works and forgets, not a blank page.

### 4. The theme is applied before first paint

An inline, synchronous script in `index.html` sets `data-theme` from storage
before the module graph loads.

Without it a reviewer whose choice differs from their OS sees the OS theme flash
and then swap. **Only that reviewer is affected** — the default writes no
attribute and needs no script — but for them it happens on every single load.

A module script is deferred, which is exactly one paint too late, so this cannot
be the same code the module exports. **The storage key is therefore a literal in
two places**, and that duplication is pinned rather than tolerated:
`theme.test.ts` reads `index.html` as text and fails if the literal and the
exported constant disagree, and again if the script acquires `type="module"`,
`defer` or `async`.

## How it is pinned

Fourteen cases on the module, six on the component, four on the HTML. **No test
asserts a class name** — Vitest runs with `css: false`, so a `.module.css`
import returns a proxy whose keys echo back and a renamed class ships unpainted
with every rendering test green (ADR-0029). The stylesheet is guarded as text by
`stylesheets.test.ts`'s census instead.
**[Corrected 2026-08-14 — this said such a class ships as `class="undefined"`.**
Neither environment produces that literal. The measurement is in
`frontend/tests/value.test.tsx`, kept in one place rather than copied here, and
what this sentence rests on is unchanged: the class reaches no rule, nothing
paints, and every rendering test stays green.**]**

### Proven red, five ways

Each mutation applied alone and reverted before the next:

| mutation | killed |
|---|---|
| `system` sets `data-theme="system"` instead of removing it | 2 |
| an unrecognised stored value is trusted | 1 |
| `setPreference` stops persisting | 4 |
| the pre-paint script becomes `type="module"` | 1 |
| the pre-paint key drifts from the exported constant | 1 |

The last two are the ones worth having: they guard a duplication and a timing
property that no rendering test can see.

## What the gates still cannot see

ADR-0029's list applies unchanged. **Nobody has looked at this control in a
browser.** jsdom renders no colour, so "the select reads correctly against the
header in both themes" is asserted by nothing here — the same gap that let
ADR-0027's `placeholder="—"` pass while being invisible on screen.

Specifically unverified: the native select's dark rendering (it follows
`color-scheme`, which is a claim about the platform widget, not about this CSS);
whether label and control align against the unstyled header; and any engine but
Chromium.

## Consequences

- **ADR-0027 decision 1 is fully delivered.** A second theme users can reach.
- **`localStorage` is no longer untouched**, and the narrowing is the reason.
  A future feature wanting storage does **not** inherit permission from this —
  ADR-0024's ruling stands for everything except this one key.
- **`index.html` now contains logic.** It was markup only. The pin is what keeps
  that from drifting.
- **The login page cannot switch themes.** Deliberate; revisit if it matters.

## What this ADR does not decide

Whether the preference should follow a reviewer between machines. That is the
server-side option, and it stays available — `localStorage` is per-browser and
this ADR does not stop a later migration from superseding it.

Nor `prefers-reduced-motion` or `prefers-contrast`, both still unexercised
(ADR-0027), and nor whether the header should be styled at all — it is still the
unstyled element `SignOutControl`'s stylesheet was written to survive.

## References

`docs/adr/0027-review-ui-design-system.md` (decision 1, the precedence rule, and
the browser pass's note that this was missing);
`docs/adr/0024-review-ui-error-recovery-contract.md` and its dated narrowing;
`docs/adr/0029-what-the-gates-certify.md`; `frontend/src/theme.ts`;
`frontend/index.html`; `frontend/tests/theme.test.ts`.
