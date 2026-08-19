/** Which screen the URL asks for. A pathname switch, deliberately not a router.
 *
 * Runtime dependencies are exactly `react`, `react-dom` and the two
 * `@fontsource` packages; the only other pathname read in the app is
 * `session.ts`'s signed-in guess; and the backend already serves a history
 * fallback (`_SpaFiles(..., html=True)` in src/receipts/review/api.py), so
 * `/app/admin` survives a reload without one. Adding a router would be a new
 * runtime dependency for four paths (ADR-0027 section 4).
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
 * The default is `review`, not a 404: an unknown path under `/app/` reaches
 * this function only because the backend already decided to serve the shell,
 * and dropping a signed-in reviewer on the queue is better than telling them a
 * URL they did not type is wrong.
 */
export type Route = 'login' | 'review' | 'admin' | 'receipts'

export function currentRoute(pathname: string = window.location.pathname): Route {
  if (pathname === '/app/login') {
    return 'login'
  }
  // `startsWith` rather than equality, so the trailing slash a browser adds is
  // the same route and not a silent fall-through to the review queue.
  if (pathname.startsWith('/app/admin')) {
    return 'admin'
  }
  // Same `startsWith`, for the same reason. The results list is reached only by
  // typing or bookmarking the path -- nothing in the app links to it yet -- so
  // the slashed form a browser offers is the likelier of the two to arrive.
  if (pathname.startsWith('/app/receipts')) {
    return 'receipts'
  }
  return 'review'
}
