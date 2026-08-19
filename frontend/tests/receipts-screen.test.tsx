import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/client'
import { ReceiptsScreen } from '../src/receipts/ReceiptsScreen'
import type { Identity } from '../src/api/admin'
import type { ExportReceiptPage } from '../src/api/receipts'
import type { Money, ReceiptSummary } from '../src/api/types'

/** The results list -- design sections 6 and 7 of the results-list spec.
 *
 * ## `@testing-library/jest-dom` is not in this repository
 *
 * The task brief's fixtures were written with `toBeInTheDocument()` and
 * `toHaveTextContent()`. Neither matcher exists here: `package.json` has no
 * `@testing-library/jest-dom`, `node_modules/@testing-library` holds exactly
 * `dom`, `react` and `user-event`, and `vite.config.ts` declares no
 * `setupFiles`. As written those assertions are a `TypeError`, not a failing
 * expectation. Every one of them is expressed below in the idiom the rest of
 * this suite already uses -- `toBeNull()`, `toBeDefined()`, `.textContent` --
 * which is why `admin-screen.test.tsx` and `value.test.tsx` are written that
 * way too.
 *
 * ## The API module is mocked, the client module is not
 *
 * What is under test is the screen, so `fetchExportReceipts` and
 * `downloadExportWorkbook` are replaced wholesale -- `receipts-api.test.ts`
 * already pins what they do against `fetch`, and re-deriving that here would
 * make every assertion below depend on the shape of a `Response`.
 *
 * `../src/api/client` is deliberately left real: the screen discriminates on
 * `caught instanceof ApiError`, and a mocked module would give the test a
 * different class object than the component holds, so that branch would be
 * exercised against a lie.
 *
 * ## No `vi.spyOn` anywhere in this file
 *
 * `vi.unstubAllGlobals()` does not undo a spy and nothing sets `restoreMocks`,
 * so a spy outlives the test that installed it -- measured in
 * `receipts-api.test.ts`, where it made an assertion unable to fail. The mocks
 * here come from the `vi.mock` factory and are reset explicitly per test.
 */

const api = vi.hoisted(() => ({
  fetchExportReceipts: vi.fn(),
  downloadExportWorkbook: vi.fn(),
}))

vi.mock('../src/api/receipts', () => api)

// `globals: true` is deliberately absent from vite.config.ts, so
// `@testing-library/react` never installs its auto-cleanup hook and every render
// here has to be unmounted by this file.
afterEach(() => {
  cleanup()
})

beforeEach(() => {
  // The factory above runs once per file, so the queue `mockResolvedValueOnce`
  // builds and any implementation a previous test set would otherwise be handed
  // to the next one.
  api.fetchExportReceipts.mockReset()
  api.downloadExportWorkbook.mockReset()
})

// --------------------------------------------------------------------------- //
// Fixtures
// --------------------------------------------------------------------------- //

const ADMIN: Identity = { username: 'ada', role: 'admin' }
const REVIEWER: Identity = { username: 'bob', role: 'reviewer' }
/** Neither role the system defines. `role` is a `string` because `request<T>` is
 *  an unchecked cast, so this is a value the server really can send. */
const AUDITOR: Identity = { username: 'eve', role: 'auditor' }

/** Distinct ids without a caller having to think about them.
 *
 *  Two pages appended into one array is the whole point of the paging test, and
 *  two rows sharing a `key` is a React warning plus a dropped row -- a test that
 *  fabricated its own duplicate would then be measuring the fixture. */
let nextRow = 0

function rowFixture(overrides: Partial<ReceiptSummary> = {}): ReceiptSummary {
  nextRow += 1
  return {
    id: `receipt-${nextRow}`,
    status: 'reviewed',
    confidence: '0.940' as Money,
    merchant_name_raw: 'Summit Fuel',
    txn_date: '2026-08-14',
    currency: 'PHP',
    total: '1234.50' as Money,
    created_at: '2026-08-14T09:15:00+00:00',
    ...overrides,
  }
}

function stubPage(page: ExportReceiptPage) {
  api.fetchExportReceipts.mockResolvedValue(page)
  return api.fetchExportReceipts
}

/** The pages a test plans for, in order, and a **loud** answer after them.
 *
 *  The fallback is a rejection rather than the last page repeated: a screen that
 *  listed one page too many would otherwise be handed data that looks right, and
 *  the extra call would leave no trace. */
function stubPages(pages: readonly ExportReceiptPage[]) {
  api.fetchExportReceipts.mockRejectedValue(
    new Error('fetchExportReceipts was called more times than this test planned'),
  )
  for (const page of pages) {
    api.fetchExportReceipts.mockResolvedValueOnce(page)
  }
  return api.fetchExportReceipts
}

