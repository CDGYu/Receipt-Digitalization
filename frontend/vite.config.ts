// `defineConfig` comes from 'vitest/config', not from 'vite'. Vite's own
// `UserConfig` has no `test` key, so the `vite` import fails to compile with
// `TS2769: ... 'test' does not exist in type 'UserConfigExport'` -- verified by
// running `tsc -b` on the 'vite' version first. 'vitest/config' re-exports a
// `defineConfig` whose config type is Vite's plus `test`, so every option
// below (base, build, server) still means exactly what it means to Vite.
import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Every prefix the API owns. A missing entry fails only at runtime, and the
// symptom is an HTML page arriving where JSON was expected -- so this list is
// exhaustive rather than "the ones the review screen happens to call".
//
// The list below was ENUMERATED FROM THE BUILT APP, not grepped for decorators
// and not recalled: build `create_app`, then walk `app.routes` recursing
// through `.original_router.routes`. That recursion is not optional --
// `include_router` wraps the auth router in an `_IncludedRouter`, so a FLAT
// walk yields ZERO /auth/* paths. This comment previously claimed to be
// "cross-checked against every route `create_app` registers" and was missing
// three of them, which is what a list in prose costs when it is trusted
// instead of re-derived (review standards 17 and 20).
//
// Re-derived 2026-08-24 with DOCS_ENABLED unset and SERVE_SPA=false, so the
// number below is routes only: 19. Serving the SPA adds the /app mount and
// nothing else.
//   GET  /health          GET  /metrics
//   GET  /receipts        GET  /receipts/{id}       PATCH /receipts/{id}
//   GET  /receipts/{id}/image                       GET   /receipts/{id}/image/blob
//   GET  /receipts/{id}/corrections                 GET   /receipts/{id}/progress
//   POST /upload          GET  /export/xlsx         GET   /export/receipts
//   GET  /review/next     GET  /review/tasks
//   POST /review/{id}/complete                      POST  /review/{id}/release
//   POST /auth/login      POST /auth/logout         GET   /auth/me
//
// This block said 17 and omitted /export/receipts and /receipts/{id}/progress
// until 2026-08-24. It was correct on 2026-08-11 when it was written and then
// rotted twice: /export/receipts landed 2026-08-19 and /receipts/{id}/progress
// on 2026-08-23. Second time this list has been overtaken by new routes --
// which is why the method and the date are recorded above, and why the fix is
// to re-run the enumeration rather than to patch the list by hand.
//
// The SPA itself lives under /app/, which no API route uses, so nothing here
// can collide with a client-side route.
const API_PREFIXES = [
  '/receipts',
  '/review',
  '/auth',
  '/upload',
  '/export',
  '/health',
  '/metrics',
  // FastAPI's own, registered by `create_app` only when DOCS_ENABLED is true
  // (config/settings.py defaults it to false). **Three prefixes, four route
  // paths** -- the same enumeration run with DOCS_ENABLED=true returns 23
  // rather than 19, because /docs also registers /docs/oauth2-redirect. Three
  // entries still cover all four, since this array matches by prefix. The SPA
  // never fetches them, but "every prefix the API owns" includes the ones a
  // developer opens by hand, and a dev server that answers /docs with the SPA
  // shell instead of Swagger is the same class of confusion this list exists
  // to prevent.
  '/docs',
  '/redoc',
  '/openapi.json',
]

export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: { outDir: 'dist' },
  server: {
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [p, { target: 'http://localhost:8000', changeOrigin: false }]),
    ),
  },
  // No `globals: true`. Every test imports `describe`/`it`/`expect` from
  // 'vitest' explicitly, and no tsconfig lists `vitest/globals` in `types` --
  // so a test that leaned on the globals would run green under Vitest and fail
  // `tsc -b`. Dropping it keeps the runner and the compiler telling the same
  // story. (`@testing-library/react`'s auto-cleanup needs a global `afterEach`,
  // which is why every component test calls `cleanup()` in its own `afterEach`.)
  // `e2e/**` is excluded because Vitest's default `include` is
  // `**/*.{test,spec}.*` -- which matches `e2e/review.spec.ts`, the Playwright
  // acceptance spec. The two runners share a filename convention and nothing
  // else. Measured by dropping this `exclude` and running `npx vitest run`:
  // `FAIL e2e/review.spec.ts` / `Error: Playwright Test did not expect test()
  // to be called here.`, one failed file alongside the fifteen that pass.
  // `testTimeout` is 15s, not Vitest's 5s default, and the reason is measured
  // rather than defensive. Four runs of the SAME tree gave 4, 1, 0 and 5
  // failures; every failure was `Test timed out in 5000ms` in a test that
  // mounts the whole app or `await import('../src/main')`, and the durations
  // cluster just past the line -- 5046, 5151, 5296, 5411, 6572, 7121ms. The
  // files differ run to run, which is the signature of a budget being crossed
  // rather than a defect: bisecting it reads as noise.
  //
  // `main.tsx` now imports eight screens plus the nav and sign-out control, and
  // the entry module pulls seven `@fontsource` packages, on a 2-core box that
  // is also running Postgres, Redis, two Ollamas and four Claude sessions. The
  // 5s default stopped being generous somewhere in that growth.
  //
  // 15s is three times the observed worst case, and still fails fast on a real
  // hang. **This does not make a slow test pass** -- it stops a loaded machine
  // reporting a green tree as red, which is worse than useless because it
  // teaches everyone to re-run rather than to read.
  test: {
    environment: 'jsdom',
    exclude: [...configDefaults.exclude, 'e2e/**'],
    testTimeout: 15_000,
  },
})
