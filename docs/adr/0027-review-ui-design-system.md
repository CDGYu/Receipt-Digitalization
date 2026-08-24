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
read in the app is `session.ts`'s signed-in guess; and the backend already
serves a history fallback (`_SpaFiles(..., html=True)`, `api.py`), so
`/app/admin` survives a reload without a router. Adding one would be the app's
third runtime dependency for a single route.

> **Correction (2026-08-07): two of the three clauses above are false as
> written.** See `## Correction (2026-08-07)` at the foot of this ADR. The
> *decision* — a pathname switch, not a router — is unaffected and stands.

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

## Correction (2026-08-06)

**The Consequences section's "Every one of the 17 correctable paths is an
`<input>`" is false, and the operative half of that sentence is narrower than
it reads.** Found in the review-screen task's pre-flight, before any styling
was written.

Answered by enumerating rather than by arguing (review standard 17). The 17
paths are exactly the keys of `_RECEIPT_FIELDS`
(`src/receipts/persist/repository.py`) — measured, 17 — and `ReceiptForm.tsx`
renders one control for each:

| Source | Count | Element |
|---|---|---|
| `TEXT_FIELDS` | 8 | `<input type="text">` |
| `MONEY_FIELDS`, via `MoneyInput` | 6 | `<input type="text" inputMode="decimal">` |
| `meta.legibility` | 1 | **`<select>`** |
| `meta.is_handwritten`, `meta.receipt_is_inconsistent` | 2 | **`<input type="checkbox">`** |

