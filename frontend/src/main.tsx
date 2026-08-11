// The fonts, then the tokens that name them -- once, at the entry, never
// per-component. `@fontsource` self-hosts: Vite bundles the woff2 files into
// `dist`, so this costs no network request at runtime, which is the actual
// requirement behind design §2.3. The alternative considered was hand-vendored
// woff2 files under `src/assets/fonts/`; these packages are lockfile-pinned
// with integrity hashes, which is provenance a hand-copied binary cannot prove.
//
// Five imports because the design uses five faces (§3.1): Fira Sans 400/500/600
// for prose and labels, Fira Code 400/500 for every number. Each file declares
// all of the family's subsets with a `unicode-range`, so a browser rendering
// latin text fetches only the latin woff2 -- the rest sit in `dist` unrequested,
// and a merchant name in Cyrillic or Greek still renders in the right family
// instead of falling back mid-string.
import '@fontsource/fira-sans/400.css'
import '@fontsource/fira-sans/500.css'
import '@fontsource/fira-sans/600.css'
import '@fontsource/fira-code/400.css'
import '@fontsource/fira-code/500.css'
import './styles/tokens.css'
import { StrictMode, useEffect, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import { AdminScreen } from './admin/AdminScreen'
import { ErrorBoundary } from './ErrorBoundary'
import { currentRoute } from './route'
import { currentIdentity, hydrateIdentity, isSignedIn, setSignedIn, subscribe } from './session'
import { LoginPage } from './login/LoginPage'
import { ReviewScreen } from './review/ReviewScreen'
import { SignOutControl } from './SignOutControl'
import { ThemeControl } from './ThemeControl'

/** Three screens, no routing library -- three paths do not need one.
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
 *
 * `ErrorBoundary` wraps `App` rather than sitting inside it, so a throw from
 * either screen -- or from `App` itself -- still has somewhere to land. Without
 * it React unmounts the tree and the reviewer gets a blank page; `request` is an
 * unchecked cast, so a reply missing a field really can throw inside render.
 *
 * The signed-in screen carries a `<header>` above the screen holding
 * `SignOutControl`, so ending the session is reachable from any review.
 *
 * ## Which screen, and who is asking
 *
 * `currentRoute()` reads `window.location.pathname` once per render. There is no
 * client-side navigation in this app -- every route change is a real document
 * load, which the backend's history fallback serves -- so nothing can make that
 * value stale between renders. The path literals live in `route.ts`, and the
 * no-dot rule above is pinned there rather than here.
 *
 * `hydrateIdentity` replaces the pathname *guess* with what `GET /auth/me` says.
 * It runs from an effect and only while signed in: on the login page the answer
 * is a 401 by design (ADR-0026 decision 1), and asking for one costs a round
 * trip to learn what the URL already said. It is re-run when `signedIn` flips,
 * which is how the identity arrives after a login rather than after a reload.
 *
 * **This is not where the 401 handler is registered.** That is at `session.ts`'s
 * module scope, on import -- before `createRoot` runs -- because React flushes
 * child effects before parent effects, so a handler installed here would still
 * be the module default when a child's first request answers 401. See that
 * module's docstring.
 *
 * `Date.now()` is read during render rather than held in state, so the admin
 * screen's age column is current as of the last render and there is no timer to
 * tear down. Nothing on that screen ticks; ages advance when something else
 * causes a render, which is honest about a page that does not poll.
 */
function App() {
  const signedIn = useSyncExternalStore(subscribe, isSignedIn)
  // `currentIdentity` returns the module's cached object, never a fresh one:
  // `useSyncExternalStore` re-renders forever if `getSnapshot` allocates, which
  // is why `setIdentity` compares before it stores.
  const identity = useSyncExternalStore(subscribe, currentIdentity)

  useEffect(() => {
    if (!signedIn) {
      return
    }
    // Never rejects -- it catches the 401 whose *side effect* is the point. A
    // rejected promise would have nowhere to land: `ErrorBoundary` catches a
    // throw during render, not a rejection.
    void hydrateIdentity()
  }, [signedIn])

  if (!signedIn) {
    return <LoginPage onSignedIn={() => setSignedIn(true)} />
  }
  return (
    <>
      <header>
        <ThemeControl />
        <SignOutControl />
      </header>
      {currentRoute() === 'admin' ? (
        <AdminScreen identity={identity} now={Date.now()} />
      ) : (
        <ReviewScreen />
      )}
    </>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
