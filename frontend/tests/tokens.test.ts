// @vitest-environment node
//
// A filesystem read of the stylesheet as text, so jsdom buys nothing -- and
// under it this file cannot work at all. Vite rewrites the *pattern*
// `new URL(specifier, import.meta.url)` into a static-asset URL, which the
// jsdom environment then resolves against the document base: measured, the
// expression below yields `http://localhost:3000/src/styles/tokens.css` and
// `readFileSync` dies with `TypeError: The URL must be of scheme file` before a
// single assertion runs. (`import.meta.url` on its own is a file:// URL in both
// environments; it is the surrounding `new URL(...)` that is transformed.)
// `tests/no-float-in-money-path.test.ts` carries this same docblock for the
// same reason.
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
