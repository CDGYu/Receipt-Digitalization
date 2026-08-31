import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginPage } from '../src/login/LoginPage'
import { onUnauthorized } from '../src/api/client'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function signIn() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Username'), 'alice')
  await user.type(screen.getByLabelText('Password'), 'pw-alice')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

beforeEach(() => {
  // `client.ts` keeps the handler in module state, so a 401 raised by one test
  // would otherwise still be wired to the previous test's spy.
  onUnauthorized(() => {})
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('LoginPage', () => {
  it('posts the credentials to /auth/login as the API expects them', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { username: 'alice', role: 'reviewer' }))
    vi.stubGlobal('fetch', fetchMock)

    render(<LoginPage onSignedIn={() => {}} onShowRegister={() => {}} />)
    await signIn()

    // The shape `_LoginBody` in src/receipts/review/auth.py actually parses.
    // There is no token in the reply to store: the cookie is set server-side,
    // which is why `credentials` must ride along on every request.
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/auth/login')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('same-origin')
    expect(JSON.parse(init.body as string)).toEqual({ username: 'alice', password: 'pw-alice' })
  })

  it('calls onSignedIn once the credentials are accepted', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(200, { username: 'alice', role: 'reviewer' })),
    )
    const onSignedIn = vi.fn()

    render(<LoginPage onSignedIn={onSignedIn} onShowRegister={() => {}} />)
    await signIn()

    expect(onSignedIn).toHaveBeenCalledOnce()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it("shows the API's own message when the credentials are rejected", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'invalid credentials' } })),
    )
    const onSignedIn = vi.fn()

    render(<LoginPage onSignedIn={onSignedIn} onShowRegister={() => {}} />)
    await signIn()

    // A failure the reviewer can read, on screen -- not a console log, and not
    // a spinner that never stops.
    expect(screen.getByRole('alert').textContent).toBe('invalid credentials')
    expect(onSignedIn).not.toHaveBeenCalled()
    // `busy` must have been released, or a reviewer who mistypes their password
    // is locked out of the form until they reload.
    const button = screen.getByRole('button', { name: 'Sign in' }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
  })

  it('shows something readable when the request never reaches the API', async () => {
    // `fetch` rejects on a dropped connection or a dev server that is not up,
    // so the caught value is a TypeError rather than an ApiError. That branch
    // must still put words on the screen.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    render(<LoginPage onSignedIn={() => {}} onShowRegister={() => {}} />)
    await signIn()

    expect(screen.getByRole('alert').textContent).toBe('could not sign in')
  })
})
