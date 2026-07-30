import { beforeEach, describe, expect, it, vi } from 'vitest'

/** The 401 handler must be installed by *importing* the module, not by
 *  rendering a component (fix round 1, finding 8).
 *
 * The original `main.tsx` registered `onUnauthorized` inside `App`'s
 * `useEffect`. React flushes **child** effects before parent effects, so a
 * child that fires a request from its own effect runs while `client.ts` still
 * holds its module-default no-op handler, and a synchronously-resolved 401 is
 * dropped on the floor. Production got away with it because network 401s are
 * async; Task 3's mocked-fetch tests would not, and Task 3 is next.
 *
 * Every test below imports `../src/session` and **never renders anything**.
 * That is the point: if the registration needs a render to happen, these fail.
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A fresh module graph per test: `session.ts` and `client.ts` both hold module
 *  state, and a handler registered by one test must not leak into the next. */
async function freshModules() {
  vi.resetModules()
  const session = await import('../src/session')
  const client = await import('../src/api/client')
  return { session, client }
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('the session store', () => {
  it('starts signed in when the URL is not /app/login', async () => {
    // jsdom serves "/" here, which is the not-/app/login case.
    const { session } = await freshModules()
    expect(session.isSignedIn()).toBe(true)
  })

  it('flips to signed out on a 401, with no component ever rendered', async () => {
    const { session, client } = await freshModules()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'authentication required' } })),
    )

    await expect(client.request('/receipts')).rejects.toBeInstanceOf(client.ApiError)

    expect(session.isSignedIn()).toBe(false)
  })

  it('notifies subscribers, and stops after unsubscribe', async () => {
    // `useSyncExternalStore` relies on both halves: the notification, and the
    // teardown the old `useEffect` never had.
    const { session } = await freshModules()
    const listener = vi.fn()
    const unsubscribe = session.subscribe(listener)

    session.setSignedIn(false)
    expect(listener).toHaveBeenCalledOnce()

    unsubscribe()
    session.setSignedIn(true)
    expect(listener).toHaveBeenCalledOnce()
  })

  it('does not notify when the value is unchanged', async () => {
    const { session } = await freshModules()
    const listener = vi.fn()
    session.subscribe(listener)

    session.setSignedIn(true) // already true
    expect(listener).not.toHaveBeenCalled()
  })
})
