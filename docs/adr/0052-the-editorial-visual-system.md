# ADR 0052 — The Editorial visual system: the ramp changed hue, not brightness

**Status:** Accepted (2026-08-24)
**Builds on:** ADR-0027 (the review UI's design system — all five of its
decisions stand; the palette *values* of its decision 2 are the one thing this
**corrects** — see its `## Correction (2026-08-24)`), ADR-0029 (what the gates
certify — the closing section here is a new instance of its blind spot, measured
on this branch rather than argued)
**Implements:**
`docs/superpowers/specs/2026-08-23-upload-and-visual-refresh-design.md`
(§5, decisions 12 and 13)

**Every value quoted below was read from `frontend/src/styles/tokens.css` and
every ratio re-derived from those values, not transcribed from the plan.** The
plan and this ADR agree; that agreement is a result, not an assumption.

## Context

The owner asked on 2026-08-23 for a refresh that holds up in a live walkthrough,
and chose the direction — **Editorial: document-forward, generous,
hairline-ruled** — with a grotesque display face. The visual system it lands on
is ADR-0027's, which has been in the tree since 2026-08-05 and has since been
verified in a browser (97 screenshots, 64 in-page measurement records).

So the question this ADR answers is not "what should the design system be". It
is: **what part of an accepted, measured, browser-verified design system may a
visual refresh move, and what may it not.** The answer turned out to be narrower
than the direction implied, and the thing that narrowed it was arithmetic that
was already in the tree.

## Decision

### 1. All five of ADR-0027's decisions stand. This changes values, plus four names.

Nothing here reopens any of them:

| ADR-0027 | still stands |
|---|---|
| 1. Light default, dark available — not dark default | yes, and the reason is unchanged: the reviewer's reference truth is a photograph of white receipt paper |
| 2. CSS Modules plus one `tokens.css`, no new runtime dependency | yes — the refresh adds **no** stylesheet and **no** build-config change |
| 3. Fonts self-hosted via `@fontsource`, never a CDN | yes — the display face arrives as `@fontsource/archivo`, imported by weight in `src/main.tsx`, exactly as Fira Sans and Fira Code already are |
| 4. A pathname switch, not React Router | yes — untouched by this work |
| 5. `null` ≠ `0` ≠ empty | yes — and the token that carries it, `--color-null`, moved value but not role |

Decision 2 is the only one whose *content* moves at all, and only in its palette
values. Its **reasoning is not superseded** — see decision 3 below, where that
reasoning is what forces the shape of the new ramp.

`tokens.css` now declares **69 declarations over 39 unique names**, up from
65/35: the two dark blocks still redeclare 15 colours each, and four new
non-colour names were added once. (Re-derive: strip `/* … */` from the file,
match `--name:`, count distinct. `tokens.test.ts` pins `TOKENS.length` at 39.)

### 2. Four new token names, and only four

Read from `tokens.css`:

| name | value | why it is new |
|---|---|---|
| `--font-display` | `'Archivo', 'Fira Sans', system-ui, -apple-system, 'Segoe UI', sans-serif` | there was no display face; `--font-sans` was doing headings |
| `--text-3xl` | `2.5rem` | the scale ran `--text-xl` `1.5rem` → `--text-2xl` `2rem` and stopped, so there was no display step |
| `--space-4xl` | `48px` | the spacing scale stopped at `--space-3xl` `32px`, which is why every screen read tight |
| `--space-5xl` | `64px` | the same, one step further |

**No new colour token is introduced.** Every colour the refresh touches is a
value on a name ADR-0027 already established, which is why the change reaches
almost nothing downstream.

`--space-5xl` is **declared and unused** — `git grep -- '--space-5xl' frontend/src`
returns only its own declaration. Recorded rather than hidden: a token nothing
paints is normally furniture, and it is kept only pending the browser pass of
design decision 14. If that pass does not want it, it should be deleted rather
than left standing.

### 3. The ramp changed hue at roughly constant luminance, because the reserved severity colours have 0.12 of headroom

**This is the load-bearing decision on this page, and it is a measurement, not a
preference.**

`frontend/tests/stylesheets.test.ts` enforces a **4.5:1 contrast floor across all
three theme blocks** — for every rule that sets `color` and `background`
together, and for every inherited colour token against the two surfaces in
`INHERITABLE_SURFACES`, which are `--color-background` and `--color-surface`. It
computes WCAG relative luminance itself and requires every colour token to be a
plain `#RRGGBB`, because anything else makes the arithmetic return `NaN` and
`NaN >= 4.5` is false.

