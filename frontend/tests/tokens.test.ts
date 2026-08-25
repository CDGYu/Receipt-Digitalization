// @vitest-environment node
//
// A filesystem read of the stylesheet as text, so jsdom buys nothing -- and
// under it this file cannot work at all. Vite rewrites the *pattern*
// `new URL(specifier, import.meta.url)` into a static-asset URL, which the
// jsdom environment then resolves against the document base instead of the
// filesystem; `readFileSync` is handed an http:// URL and dies with
// `TypeError: The URL must be of scheme file` before a single assertion runs.
// (`import.meta.url` on its own is a file:// URL in both environments; it is
// the surrounding `new URL(...)` that is transformed.)
// `tests/no-float-in-money-path.test.ts` carries the same directive for the
// same reason -- though its docblock states a different cause.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const raw = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8')
const main = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8')

/** The stylesheet with comments removed.
 *
 * Every structural assertion below runs against this rather than `raw`, because
 * this file's own prose mentions the selectors it documents. Review round 1
 * found that literally: `raw.indexOf("[data-theme='dark']")` matches the
 * *comment* above the media query, so deleting the entire dark block left the
 * old version of this suite green. Prose cannot be allowed to answer for code.
 */
const css = raw.replace(/\/\*[\s\S]*?\*\//g, '')

const LIGHT = ':root'
const DARK_ATTR = ":root[data-theme='dark']"
const DARK_MEDIA = ":root:not([data-theme='light'])"

/** The body of the one rule whose selector is exactly `selector`, bounded at
 *  that rule's own closing brace.
 *
 *  **Bounded, not sliced to end of file.** The predecessor of this helper was
 *  `css.slice(css.indexOf(...))`, which ran to EOF and so let a token defined
 *  in any *later* block answer for this one -- with the result that deleting a
 *  token from the `data-theme` block was undetectable, because the
 *  `prefers-color-scheme` copy below it still contained the name.
 *
 *  Anchored on `selector + ' {'` -- the declaration -- rather than on a bare
 *  substring, so `:root` cannot match `:root[data-theme='dark']` and no
 *  selector can be satisfied by a mention of it somewhere else. */
function block(selector: string): string {
  const at = css.indexOf(`${selector} {`)
  if (at === -1) {
    throw new Error(`no rule with the selector \`${selector}\``)
  }
  const open = css.indexOf('{', at)
  const close = css.indexOf('}', open)
  if (close === -1) {
    throw new Error(`unterminated block for \`${selector}\``)
  }
  return css.slice(open + 1, close)
}

/** Every `property: value;` declaration in a chunk of CSS.
 *
 *  Scans *declarations*, not lines. `tokens.css` uses several declarations on
 *  one line as house style (the type and spacing scales), and a line-anchored
 *  regex silently captures only the first of each -- so `--text-sm`,
 *  `--space-sm` and six others were invisible to the previous version of this
 *  guard. Nothing enforces that convention, so the parser must not depend on
 *  it either way. Pinned by `it('reads every declaration ...')` below.
 *
 *  `var(--x)` references are not declarations and do not appear here: the name
 *  inside `var(...)` is followed by `)`, not `:`. */
function declarations(source: string): Map<string, string> {
  const found = new Map<string, string>()
  for (const [, name, value] of source.matchAll(/([\w-]+)\s*:\s*([^;]+);/g)) {
    found.set(name, value.trim())
  }
  return found
}

const customProperties = (source: string): string[] =>
  [...declarations(source).keys()].filter((name) => name.startsWith('--'))

/** Every token design §3 names, by section. Test 1 asserts each is *declared*
 *  -- name plus colon -- rather than merely present as a substring, which is
 *  what let `--color-surface-raised` answer for a deleted `--color-surface`. */
const TOKENS: readonly string[] = [
  // §3.1 typography, plus the Editorial display face and its headline step
  '--font-sans', '--font-display', '--font-mono',
  '--text-xs', '--text-sm', '--text-base', '--text-lg', '--text-xl', '--text-2xl',
  '--text-3xl',
  // §3.2 colour, plus the two surfaces added by the round-1 controller ruling
  '--color-background', '--color-surface', '--color-surface-raised',
  '--color-surface-active', '--color-surface-sunken',
  '--color-foreground', '--color-muted-foreground', '--color-border',
  '--color-primary', '--color-ring', '--color-severity-error',
  '--color-severity-warn', '--color-severity-info', '--color-positive',
  '--color-null',
  // §3.3 spacing, radii, elevation
  '--space-xs', '--space-sm', '--space-md', '--space-lg', '--space-xl',
  '--space-2xl', '--space-3xl', '--space-4xl', '--space-5xl',
  '--radius-sm', '--radius-md', '--radius-lg',
  '--shadow-sm', '--shadow-md',
]

describe('the guard is not passing vacuously', () => {
  it('reads every declaration on a line, not just the first', () => {
    // The house style this parser must survive: `tokens.css` puts three type
    // steps on one line. A `^\s*(--[\w-]+):`-style regex sees only `--text-xs`.
    const scale = declarations(block(LIGHT))
    expect(scale.get('--text-xs')).toBe('0.75rem')
    expect(scale.get('--text-sm'), 'second declaration on its line went unseen').toBe('0.875rem')
    expect(scale.get('--text-base'), 'third declaration on its line went unseen').toBe('1rem')
    expect(scale.get('--space-lg'), 'fourth declaration on its line went unseen').toBe('12px')

    // ...and the parser is reading a real file, not an empty string.
    expect(customProperties(block(LIGHT)).length).toBeGreaterThan(30)
  })

  it('bounds a block at its own closing brace', () => {
    // If `block` ran to EOF, every "the `:root` block says X" assertion below
    // would be answerable by any *later* rule in the file.
    //
    // **Re-anchored when the dark theme was removed.** This used to bound
    // `:root` against the dark block that followed it; with no second token
    // block, `body` is the neighbour that proves the bound. `margin` is
    // declared only there -- if it leaks into `block(LIGHT)`, the helper is
    // running past its own closing brace.
    //
    // The positive canary is the token's NAME, not a hex. It read `#FAFAF9`,
    // the current `--color-background`, which pins the palette to a value and
    // reports a bounding bug the moment anyone re-themes -- measured: a palette
    // edit broke this test while nothing about the bound had changed.
    expect(block(LIGHT)).toContain('--color-background')
    expect(block(LIGHT), 'the `:root` block leaked into `body`').not.toContain('margin')
    expect(block('body')).toContain('margin')
    expect(block('body'), '`body` leaked into a later rule').not.toContain('outline')
  })

  it('ignores prose, so a comment cannot satisfy a structural assertion', () => {
    // The exact hole round 1 found: this file's own comments name the dark
    // selector, so the un-stripped source "contains" it even with every dark
    // rule deleted.
    //
    // **Re-anchored when the dark theme was removed, and the removal turned
    // this test into a sharper version of itself.** It used to assert that
    // `raw` and `css` BOTH contained `data-theme` -- true while the rule
    // existed, and it only proved stripping left the rule alone. Now the
    // selector appears in the prose and nowhere else, so the two sources
    // genuinely disagree, which is the property being tested: `raw` has it,
    // `css` must not. That disagreement is also exactly what
    // `ships NO dark theme` depends on -- without stripping, that test could
    // never pass while `tokens.css` explains why the theme is gone.
    expect(raw, 'the prose no longer names the selector, so this proves nothing').toContain(
      'data-theme',
    )
    expect(css, 'comments were not stripped').not.toContain('data-theme')
    expect(css, 'a comment survived stripping').not.toContain('on purpose')
  })
})

describe('tokens.css', () => {
  it('defines every token the design system names', () => {
    const declared = declarations(block(LIGHT))
    for (const token of TOKENS) {
      expect(declared.has(token), `${token} is not declared in the ${LIGHT} block`).toBe(true)
    }
    expect(TOKENS.length).toBe(39)
  })

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

  it('ships NO dark theme, by either route', () => {
    // Owner ruling: light only. Three tests used to live here asserting the
    // dark theme was complete, agreed with its media copy, and could be beaten
    // by an explicit light choice. They are replaced by one asserting it is
    // gone.
    //
    // **Both routes, because deleting one changes nothing a viewer sees.** The
    // theme chooser went at `824bf46`, so nothing writes `data-theme`; that
    // left `prefers-color-scheme` as the only *live* route to dark, silently
    // following the OS with no way off. An attribute-only removal would have
    // been invisible.
    //
    // `css` is comment-stripped (see its definition), which is what lets
    // `tokens.css` go on NAMING both selectors in the prose that explains why
    // they are gone. Without the stripping this test and that comment could not
    // both exist.
    expect(css, 'a data-theme rule is still in the stylesheet').not.toContain('data-theme')
    // Both dead selectors named by their constants rather than as loose
    // strings. `DARK_ATTR` was left declared and unused when the three dark
    // tests went, which is a `tsc -b` failure (TS6133) and NOT one any Vitest
    // run reports -- `vitest` type-checks nothing. It shipped green through a
    // full `npm test` and was caught by the typecheck gate afterwards.
    expect(css, `${DARK_ATTR} is still in the stylesheet`).not.toContain(DARK_ATTR)
    expect(css, `${DARK_MEDIA} is still in the stylesheet`).not.toContain(DARK_MEDIA)
    expect(css, 'a prefers-color-scheme: dark rule is still in the stylesheet').not.toMatch(
      /@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)/,
    )
    // Not vacuous: the file is real, has rules, and still has the OTHER media
    // query. An empty or unreadable file would satisfy both assertions above.
    expect(customProperties(block(LIGHT)).length).toBeGreaterThan(30)
    expect(css, 'the whole file went missing').toContain('prefers-reduced-motion')
  })

  it('tells the user agent which palette its own widgets should use', () => {
    // Without `color-scheme` the UA paints scrollbars, form controls, autofill
    // and spellcheck underlines from the OS preference -- so on a dark-set
    // machine a light-only page still gets dark widgets, which reads as a bug
    // rather than a preference. This declaration is what makes "light only"
    // true for the parts of the page this stylesheet does not paint.
    expect(declarations(block(LIGHT)).get('color-scheme')).toBe('light')
  })

  it('never reaches the network for a font', () => {
    // A CDN @import renders fallback fonts exactly where this app is deployed
    // (LAN, offline suite) -- design section 2.3.
    expect(css).not.toMatch(/@import\s+url\(\s*['"]?https?:/)
    expect(css).not.toContain('fonts.googleapis.com')
  })

  it('self-hosts every weight the design uses, from the entry module', () => {
    // Nothing else reads main.tsx as text, so without this a later task can
    // delete an @fontsource import and every gate stays green while the app
    // silently renders in the fallback stack -- the exact failure design §2.3
    // exists to prevent.
    for (const specifier of [
      '@fontsource/fira-sans/400.css',
      '@fontsource/fira-sans/500.css',
      '@fontsource/fira-sans/600.css',
      '@fontsource/fira-code/400.css',
      '@fontsource/fira-code/500.css',
      '@fontsource/archivo/600.css',
      '@fontsource/archivo/700.css',
    ]) {
      expect(main, `main.tsx does not import ${specifier}`).toContain(`import '${specifier}'`)
    }
    expect(main, 'main.tsx does not import the tokens').toContain("import './styles/tokens.css'")
  })

  it('respects prefers-reduced-motion', () => {
    expect(css).toContain('prefers-reduced-motion')
  })
})
