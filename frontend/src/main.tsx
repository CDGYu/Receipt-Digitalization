import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { onUnauthorized } from './api/client'
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
 * The initial guess is "signed in unless the URL says otherwise", and the 401
 * handler corrects it: the session cookie is HttpOnly-by-nature server state,
 * so the page cannot read it and must learn from a rejected request instead.
 */
function App() {
  const [signedIn, setSignedIn] = useState(window.location.pathname !== '/app/login')

  useEffect(() => {
    onUnauthorized(() => setSignedIn(false))
  }, [])

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
