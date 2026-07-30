import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from '../src/ErrorBoundary'

// React reports an error a boundary caught through `console.error`, including a
// component stack. Silenced so a green run is readable, and restored afterwards
// so nothing later in the file is quietly muted.
let consoleError: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  cleanup()
  consoleError.mockRestore()
  vi.unstubAllGlobals()
})

/** The shape this boundary exists for. `request<T>` is an unchecked cast, so a
 *  reply that omits `findings` really does reach `findings.length` in render. */
function Boom(): never {
  throw new TypeError("Cannot read properties of undefined (reading 'length')")
}

describe('ErrorBoundary', () => {
  it('renders its children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <p>the review screen</p>
      </ErrorBoundary>,
    )

    expect(screen.getByText('the review screen')).toBeDefined()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('puts a render throw on screen instead of blanking the page', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )

    // Without a boundary React unmounts the tree: the container is empty and the
    // only trace is in a console the reviewer is not reading.
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain("Cannot read properties of undefined (reading 'length')")
    expect(screen.getByRole('button', { name: /reload/i })).toBeDefined()
  })

  it('is what stands between a render throw and an empty page', () => {
    // The premise, measured instead of asserted in a comment: the same component
    // with no boundary above it takes the whole tree down and leaves nothing for
    // a reviewer to read. This is the only test here that renders without one.
    const container = document.createElement('div')
    document.body.append(container)

    expect(() => render(<Boom />, { container })).toThrow(
      "Cannot read properties of undefined (reading 'length')",
    )
    expect(container.textContent).toBe('')

    container.remove()
  })

  it('offers a reload that really reloads', async () => {
    // The only recovery a boundary can honestly offer -- re-rendering the same
    // children hits the same error. A button that looked like an escape and did
    // nothing would be worse than no button, and nothing pinned it before.
    const reload = vi.fn()
    vi.stubGlobal('location', { pathname: '/app/review', reload })

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    await userEvent.click(screen.getByRole('button', { name: /reload/i }))

    expect(reload).toHaveBeenCalledOnce()
  })

  it('renders a thrown non-Error rather than the word undefined', () => {
    function ThrowString(): never {
      throw 'the worker returned nothing'
    }

    render(
      <ErrorBoundary>
        <ThrowString />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('alert').textContent).toContain('the worker returned nothing')
  })
})
