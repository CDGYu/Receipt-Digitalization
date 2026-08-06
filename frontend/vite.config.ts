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
// walk yields 13 routes with ZERO /auth/* paths. This comment previously
// claimed to be "cross-checked against every route `create_app` registers" and
// was missing three of them, which is what a list in prose costs when it is
// trusted instead of re-derived (review standards 17 and 20).
//
// Measured 2026-08-06 with DOCS_ENABLED unset: 16 routes plus the /app mount.
//   GET  /health          GET  /metrics
//   GET  /receipts        GET  /receipts/{id}       PATCH /receipts/{id}
//   GET  /receipts/{id}/image                       GET   /receipts/{id}/image/blob
//   POST /upload          GET  /export/xlsx
//   GET  /review/next     GET  /review/tasks
//   POST /review/{id}/complete                      POST  /review/{id}/release
//   POST /auth/login      POST /auth/logout         GET   /auth/me
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
  // paths** -- the same enumeration run with DOCS_ENABLED=true returns 21
  // rather than 17, because /docs also registers /docs/oauth2-redirect. Three
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
  test: { environment: 'jsdom', exclude: [...configDefaults.exclude, 'e2e/**'] },
})