*(Every row above names a symbol to search `ReceiptForm.tsx` for. It carried
line numbers when written and all five had rotted by 2026-08-07; they are
removed rather than repointed — **ADR-0028 §5**, review standard 21. The table's
counts are re-derivable: `_RECEIPT_FIELDS`' keys, and the four literals above.)*

So the surface is **sixteen `<input>` elements and one `<select>`**, not
seventeen inputs.

**What this changes in practice: `placeholder="—"` reaches 14 of the 17.** A
`<select>` bound to a closed option list has no empty state, and a checkbox has
no third state — `ReceiptForm.tsx` already records both (search it for "A
checkbox has no third state" and for the no-`placeholder` note beside the
`<select>`; **this citation deliberately carries no line numbers** — it named
`:221-224` when written on 2026-08-06 and that had already rotted by the end of
the same day, when the review-screen task inserted the placeholder and its
comment above them, review standard 5), and records
why: a column that is `NULL` today stays `NULL` until the reviewer actually
clicks it, at which point they have made a real edit. Neither element honours
`placeholder` at all. Followed literally, the uncorrected sentence puts a
placeholder on a checkbox.

**The claim the sentence was written to make is untouched and still stands:**
none of these 17 controls is a `Value`, every one is a form control, so §4's
null rule cannot reach this screen through the primitive — and a null total
still renders as a blank box until the review-screen task closes it.

The line-items table is a **separate** surface and is not part of the 17.
Measured: `_LINE_ITEM_FIELDS` has 7 keys, and `LineItemsTable` renders 6 controls
per row, holding `position` read-only because it is the addressing key every
other edit in the row depends on — search that file for **"`position` is
read-only"**, which states the rule and the reason.

## Dated note (2026-08-06) — the browser pass ran, and what it found

The Consequences section above ends: *"A browser pass is part of 'done' for this
system (user ruling). Nothing in the token or primitive work proves anything
**renders**."* It has now run — 97 screenshots at 375 / 1024 / 1440px in both
themes across eleven surfaces, every one opened and read, with 64 in-page
measurement records beside them. Full report:
`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`. Screenshots live
in `var/e2e/visual/`, gitignored, because they contain receipt data.

### The ruling was right, and this is the evidence

**§5's null rule was asserted green in jsdom and invisible in a browser.**

`placeholder="—"` was present on every money control, and the
universally-quantified pin that guards it was correct and passing — the
milestone spent five fix rounds converging on that pin, and it never lied. But
`MoneyInput`'s label was `display: inline-flex`, which shrink-wraps to an
`<input>`'s `size="20"` intrinsic width — about **246px** — inside line-item
cells measured **92–119px**. Every money control overflowed its column by
127–155px, painted over the neighbouring column, clipped the last one away
entirely, and pushed the right-aligned `—` outside the visible box.

**So on the line-items table, "never extracted" and "not filled in yet" looked
identical — on money, which is the one place §5 exists to protect — with all
five gates green.**

A jsdom assertion cannot see a clipped box. That is the whole argument for the
ruling, and it is now measured rather than argued. **A pin can be genuinely
universal, proven to fail, and still not measure the property you care about,
because the assertion layer cannot see what a person sees.**

Fixed in the same milestone: `cellOverflow` **204 → 0** across all 64 records.
Note the diagnosis was wrong before it was right — the controller briefed the
cause as a missing `width`, and removing that `width` broke nothing; the
implementer found `inline-flex` by mutation and then **removed two declarations
it could not break** rather than ship inert armour.

### Two other Criticals, both scope gaps rather than mistakes

* **The login page had no stylesheet at all** and was the first screen every
  reviewer saw: labels sharing a line with their inputs, 21px controls against
  §6's 44px floor. **`frontend/src/login/` was in no task's file set in any of
  the six tasks** — the plan drew boundaries around every file it thought about
  and left the entry point out.
* **`--color-null` measured 3.91:1 in dark**, below the 4.5:1 floor, on the one
  glyph carrying the prime directive. It was `#64748B` in all three token
  blocks — identical light and dark, which is exactly why it passed on white
  and failed on `#0E1223`. Now `#7C8CA2` in both dark blocks: **5.43:1**
  (corrected 2026-08-07 from `5.45`, a hand computation with a wrong green
  luminance; the browser reports 5.43 across 26 records).

### What the pass confirmed is right

Recorded deliberately, because three milestones shipped unseen and "this part is
fine" was information nobody had. **Theme precedence works in both directions** —
`:root:not([data-theme='light'])` behaves exactly as decision 1 says. **Fira
Code's tabular figures are real**: `1111111111`, `0000000000` and `9999999999`
each measure exactly 96px at 16px, so a transposed digit does break the column.
**Severity colours pass in dark** (4.94 / 8.66 / 7.31) and each carries its word.
**Nothing scrolls horizontally at 375px.** Focus rings are correct on every
input, select and button in both themes. The two-column shell lands where
intended, and `LineItemsTable` does have its `overflow-x` wrapper — two standing
controller suspicions, both unfounded in this tree.

### One decision this ADR made that the pass showed is incomplete

**Decision 1 ships dark as a full second theme, and there is no theme control in
the application.** The only ways into dark are the OS preference and setting
`data-theme` by hand. That is not a defect in anything built — every token,
every contrast ratio and the precedence rule are correct and now verified in a
browser — but a second theme a user cannot choose is a half-delivered decision.
**Not fixed here, and deliberately not decided here**: it needs a home for the
control, which is a design question this ADR did not open.

### Still open

Five Important findings (I5 below-the-fold terminal states, I6 the inline
error's grid distance, I7 the silent 401 swap, I8 contradictory reviewer tiles,
I9 the doubled 503 sentence) and seven Minor, all measured and listed in the
report's §3. **I5 and I7 touch ADR-0024's contract**, so neither is a drive-by
fix. Also unproven: Chromium only — intrinsic input widths differ per engine, so
the defect class above is engine-specific — and `prefers-reduced-motion` and
`prefers-contrast` remain unexercised.

## Correction (2026-08-07) — decision 4's two counts, and a finding against decision 2 that does not survive

The whole-branch review at this milestone's close raised three counts here.
**Two are real and are corrected below. The third is not a defect, and the
finding against it is itself an instance of the defect ADR-0028 names** — which
is why it is recorded rather than quietly dropped. Every number below was
re-derived on 2026-08-07 before being written (**ADR-0028** rule 1), with its
method (rule 2). **No decision changes.**

### Corrected: decision 4 is wrong twice in one sentence

| The claim | Measured 2026-08-07 | Method |
|---|---|---|
| "Runtime dependencies are exactly `react` and `react-dom`", and a router "would be the app's **third**" | **Four**, so a router would be the **fifth**: `react`, `react-dom`, `@fontsource/fira-sans`, `@fontsource/fira-code`. **Decision 3 on this same page already says so** — "runtime dependencies go from two to four". | `python -c "import json;print(list(json.load(open('frontend/package.json'))['dependencies']))"` |
| "the **only** pathname read in the app" | **Two.** `session.ts` holds the signed-in guess; `route.ts`'s `currentRoute` takes `window.location.pathname` as a live default parameter. `route.ts`'s own docstring has it right — "the only *other* pathname read in the app is `session.ts`". | `git grep -n "location.pathname" -- frontend/src` — three hits, of which `main.tsx`'s is a comment describing `currentRoute`, not a read. |

**Neither touches the decision.** A pathname switch rather than React Router is
still right: the argument is that a router is a *new* dependency for a handful of
paths, and that holds at four exactly as it held at two.

### Not corrected: "35 custom properties" is right, and the finding against it is not

The review reported decision 2's "one file with **35 custom properties** in three
blocks" as false, measuring **54 declarations / 24 unique names**, and explained
the 35 as borrowed from decision 3's "the built CSS carries 35 `@font-face`
rules" further down this page.

**Re-derived: the ADR is correct and the finding is wrong.**

```
python -c "import re,pathlib; \
 t=re.sub(r'/\*.*?\*/','',pathlib.Path('frontend/src/styles/tokens.css').read_text(encoding='utf-8'),flags=re.S); \
 d=re.findall(r'(--[A-Za-z0-9-]+)\s*:',t); print(len(d),'declarations,',len(set(d)),'unique')"
```

**65 declarations, 35 unique names** — and the three theme blocks are `:root`,
`:root[data-theme='dark']`, and `:root:not([data-theme='light'])` inside the
`prefers-color-scheme` query. The arithmetic checks: 15 colour tokens declared in
each of the three blocks, plus 20 non-colour tokens declared once, is 65
declarations over 35 names.

**Where 54 / 24 came from.** A line-anchored pattern — `^\s*--[a-z]` — counts
only declarations that *begin* a line, and misses the eleven that share a line
with a neighbour (`--text-sm`, `--text-base`, `--text-xl`, `--text-2xl`,
`--space-sm`, `--space-md`, `--space-lg`, `--space-2xl`, `--space-3xl`,
`--radius-md`, `--radius-lg`). 54 + 11 = 65; 24 + 11 = 35. The unique count was
additionally deduplicated *with* its leading whitespace, so identically-named
tokens at different indentation counted twice.

**And the two 35s are unrelated.** `tokens.css` contains **zero** `@font-face`
rules; decision 3's 35 is a count of the *built* CSS, where `@fontsource` emits
them. Two true numbers about two different artefacts happened to coincide, and a
causal story was built on the coincidence — **the same mistake, in the same
review, that ADR-0028's own correction records for the "two different 13s"**. A
matching count is not evidence of a shared origin. That the reviewer hunting this
defect committed it while hunting it is the strongest argument this repository
has for ADR-0028 rule 1 applying to *findings* as well as to claims.

### Citations

**Every line-number citation in this ADR has been removed rather than
repointed** — including the five in the 2026-08-06 Correction's table, which sat
a few lines above that correction's own sentence explaining why *it* deliberately
carries none. Review standard 21 (*a citation is a claim too*) failed inside the
document that best knew better. ADR-0028 §5 is the rule: quote the text, or name
the symbol.

## Correction (2026-08-14) — "Still open" lists four findings that are closed

The *Still open* section above says **"Five Important findings (I5, I6, I7, I8,
I9)"**. One is still open. Re-derived 2026-08-14 from the status-note table in
`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`, which carries a
dated verdict per finding:

