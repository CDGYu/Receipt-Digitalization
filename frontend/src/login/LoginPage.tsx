import { useState, type FormEvent } from 'react'
import { ApiError, request } from '../api/client'

export function LoginPage({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await request('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      })
      onSignedIn()
    } catch (caught) {
      // Never silent: the reviewer must see why they are still on this page.
      setError(caught instanceof ApiError ? caught.message : 'could not sign in')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <h1>Sign in</h1>
      <label>
        Username
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          autoFocus
        />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
      </label>
      {error !== null && <p role="alert">{error}</p>}
      <button type="submit" disabled={busy}>
        Sign in
      </button>
    </form>
  )
}
