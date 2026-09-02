import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/client'
import { PAGE_SIZE, ReceiptsScreen } from '../src/receipts/ReceiptsScreen'
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
  it('carries the six columns in the order the design sets', async () => {
    // Five until 2026-08-25, when the row gained a View action. The count is in
    // the name because the name is what a reader checks the header against --
    // and this assertion is the reason a sixth column could not be added
    // silently. `Detail` carries a real header rather than an empty cell: an
    // unnamed column is announced as nothing.
    stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)

    const table = await screen.findByRole('table')
    const headers = [...table.querySelectorAll('thead th')].map((th) => th.textContent?.trim())
    expect(headers).toEqual([
      'Date',
      'Merchant',
      'Total',
      'Status',
      'Accuracy',
      'Detail',
    ])
  })

  it('gives every right-aligned column a header aligned with its cells', async () => {
    // The defect this pins, measured in Chromium on the deployed app on
    // 2026-08-25: `.head th` sets `text-align: left` for the whole header row
    // while `.number` and `.detail` set `text-align: right` on the cells. So
    // CONFIDENCE sat hard against the left edge of a column whose figures sat
    // against the right, and DETAIL did the same over its buttons -- a label at
    // one edge and its values at the other read as two columns.
    //
    // Pinned as CLASS AGREEMENT rather than as computed alignment because
    // `vite.config.ts` leaves Vitest's `css: false` default in place: jsdom here
    // has class names and no stylesheet at all, so `getComputedStyle` would
    // report the jsdom default for every cell and pass whatever the CSS said.
    // The rule itself is pinned by the census in `stylesheets.test.ts`; this end
    // pins that the header and the cell ask for the same one.
    stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={REVIEWER} />)
    await screen.findByText('Summit Fuel')

    const table = screen.getByRole('table')
    const headers = [...table.querySelectorAll('thead th')]
    const cells = [...table.querySelectorAll('tbody tr:first-child > td')]
    const labels = headers.map((th) => th.textContent?.trim())

    // Confidence is NOT in this list any more: it carries a banded `Chip` now
    // and reads from the left like Status, so it is no longer a right-aligned
    // column whose header has to chase its cells to the right edge. Total and
    // Detail still are.
    for (const column of ['Total', 'Detail']) {
      const at = labels.indexOf(column)
      const cellClass = cells[at].className
      // Non-vacuity, and it is the whole risk here: an unresolved `styles.x`
      // renders no class attribute at all, so `className` is `''` on BOTH sides
      // and a bare equality would pass on two nothings while the rendered table
      // stayed ragged.
      expect(cellClass).toBeTruthy()
      expect(headers[at].className).toBe(cellClass)
    }
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
    expect(cellUnder(row, table, 'Accuracy').textContent).toContain('94%')
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
    // Confidence is NOT in this list: its column carries a `ConfidenceChip`, not
    // a `ui/Value`, so a null confidence renders the neutral "no score" chip
    // rather than the not-extracted mark. That chip is asserted separately
    // below. The other three nullable columns still show the mark.
    for (const column of ['Date', 'Merchant', 'Total']) {
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
    // The confidence cell's own null treatment: the neutral band chip reading
    // "no score", not a blank cell.
    expect(cellUnder(row, table, 'Accuracy').textContent).toContain('no score')
  })

  it('renders an empty-string status as not-extracted, because the cast is unchecked', async () => {
    // The one column `receipt_summary` types as `str` and never sends null, so
    // the row shape says it cannot be missing. `request<T>` is an unchecked
    // cast, and `''` is the third state design section 4 names -- the one
    // `ui/Value` exists to catch, and the one a bare `{row.status}` renders as a
    // blank cell indistinguishable from a column that was never drawn.
    stubPage({ items: [rowFixture({ status: '' })], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)

    const table = await screen.findByRole('table')
    const cell = cellUnder(bodyRows(table)[0], table, 'Status')
    expect(within(cell).getByRole('img', { name: 'not extracted' })).toBeDefined()
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

  it('refreshes the filtered results after a successful export', async () => {
    stubPages([
      { items: [rowFixture({ merchant_name_raw: 'Initial' })], has_more: false },
      {
        items: [rowFixture({ merchant_name_raw: 'Filtered', status: 'needs_review' })],
        has_more: false,
      },
      { items: [], has_more: false },
    ])
    const user = userEvent.setup()

    render(<ReceiptsScreen identity={ADMIN} />)
    await screen.findByText('Initial')
    await user.selectOptions(screen.getByLabelText(/status/i), 'needs_review')
    await screen.findByText('Filtered')

    await user.click(screen.getByRole('button', { name: /export/i }))

    await screen.findByText(/no receipts are in scope/i)
    expect(api.downloadExportWorkbook).toHaveBeenCalledExactlyOnceWith({
      status: 'needs_review',
    })
    expect(api.fetchExportReceipts.mock.calls[2]?.[0]).toEqual({
      limit: PAGE_SIZE,
      offset: 0,
      status: 'needs_review',
    })
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
  // back as strings, so `styles.tabel` ships unpainted and every
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

describe('the status and confidence filters (P5.T2)', () => {
  it('lists everything until a filter is chosen', async () => {
    // The screen must not invent a default filter. A list that quietly starts
    // filtered shows fewer rows than the workbook it claims to preview, which
    // is the exact mismatch `fetchExportReceipts` exists to avoid.
    const fetchMock = stubPage({ items: [rowFixture()], has_more: false })

    render(<ReceiptsScreen identity={ADMIN} />)
    await screen.findByRole('table')

    expect(fetchMock.mock.calls[0]?.[0]).toEqual({ limit: PAGE_SIZE, offset: 0 })
  })

  it('re-queries with the chosen status, from the first page', async () => {
    const fetchMock = stubPage({ items: [rowFixture()], has_more: false })
    render(<ReceiptsScreen identity={ADMIN} />)
    await screen.findByRole('table')

    await userEvent.selectOptions(
      screen.getByLabelText(/status/i),
      'needs_review',
    )

    // `offset: 0`, not the row count. Filtering is a new result set, and
    // carrying the old offset would page into the middle of it -- the same
    // hazard this screen's docblock names for "Load more".
    expect(fetchMock.mock.lastCall?.[0]).toEqual({
      limit: PAGE_SIZE,
      offset: 0,
      status: 'needs_review',
    })
  })

  it('re-queries with the chosen confidence floor, as a string', async () => {
    const fetchMock = stubPage({ items: [rowFixture()], has_more: false })
    render(<ReceiptsScreen identity={ADMIN} />)
    await screen.findByRole('table')

    await userEvent.selectOptions(
      screen.getByLabelText(/accuracy/i),
      '0.90',
    )

    // A **string**, never a number: confidence is decimal and this codebase
    // keeps decimals out of floats (ADR-0001). `0.9` would also be a different
    // wire value than the option's label says.
    expect(fetchMock.mock.lastCall?.[0]).toEqual({
      limit: PAGE_SIZE,
      offset: 0,
      minConfidence: '0.90',
    })
  })

  it('composes the two filters rather than replacing one with the other', async () => {
    const fetchMock = stubPage({ items: [rowFixture()], has_more: false })
    render(<ReceiptsScreen identity={ADMIN} />)
    await screen.findByRole('table')

    await userEvent.selectOptions(screen.getByLabelText(/status/i), 'needs_review')
    await userEvent.selectOptions(screen.getByLabelText(/accuracy/i), '0.90')

    // The route ANDs its filters, so both must arrive together. Sending only
    // the most recent one is a screen that silently widens the result set the
    // moment a second filter is chosen.
    expect(fetchMock.mock.lastCall?.[0]).toEqual({
      limit: PAGE_SIZE,
      offset: 0,
      status: 'needs_review',
      minConfidence: '0.90',
    })
  })

  it('clearing a filter drops it from the query rather than sending it empty', async () => {
    const fetchMock = stubPage({ items: [rowFixture()], has_more: false })
    render(<ReceiptsScreen identity={ADMIN} />)
    await screen.findByRole('table')

    await userEvent.selectOptions(screen.getByLabelText(/status/i), 'needs_review')
    await userEvent.selectOptions(screen.getByLabelText(/status/i), '')

    // `status: ''` is not "every status" on the wire -- it fails validation
    // against `ReceiptStatus | None` and the page 422s.
    expect(fetchMock.mock.lastCall?.[0]).toEqual({ limit: PAGE_SIZE, offset: 0 })
  })

  it('load more keeps the active filters', async () => {
    const first = { items: [rowFixture()], has_more: true }
    const second = { items: [rowFixture()], has_more: false }
    const fetchMock = stubPages([first, first, second])
    render(<ReceiptsScreen identity={ADMIN} />)
    await screen.findByRole('table')

    await userEvent.selectOptions(screen.getByLabelText(/status/i), 'needs_review')
    await userEvent.click(await screen.findByRole('button', { name: /load more/i }))

    // Paging inside a filtered set must stay inside it. Dropping the filter
    // here appends rows the filter excluded, and the table then shows a mix
    // with nothing saying so.
    expect(fetchMock.mock.lastCall?.[0]).toEqual({
      limit: PAGE_SIZE,
      offset: 1,
      status: 'needs_review',
    })
  })
})

/** The View action -- opening one finished receipt without leaving the list.
 *
 * The panel itself is pinned in `receipt-detail-panel.test.tsx`; what belongs
 * here is only the list's half: which rows offer the action, and that using it
 * puts the panel on screen. Asserting the panel's *contents* from here would
 * re-derive that file's assertions against a second fixture.
 */
describe('viewing one finished receipt from the list', () => {
  it('offers View on a finished row', async () => {
    stubPage({ items: [rowFixture({ status: 'reviewed' })], has_more: false })
    render(<ReceiptsScreen identity={REVIEWER} />)
    const row = await screen.findByText('Summit Fuel')
    expect(
      within(row.closest('tr') as HTMLElement).getByRole('button', { name: /view/i }),
    ).toBeDefined()
  })

  it('offers no View on a row that has not finished', async () => {
    // `pending` is an upload still in flight: there is no extraction to look at
    // and no image pane worth opening. The action is absent rather than
    // disabled -- a control a person can press and get nothing from reads as
    // the defect this feature was asked to fix.
    stubPage({ items: [rowFixture({ status: 'pending' })], has_more: false })
    render(<ReceiptsScreen identity={REVIEWER} />)
    const row = await screen.findByText('Summit Fuel')
    expect(
      within(row.closest('tr') as HTMLElement).queryByRole('button', { name: /view/i }),
    ).toBeNull()
  })

  it('puts the detail panel on screen when View is used', async () => {
    stubPage({ items: [rowFixture({ status: 'needs_review' })], has_more: false })
    render(<ReceiptsScreen identity={REVIEWER} />)
    const row = await screen.findByText('Summit Fuel')
    expect(screen.queryByLabelText('Receipt detail')).toBeNull()
    await userEvent.click(
      within(row.closest('tr') as HTMLElement).getByRole('button', { name: /view/i }),
    )
    expect(screen.getByLabelText('Receipt detail')).toBeDefined()
  })
})

describe('the status column as a chip', () => {
  /** The chip's text and its glyph, read off the rendered row. */
  function statusCell(): HTMLElement {
    const row = screen.getByText('Summit Fuel').closest('tr') as HTMLElement
    // The chip is the only element in the row carrying an svg; the row's other
    // controls are text boxes and a button.
    //
    // `parentElement` of the icon's own span, NOT `svg.closest('span')`: `Chip`
    // wraps its glyph in an inner `<span className={icon}>`, so `closest`
    // returns that wrapper and its `textContent` is `''` -- which is how the
    // first version of this helper reported an empty status cell on a row that
    // was rendering correctly.
    return row.querySelector('svg')?.closest('span')?.parentElement as HTMLElement
  }

  it('reads as words, not as the column it came out of', async () => {
    // The wire spelling is `needs_review`. A badge that shows it has leaked its
    // database into the interface -- which is what the row did until the chip
    // landed, and what this pins against a regression to `<Value>`.
    stubPage({ items: [rowFixture({ status: 'needs_review' })], has_more: false })
    render(<ReceiptsScreen identity={REVIEWER} />)
    await screen.findByText('Summit Fuel')

    expect(statusCell().textContent).toContain('needs review')
    expect(statusCell().textContent).not.toContain('needs_review')
  })

  it('gives each status its own glyph, so the chip reads without its colour', async () => {
    // The rule `admin/TaskTable.tsx` states for `GlyphPriority` and the reason
    // five tones are not enough on their own: a reader who cannot separate the
    // green from the amber still has to be able to tell these apart.
    const seen = new Map<string, string>()
    for (const status of ['auto_approved', 'reviewed', 'needs_review', 'failed', 'extracted']) {
      cleanup()
      stubPage({ items: [rowFixture({ status })], has_more: false })
      render(<ReceiptsScreen identity={REVIEWER} />)
      await screen.findByText('Summit Fuel')
      const svg = statusCell().querySelector('svg') as SVGElement
      seen.set(status, svg.innerHTML)
    }
    // Five statuses, five DISTINCT drawings. Sharing one would make two states
    // indistinguishable to anyone reading shape rather than hue.
    expect(new Set(seen.values()).size).toBe(5)
  })

  it('gives an unknown status a chip rather than a blank cell', async () => {
    // `GET /export/receipts` decides which statuses reach this list and has
    // changed before. A status the map has never heard of must still arrive as
    // something a reader can see.
    stubPage({ items: [rowFixture({ status: 'quarantined' })], has_more: false })
    render(<ReceiptsScreen identity={REVIEWER} />)
    await screen.findByText('Summit Fuel')

    expect(statusCell().textContent).toContain('quarantined')
  })

  it('renders no chip at all for an empty status', async () => {
    // `receipt_summary` types this `str` and never sends null, but `request<T>`
    // is an unchecked cast. An empty chip is a coloured pill with nothing in
    // it; `Value` owns that case and says so with an em dash.
    stubPage({ items: [rowFixture({ status: '' })], has_more: false })
    render(<ReceiptsScreen identity={REVIEWER} />)
    const row = (await screen.findByText('Summit Fuel')).closest('tr') as HTMLTableRowElement

    // Scoped to the STATUS cell, not the whole row: the confidence column now
    // always carries a `ConfidenceChip` whose gauge glyph is an `svg`, so a
    // row-wide `querySelector('svg')` would find that instead. The claim here is
    // only that an empty status renders no status chip.
    const table = row.closest('table') as HTMLElement
    const statusCell = cellUnder(row, table, 'Status')
    expect(statusCell.querySelector('svg')).toBeNull()
  })
})
