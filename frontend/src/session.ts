import { onUnauthorized } from './api/client'
import { fetchMe } from './api/admin'
import type { Identity } from './api/admin'

/** Whether the reviewer is signed in, as module state rather than component state.
 *
 * **The 401 handler is registered here, at module scope, on import.** It used to
 * live in `App`'s `useEffect`, which is too late: React flushes *child* effects
 * before parent effects, so a child that fires a request from its own effect
 * runs while `client.ts` still holds its module-default no-op handler, and a
 * 401 that resolves synchronously is dropped. Production survived that because
 * network 401s are async, but Task 3's mocked-fetch tests would not.
 *
 * Module scope also removes the leak the effect had: nothing needs to un-register
 * an app-lifetime handler, and there is no second `App` to race with. What *does*
 * get torn down is the per-component subscription -- `subscribe` returns its own
 * unsubscribe, which `useSyncExternalStore` calls on unmount.
 *
 * The initial guess is "signed in unless the URL says otherwise": the session
 * cookie is server state the page cannot read, so the only way to learn
 * otherwise is a rejected request.
 */
let signedIn = window.location.pathname !== '/app/login'

const listeners = new Set<() => void>()

export function isSignedIn(): boolean {
  return signedIn
}

export function setSignedIn(next: boolean): void {
  if (signedIn === next) {
    return
  }
  signedIn = next
  notify()
}

/** Subscribe to changes. Returns the unsubscribe `useSyncExternalStore` needs.
 *
 * One subscription covers both the boolean and the identity: they change
 * together far more often than not (a 401 clears both), and a second listener
 * set would be a second thing every consumer had to remember to subscribe to.
 */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function notify(): void {
  for (const listener of listeners) {
    listener()
  }
}

/** Who the caller is, or `null` while that is still unknown.
 *
 * **`null` here means "not yet answered", not "not an admin".** The boolean
 * above starts as a *guess* off the URL; this starts as an honest absence,
 * because there is nothing about a pathname that could suggest a username or a
 * role. A consumer that treated `null` as a role decision would show an admin a
 * refusal for as long as one round trip takes.
 */
let identity: Identity | null = null

export function currentIdentity(): Identity | null {
  return identity
}

/** Set (or clear) the identity, notifying only on a real change.
 *
 * The equality check is not an optimisation. `useSyncExternalStore` requires
 * `getSnapshot` to return a cached value -- a fresh object per read makes React
 * re-render forever -- so `hydrateIdentity` being called twice (which
 * `StrictMode` guarantees in development) must not install a second, equal
 * object and announce it as news.
 */
export function setIdentity(next: Identity | null): void {
  const same =
    next === null
      ? identity === null
      : identity !== null && identity.username === next.username && identity.role === next.role
  if (same) {
    return
  }
  identity = next
  notify()
}

/** Replace the pathname guess with what the server says. **Never rejects.**
 *
 * `GET /auth/me` answers **401** when signed out (ADR-0026 decision 1, chosen
 * over `200 {"user": null}`), and `request` fires the global unauthorized
 * handler *and then throws*. The side effect is exactly what is wanted -- the
 * handler registered at the foot of this module flips `signedIn` to false, so a
 * signed-out user deep-linking to `/app/` is corrected with no new logic -- but
 * the rejection is not caught by anything else in the tree: `ErrorBoundary`
 * catches a throw during *render*, never a rejected promise. So it is caught
 * here, and this function resolves whatever happened.
 *
 * Every other failure (the API unreachable, a 500, a body that will not parse)
 * leaves the identity `null`, which is the honest answer: still unknown. It is
 * deliberately not retried -- a screen that needs an identity says so, and a
 * retry loop against a route that answers 401 by design would be an infinite
 * one.
 */
export async function hydrateIdentity(): Promise<void> {
  try {
    setIdentity(await fetchMe())
  } catch {
    setIdentity(null)
  }
}

// A 401 on ANY request ends the session, so it clears both halves of it. The
// identity goes first: a listener woken by the boolean must not be able to read
// a stale username back out of this module.
onUnauthorized(() => {
  setIdentity(null)
  setSignedIn(false)
})
