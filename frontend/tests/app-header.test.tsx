import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** Is the sign-out control actually wired into the tree `main.tsx` renders?
 *
 * `sign-out.test.tsx` proves the component works; it says nothing about whether
 * anything renders it. Measured before this file existed: deleting
 * `<header><SignOutControl /></header>` and its import from `main.tsx` left the
 * whole suite green and `tsc -b` at exit 0 -- the milestone's first named
 * deliverable could vanish without a word.
 *
 * `app-root.test.tsx` cannot see it: that file mocks `ReviewScreen` with a
 * component that throws, so the boundary replaces the entire tree and the header
 * is never in the document. Hence a second file with the same shape and a
 * *benign* stub -- the mock is file-scoped, which is why this is its own file.
 *
 * Both halves of the branch are asserted. `session.ts` guesses "signed in"
 * from `window.location.pathname !== '/app/login'` at module scope, so the
 * signed-out case is driven by moving the URL there and re-importing the module
 * graph, the way `session.test.ts` drives its own fresh imports.
 */
vi.mock('../src/review/ReviewScreen', () => ({
  ReviewScreen: () => <p>the review screen</p>,
}))

let consoleError: ReturnType<typeof vi.spyOn>
let root: HTMLDivElement

beforeEach(() => {
  // React logs the missing-`act` warning through `console.error`; `main.tsx`
  // renders itself on import and there is no `act` to wrap that in.
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  // A fresh module graph per test: `main.tsx` renders on import, and
  // `session.ts` reads the path once, at module scope.
  vi.resetModules()
  root = document.createElement('div')
  root.id = 'root'
  document.body.append(root)
  // No screen here calls it, but an unstubbed `fetch` would make a stray call
  // a network error rather than a readable failure.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
})

afterEach(() => {
  consoleError.mockRestore()
  vi.unstubAllGlobals()
  vi.resetModules()
  root.remove()
  window.history.pushState({}, '', '/')
})

describe('the app header', () => {
  it('renders the sign-out control above the review screen when signed in', async () => {
    // jsdom serves "/", which is the not-/app/login case.
    await import('../src/main')

    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeDefined()
    // ...above the screen it belongs to, not instead of it.
    expect(screen.getByText('the review screen')).toBeDefined()
  })

  it('renders no sign-out control on the login page', async () => {
    window.history.pushState({}, '', '/app/login')

    await import('../src/main')

    // Positively: the login page is what rendered. Without this the absence
    // assertion below would also pass on an empty document.
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeDefined()
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
  })
})