function stubDownloadRejection(caught: unknown) {
  api.downloadExportWorkbook.mockRejectedValue(caught)
  return api.downloadExportWorkbook
}

/** A download that is still in flight when the assertion runs.
 *
 *  A promise that never settles, so the pending state cannot be raced: the
 *  component's `finally` never fires and the button stays disabled for the whole
 *  test. Nothing rejects, so there is no unhandled rejection to leak. */
function stubSlowDownload() {
  api.downloadExportWorkbook.mockReturnValue(new Promise<void>(() => {}))
  return api.downloadExportWorkbook
}

/** A page fetch the test controls the settling of, for the same reason. */
function deferredPage() {
  let settle: (page: ExportReceiptPage) => void = () => {}
  const promise = new Promise<ExportReceiptPage>((resolve) => {
    settle = resolve
  })
  return { promise, settle }
}

// --------------------------------------------------------------------------- //
// Reading the table by its own headers rather than by a hard-coded index
// --------------------------------------------------------------------------- //

/** The index of the column headed `header`, read off the rendered `<thead>`.
 *
 *  A hard-coded `cells[2]` silently follows a reordered column onto the wrong
 *  data and goes on passing; this throws instead, naming the columns it did
 *  find. Copied from `admin-screen.test.tsx`, which records the same reason. */
function columnIndex(table: HTMLElement, header: string): number {
  const headers = [...table.querySelectorAll('thead th')].map((th) => th.textContent?.trim() ?? '')
  const index = headers.indexOf(header)
  if (index === -1) {
    throw new Error(`no column headed "${header}"; the columns are: ${headers.join(' | ')}`)
  }
  return index
}

function cellUnder(row: HTMLTableRowElement, table: HTMLElement, header: string): HTMLElement {
  return row.cells[columnIndex(table, header)]
}

function bodyRows(table: HTMLElement): HTMLTableRowElement[] {
  return [...table.querySelectorAll<HTMLTableRowElement>('tbody tr')]
}

// --------------------------------------------------------------------------- //
// Identity, and the admin gate
// --------------------------------------------------------------------------- //

describe('the screen asks for nothing until it knows who is asking', () => {
  it('renders a wait branch while the identity is unknown', () => {
    render(<ReceiptsScreen identity={null} />)

    // `null` means "not yet answered", never "not an admin" -- so the export
    // button is absent because the question is open, not because it was refused.
    expect(screen.queryByRole('button', { name: /export/i })).toBeNull()
    expect(screen.getByText(/waiting/i)).toBeDefined()
    // And nothing is listed either. The list is the export's own scope, which is
    // the same for both roles, but `AdminScreen`'s rule is the one being copied:
    // an identity that has not arrived means the caller is unknown.
    expect(api.fetchExportReceipts).not.toHaveBeenCalled()
  })

  it('shows the export button to an admin', async () => {
    stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)

    expect(await screen.findByRole('button', { name: /export/i })).toBeDefined()
  })

  it('hides the export button from a reviewer', async () => {
    stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={REVIEWER} />)

    // The list itself is `require_user`, so a reviewer does see the rows -- the
    // asymmetry design decision 3 sets, and the reason the wait is on the button
    // rather than on the table.
    await screen.findByText('Summit Fuel')
    expect(screen.queryByRole('button', { name: /export/i })).toBeNull()
  })

  it('hides the export button from an unrecognised role, rather than failing open', async () => {
    stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={AUDITOR} />)

    // The gate is `role === 'admin'` compared positively, so every other value
    // -- including one this app has never heard of -- takes the narrow branch.
    // A `role !== 'reviewer'` gate would hand this session the button.
    await screen.findByText('Summit Fuel')
    expect(screen.queryByRole('button', { name: /export/i })).toBeNull()
  })
})

// --------------------------------------------------------------------------- //
// The columns, and the null treatment on every one of them that can be null
// --------------------------------------------------------------------------- //

