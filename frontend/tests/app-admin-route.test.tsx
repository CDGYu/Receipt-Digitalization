import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { currentRoute } from '../src/route'
import type { Route } from '../src/route'

/** Is every screen actually reachable from the tree `main.tsx` renders?
 *
 * `admin-screen.test.tsx` proves `AdminScreen` works and that `currentRoute`
 * maps `/app/admin`; neither says anything about whether the entry point ever
 * puts the two together. **Measured before this file existed** -- the same
 * measurement `app-header.test.tsx` records for `SignOutControl`, run again for
 * Task 4's own deliverable: with the import and the route branch deleted from
 * `main.tsx`, so that `App` renders `<ReviewScreen />` unconditionally,
 * `tsc -b` exits 0, `oxlint` reports only its pre-existing fast-refresh warning,
 * and **all 316 tests pass**. The whole `/app/admin` surface could be built,
 * merged and then quietly unreachable, with every gate green.
 *
 * **The same hole was measured again for `/app/receipts` on 2026-08-19**, and the
 * answer had not changed: with the `ReceiptsScreen` import and the
 * `route === 'receipts'` branch removed from `main.tsx`, `tsc -b` exits 0 and
 * **all 422 tests in 29 files pass**. Task 6 had built the results list -- a
 * paginated table, an export button, its own stylesheet, tests of its own -- and
 * nothing in the suite could tell that no user could reach it. The compile
 * staying clean is what makes it damning: the deletion is not a mistake any gate
 * treats as one.
 *
 * **And a third time, for `/app/upload` on 2026-08-24, with this file already
 * standing and two cases closed in it.** The `UploadScreen` import and the
 * `route === 'upload'` branch were deleted from `main.tsx`, and **all 454 tests
 * in 31 files passed, `tsc -b` exited 0, `oxlint` reported only its pre-existing
 * fast-refresh warning, and `vite build` succeeded.**
 *
 * ## Why this file is one property and not a list of cases
 *
 * The first answer to that measurement was one more hand-written case, which
 * reproduces the defect it was written for: the next route ships unguarded until
 * somebody remembers, which is precisely how `/app/upload` shipped unguarded --
 * *here*, with `/app/admin` and `/app/receipts` already closed above it. An
 * enumerated defence never converges.
 *
 * So the claim below is one sentence over a derived list:
 *
 * > **Every `/app/` path literal `route.ts` declares mounts the screen
 * > `currentRoute` names for it, and mounts no other screen.**
 *
 * Neither half is retyped here. The literals are read out of `route.ts`'s own
 * source with the same regex `admin-screen.test.tsx` uses for the no-dot rule --
 * that file applies it to path *shape*, this one applies it to *mounting*. The
 * expected screen comes from `SCREEN`, which is a `Record<Route, string>`: a
 * sixth member on the `Route` union fails `tsc -b` here until it has an entry,
 * so the mapping is held by the compiler rather than by memory. A route added to
 * `route.ts` is therefore covered on the day its literal is declared, with
 * nothing here to remember to add.
 *
 * **What this does not claim.** It says a literal mounts the screen the route
 * mapping names; it does not say the mapping is right. That is
 * `admin-screen.test.tsx`'s property, asserted there by name, and the division
 * is deliberate: this file would otherwise re-derive the switch it is testing.
 *
 * Path literals inside BLOCK comments are stripped before matching, because a
 * path written in prose is not a route this switch can mount. Line comments are
 * NOT stripped, and `route.ts` uses them throughout `currentRoute` -- so a
 * single-quoted `/app/` path written in a `//` comment would become a row here.
 * None is: stripping line comments as well yields the identical list, checked
 * rather than assumed. `admin-screen.test.tsx`'s read of `route.ts` strips
 * nothing, so its list can differ from this one; that file states no intent
 * either way, and this sentence is not one on its behalf. (It does strip
 * comments elsewhere, in its stylesheet census -- the unqualified claim that
 * it "strips nothing at all" was false, and only its `route.ts` read was ever
 * meant.)
 *
 * **There are two fall-throughs and they land on different screens.** Say which
 * one you mean, always:
 *
 *   * `route.ts`'s **route-resolution** default is `home` -- what an
 *     unrecognised *path* resolves to. Executed: `/app/`, `/`, `/app/xyz` all
 *     give `home`.
 *   * `main.tsx`'s **render fallback** is the terminal `else` of its ternary
 *     chain, and it is `<ReviewScreen />` -- what a *route with no branch*
 *     renders. Executed by deleting the `route === 'admin'` branch: `/app/admin`
 *     renders **the review screen**, not the home screen.
 *
 * `/app/` is not among the literals: `home` is the route-resolution default and
 * `route.ts` declares no string for it. The last case below covers it. But the
 * reason every case here asserts the expected screen **by name** rather than
 * "not the admin screen" is the *second* fall-through -- an unmounted route
 * does not throw, it quietly serves the review screen.
 *
 * `3f58425` moved the first of those two and left the second where it was. A
 * sweep that rewrote "the review queue" to "the landing screen" by vocabulary
 * broke this sentence, because the two fall-throughs share every word and only
 * a mutation tells them apart.
 *
 * Every screen is mocked, and that is the point rather than a shortcut: what is
 * under test is the *switch*, not any one of the components. A real
 * `AdminScreen` here would pass for the wrong reason the day it renders an empty
 * state that happens to look like a review screen, and a real `ReviewScreen`
 * would fire requests that have nothing to do with routing.
 *
 * `LoginPage` is mocked too, and it is the one screen the route chain never
 * reaches: `session.ts:23` seeds `signedIn` from the pathname, so `/app/login`
 * takes `App`'s early return instead. Leaving it real would have made the
 * `/app/login` row assert against a live form; including it in `SCREEN` is what
 * lets the property cover the login route like any other, with no carve-out.
 *
 * Both directions are asserted for every row: a switch that renders one screen
 * everywhere is as broken as one that renders it nowhere, and only the negative
 * half tells them apart. The negative half here is every *other* value of
 * `SCREEN`, so it grows with the union too.
 *
 * The mocks are file-scoped, which is why this is its own file -- the same
 * reason `app-root.test.tsx` and `app-header.test.tsx` are theirs.
 */
