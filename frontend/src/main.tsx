// The fonts, then the tokens that name them -- once, at the entry, never
// per-component. `@fontsource` self-hosts: Vite bundles the woff2 files into
// `dist`, so this costs no network request at runtime, which is the actual
// requirement behind design §2.3. The alternative considered was hand-vendored
// woff2 files under `src/assets/fonts/`; these packages are lockfile-pinned
// with integrity hashes, which is provenance a hand-copied binary cannot prove.
//
// Seven imports because the design uses seven faces: the five §3.1 names --
// Fira Sans 400/500/600 for prose and labels, Fira Code 400/500 for every
// number -- plus Archivo 600/700, the two weights behind `--font-display`. Each
// file declares all of the family's subsets with a `unicode-range`, so a browser
// rendering latin text fetches only the latin woff2 -- the rest sit in `dist`
// unrequested, and a merchant name in Cyrillic or Greek still renders in the
// right family instead of falling back mid-string.
//
// Archivo is the exception to that last clause, and `--font-display`'s stack is
// why it costs nothing: this package ships latin, latin-ext and vietnamese and
// no others -- no Cyrillic, no Greek, against Fira Sans's seven subsets -- so a
// heading in either script falls through to `'Fira Sans'`, which is next in the
// stack precisely because it carries them.
//
// The variable package is deliberately not used, and neither is `index.css`:
// that entrypoint pulls every weight the family ships, and the design asks for
// two.
import '@fontsource/fira-sans/400.css'
import '@fontsource/fira-sans/500.css'
import '@fontsource/fira-sans/600.css'
import '@fontsource/fira-code/400.css'
import '@fontsource/fira-code/500.css'
import '@fontsource/archivo/600.css'
import '@fontsource/archivo/700.css'
import './styles/tokens.css'
import { StrictMode, useEffect, useState, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import { AdminScreen } from './admin/AdminScreen'
import { ErrorBoundary } from './ErrorBoundary'
import { currentRoute } from './route'
import { currentIdentity, hydrateIdentity, isSignedIn, setSignedIn, subscribe } from './session'
import { HomeScreen } from './home/HomeScreen'
import { LoginPage } from './login/LoginPage'
import { RegisterPage } from './register/RegisterPage'
import { Nav } from './Nav'
import navStyles from './Nav.module.css'
import { ProcessingListScreen } from './processing/ProcessingListScreen'
import { ReceiptsScreen } from './receipts/ReceiptsScreen'
import { ReviewQueue } from './review/ReviewQueue'
import { ReviewScreen } from './review/ReviewScreen'
import { SignOutControl } from './SignOutControl'
import { UploadScreen } from './upload/UploadScreen'

/** No routing library: these paths do not need one.
 *
 * **Every client-side path must keep its final segment free of a dot.** Task
 * 1's mount only falls back to the shell for requests whose last segment has no
 * file extension (`_names_a_file` in src/receipts/review/api.py); a path like
 * `/app/receipt/inv-2026.01` is read as a missing *file* and gets a 404 rather
 * than the app. Every literal `route.ts` declares is safe, and
 * `tests/admin-screen.test.tsx` derives that list from the module's own source
 * rather than from a copy typed here. Anything built from receipt data -- an id,
 * a merchant name, an uploaded filename -- is not, so it belongs in a query
 * string, not in a path segment. That is why the results list's rows are not
 * links in v1: a row carries a receipt id, and `/app/receipt/inv-2026.01`
 * would 404 on reload.
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
  // Which signed-out screen to show. Local component state, not a route: signup
  // is a modeless toggle on the login card, not a URL a browser bookmarks or a
  // deep-link the backend's history fallback has to serve. It only matters while
  // `signedIn` is false, and it resets to `false` on every fresh mount, which is
  // the wanted default -- the first screen a signed-out visitor sees is sign-in.
  const [showRegister, setShowRegister] = useState(false)

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
    return showRegister ? (
      <RegisterPage
        onSignedIn={() => setSignedIn(true)}
        onShowLogin={() => setShowRegister(false)}
      />
    ) : (
      <LoginPage
        onSignedIn={() => setSignedIn(true)}
        onShowRegister={() => setShowRegister(true)}
      />
    )
  }
  // Read once into a local and switched on twice, rather than called per branch:
  // two `currentRoute()` calls would be two reads of `window.location.pathname`
  // in a single render, which is what the docstring above promises there is not.
  const route = currentRoute()
  return (
    <>
      <header className={navStyles.bar}>
        {/* The brand lockup links home, the same destination `Nav`'s `Home`
         * entry points at. It carries the product name as artwork, so the bar
         * reads as this app rather than a generic shell -- the wordmark lives in
         * the SVG, not in markup that would need translating. */}
        <a className={navStyles.brand} href="/app/" aria-label="Receipt Digitalization — home">
          <img className={navStyles.brandMark} src="/logo-lockup.svg" alt="Receipt Digitalization" />
        </a>
        <Nav identity={identity} route={route} />
        <SignOutControl />
      </header>
      {route === 'admin' ? (
        <AdminScreen identity={identity} now={Date.now()} />
      ) : route === 'receipts' ? (
        // The same `identity` object `AdminScreen` gets, and nothing else: this
        // screen reads `role` to decide whether to offer the export button, and
        // needs no clock -- it renders no ages.
        <ReceiptsScreen identity={identity} />
      ) : route === 'home' ? (
        // No `identity`: the counts are system-wide and every signed-in caller
        // gets the same three destinations. The admin link is the nav's job and
        // is gated there.
        <HomeScreen />
      ) : route === 'queue' ? (
        // No `identity`: the queue splits its rows by state alone -- every
        // `in_progress` row is offered as a resume and every `open` row as
        // backlog. `list_tasks` already scopes a reviewer to open rows plus
        // their own in any state (ADR-0026), so who may see a row is decided at
        // the API, not by a prop here.
        <ReviewQueue />
      ) : route === 'upload' ? (
        // No `identity`: nothing on this screen is decided by who is asking.
        // `POST /upload` takes `require_upload`, which is the API key or ANY
        // signed-in user with no role check (review/auth.py), and the screen
        // offers the one control to all of them -- so passing an identity it
        // does not read would be a prop that looks like a gate and is not one.
        <UploadScreen />
      ) : route === 'processing' ? (
        // No `identity`: `GET /receipts` is `require_user` with no role check,
        // so every signed-in caller sees the same list of what is processing.
        <ProcessingListScreen />
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
