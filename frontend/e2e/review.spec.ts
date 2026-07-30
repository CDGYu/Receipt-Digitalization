import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

/** P5.T1's acceptance: a reviewer corrects a receipt and the correction lands.
 *
 * Everything this file asserts about the outcome is read from the API or from
 * the `corrections` table -- never from the screen's own success message, which
 * would be the UI confirming itself.
 */

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const SEED_SCRIPT = 'scripts/seed_review_e2e.py'
const MANIFEST = path.join(REPO_ROOT, 'var', 'e2e', 'seed.json')
const PYTHON = process.env.PYTHON ?? 'python'

/** What the reviewer types. */
const NEW_TOTAL = '1234.56'
const NEW_QTY = '5'

/** What the API returns for them afterwards -- **not** the same strings.
 *
 * Both columns are `Numeric(_, 4)`, so SQLAlchemy renders four decimal places
 * back out and `money()` hands that to JSON verbatim (ADR-0001: a string, never
 * a float). Measured through the real route: `PATCH {'totals.total':
 * '1234.56'}` reads back as `'1234.5600'`, and `{'line_items[1].qty': '5'}` as
 * `'5.0000'`. Asserting the typed string here would fail, and "correct" it in
 * the wrong direction -- the display scale is the database's, not a bug.
 */
const STORED_TOTAL = '1234.5600'
const STORED_QTY = '5.0000'

interface Fixture {
  readonly db_url: string
  readonly receipt_id: string
  readonly username: string
  readonly password: string
}

interface Correction {
  readonly field_path: string
  readonly value_before: string | null
  readonly value_after: string | null
  readonly corrected_by: string
}

/** Identifiers and credentials, written by the seed. It carries no field
 *  values on purpose -- see the seed script -- so nothing here can compare the
 *  API against a round trip of the fixture's own idea of what it wrote. */
function fixture(): Fixture {
  return JSON.parse(readFileSync(MANIFEST, 'utf8')) as Fixture
}

/** The `corrections` rows for a receipt: the audit trail, read out of band.
 *
 * **No API route exposes this table.** `PATCH /receipts/{id}` writes it through
 * `apply_corrections` and no read route selects it, so the acceptance criterion
 * design 6.3 actually names -- the audit trail, with the reviewer's username on
 * it -- is not reachable over HTTP. The seed script reads it back instead. That
 * is a gap in the API, recorded rather than papered over: a reviewer cannot see
 * the history of a receipt they are correcting either.
 */
function corrections(dbUrl: string, receiptId: string): Correction[] {
  const stdout = execFileSync(
    PYTHON,
    [SEED_SCRIPT, '--db', dbUrl, '--dump-corrections', receiptId],
    { cwd: REPO_ROOT, encoding: 'utf8' },
  )
  return JSON.parse(stdout) as Correction[]
}