vi.mock('../src/review/ReviewQueue', () => ({
  ReviewQueue: () => <p>the review queue</p>,
}))

vi.mock('../src/review/ReviewScreen', () => ({
  ReviewScreen: () => <p>the review screen</p>,
}))

vi.mock('../src/admin/AdminScreen', () => ({
  AdminScreen: () => <p>the admin screen</p>,
}))

vi.mock('../src/receipts/ReceiptsScreen', () => ({
  ReceiptsScreen: () => <p>the receipts screen</p>,
}))

vi.mock('../src/upload/UploadScreen', () => ({
  UploadScreen: () => <p>the upload screen</p>,
}))

vi.mock('../src/processing/ProcessingListScreen', () => ({
  ProcessingListScreen: () => <p>the processing screen</p>,
}))

vi.mock('../src/login/LoginPage', () => ({
  LoginPage: () => <p>the login page</p>,
}))

vi.mock('../src/home/HomeScreen', () => ({
  HomeScreen: () => <p>the home screen</p>,
}))

/** What each route must put on the page, one entry per `Route` member.
 *
 * `Record<Route, string>` and not a partial: a NEW member on the union is a
 * `tsc -b` failure here until it is given a screen, which is the half of this
 * property a test run cannot enforce on its own. (This said "a sixth member"
 * while the union had six; the count was true when written and stopped being
 * true the moment the property it describes did its job. The rule does not
 * depend on how many there are, so it no longer says.) */
const SCREEN: Record<Route, string> = {
  login: 'the login page',
  home: 'the home screen',
  review: 'the review screen',
  queue: 'the review queue',
  admin: 'the admin screen',
  receipts: 'the receipts screen',
  upload: 'the upload screen',
  processing: 'the processing screen',
}

