import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** Is the admin surface actually reachable from the tree `main.tsx` renders?
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
 * paginated table, an export button, its own stylesheet, 22 tests of its own --
 * and nothing in the suite could tell that no user could reach it. The compile
 * staying clean is what makes it damning: the deletion is not a mistake any gate
 * treats as one. The third case below closes that, and was proved red by exactly
 * that deletion rather than by reasoning about it.
 *
 * All three screens are mocked, and that is the point rather than a shortcut:
 * what is under test is the *switch*, not any one of the components. A real
 * `AdminScreen` here would pass for the wrong reason the day it renders an empty
 * state that happens to look like a review screen, and a real `ReviewScreen` or
 * `ReceiptsScreen` would fire requests that have nothing to do with routing.
 *
 * Both directions are asserted for each screen. A switch that renders the admin
 * screen everywhere is as broken as one that renders it nowhere, and only the
 * negative half can tell them apart; the same holds for the results list, whose
 * negative half is the `queryByText` in the default case below.
 *
 * The mocks are file-scoped, which is why this is its own file -- the same
 * reason `app-root.test.tsx` and `app-header.test.tsx` are theirs.
 */
vi.mock('../src/review/ReviewScreen', () => ({
  ReviewScreen: () => <p>the review screen</p>,
}))

vi.mock('../src/admin/AdminScreen', () => ({
  AdminScreen: () => <p>the admin screen</p>,
}))

vi.mock('../src/receipts/ReceiptsScreen', () => ({
  ReceiptsScreen: () => <p>the receipts screen</p>,
}))

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

describe('the app entry point routes by pathname', () => {
  it('renders the admin screen at /app/admin', async () => {
    window.history.pushState({}, '', '/app/admin')

    await import('../src/main')

    expect(await screen.findByText('the admin screen')).toBeDefined()
    expect(screen.queryByText('the review screen')).toBeNull()
  })

  it('renders the receipts screen at /app/receipts', async () => {
    window.history.pushState({}, '', '/app/receipts')

    await import('../src/main')

    expect(await screen.findByText('the receipts screen')).toBeDefined()
    expect(screen.queryByText('the review screen')).toBeNull()
    expect(screen.queryByText('the admin screen')).toBeNull()
  })

  it('renders the review screen everywhere else', async () => {
    // jsdom serves "/", which `currentRoute` maps to `review` by default.
    await import('../src/main')

    expect(await screen.findByText('the review screen')).toBeDefined()
    expect(screen.queryByText('the admin screen')).toBeNull()
    // The negative half for the results list: a switch that mounted it
    // unconditionally would satisfy the positive case above and still be broken.
    expect(screen.queryByText('the receipts screen')).toBeNull()
  })
})
