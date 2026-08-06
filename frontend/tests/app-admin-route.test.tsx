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
 * Both screens are mocked, and that is the point rather than a shortcut: what is
 * under test is the *switch*, not either component. A real `AdminScreen` here
 * would pass for the wrong reason the day it renders an empty state that happens
 * to look like a review screen, and a real `ReviewScreen` would fire requests
 * that have nothing to do with routing.
 *
 * Both directions are asserted. A switch that renders the admin screen
 * everywhere is as broken as one that renders it nowhere, and only the negative
 * half can tell them apart.
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

  it('renders the review screen everywhere else', async () => {
    // jsdom serves "/", which `currentRoute` maps to `review` by default.
    await import('../src/main')

    expect(await screen.findByText('the review screen')).toBeDefined()
    expect(screen.queryByText('the admin screen')).toBeNull()
  })
})