/** Every `/app/` path literal `route.ts` declares, read from its source.
 *
 *  Block comments are stripped first, and only those; see the header. The
 *  regex is the one `admin-screen.test.tsx` uses on the same file for the
 *  no-dot rule. */
const LITERALS: readonly string[] = (() => {
  const source = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'route.ts'),
    'utf8',
  ).replace(/\/\*[\s\S]*?\*\//g, '')
  return [...source.matchAll(/'(\/app\/[^']*)'/g)].map((match) => match[1])
})()

let consoleError: ReturnType<typeof vi.spyOn>
let root: HTMLDivElement

beforeEach(() => {
  // React logs the missing-`act` warning through `console.error`; `main.tsx`
  // renders itself on import and there is no `act` to wrap that in.
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  // A fresh module graph per test: `main.tsx` renders on import, `session.ts`
  // reads the path once at module scope, and `currentRoute()` is read during the
  // render that import performs.
  vi.resetModules()
  root = document.createElement('div')
  root.id = 'root'
  document.body.append(root)
  // `App` hydrates the identity on mount. Rejecting is the honest stub for a
  // suite with no server: `hydrateIdentity` catches it and resolves, leaving the
  // identity null, and an unstubbed `fetch` would make that a network error
  // rather than a readable failure.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
})

afterEach(() => {
  consoleError.mockRestore()
  vi.unstubAllGlobals()
  vi.resetModules()
  root.remove()
  window.history.pushState({}, '', '/')
})

/** The one assertion, both directions: this screen and no other. */
async function expectOnly(route: Route): Promise<void> {
  expect(await screen.findByText(SCREEN[route])).toBeDefined()
  for (const [other, text] of Object.entries(SCREEN)) {
    if (other !== route) {
      expect(screen.queryByText(text), `${text} rendered as well`).toBeNull()
    }
  }
}

describe('the app entry point routes by pathname', () => {
  it('reaches every route the union declares, from the literals alone', () => {
    // The anti-vacuity control, and the half that makes the property below
    // converge rather than merely pass. A regex that stopped matching would
    // leave the `it.each` with nothing to run and this file would still be
    // green -- the failure mode of every derived list.
    //
    // Stated as coverage rather than as a count, because a count is what this
    // file is getting away from: `home` aside, every member of `Route` must be
    // the route of some literal `route.ts` declares. So a sixth member that is
    // typed but never routed fails HERE, and a sixth member with no screen fails
    // `tsc -b` on `SCREEN` -- measured 2026-08-24 by adding `'settings'` to the
    // union: `TS2741: Property 'settings' is missing in type ... but required in
    // type 'Record<Route, string>'`.
    expect(LITERALS.length, 'no /app/ path literal was found in route.ts at all').toBeGreaterThan(0)
    // `home` has no literal by design: it is the fall-through, covered by the
    // last case below rather than by a declared path. That seed was `review`
    // until 2026-08-24, when `/app/` became a landing screen: `home` took the
    // default and `review` gained the explicit `/app/review` branch it had
    // never needed while it *was* the default. So the exemption moved with the
    // fall-through rather than staying attached to a route name.
    const reached = new Set<string>(['home', ...LITERALS.map((literal) => currentRoute(literal))])
    expect(
      Object.keys(SCREEN).filter((route) => !reached.has(route)),
      'a Route member is declared and no /app/ literal reaches it, so nothing below mounts it',
    ).toEqual([])
  })

  it.each(LITERALS)('mounts the screen %s asks for, and nothing else', async (literal) => {
    window.history.pushState({}, '', literal)

    await import('../src/main')

    await expectOnly(currentRoute(literal))
  })

  it('renders the home screen everywhere else', async () => {
    // jsdom serves "/", which `currentRoute` maps to `home` by default. This is
    // the one route with no literal to derive, because it is the fall-through
    // rather than a declared path -- and the fall-through moved from `review`
    // to `home` when `/app/` became a landing screen. `/app/review` gained an
    // explicit branch in the same change, so review is no longer reachable this
    // way at all.
    await import('../src/main')

    await expectOnly('home')
  })
})