| Finding | Verdict there |
|---|---|
| I5 | **FIXED 2026-08-12** — `99f0207`, recorded in **ADR-0041** |
| I6 | **FIXED 2026-08-13** — `e7e5d9e` |
| I7 | **OPEN**, unchanged |
| I8 | **FIXED 2026-08-14** — `3f552d1`, reworded at `7a770c3` |
| I9 | **FIXED 2026-08-14** — the copy at `1322932`, the frame at `fcfc627` |

So **one Important finding, I7, the silent 401 swap**. The seven Minor findings
(m10–m16) are unchanged and still open, so that half of the sentence stands.

The same paragraph's "**I5 and I7 touch ADR-0024's contract**, so neither is a
drive-by fix" keeps only its I7 half — and that half is why I7 is the one left.

**[Corrected 2026-08-14, later the same day. This said "None of the four was
closed by a person looking at it", and cited the I6, I8 and I9 rows as saying
MEASURED, NOT SEEN in as many words.** Both halves died within the day. The
Playwright acceptance run was executed against the merged tree and its captures
were read, so **I6, I8 and I9 have been seen**; those rows no longer carry that
phrase, which is also why the citation had to go rather than be re-aimed.

**The note that records it makes no claim about I5**, so I5's footing is
unchanged by it — which is also why this correction does not say "all four".
The seen-status of **I6, I8 and I9** is in the *SUPERSEDED IN PART* block in §3
of `docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md`, and the widths,
the theme and the one question it opened are deliberately **not** copied into
this ADR. A verdict in two documents is a verdict that can disagree with
itself.**]**