The severity colours are the constraint, and the reason they are is **ADR-0027
decision 2's own argument**: *severity colours are reserved; nothing decorative
may use error red, warn amber or info blue — "if amber is the brand colour, a
WARN finding has no colour left."* That ruling forbids retuning them to buy
room. They are fixed points, and they sit close to the floor:

| pair | ratio | headroom over 4.5 |
|---|---|---|
| `--color-severity-error` `#DC2626` on the **previous** `--color-background` `#F8FAFC` | **4.62:1** | 0.12 |
| `--color-severity-error` `#DC2626` on the **new** `--color-background` `#FAFAF9` | **4.62:1** | 0.12 |
| `--color-null` `#64748B` on the **previous** `--color-background` `#F8FAFC` | **4.55:1** | 0.05 |
| `--color-null` `#78716C` on the **new** `--color-background` `#FAFAF9` | **4.59:1** | 0.09 |

With 0.12 and 0.05 of headroom, **the ground cannot get darker.** Contrast
against a lighter background falls as that background darkens, so any real move
toward a deeper paper tone puts reserved error red under a gate that is already
running. The direction "cool Slate toward warm paper" therefore had to be
executed as **a hue change at roughly constant luminance**, and it was:

- previous `#F8FAFC` relative luminance **0.95356**
- new `#FAFAF9` relative luminance **0.95535**

A lift of 0.0018 — which is why error red reads 4.62:1 on both, to the two
decimal places the suite rounds to. The ramp is warmer and is not brighter or
darker in any way the arithmetic can see.

**The bound is two-sided in practice.** Below, the severity floor. Above,
`--color-surface` is `#FFFFFF` and `--color-surface-raised` is `#FFFDF9`; the
ground has to stay under both or the elevation order inverts and nothing can sit
raised. The background is squeezed into a narrow band and moves sideways within
it. That is the whole content of "a cooled-neutral ramp".

The rest of the light block, read from the tree:

```
--color-background: #FAFAF9;      --color-surface: #FFFFFF;
--color-surface-raised: #FFFDF9;  --color-surface-sunken: #F4F3F0;
--color-foreground: #1C1B19;      --color-muted-foreground: #57534E;
--color-border: #E4E1DB;          --color-primary: #1C1B19;
--color-null: #78716C;
```

`--color-surface-raised` is the one whose *purpose* changed rather than its
shade: it and `--color-surface` were **both `#FFFFFF`**, so nothing in light mode
could sit above anything and the flatness was in the token layer, not in the
components. `tokens.test.ts` gained a pin that reads both values and requires
them different, and that pin was proven red on the pre-refresh file.

Unchanged in light, deliberately: `--color-surface-active` `#EFF6FF` (tied to
`--color-ring` `#2563EB`; ADR-0027 forbids the yellow it replaced, because a
yellow row reads as a warning about that row), `--color-ring`, and all four
reserved colours — `--color-severity-error` `#DC2626`, `--color-severity-warn`
`#B45309`, `--color-severity-info` `#1D4ED8`, `--color-positive` `#15803D`.

The two shadows were re-tinted from neutral black to the foreground's own warm
near-black and given more travel — `--shadow-sm: 0 1px 2px rgba(28,27,25,.06)`
and `--shadow-md: 0 6px 16px rgba(28,27,25,.10)` — so a card reads as an object
on a desk rather than a rectangle with a grey edge.

### 4. The dark blocks were deliberately not touched, and the cost is stated

**Nothing below the light block's closing brace changed.** This is a ruling, not
an oversight, and the reason is that dark is the theme with the evidence behind
it: every dark value is backed by a browser measurement from ADR-0027's
2026-08-06 pass, and one of them is load-bearing twice over.

`--color-null: #7C8CA2` measures **5.43:1** on `--color-surface` `#0E1223`. It
replaced `#64748B`, which was spelled identically in all three blocks and
therefore passed on white (4.76:1) and failed in dark (**3.91:1**) — the one
token that pass found under the floor, on the single glyph carrying the prime
directive. (All three ratios re-derived here; `stylesheets.test.ts` pins each of
them as an arithmetic control.)
That value is the subject of **a recorded correction** (ADR-0027's dated note was
itself corrected on 2026-08-07 from `5.45`, a hand computation with a wrong green
luminance) **and of a pinned arithmetic control** in `stylesheets.test.ts`, which
asserts `contrastRatio('#7C8CA2', '#0E1223')` is exactly `5.43`. Re-tinting dark
would invalidate recorded measurements and move a pinned constant, to buy
coherence in the theme a live walkthrough will not open.

