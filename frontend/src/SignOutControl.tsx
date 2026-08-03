import { useState } from 'react'
import { ApiError, request } from './api/client'
import { setSignedIn } from './session'
import { clear, hasDirtyEdits } from './review/stash'

/** Sign out, honestly.
 *
 * The session cookie is server state, so this control never pretends: on any
 * failure that leaves the cookie alive it stays signed in and shows the
 * server's words. The stash is cleared exactly when the session actually
 * ends -- a 204, or a 401 that means it was already over (`client.ts` fires
 * `onUnauthorized` before throwing, so the signed-in flag has flipped by the
 * time the catch runs; only the stash is left to clean). Any other ending
 * keeps the stash: the discard did not happen, the edits are still live on
 * screen, and the stash keeps tracking them.
 *
 * Dirty edits gate the click behind a two-step inline confirm rather than
 * `window.confirm` -- the same explicit-DOM choice the rest of this app
 * makes, and testable the same way. A held claimed task is deliberately left
 * alone: ADR-0016 hands it back at the next sign-in.
 */
export function SignOutControl() {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function signOut(): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await request('/auth/logout', { method: 'POST' })
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        clear()
        return
      }
      setBusy(false)
      setConfirming(false)
      setError(caught instanceof ApiError ? caught.message : 'could not sign out')
      return
    }
    clear()
    setSignedIn(false)
  }

  if (confirming) {
    return (
      <span>
        <span role="alert">You have unsaved edits on this receipt.</span>
        <button type="button" disabled={busy} onClick={() => void signOut()}>
          Discard edits and sign out
        </button>
        <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
          Cancel
        </button>
      </span>
    )
  }
  return (
    <span>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          if (hasDirtyEdits()) {
            setConfirming(true)
            return
          }
          void signOut()
        }}
      >
        Sign out
      </button>
      {error !== null && <span role="alert">Could not sign out: {error}</span>}
    </span>
  )
}
