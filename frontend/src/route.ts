/** Which screen the URL asks for. A pathname switch, deliberately not a router.
 *
 * Runtime dependencies are exactly `react`, `react-dom` and the two
 * `@fontsource` packages; the only other pathname read in the app is
 * `session.ts`'s signed-in guess; and the backend already serves a history
 * fallback (`_SpaFiles(..., html=True)` in src/receipts/review/api.py), so
 * `/app/admin` survives a reload without one. Adding a router would be a new
 * runtime dependency for the handful of paths below (ADR-0027 section 4).
 *
 * **Every path literal below must keep its last segment free of a dot**, and
 * the rule is pinned in `tests/admin-screen.test.tsx` rather than trusted:
 * that mount only falls back to the SPA shell when the final segment has no
 * file extension, so `/app/receipt/inv-2026.01` is served as a missing *file*
 * and 404s. Anything built from receipt data belongs in a query string.
 *
 * `pathname` is a parameter with a live default rather than a bare read of
 * `window.location`, so the mapping can be tested at every path without
 * pushing history state. `main.tsx` calls it with no argument.
 *
 * The default is `home`, not a 404: an unknown path under `/app/` reaches this
 * function only because the backend already decided to serve the shell, so
 * landing somebody somewhere useful beats telling them a URL they did not type
 * is wrong. The argument is unchanged from when the default was `review`; only
 * the destination moved, because `/app/` became a landing screen that offers
 * every way forward rather than a queue that is usually empty.
 */
export type Route = 'login' | 'home' | 'review' | 'admin' | 'receipts' | 'upload'

export function currentRoute(pathname: string = window.location.pathname): Route {
  if (pathname === '/app/login') {
    return 'login'
  }
  // `startsWith` rather than equality, so the trailing slash a browser adds is
  // the same route and not a silent fall-through to the landing screen.
  if (pathname.startsWith('/app/admin')) {
    return 'admin'
  }
  // Same `startsWith`, for the same reason: a browser offers the slashed form
  // and the backend's history fallback serves it.
  //
  // This said "the results list is reached only by typing or bookmarking the
  // path -- nothing in the app links to it yet" until 2026-08-24. It was true
  // when written and `a7e5fa0` falsified it that morning by adding the nav,
  // which links here, and the home screen links here too. (The nav reaches
  // every signed-in screen except this file's own `login`, and `admin` only for
  // an admin -- so "every other screen" would overstate it.) Missed in that
  // commit's own sweep and corrected here.
  if (pathname.startsWith('/app/receipts')) {
    return 'receipts'
  }
  // `startsWith`, like its siblings, so the trailing slash a browser adds is
  // the same route rather than a silent fall-through to the landing screen.
  //
  // Its position relative to the other branches does not matter -- no two of
  // these prefixes overlap -- but its position above the `return` does, and that
  // is the whole hazard: an unrouted `/app/upload` does not throw, it quietly
  // renders the landing screen. Which is why the pin in
  // `tests/admin-screen.test.tsx` asserts the route BY NAME: "not admin" passes
  // with no branch here at all.
  if (pathname.startsWith('/app/upload')) {
    return 'upload'
  }
  // Explicit since `/app/` became a landing screen. This branch used to not
  // exist: `/app/review` resolved only by falling through the default, which
  // was `review`. `upload/ProcessingView.tsx` has always linked here, and the
  // nav links here, so the fall-through was load-bearing without being written
  // down anywhere. Moving the default to `home` would have silently pointed
  // both at the landing screen.
  if (pathname.startsWith('/app/review')) {
    return 'review'
  }
  return 'home'
}