**The cost, stated plainly: light now reads neutral-warm and dark stays
blue-slate. The two themes have different temperaments.** That is a real defect
of coherence, it was accepted knowingly, and it is the browser pass of design
decision 14's job to say how badly it shows. The fix, if it is wanted, is one
line per token — and it is not free, because it lands on the measurements above.

## Consequences

- **The refresh widens the set of sub-floor pairs by nothing.** Re-derived on
  2026-08-24 with `stylesheets.test.ts`'s own `contrastRatio` over both ramps:
  the same five pairs sit under 4.5 before and after, and only light digits
  moved. One of them (`--color-severity-error` on `--color-surface-sunken`, 4.41
  before and 4.35 after) had been missing from that file's recorded list all
  along — worth knowing about a list nothing executes.
- **`--color-null` on `--color-surface-sunken` is thin and carried, not
  introduced**: 4.34:1 before, 4.32:1 after. Ungated, because
  `--color-surface-sunken` is not in `INHERITABLE_SURFACES` and no rule pairs the
  two directly. Flagged for the browser pass; changing it is a separate decision
  about a reserved token.
- **A raised surface is a 1.02:1 lift over `--color-surface`, and the elevation
  is really the shadow.** Whether two cards read as raised is exactly what a text
  gate cannot answer, and at the time of writing nobody has answered it.
- ADR-0027 decision 3's cost line moves again: runtime dependencies go from four
  to five with `@fontsource/archivo`. The decision itself — self-hosted,
  lockfile-pinned, never a CDN — is unchanged and is the reason the display face
  arrives this way at all.

## What no gate can see

Recorded here because it is the honest description of what this milestone
guarantees, and because it was **proven by execution rather than assumed**.

`frontend/tests/stylesheets.test.ts` is a census: it pins declarations **by
name**, and quantities by presence only. Vitest runs with `css: false`, so a
`.module.css` import returns a proxy whose keys echo back; jsdom lays nothing
out. So the census can tell you that `.heading` has a `font-family` and that
`.field` has a `box-shadow`. It cannot tell you that the heading is larger, that
the padding is deeper, or that the surface is the raised one.

During the second task of this milestone, `UploadScreen.module.css` was mutated
to revert all three quantities while leaving every declaration name in place:

```
padding: var(--space-4xl) var(--space-2xl);   ->  padding: var(--space-2xl);
font-size: var(--text-3xl);                   ->  font-size: var(--text-2xl);
background: var(--color-surface-raised);      ->  background: var(--color-surface);
```

Valid CSS and valid token names, so a red could not have come from a syntax
error. **All five gates stayed green.** The entire visible effect of that task
reverts without anything noticing.

**The one part of the ramp that *is* gated is its brightness, and only against
two surfaces.** The 4.5:1 floor runs in all three theme blocks — that is what
makes decision 3 above a constraint rather than a preference — but
`INHERITABLE_SURFACES` holds exactly `--color-background` and `--color-surface`.
**`--color-surface-raised`, `--color-surface-active` and `--color-surface-sunken`
are outside it.** Spacing, radii, type sizes and shadows are ungated entirely.

So the accurate summary of this ADR's guarantees is: *the ramp's brightness is
held by arithmetic; its hue, its spacing, its type scale and its elevation are
held by nobody having edited them.* That is ADR-0029's blind spot at full scale,
and it is why design decision 14 puts a browser pass **inside** this milestone
rather than after it. **The milestone is not done when the gates pass; it is done
when someone has looked.**

## What this ADR does not decide

Whether any of it looks right. Nothing here has been seen at 1440, 768 or 375, in
either theme, by a person. Specifically open for that pass: whether `#FFFDF9` on
`#FAFAF9` reads as raised or as flat; whether the warm ground sits acceptably
next to the four reserved colours it deliberately did not move; how badly the
warm-light/cool-dark split shows; and whether `--space-4xl` clips or scrolls
anything at the two narrow widths.

## References

`docs/superpowers/specs/2026-08-23-upload-and-visual-refresh-design.md` (§5
decisions 12–13, §7 and its 2026-08-24 dated correction — the gated/ungated
split);
`docs/superpowers/plans/2026-08-24-editorial-visual-refresh.md` (the six tasks
and the measured ramp);
`docs/superpowers/specs/2026-08-05-review-ui-browser-pass.md` (the dark
measurements decision 4 above declines to invalidate);
ADR-0027 (the system this extends), ADR-0029 (what the gates certify).