## Correction (2026-08-24) — decision 2's palette values are superseded by ADR-0052; its reasoning is not

**The light palette values quoted in and implied by decision 2 were superseded on
2026-08-24 by ADR-0052**, which retunes the light ramp for the Editorial visual
direction. This is a dated record of what moved, not an edit to any decision.

**All five decisions on this page stand, unchanged.** ADR-0052 changes *values*
on names decision 2 already established, and adds four new non-colour token
names (`--font-display`, `--text-3xl`, `--space-4xl`, `--space-5xl`). It
introduces no new colour token, no second stylesheet and no build-config change,
which is decision 2 continuing to hold rather than being set aside.

Two figures in decision 2's own text are stale as a result, and are recorded here
rather than rewritten above:

| decision 2 says | reads in the tree on 2026-08-24 |
|---|---|
| "**`--color-muted-foreground` is `#475569` in light**" | **`#57534E`** — 7.63:1 on `#FFFFFF`, against `#475569`'s 7.58:1. The *argument* that sentence makes is untouched: the generated `#94A3B8` still fails the body-text rule, and the replacement still clears it comfortably. |
| "one file with **35 custom properties** in three blocks" | **39**, over **69** declarations. The four new names above, declared once each. The 2026-08-07 correction's method still re-derives it: strip comments, match `--name:`, count distinct. |

**Decision 2's reasoning is what forced the new ramp's shape, and is the reason
ADR-0052 exists in the form it does.** *Severity colours are reserved* — "if
amber is the brand colour, a WARN finding has no colour left" — so the reserved
colours could not be retuned to make room for a warmer ground. Measured under
that constraint: `--color-severity-error` `#DC2626` clears the 4.5:1 floor by
**0.12** on the light background (4.62:1 on the old `#F8FAFC`, 4.62:1 on the new
`#FAFAF9`), and `--color-null` cleared it by **0.05** (4.55:1). With that little
headroom the ground **cannot get darker**; it can only change hue at roughly
constant luminance, which is exactly what it did — relative luminance 0.95356
before, 0.95535 after. A ruling made on this page in 2026-08-05 set the shape of
a palette written nineteen days later.

**The dark blocks are byte-identical.** ADR-0052 declines to touch them because
the 2026-08-06 pass above is what backs them, and `--color-null: #7C8CA2` at
**5.43:1** is the subject of a correction on this very page and of a pinned
arithmetic control in `stylesheets.test.ts`. The stated cost is that light now
reads neutral-warm while dark stays blue-slate.

## References

`docs/superpowers/specs/2026-08-05-review-ui-design-system.md` (the design,
with §2's three overrides of the generated system and §9's four rulings);
`docs/superpowers/plans/2026-08-05-review-ui-styling.md`;
`design-system/receipt-review/MASTER.md` (raw generated output);
`.superpowers/sdd/2026-08-05-review-ui-styling/progress.md` (the ledger —
every plan defect and every mutation);
ADR-0012 (the persisted breakdown's `NULL` vs `[]`), ADR-0015, ADR-0017,
ADR-0024, ADR-0026.
