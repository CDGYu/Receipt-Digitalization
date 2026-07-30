import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from '@playwright/test'

/** The acceptance run: a real browser against a real API on SQLite (design 6.3).
 *
 * `__dirname` does not exist here -- `frontend/package.json` sets
 * `"type": "module"`, so this file is ESM and the config's own directory has to
 * come from `import.meta.url`.
 */
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

/** Not 8000: that is where a hand-started dev API lives (see `vite.config.ts`'s
 *  proxy target), and an acceptance run must not quietly attach itself to one. */
const PORT = 8100
const BASE_URL = `http://127.0.0.1:${PORT}`

/** Repo-root-relative, because `webServer.cwd` is the repo root. */
const DB_URL = 'sqlite:///var/e2e/review-e2e.db'

/** `python3` on most Linux images, `python` here. */
const PYTHON = process.env.PYTHON ?? 'python'

/** Build, seed, serve -- in one command, in that order, on purpose.
 *
 * The three are a chain rather than three `webServer` entries because each one
 * has to finish before the next begins and only the last one listens on a port:
 *
 *   * the **build** first, so the run cannot test a stale bundle. Serving the
 *     built app through FastAPI (rather than through the Vite dev server) is
 *     what makes this the same-origin arrangement production would use, and it
 *     is the only thing that exercises Task 1's `/app` mount at all;
 *   * the **seed** second, and it deletes the database file, which is only
 *     possible while nothing has it open -- so it cannot be a `globalSetup`
 *     racing the server for the same file on Windows;
 *   * the **server** last, and Playwright waits for its `/health`.
 */
const COMMAND = [
  'npm --prefix frontend run build',
  `${PYTHON} scripts/seed_review_e2e.py --db ${DB_URL} --reset`,
  `${PYTHON} scripts/serve_review_e2e.py --db ${DB_URL} --port ${PORT}`,
].join(' && ')

export default defineConfig({
  testDir: './e2e',
  /** Under `var/`, which is already git-ignored, rather than the default
   *  `test-results/` -- traces and screenshots of receipt data are exactly what
   *  that ignore rule exists for. */
  outputDir: path.join(REPO_ROOT, 'var', 'e2e', 'test-results'),
  reporter: 'list',
  /** One worker, no parallelism, and **no retries**: there is one queued review
   *  task in the fixture and the first test consumes it. A retry would re-run
   *  against a drained queue and fail for a reason that has nothing to do with
   *  the defect, so a red run here has to stay red. Re-running the suite
   *  re-seeds (see `COMMAND`) and is the supported way to try again. */
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: COMMAND,
    cwd: REPO_ROOT,
    url: `${BASE_URL}/health`,
    /** Never reuse: the seed is part of `COMMAND`, so attaching to a server
     *  somebody else started would run the tests against whatever state that
     *  database happens to be in -- including a queue task already closed. */
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
    timeout: 180_000,
  },
})
