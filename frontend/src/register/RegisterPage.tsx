import { useState, type FormEvent } from 'react'
import { ApiError, request } from '../api/client'
import { ROLES } from '../api/admin'
import styles from '../login/LoginPage.module.css'

/** The self-service signup screen -- the login page's sibling.
 *
 * It reuses `LoginPage.module.css` wholesale: a reviewer should not learn one
 * visual vocabulary for signing in and another for signing up, and the two
 * forms are the same shape (a centred card that is also the page) but for the
 * one extra control. That control is a role `<select>`, populated from
 * `ROLES` in `api/admin.ts` rather than typed here, so the two options stay in
 * one place; the backend validates the value regardless (a bad one is a 400
 * this form shows), so the dropdown is a convenience, not the gate.
 *
 * On success `POST /auth/register` has already set the session, so this calls
 * the same `onSignedIn` the login page does -- registering lands the new
 * account straight in the app rather than bouncing it back to sign in.
 */
export function RegisterPage({
  onSignedIn,
  onShowLogin,
}: {
  onSignedIn: () => void
  onShowLogin: () => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<string>(ROLES[0])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await request('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username, password, role }),
      })
      onSignedIn()
    } catch (caught) {
      // Never silent: the person must see why the account was not created.
      setError(caught instanceof ApiError ? caught.message : 'could not register')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <h1 className={styles.heading}>Create account</h1>
      <label className={styles.field}>
        Username
        <input
          className={styles.input}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
        />
      </label>
      <label className={styles.field}>
        Password
        <input
          className={styles.input}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
        />
      </label>
      <label className={styles.field}>
        Role
        <select
          className={styles.input}
          value={role}
          onChange={(e) => setRole(e.target.value)}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      {error !== null && <p className={styles.error} role="alert">{error}</p>}
      <button className={styles.button} type="submit" disabled={busy}>
        Create account
      </button>
      <button
        className={styles.link}
        type="button"
        onClick={onShowLogin}
        disabled={busy}
      >
        Already have an account? Sign in
      </button>
    </form>
  )
}
