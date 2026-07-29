# ADR 0015 — The review UI is served same-origin under `/app`

**Status:** Accepted (P5.T0/P5.T1, 2026-07-29)

## Context

The review API is finished and enforced (ADR-0012): eleven routes, session auth
with roles, a machine upload key, signed image URLs, and a closed set of
correctable field paths. Phase 5 adds the browser client that a human actually
uses, and the user chose **React 19 + Vite + TypeScript** for it.

Three facts about the existing code shaped every decision here, and all three
were found by reading the code rather than by planning against it.

**There is no CORS middleware anywhere.** `review/auth.py` installs
`SessionMiddleware` with `same_site="lax"` and nothing else. A Vite dev server on
`:5173` calling an API on `:8000` is cross-origin, so the session cookie would
not be sent and every authenticated request would fail. The obvious fix —
add `CORSMiddleware`, set `SameSite=None; Secure` — weakens the cookie that
carries reviewer identity, which is the one thing ADR-0012 exists to protect.

**The API owns the bare paths.** `/receipts`, `/review`, `/upload`, `/export`,
`/auth`, `/health`, `/metrics`. In particular `GET /review/next` is an API
route, so a SPA client-side route also called `/review/...` collides. Moving the
API under `/api` would break every existing test and the contract ADR-0012
documents.

**Money crosses the wire as strings, deliberately.** `review/serializers.py`:
*"A JSON number is a float (ADR-0001), so every `Decimal` this API returns
passes through here first."* `confidence` uses the same function, and
`confidence_reasons` is encoded as `[{"reason": str, "penalty": str}]` for the
same reason. JavaScript has no decimal type, so the browser is the easiest place
in the whole system to reintroduce the float that ADR-0001 forbids.

## Decision

**The browser is same-origin in dev and in prod. No `CORSMiddleware` is ever
added.**

- **Dev:** Vite's `server.proxy` forwards every API prefix to
  `http://localhost:8000`. The browser only ever addresses `:5173`.
- **Prod:** `npm run build` → `frontend/dist`, served by the existing FastAPI
  app through a `StaticFiles` mount.

`auth.py` is not modified and the cookie keeps `same_site="lax"`.

**SPA pages live under `/app/*`; the API keeps its exact current paths.** The
history fallback applies only under `/app`, via a `_SpaFiles` subclass that
swallows a 404 into `index.html` and re-raises everything else, so a hard
refresh on `/app/review` returns the shell instead of a 404.

**The mount is skipped entirely when `frontend/dist` is absent.** `StaticFiles`
resolves and checks its directory at construction, so an unguarded mount breaks
`create_app` for a base install, for CI, and for every developer who has never
run `npm`. This is ADR-0014's discipline applied to a directory instead of an
import, and it is enforced by a test that fails with
`RuntimeError: Directory '...' does not exist` when the guard is removed.

**What protects API paths is the `/app` prefix, not the registration order.**
This ADR states it explicitly because the first version of the design claimed
the opposite and shipped a vacuous test on the strength of it. A Starlette mount
only ever intercepts paths under its own prefix, so a mount at `/app` cannot
compete with `/health` at *any* registration order — verified by moving
`_install_spa` ahead of the read routes and watching all five tests stay green.
The mount is still registered last, because that costs nothing and is the
property that would matter if it ever moved to `/`, where order really would
decide the winner.

**Money stays a string from the database to the input and back.** The frontend
declares `type Money = string & { readonly __money: unique symbol }` with no
arithmetic defined on it, and **`<input type="number">` is banned on money
fields** in favour of `type="text" inputMode="decimal"` — `valueAsNumber` and the
browser's own reformatting are exactly the float path ADR-0001 forbids, and
`"1000.00"` must survive a round trip with its trailing zeros intact.

## Consequences

- **The backend change for the entire frontend is one guarded mount.** No route
  moves, no contract changes, no new Python runtime dependency (`StaticFiles` is
  Starlette, already present via the `api` extra).
- **A missed prefix in the Vite proxy fails only at runtime**, and the symptom is
  an HTML page arriving where JSON was expected. The proxy list is therefore
  exhaustive — every prefix the API owns — rather than only the ones the review
  screen happens to call.
- **`base: '/app/'` is required in `vite.config.ts`.** Without it the built asset
  URLs point at `/assets/...` and 404 behind the mount.
- **Frontend tests are a second suite, by design.** `python -m pytest` gains no
  Node dependency and must still pass on a machine with no `npm`. Vitest and
  Playwright run separately.
- The backend still defends itself: `_coerce_money` refuses a float outright, so
  a frontend mistake is a 400 rather than silent corruption. The `Money` type is
  belt and braces, not the only guard.
- **A test that asserts the absence of breakage cannot be proven by a RED run.**
  Three of this task's five tests passed before the feature existed, because they
  assert that nothing broke. The only way to prove them is to revert each
  guarantee separately and watch the right test fail — which is what exposed the
  vacuous one. See the ledger entry for the reproduction.

## References

ADR-0001 (`Decimal` money path — the reason money is a string in the browser);
ADR-0012 (review API identity, the persisted confidence breakdown, and "a machine
run never overwrites a `reviewed` row"); ADR-0014 (the same
skip-it-when-it-is-absent discipline, applied to imports);
`docs/superpowers/specs/2026-07-29-review-ui-design.md` (the full design,
including why bbox highlighting is out of scope);
`docs/superpowers/plans/2026-07-29-review-ui.md` (the five-task plan);
`src/receipts/review/api.py` (`_SpaFiles`, `_install_spa`);
`tests/test_api_static.py` (the guards);
`.superpowers/sdd/2026-07-29-review-ui/progress.md` (the vacuous-test
reproduction and its ruling).