test('a reviewer corrects a receipt and the correction is persisted', async ({ page }) => {
  const seed = fixture()
  const started = Date.now()

  await page.goto('/app/login')
  await page.getByLabel('Username').fill(seed.username)
  await page.getByLabel('Password').fill(seed.password)
  await page.getByRole('button', { name: 'Sign in' }).click()

  // The line-items table comes from `GET /receipts/{id}`, the second of the two
  // requests the screen makes, so it being on screen means the whole
  // claim-then-load chain finished.
  await expect(page.getByRole('table')).toBeVisible()

  // Read the receipt as the API has it *now*, through the same session the
  // browser holds (`page.request` shares the context's cookies; the bare
  // `request` fixture does not, and would get a 401 here). This is the
  // left-hand side of every "did anything else move" assertion below, and it
  // comes from the API rather than from the seed.
  const before = await page.request.get(`/receipts/${seed.receipt_id}`)
  expect(before.ok()).toBeTruthy()
  const was = await before.json()
  expect(was.status).toBe('needs_review')

  // `exact` on every label. Playwright's default label match is a
  // case-insensitive substring, so a bare `Total` resolves to every label
  // containing `total` -- `Subtotal`, and one `Line total N` per line item --
  // which is a strict-mode violation and fails the call. `Qty 1` addresses the
  // item at *position* 1, which is the second row: the form labels line-item
  // controls by position, not by index.
  await page.getByLabel('Total', { exact: true }).fill(NEW_TOTAL)
  await page.getByLabel('Qty 1', { exact: true }).fill(NEW_QTY)
  await page.keyboard.press('ControlOrMeta+Enter')

  // The queue held exactly one task, so the screen advancing to its empty state
  // is the whole chain -- PATCH, then complete, then the next claim -- having
  // run to the end. A screen that stopped on a rewrite notice or an error would
  // still be showing the receipt.
  await expect(page.getByText('The review queue is empty.')).toBeVisible()

  // Stopped here, before the assertions: the budget is about the reviewer's
  // path through the screen, not about this file's verification tooling (which
  // spawns a Python process and would add a second or two of nothing to do with
  // the UI).
  const elapsedMs = Date.now() - started

  const after = await page.request.get(`/receipts/${seed.receipt_id}`)
  expect(after.ok()).toBeTruthy()
  const now = await after.json()
  expect(now.status).toBe('reviewed')
  expect(now.totals.total).toBe(STORED_TOTAL)
  const edited = now.line_items.find((item: { position: number }) => item.position === 1)
  expect(edited.qty).toBe(STORED_QTY)

  // Untouched fields, byte for byte, with the API on both sides of the
  // comparison. `txn_time` is the sharp one: it is `14:30:45` in the fixture and
  // a screen that rendered it as `14:30` would have sent the shortened form
  // back, which the route accepts -- destroying the seconds and booking a
  // correction for an edit nobody made.
  expect(now.txn_time).toBe(was.txn_time)
  expect(now.totals.subtotal).toBe(was.totals.subtotal)
  expect(now.date_raw).toBe(was.date_raw)
  expect(now.payment_method).toBe(was.payment_method)

  // The audit trail. Two rows for two edits, attributed to the session user --
  // `corrections.corrected_by` is written from the *server's* idea of who is
  // signed in, so this is also what proves the login mattered.
  //
  // Two, and not more -- but not every over-broad patch would show up here.
  // The server writes no row for a path whose *coerced* value already matches
  // what is stored, so a reformat that survives coercion is invisible to this:
  // measured, `PATCH {'totals.subtotal': '925'}` (and `'925.00'`, and
  // `'0925.0000'`) against a stored `925.0000` books nothing and changes no
  // read-back. What this does catch is a value that coerces to something
  // *different* being sent for a field nobody edited -- measured, `PATCH
  // {'receipt.time': '14:30'}` against a stored `14:30:45` answers 200, stores
  // `14:30:00` and books `('receipt.time', '14:30:45', '14:30:00')`, which is
  // the failure mode `txn_time` above describes.
  const rows = corrections(seed.db_url, seed.receipt_id)
  expect(rows.map((row) => row.field_path).sort()).toEqual([
    'line_items[1].qty',
    'totals.total',
  ])
  const total = rows.find((row) => row.field_path === 'totals.total')
  expect(total?.value_before).toBe(was.totals.total)
  expect(total?.value_after).toBe(NEW_TOTAL)
  expect(total?.corrected_by).toBe(seed.username)
  const qty = rows.find((row) => row.field_path === 'line_items[1].qty')
  expect(qty?.value_after).toBe(NEW_QTY)
  expect(qty?.corrected_by).toBe(seed.username)

  // **A regression guard, and nothing more.** The plan's acceptance is "a
  // scripted correction completes under 60s"; a scripted run does it in about
  // two, so 60s would pass even if the screen had become unusably slow. 10s is
  // roughly five times the expected time -- loose enough not to flake, tight
  // enough to trip on a real slowdown. It says nothing about how long a human
  // reviewer takes: that number needs a human trial, and a green run here is
  // not one.
  expect(elapsedMs).toBeLessThan(10_000)
})

test('an unauthenticated visitor is sent to the login page', async ({ page }) => {
  // A deep link, so this also exercises the mount's fallback: `/app/review` is
  // not a file, and the SPA shell is what must come back.
  await page.goto('/app/review')
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})
