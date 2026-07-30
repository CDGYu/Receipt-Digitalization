// `defineConfig` comes from 'vitest/config', not from 'vite'. Vite's own
// `UserConfig` has no `test` key, so the `vite` import fails to compile with
// `TS2769: ... 'test' does not exist in type 'UserConfigExport'` -- verified by
// running `tsc -b` on the 'vite' version first. 'vitest/config' re-exports a
// `defineConfig` whose config type is Vite's plus `test`, so every option
// below (base, build, server) still means exactly what it means to Vite.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Every prefix the API owns. A missing entry fails only at runtime, and the
// symptom is an HTML page arriving where JSON was expected -- so this list is
// exhaustive rather than "the ones the review screen happens to call".
//
// Cross-checked against every route `create_app` registers in
// src/receipts/review/api.py:
//   GET  /health                              GET   /metrics
//   GET  /receipts        GET /receipts/{id}  PATCH /receipts/{id}
//   GET  /receipts/{id}/image                 GET   /receipts/{id}/image/blob
//   POST /upload          GET /export/xlsx
//   GET  /review/next     POST /review/{id}/complete
//   POST /auth/login      POST /auth/logout
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
  // FastAPI's own three, registered by `create_app` only when DOCS_ENABLED is
  // true (config/settings.py defaults it to false). The SPA never fetches
  // them, but "every prefix the API owns" includes the ones a developer opens
  // by hand, and a dev server that answers /docs with the SPA shell instead of
  // Swagger is the same class of confusion this list exists to prevent.
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
  test: { environment: 'jsdom', globals: true },
})
