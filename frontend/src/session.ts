import { onUnauthorized } from './api/client'

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
  for (const listener of listeners) {
    listener()
  }
}

/** Subscribe to changes. Returns the unsubscribe `useSyncExternalStore` needs. */
export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

onUnauthorized(() => setSignedIn(false))
