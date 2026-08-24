import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Nav } from '../src/Nav'

/** The navigation, as a signed-in person meets it.
 *
 * Before this component existed the app had exactly one `<a href>` in its
 * whole source -- `upload/ProcessingView.tsx`'s link into review, which appears
 * only after an upload finishes. Every other screen was reachable only by
 * typing its URL, including the upload screen a receipt has to enter through.
 * That is what these tests pin: not that a nav renders, but that each screen
 * has a way in.
 *
 * `route` is a prop rather than a `currentRoute()` call inside the component.
 * `main.tsx`'s docstring promises the pathname is read exactly once per render,
 * and a second read here would quietly falsify it.
 *
 * Nothing here asserts a class name against the DOM. Vitest runs with
 * `css: false`, so a `.module.css` import is a proxy that echoes its keys back
 * -- `styles.typo` renders as `class="typo"` here and as `class="undefined"` in
 * a real build. The last test in this file is the one that can see that, and it
 * reads both files as text.
 */

afterEach(cleanup)

describe('Nav', () => {
  it('links to every screen a reviewer can reach', () => {
    render(<Nav identity={{ username: 'alice', role: 'reviewer' }} route="review" />)

    expect(screen.getByRole('link', { name: 'Upload' }).getAttribute('href')).toBe('/app/upload')
    expect(screen.getByRole('link', { name: 'Review' }).getAttribute('href')).toBe('/app/review')
    expect(screen.getByRole('link', { name: 'Results' }).getAttribute('href')).toBe('/app/receipts')
  })
})

describe('the admin link', () => {
  it('is offered to an admin and to nobody else', () => {
    // Gated positively on `role === 'admin'`, the way ReceiptsScreen gates its
    // export button: `role` is a `string` on the wire, so a `!== 'reviewer'`
    // test would hand an unrecognised role the admin link.
    render(<Nav identity={{ username: 'root', role: 'admin' }} route="review" />)
    expect(screen.getByRole('link', { name: 'Admin' }).getAttribute('href')).toBe('/app/admin')

    cleanup()
    render(<Nav identity={{ username: 'alice', role: 'reviewer' }} route="review" />)
    expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull()

    // An identity that has not arrived yet is not an admin. `session.ts` starts
    // it at `null` and `hydrateIdentity` fills it in one round trip later, so
    // this is the state every cold load passes through.
    cleanup()
    render(<Nav identity={null} route="review" />)
    expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull()
  })
})

describe('the current page', () => {
  it('is marked on the link that leads to it, and on no other', () => {
    render(<Nav identity={{ username: 'alice', role: 'reviewer' }} route="upload" />)

    expect(screen.getByRole('link', { name: 'Upload' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: 'Review' }).getAttribute('aria-current')).toBeNull()
    expect(screen.getByRole('link', { name: 'Results' }).getAttribute('aria-current')).toBeNull()
  })

  it('marks Review on the landing path, which routes there by default', () => {
    // `route.ts` returns 'review' for any path it does not recognise, so `/app/`
    // -- the URL a person actually lands on -- arrives here as 'review'. If the
    // marking keyed off the pathname instead of the route, the landing page
    // would show nothing marked at all.
    render(<Nav identity={{ username: 'alice', role: 'reviewer' }} route="review" />)

    expect(screen.getByRole('link', { name: 'Review' }).getAttribute('aria-current')).toBe('page')
  })
})

describe('the stylesheet and the component agree', () => {
  it('names no class the stylesheet does not define', () => {
    // The failure this exists to catch: Vitest runs with `css: false`, so a
    // `.module.css` import is a proxy that echoes its keys. `styles.typo`
    // renders as `class="typo"` under every test above and as
    // `class="undefined"` in a real build, unstyled and silent. `value.test.tsx`
    // holds this guard for the components in its own COMPONENTS list and is
    // explicitly bounded to them ("it covers the components in COMPONENTS and
    // nothing else"), so a new component arrives unguarded unless it brings
    // its own -- which is exactly how `login/LoginPage.module.css` shipped.
    const here = dirname(fileURLToPath(import.meta.url))
    const css = readFileSync(join(here, '..', 'src', 'Nav.module.css'), 'utf8')
    // Both importers, not just the component: `main.tsx` reads the bar class off
    // this same stylesheet, and a typo there is the identical silent failure.
    const sources = ['Nav.tsx', 'main.tsx'].map((name) =>
      readFileSync(join(here, '..', 'src', name), 'utf8'),
    )

    const referenced = sources.flatMap((source) =>
      [...source.matchAll(/navStyles\.([A-Za-z0-9_]+)|styles\.([A-Za-z0-9_]+)/g)].map(
        (m) => m[1] ?? m[2],
      ),
    )

    // The anti-vacuity bound. Without it this test passes on a component that
    // references no class at all -- which is the state it was written against.
    expect(referenced.length).toBeGreaterThan(0)

    // Every class name the stylesheet actually defines, read once. A selector
    // is matched by its terminator so that `.link` does not satisfy a reference
    // to `.li`, which a bare `includes` would let through.
    const defined = new Set(
      [...css.matchAll(/\.([A-Za-z0-9_-]+)(?=[\s,:{])/g)].map((m) => m[1]),
    )

    for (const name of referenced) {
      expect(
        defined.has(name),
        `styles.${name} has no .${name} rule -- it ships as class="undefined"`,
      ).toBe(true)
    }
  })
})
