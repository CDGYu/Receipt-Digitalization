import { waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** Is the boundary actually wired into the tree `main.tsx` renders?
 *
 * Unit-testing `ErrorBoundary` proves the component works; it says nothing about
 * whether `main.tsx` wraps `App` in it. This file imports `main.tsx` itself --
 * side effects, `createRoot` and all -- with `ReviewScreen` replaced by a
 * component that throws during render, so the only thing that can put words in
 * `#root` is a boundary above it. Deleting `<ErrorBoundary>` from `main.tsx`
 * turns this red.
 *
 * The mock is file-scoped, which is why this is its own file.
 */
vi.mock('../src/review/ReviewScreen', () => ({
  ReviewScreen: () => {
    throw new Error('the review screen threw during render')
  },
}))

let consoleError: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  consoleError.mockRestore()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('the app root', () => {
  it('catches a render throw from the review screen instead of blanking the page', async () => {
    const root = document.createElement('div')
    root.id = 'root'
    document.body.append(root)
    // `session.ts` guesses "signed in" from the path, and jsdom's is `/`, so
    // `App` renders the review screen rather than the login page. `fetch` is
    // stubbed anyway because a real one is not available here.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await import('../src/main')

    await waitFor(() => {
      expect(root.textContent).toContain('the review screen threw during render')
    })
    root.remove()
  })
})
