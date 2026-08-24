import type { Identity } from './api/admin'
import type { Route } from './route'
import styles from './Nav.module.css'

interface NavProps {
  readonly identity: Identity | null
  readonly route: Route
}

interface Destination {
  readonly label: string
  readonly href: string
  readonly route: Route
}

/** The screens every signed-in person can reach, in the order the work runs: a
 *  landing screen, a receipt arrives, someone reviews it, the result is read
 *  back. `Admin` is appended below and is role-gated, so this list is not the
 *  whole nav.
 *
 * `href` and `route` are both spelled out rather than one derived from the
 * other, because they genuinely differ: the results list lives at
 * `/app/receipts` and its route is named `receipts`, while `Home` points at
 * `/app/` and has no literal in `route.ts` at all -- it is the default. Neither
 * mapping is derivable from the other.
 *
 * This said `/app/review` was "a path `route.ts` matches no branch for" until
 * 2026-08-24. True when written; `3f58425` gave it an explicit branch in
 * `route.ts` and did not correct it here.
 */
const DESTINATIONS: readonly Destination[] = [
  // `/app/` rather than a named path: home is `route.ts`'s default, so it has
  // no literal of its own. That is deliberate -- an unrecognised path under
  // `/app/` lands here too, and this is the screen that offers every way on.
  { label: 'Home', href: '/app/', route: 'home' },
  { label: 'Upload', href: '/app/upload', route: 'upload' },
  { label: 'Review', href: '/app/review', route: 'review' },
  { label: 'Results', href: '/app/receipts', route: 'receipts' },
]

const ADMIN: Destination = { label: 'Admin', href: '/app/admin', route: 'admin' }

/** Where a person can go from here.
 *
 * Plain `<a href>` and a real document load, not a router: ADR-0027 decision 4
 * settled that, and the backend's history fallback serves every one of these
 * paths. So this component holds no state and intercepts no click.
 *
 * `route` arrives as a prop rather than from a `currentRoute()` call here.
 * `main.tsx` reads the pathname exactly once per render and its docstring says
 * so; a second read inside a child would falsify that quietly.
 *
 * The admin link is gated **positively** on `role === 'admin'`, matching the
 * gate on ReceiptsScreen's export button. `role` is a `string` on the wire, so
 * a `!== 'reviewer'` test would offer an unrecognised role the admin link. A
 * `null` identity -- the state every cold load passes through before
 * `hydrateIdentity` answers -- takes the narrow branch for the same reason.
 *
 * The gate is cosmetic and is not the security boundary: `/app/admin` renders
 * for anyone who types it, and the API refuses the data behind it with a 403
 * from `require_role(ROLE_ADMIN)`. Hiding the link keeps a reviewer from
 * walking into that wall; it does not stand in for it.
 */
export function Nav({ identity, route }: NavProps) {
  const destinations =
    identity?.role === 'admin' ? [...DESTINATIONS, ADMIN] : DESTINATIONS

  return (
    <nav aria-label="Screens" className={styles.nav}>
      {destinations.map((destination) => {
        const current = route === destination.route
        return (
          <a
            key={destination.href}
            className={current ? `${styles.link} ${styles.current}` : styles.link}
            href={destination.href}
            aria-current={current ? 'page' : undefined}
          >
            {destination.label}
          </a>
        )
      })}
    </nav>
  )
}
