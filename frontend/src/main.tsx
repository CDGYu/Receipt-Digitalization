import { StrictMode, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import { isSignedIn, setSignedIn, subscribe } from './session'
import { LoginPage } from './login/LoginPage'
import { ReviewScreen } from './review/ReviewScreen'

/** Two screens, no routing library -- two paths do not need one.
 *
 * **Every client-side path must keep its final segment free of a dot.** Task
 * 1's mount only falls back to the shell for requests whose last segment has no
 * file extension (`_names_a_file` in src/receipts/review/api.py); a path like
 * `/app/receipt/inv-2026.01` is read as a missing *file* and gets a 404 rather
 * than the app. `/app/login` and `/app/review` are safe. Anything built from
 * receipt data -- an id, a merchant name, an uploaded filename -- is not, so it
 * belongs in a query string, not in a path segment.
 *
 * Session state lives in `./session` rather than in this component's `useState`,
 * and the 401 handler is registered when that module is *imported* -- before
 * `createRoot` runs, and so before any child effect can fire a request. An
 * effect here was too late: React flushes child effects first. See
 * `session.ts`'s docstring.
 */
function App() {
  const signedIn = useSyncExternalStore(subscribe, isSignedIn)

  if (!signedIn) {
    return <LoginPage onSignedIn={() => setSignedIn(true)} />
  }
  return <ReviewScreen />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
