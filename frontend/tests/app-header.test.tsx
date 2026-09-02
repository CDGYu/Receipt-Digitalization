import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** Is the settings menu -- and the sign-out control it now nests -- actually
 * wired into the tree `main.tsx` renders?
 *
 * `sign-out.test.tsx` proves the sign-out component works and
 * `settings-menu.test.tsx` proves the menu opens; neither says anything about
 * whether anything renders them in the header. Measured before this file
 * existed: deleting `<header><SignOutControl /></header>` and its import from
 * `main.tsx` left the whole suite green and `tsc -b` at exit 0 -- the
 * milestone's first named deliverable could vanish without a word.
 *
 * Sign out moved inside the settings menu (a `Settings` disclosure button whose
 * panel holds the mode picker and the sign-out control), so this file now
 * asserts the `Settings` button is in the header and that opening it reveals
 * `Sign out`. The guarantee is unchanged -- ending the session is reachable from
 * the header -- only the path to it is.
 *
 * `app-root.test.tsx` cannot see it: that file mocks the same screen with a
 * component that throws, so the boundary replaces the entire tree and the header
 * is never in the document. Hence a second file with the same shape and a
 * *benign* stub -- the mock is file-scoped, which is why this is its own file.
 *
 * Both halves of the branch are asserted. `session.ts` guesses "signed in"
 * from `window.location.pathname !== '/app/login'` at module scope, so the
 * signed-out case is driven by moving the URL there and re-importing the module
 * graph, the way `session.test.ts` drives its own fresh imports.
 */
// The home screen, not the review screen: jsdom serves "/", and `route.ts`'s
// default moved from `review` to `home` when `/app/` became a landing screen.
// This test is about the header, which sits above whichever screen renders, so
// the stub follows the route rather than the route being bent to the stub.
vi.mock('../src/home/HomeScreen', () => ({
  HomeScreen: () => <p>the home screen</p>,
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
  it('renders the settings menu above the landing screen when signed in, and sign out lives in it', async () => {
    // jsdom serves "/", which is the not-/app/login case.
    await import('../src/main')

    // The Settings button is in the header...
    const settings = await screen.findByRole('button', { name: 'Settings' })
    // ...above the screen it belongs to, not instead of it.
    expect(screen.getByText('the home screen')).toBeDefined()

    // Sign out is not a bare header control any more: it is reached by opening
    // the menu. Closed, it is absent; opened, it is there.
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
    await userEvent.click(settings)
    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeDefined()
  })

  it('renders no settings menu or sign-out control on the login page', async () => {
    window.history.pushState({}, '', '/app/login')

    await import('../src/main')

    // Positively: the login page is what rendered. Without this the absence
    // assertions below would also pass on an empty document.
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeDefined()
    expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
  })
})