describe('the table renders the row shape the serializer sends', () => {
  it('carries the five columns in the order the design sets', async () => {
    stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)

    const table = await screen.findByRole('table')
    const headers = [...table.querySelectorAll('thead th')].map((th) => th.textContent?.trim())
    expect(headers).toEqual(['Date', 'Merchant', 'Total', 'Status', 'Confidence'])
  })

  it('puts each value under its own column', async () => {
    stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)

    const table = await screen.findByRole('table')
    const row = bodyRows(table)[0]
    // Read by header rather than by index, so a swapped pair of columns is a
    // failure here rather than a screen that renders a date under "Merchant".
    expect(cellUnder(row, table, 'Date').textContent).toContain('2026-08-14')
    expect(cellUnder(row, table, 'Merchant').textContent).toContain('Summit Fuel')
    expect(cellUnder(row, table, 'Status').textContent).toContain('reviewed')
    expect(cellUnder(row, table, 'Confidence').textContent).toContain('0.940')
    // The amount and the currency share one cell -- design section 6's
    // "`total` with `currency`". Asserted as two `toContain`s rather than one
    // literal, because the space between them is a CSS margin and `css: false`
    // means no stylesheet is applied here.
    const total = cellUnder(row, table, 'Total')
    expect(total.textContent).toContain('1234.50')
    expect(total.textContent).toContain('PHP')
  })

  it('renders a null field as not-extracted, not as an empty cell', async () => {
    // All four nullable columns at once, which is the supporting pin design
    // section 8 names: "each nullable column renders its null treatment rather
    // than an empty cell". A count of marks over the whole screen cannot say
    // *which* cell is blank, so each one is asked for by name.
    stubPage({
      items: [
        rowFixture({
          txn_date: null,
          merchant_name_raw: null,
          total: null,
          confidence: null,
        }),
      ],
      has_more: false,
    })

    render(<ReceiptsScreen identity={ADMIN} />)

    const table = await screen.findByRole('table')
    const row = bodyRows(table)[0]
    for (const column of ['Date', 'Merchant', 'Total', 'Confidence']) {
      // Through the accessibility tree, not through `getByLabelText`.
      // `ui/Value`'s own docstring records why: `getByLabelText` reads the
      // attribute off the DOM and never consults the role, so it passed
      // identically when the guarantee was not delivered.
      const cell = cellUnder(row, table, column)
      expect(
        within(cell).getByRole('img', { name: 'not extracted' }),
        `the ${column} cell renders a null as an empty cell`,
      ).toBeDefined()
    }
  })

  it('keeps a currency the extractor did read, even when the amount is missing', async () => {
    // `null` total and a real currency is a receipt whose amount was not read,
    // not a receipt with no currency -- and dropping the code because its
    // neighbour is missing would be the silent loss ADR-0027 decision 5 is about.
    stubPage({ items: [rowFixture({ total: null, currency: 'PHP' })], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)

    const table = await screen.findByRole('table')
    const total = cellUnder(bodyRows(table)[0], table, 'Total')
    expect(total.textContent).toContain('PHP')
    expect(within(total).getByRole('img', { name: 'not extracted' })).toBeDefined()
  })

  it('says the list is empty rather than drawing an empty table', async () => {
    stubPage({ items: [], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)

    expect(await screen.findByText(/no receipts/i)).toBeDefined()
    expect(screen.queryByRole('table')).toBeNull()
  })
})

// --------------------------------------------------------------------------- //
// Paging
// --------------------------------------------------------------------------- //

