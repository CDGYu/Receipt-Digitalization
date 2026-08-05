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
  // §3.1 typography
  '--font-sans', '--font-mono',
  '--text-xs', '--text-sm', '--text-base', '--text-lg', '--text-xl', '--text-2xl',
  // §3.2 colour, plus the two surfaces added by the round-1 controller ruling
  '--color-background', '--color-surface', '--color-surface-raised',
  '--color-surface-active', '--color-surface-sunken',
  '--color-foreground', '--color-muted-foreground', '--color-border',
  '--color-primary', '--color-ring', '--color-severity-error',
  '--color-severity-warn', '--color-severity-info', '--color-positive',
  '--color-null',
  // §3.3 spacing, radii, elevation
  '--space-xs', '--space-sm', '--space-md', '--space-lg', '--space-xl',
  '--space-2xl', '--space-3xl',
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
    // If `block` ran to EOF this would contain the dark values too, and every
    // "the light theme says X" assertion would be meaningless.
    expect(block(LIGHT)).toContain('#F8FAFC')
    expect(block(LIGHT), 'the light block leaked into the dark one').not.toContain('#020617')
    expect(block(DARK_ATTR)).toContain('#020617')
    expect(block(DARK_ATTR), 'the dark block leaked into the media copy').not.toContain(
      'prefers-color-scheme',
    )
  })

  it('ignores prose, so a comment cannot satisfy a structural assertion', () => {
    // The exact hole round 1 found: this file's own comments name the dark
    // selector, and the un-stripped source therefore "contains" it even with
    // every rule deleted.
    expect(raw).toContain(`${DARK_ATTR} {`)
    expect(css.indexOf(DARK_ATTR), 'comments were not stripped').toBeGreaterThan(-1)
    expect(css, 'a comment survived stripping').not.toContain('load-bearing')
  })
})

describe('tokens.css', () => {
  it('defines every token the design system names', () => {
    const declared = declarations(block(LIGHT))
    for (const token of TOKENS) {
      expect(declared.has(token), `${token} is not declared in the ${LIGHT} block`).toBe(true)
    }
    expect(TOKENS.length).toBe(35)
  })

  it('ships a dark theme for every colour the light theme defines', () => {
    const light = customProperties(block(LIGHT)).filter((t) => t.startsWith('--color-'))
    const dark = customProperties(block(DARK_ATTR))
    expect(light.length, 'no light colours found -- the guard is vacuous').toBeGreaterThan(10)
    for (const token of light) {
      expect(dark, `${token} has no value in the ${DARK_ATTR} block`).toContain(token)
    }
  })

  it('resolves dark from the OS preference with the same values, never different ones', () => {
    // Two routes to one theme. A drift is invisible on any single machine --
    // you would have to toggle the OS setting *and* the attribute to see it.
    expect([...declarations(block(DARK_MEDIA))].sort()).toEqual(
      [...declarations(block(DARK_ATTR))].sort(),
    )
  })

  it('lets an explicit light choice beat an OS dark preference', () => {
    // `:root:not([data-theme='light'])` is the whole mechanism: a bare `:root`
    // makes the OS setting unbeatable, and a bare attribute selector makes it
    // unreachable. Pin the selector text, not just the presence of a block.
    const media = css.match(/@media\s*\(\s*prefers-color-scheme:\s*dark\s*\)\s*\{\s*([^{]+?)\s*\{/)
    expect(media, 'no prefers-color-scheme: dark rule at all').not.toBeNull()
    expect(media?.[1]).toBe(DARK_MEDIA)
  })

  it('tells the user agent which palette its own widgets should use', () => {
    // Without `color-scheme` the UA paints scrollbars, form controls and
    // autofill from the light palette however dark the page is.
    expect(declarations(block(LIGHT)).get('color-scheme')).toBe('light')
    expect(declarations(block(DARK_ATTR)).get('color-scheme')).toBe('dark')
    expect(declarations(block(DARK_MEDIA)).get('color-scheme')).toBe('dark')
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
    ]) {
      expect(main, `main.tsx does not import ${specifier}`).toContain(`import '${specifier}'`)
    }
    expect(main, 'main.tsx does not import the tokens').toContain("import './styles/tokens.css'")
  })

  it('respects prefers-reduced-motion', () => {
    expect(css).toContain('prefers-reduced-motion')
  })
})