describe('paging is a Load more button driven by has_more', () => {
  it('offers Load more only while has_more is true, and appends', async () => {
    stubPages([
      { items: [rowFixture({ merchant_name_raw: 'First' })], has_more: true },
      { items: [rowFixture({ merchant_name_raw: 'Second' })], has_more: false },
    ])
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    await user.click(await screen.findByRole('button', { name: /load more/i }))

    // Appended, not replaced. A screen that set the rows from the new page alone
    // would still pass a "Second is on screen" assertion on its own.
    expect(screen.getByText('First')).toBeDefined()
    expect(screen.getByText('Second')).toBeDefined()
    expect(screen.queryByRole('button', { name: /load more/i })).toBeNull()
  })

  it('asks for the next page at the offset of the rows already shown', async () => {
    // Two rows on the first page, so an `offset` of 2 cannot be confused with a
    // hard-coded 1 -- and `offset: 0` on the second call, which is the mutation
    // that duplicates every row, is a failure here.
    stubPages([
      {
        items: [
          rowFixture({ merchant_name_raw: 'First' }),
          rowFixture({ merchant_name_raw: 'Second' }),
        ],
        has_more: true,
      },
      { items: [rowFixture({ merchant_name_raw: 'Third' })], has_more: false },
    ])
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    await user.click(await screen.findByRole('button', { name: /load more/i }))
    await screen.findByText('Third')

    expect(api.fetchExportReceipts.mock.calls[0]?.[0]).toEqual({ limit: 50, offset: 0 })
    expect(api.fetchExportReceipts.mock.calls[1]?.[0]).toEqual({ limit: 50, offset: 2 })
    expect(api.fetchExportReceipts).toHaveBeenCalledTimes(2)
  })

  it('does not fire a second page request while one is in flight', async () => {
    const second = deferredPage()
    api.fetchExportReceipts
      .mockResolvedValueOnce({ items: [rowFixture({ merchant_name_raw: 'First' })], has_more: true })
      .mockReturnValueOnce(second.promise)
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    const more = await screen.findByRole('button', { name: /load more/i })
    await user.click(more)
    expect(more.hasAttribute('disabled')).toBe(true)
    await user.click(more)

    expect(api.fetchExportReceipts).toHaveBeenCalledTimes(2)

    second.settle({ items: [rowFixture({ merchant_name_raw: 'Second' })], has_more: false })
    await screen.findByText('Second')
  })

  it('keeps the rows it already has when the next page fails', async () => {
    // The first page is still exactly what the server sent. Clearing it because
    // a *later* page failed would destroy good data -- which is why the
    // `setRows(null)` that a failed first load performs must not be shared here.
    stubPages([{ items: [rowFixture({ merchant_name_raw: 'First' })], has_more: true }])
    api.fetchExportReceipts.mockRejectedValue(new ApiError(500, 'the database went away'))
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    await user.click(await screen.findByRole('button', { name: /load more/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('the database went away')
    expect(screen.getByText('First')).toBeDefined()
  })
})

// --------------------------------------------------------------------------- //
// The one alert region, and the export
// --------------------------------------------------------------------------- //

describe('one role="alert" region, whatever went wrong', () => {
  it("surfaces the export's own message in the one alert region", async () => {
    stubPage({ items: [rowFixture()], has_more: false })
    // The route refuses rather than truncating above `_EXPORT_MAX_ROWS`, and its
    // advice names filters v1 does not have. Surfaced verbatim anyway: ADR-0024
    // says the classifier never invents copy.
    stubDownloadRejection(new ApiError(400, 'this export matches more than 5000 receipts'))
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    await user.click(await screen.findByRole('button', { name: /export/i }))

    const alerts = await screen.findAllByRole('alert')
    expect(alerts).toHaveLength(1)
    expect(alerts[0].textContent).toMatch(/more than 5000/i)
  })

  it('holds a failed listing and a failed export in the SAME region', async () => {
    // The property the single region exists for, and the only assertion that can
    // tell one shared region from two regions that happen not to be shown at
    // once. Two would make every `findByRole('alert')` in this file throw.
    api.fetchExportReceipts.mockRejectedValue(new ApiError(500, 'could not reach the database'))
    stubDownloadRejection(new ApiError(400, 'this export matches more than 5000 receipts'))
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    await screen.findByText(/could not reach the database/)
    await user.click(screen.getByRole('button', { name: /export/i }))
    await screen.findByText(/more than 5000/)

    const alerts = screen.getAllByRole('alert')
    expect(alerts).toHaveLength(1)
    expect(alerts[0].textContent).toContain('could not reach the database')
    expect(alerts[0].textContent).toContain('more than 5000')
  })

  it('falls back to its own sentence when the failure carries no API message', async () => {
    // A `TypeError: Failed to fetch` from a server that is not up carries
    // nothing a reader can act on; a 400's own words are the whole answer. The
    // same split `AdminScreen`, `ReviewScreen` and `LoginPage` already make.
    stubPage({ items: [rowFixture()], has_more: false })
    stubDownloadRejection(new TypeError('Failed to fetch'))
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    await user.click(await screen.findByRole('button', { name: /export/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).not.toContain('Failed to fetch')
    expect(alert.textContent).toMatch(/export/i)
  })

  it('does not fire a second download while one is in flight', async () => {
    stubPage({ items: [rowFixture()], has_more: false })
    const download = stubSlowDownload()
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)

    const button = await screen.findByRole('button', { name: /export/i })
    await user.click(button)
    // The mechanism, asserted separately from the property below: the workbook
    // is built synchronously and wholly in memory server-side, so a second click
    // while the first is in flight is a real hazard, not a theoretical one.
    expect(button.hasAttribute('disabled')).toBe(true)
    await user.click(button)

    expect(download).toHaveBeenCalledOnce()
  })
})

// --------------------------------------------------------------------------- //
// The class-name guard: under `css: false` nothing else can see a typo
// --------------------------------------------------------------------------- //

describe('every class this screen references exists in its stylesheet', () => {
  // Under Vitest's `css: false` a `.module.css` import is a proxy whose keys echo
  // back as strings, so `styles.tabel` renders `class="undefined"` and every
  // rendering test above still passes. Anything about the CSS itself therefore
  // has to be read off the file -- the same shape `admin-screen.test.tsx`,
  // `review-null-rule.test.tsx` and `value.test.tsx` use.
  //
  // `dirname(fileURLToPath(import.meta.url))` rather than
  // `new URL(specifier, import.meta.url)`: Vite rewrites that *pattern* into a
  // static-asset import and refuses outright for a `.module.css` specifier with
  // `?url is not supported with CSS modules`.
  const RECEIPTS_SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'receipts')

  function readReceiptsFile(relative: string): string {
    try {
      return readFileSync(join(RECEIPTS_SRC, relative), 'utf8')
    } catch (cause) {
      throw new Error(
        `a guard in this file cannot read src/receipts/${relative}. If that file moved ` +
          `or was renamed, update this path -- the guard is not optional cover.`,
        { cause },
      )
    }
  }

  /** Class selectors the stylesheet declares, comments stripped first -- this
   *  file documents the rules it contains, and prose must not answer for code. */
  function declaredClasses(css: string): Set<string> {
    const source = css.replace(/\/\*[\s\S]*?\*\//g, '')
    return new Set(Array.from(source.matchAll(/\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  /** `styles.foo` references the component makes, comments stripped for the same
   *  reason: it names its own classes in prose too. */
  function referencedClasses(tsx: string): Set<string> {
    const source = tsx.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    return new Set(Array.from(source.matchAll(/\bstyles\.([A-Za-z][\w-]*)/g), (m) => m[1]))
  }

  it('extracts from both sides, and is not fooled by a comment', () => {
    expect(declaredClasses('.real { color: red }').has('real')).toBe(true)
    expect(declaredClasses('/* .ghost {} */ .real {}').has('ghost')).toBe(false)
    expect(referencedClasses('x = styles.real').has('real')).toBe(true)
    expect(referencedClasses('/* styles.ghost */ x = styles.real').has('ghost')).toBe(false)
    expect(referencedClasses('// styles.ghost\nx = styles.real').has('ghost')).toBe(false)
  })

  it('declares every class the component reaches', () => {
    const declared = declaredClasses(readReceiptsFile('ReceiptsScreen.module.css'))
    const referenced = referencedClasses(readReceiptsFile('ReceiptsScreen.tsx'))
    expect(referenced.size, 'ReceiptsScreen.tsx references no styles.*').toBeGreaterThan(0)
    const missing = [...referenced].filter((name) => !declared.has(name))
    expect(
      missing,
      'ReceiptsScreen.tsx reaches classes ReceiptsScreen.module.css does not declare',
    ).toEqual([])
  })

  // The other direction, and it is not symmetry for its own sake. The check above
  // can only fail on a reference with no declaration, so deleting a `className`
  // outright is invisible to it -- measured in `admin-screen.test.tsx` on
  // 2026-08-14 by deleting `<div className={styles.grid}>` from `StatTiles.tsx`:
  // whole suite green, `tsc -b` clean, build green, and the tiles rendered as
  // four full-width rows. `stylesheets.test.ts`'s census audits declarations
  // without asking whether anything reaches them.
  //
  // The bound: `referencedClasses` matches `styles.NAME` only, so a class reached
  // by dynamic indexing -- `styles[tone]`, which `ui/Chip` does -- is invisible to
  // it and would fail here. Measured when this was written: `ReceiptsScreen.tsx`
  // does not index `styles` at all. If it gains dynamic indexing the answer is a
  // computed list, the way `value.test.tsx` holds one, not an exception.
  it('reaches every class its stylesheet declares, so a rule cannot be left dead', () => {
    const declared = declaredClasses(readReceiptsFile('ReceiptsScreen.module.css'))
    const referenced = referencedClasses(readReceiptsFile('ReceiptsScreen.tsx'))
    expect(declared.size, 'ReceiptsScreen.module.css declares no classes').toBeGreaterThan(0)
    const dead = [...declared].filter((name) => !referenced.has(name))
    expect(
      dead,
      'ReceiptsScreen.module.css declares classes ReceiptsScreen.tsx never reaches',
    ).toEqual([])
  })

  it('paints from tokens, with no raw hex', () => {
    // The Global Constraint, and a thing no rendering test can see. The census
    // in `stylesheets.test.ts` records that a colour declaration exists; it does
    // not care what the value is.
    const css = readReceiptsFile('ReceiptsScreen.module.css').replace(/\/\*[\s\S]*?\*\//g, '')
    expect(css.match(/#[0-9A-Fa-f]{3,8}\b/g) ?? []).toEqual([])
  })
})
