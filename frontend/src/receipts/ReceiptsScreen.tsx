import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { downloadExportWorkbook, fetchExportReceipts } from '../api/receipts'
import type { Identity } from '../api/admin'
import type { ReceiptSummary } from '../api/types'
import { Button } from '../ui/Button'
import type { JSX } from 'react'
import { Chip } from '../ui/Chip'
import { ConfidenceChip } from '../ui/ConfidenceChip'
import { accuracyPercent } from '../ui/accuracy'
import { Value } from '../ui/Value'
import { ReceiptDetailPanel } from './ReceiptDetailPanel'
import styles from './ReceiptsScreen.module.css'

/** The one status with nothing to show yet.
 *
 *  Named rather than spelled inline at the row: the wire spelling is the
 *  server's, and a second literal is the copy that drifts when it changes.
 */
const PENDING_STATUS = 'pending'

/** The API's own words when it gave us any, and the caller's sentence when not.
 *
 * A `TypeError: Failed to fetch` from a server that is not up carries nothing a
 * reader can act on, while a 400's "this export matches more than N receipts" is
 * the whole answer. The same split `AdminScreen`, `ReviewScreen` and `LoginPage`
 * already make. */
function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

/** The two things that can fail here, each with the label its message keeps.
 *
 * A fixed list rather than a filtered array of bare strings, for the reason
 * `AdminScreen` records: two failures really can carry identical text
 * (`request failed (500)` from both routes at once), and keying React's list on
 * the message itself would then be a duplicate key. The source name is unique
 * whatever the servers say. */
const FAILURE_ORDER = ['listing', 'export'] as const

/** The page size this screen asks for, spelled rather than left to the server.
 *
 * `GET /export/receipts` defaults `limit` to 50 and bounds it at
 * `MAX_PAGE_LIMIT` 200 (`PageLimit` in review/api.py). Sending it explicitly is
 * what makes the offset arithmetic below self-consistent: "Load more" asks from
 * the count of rows already on screen, and a page size decided at the other end
 * of the wire would make that count and the request disagree the day the
 * server's default moves.
 *
 * Exported so `receipts-screen.test.tsx` asserts against THIS number rather
 * than a second copy of it: a test that hard-coded 50 would keep passing the
 * day this moved, and assert nothing about the screen. */
export const PAGE_SIZE = 50

/** The two filters P5.T2 asks for. `''` is "not chosen", never a wire value.
 *
 *  Both are strings because both go onto a query string. `minConfidence`
 *  especially: confidence is a decimal, and a `number` here would put
 *  `0.9` where the option says `0.90` and reintroduce the float the money path
 *  is built to exclude (ADR-0001). The route parses it into a `Decimal`.
 */
interface Filters {
  readonly status: string
  readonly minConfidence: string
}

const NO_FILTERS: Filters = { status: '', minConfidence: '' }

/** The statuses this screen offers, and **only** these.
 *
 *  `pending` and `rejected` are deliberately absent: this list previews the
 *  export, and `GET /export/receipts` excludes both, so offering them would be
 *  a control that can only ever return nothing.
 */
const STATUS_OPTIONS = ['auto_approved', 'needs_review', 'reviewed'] as const

/* --------------------------------------------------------------------------
 * Status glyphs.
 *
 * 20x20, `stroke="currentColor"`, stroke width 1.5 -- the house shape, matched
 * to `admin/TaskTable.tsx` rather than invented alongside it.
 *
 * **Each reads without its colour.** That is TaskTable's own stated rule for
 * `GlyphPriority` and it matters more here, where the five tones carry meaning:
 * a reader who cannot separate the green from the amber still sees a tick, a
 * bolt, an exclamation, a cross or a bare ring.
 * ------------------------------------------------------------------------ */

/** Passed without a human: a bolt. */
function GlyphAuto() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M11 3 L6 10.5 H9.5 L9 17 L14 9.5 H10.5 Z" strokeLinejoin="round" />
    </svg>
  )
}

/** A person looked and accepted it: a tick in a ring. */
function GlyphReviewed() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
      <path d="M6.75 10.25 L9 12.5 L13.25 7.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Waiting on a person: an exclamation in a ring. */
function GlyphNeedsReview() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
      <path d="M10 6.5 V10.5" strokeLinecap="round" />
      <path d="M10 13.25 V13.26" strokeLinecap="round" />
    </svg>
  )
}

/** It did not get through: a cross in a ring. */
function GlyphFailed() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
      <path d="M7.75 7.75 L12.25 12.25 M12.25 7.75 L7.75 12.25" strokeLinecap="round" />
    </svg>
  )
}

/** Anything still on its way through: a bare ring, the same one
 *  `TaskTable`'s `GlyphOpen` draws. */
function GlyphInFlight() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
    </svg>
  )
}

/** A `ReceiptStatus` as a tone and a glyph.
 *
 *  **The default is deliberate and is not an error branch.** `GET
 *  /export/receipts` decides which statuses reach this list, and it has changed
 *  before; a status this map has never heard of gets the neutral ring and its
 *  own name rather than nothing, so a new one appears as a plain chip instead
 *  of a blank cell.
 */
function chipFor(status: string): { tone: 'error' | 'warn' | 'positive' | 'neutral'; icon: JSX.Element } {
  switch (status) {
    case 'auto_approved':
      return { tone: 'positive', icon: <GlyphAuto /> }
    case 'reviewed':
      return { tone: 'positive', icon: <GlyphReviewed /> }
    case 'needs_review':
      return { tone: 'warn', icon: <GlyphNeedsReview /> }
    case 'failed':
    case 'rejected':
      return { tone: 'error', icon: <GlyphFailed /> }
    default:
      return { tone: 'neutral', icon: <GlyphInFlight /> }
  }
}

/** Confidence floors, as strings, coarse on purpose: this is a filter, not a
 *  calibration instrument, and a free-text number would invite `0.9` / `.9` /
 *  `90` and a 422 for two of the three. */
const CONFIDENCE_OPTIONS = ['0.50', '0.70', '0.90'] as const

/** The filters as the API takes them, with an unchosen one **omitted**.
 *
 *  `status: ''` is not "every status" on the wire: it fails validation against
 *  `ReceiptStatus | None` and the page 422s. Absent is the only spelling of
 *  "no filter" the route accepts.
 */
function queryFor(next: Filters): { status?: string; minConfidence?: string } {
  return {
    ...(next.status === '' ? {} : { status: next.status }),
    ...(next.minConfidence === '' ? {} : { minConfidence: next.minConfidence }),
  }
}

export interface ReceiptsScreenProps {
  readonly identity: Identity | null
}

/** The results list at `/app/receipts` -- the results-list design, sections 6-7.
 *
 * ## It lists the export's own query, not `GET /receipts`
 *
 * `GET /receipts` applies no status exclusion, and its `status` filter is a
 * single equality, so it cannot express "every status except these two" -- which
 * is why `query_export_receipts` exists as a separate function at all. A list
 * built on the broad route would show rows the workbook silently omits: a reader
 * sees a list, clicks Export, and receives strictly fewer receipts with no
 * notice. `fetchExportReceipts` calls the export's own query, so the two cannot
 * disagree -- there is no second scope to keep in step.
 *
 * ## It asks for nothing until it knows who is asking
 *
 * `identity` is `Identity | null`, and the null branch renders a wait rather
 * than a table, exactly as `AdminScreen` does. Null means **"not yet
 * answered"**, never "not an admin" -- `session.ts` starts it there -- so a
 * screen that treated it as a decision would flash the reviewer's view of the
 * page at an admin on every reload.
 *
 * The gate itself is `identity.role === 'admin'`, compared **positively**, so
 * every other value takes the narrow branch. `role` is a `string` rather than a
 * union because `request<T>` is an unchecked cast: a union would be a claim
 * about the server that nothing validates, and an unrecognised role would
 * type-check as impossible while arriving anyway. A `role !== 'reviewer'` gate
 * would hand an unknown role the export button.
 *
 * **The button is a courtesy, not the gate.** `GET /export/xlsx` takes
 * `Depends(require_role(ROLE_ADMIN))` and the role is re-read per request
 * (ADR-0012), so an account demoted between `/auth/me` and the click gets a 403
 * -- which lands in the alert region below like any other failure.
 *
 * ## One `role="alert"`, whatever went wrong
 *
 * ADR-0024's contract, restated by the design's decision 7: **exactly one
 * `role="alert"` region on screen**. Two regions make every single-alert query
 * in the suite ambiguous -- `findByRole('alert')` matches two elements and
 * throws. The listing and the export can fail independently and at the same
 * time, so their messages are collected into one region as separate lines
 * rather than dropped or raced. Nothing invents copy: the server's own words are
 * what render, including the 400 whose advice names filters this screen does not
 * offer.
 *
 * ## A failed first page clears the rows; a failed *next* page does not
 *
 * `AdminScreen` clears its page on a listing failure, because a stale table
 * beside a fresh failure reads as a queue that is still being shown. That
 * reasoning is about a **re-list**, and it does not carry to "Load more": the
 * rows already on screen are still exactly what the server sent, and dropping
 * them because an *additional* page failed would destroy good data and lose the
 * reader's place. So the failure is reported, the rows stay, and `has_more`
 * stays true -- the button is still there to retry with.
 *
 * ## The export button holds a pending state
 *
 * The workbook is built synchronously and wholly in memory before the response
 * is handed to Starlette, so a second click while the first is in flight is a
 * real hazard rather than a theoretical one. "Load more" holds one for the same
 * reason in a smaller way: a second click at the same offset appends the same
 * page twice.
 *
 * ## Filters, and what is still deliberately not here
 *
 * **Status and confidence filters ship (P5.T2, 2026-08-25.)** This section used
 * to read "No filters, no sorting, no column choice" -- all three ruled out of
 * v1. The other two remain out.
 *
 * **`rows are not clickable` stays, and it is the load-bearing one.** With no
 * row navigation nothing on this screen is built from receipt data, so no
 * receipt id ever enters a path segment and `route.ts`'s no-dot rule is never
 * approached. Filtering does not touch that: a filter puts a *status* and a
 * *decimal* on a query string, never an id in a path.
 *
 * The filters are server-side, not a client-side `Array.filter`. The rows on
 * screen are one page of a larger set, so filtering locally would filter the
 * page and silently claim to have filtered the set -- and `has_more` would then
 * describe a different query than the one the reader is looking at.
 *
 * **The status column IS a `Chip` now**, on the owner's instruction 2026-08-25.
 * This paragraph used to say the opposite -- that `Chip` needs an icon per tone
 * and "which icon each `ReceiptStatus` gets is a design decision nobody has
 * made, so no glyph is invented for it here". That was the correct call to make
 * without authority. The authority arrived, the five glyphs are defined below,
 * and each is drawn to read without its colour.
 *
 * The screen does not poll. Like `AdminScreen`, it is current as of its last
 * render.
 */
export function ReceiptsScreen({ identity }: ReceiptsScreenProps) {
  const [rows, setRows] = useState<ReceiptSummary[] | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [listFailure, setListFailure] = useState<string | null>(null)
  const [exportFailure, setExportFailure] = useState<string | null>(null)
  const [pageInFlight, setPageInFlight] = useState(false)
  const [exporting, setExporting] = useState(false)
  /** The receipt whose detail panel is open, or `null` for none. Held as an
   *  id rather than a row: the panel fetches the full detail itself, and a
   *  summary held here would be a second, staler copy of what it shows. */
  const [viewing, setViewing] = useState<string | null>(null)

  /** The active filters. Held together in one object so `loadMore` sends BOTH
   *  -- the route ANDs them, and paging with only the most recently changed one
   *  would silently widen the set mid-scroll. */
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)

  const load = useCallback(async (next: Filters) => {
    setPageInFlight(true)
    try {
      const page = await fetchExportReceipts({
        limit: PAGE_SIZE,
        offset: 0,
        ...queryFor(next),
      })
      setRows(page.items)
      setHasMore(page.has_more)
      setListFailure(null)
    } catch (caught) {
      // The rows are cleared, not kept: this is the first page, so there is no
      // reader's place to lose and a table left standing beside a fresh failure
      // reads as a list that is still being shown.
      setRows(null)
      setHasMore(false)
      setListFailure(messageOf(caught, 'could not load the receipts'))
    } finally {
      setPageInFlight(false)
    }
  }, [])

  /** The identity the current page was loaded for, so `StrictMode`'s second
   *  effect pass -- and every unrelated re-render -- does not list the receipts
   *  again, while a genuinely different caller does. */
  const loadedFor = useRef<string | null>(null)

  useEffect(() => {
    if (identity === null) {
      return
    }
    const key = `${identity.username}/${identity.role}`
    if (loadedFor.current === key) {
      return
    }
    loadedFor.current = key
    void load(filters)
  // `filters` is deliberately NOT a dependency. This effect is the
  // identity-keyed first load; a filter change re-lists through `applyFilters`
  // below, which calls `load` directly with the new value. Adding it here would
  // fight the `loadedFor` guard and re-list twice on every change.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity, load])

  /** Re-list from the first page under a changed filter.
   *
   *  Takes the new value rather than reading `filters` back: `setFilters` is
   *  asynchronous, so a `load` that read state here would send the PREVIOUS
   *  filter and the table would lag one change behind.
   *
   *  `offset: 0` is not an optimisation. A filter change is a new result set,
   *  and carrying the old offset pages into the middle of it -- the same hazard
   *  this screen's docblock names for "Load more".
   */
  function applyFilters(next: Filters): void {
    setFilters(next)
    void load(next)
  }

  async function loadMore(): Promise<void> {
    if (rows === null) {
      return
    }
    // The rows already on screen ARE the offset. `query_export_receipts` orders
    // by `created_at` then `id` -- a total order chosen so that paging cannot
    // repeat or skip a row when two receipts share a timestamp -- so counting
    // them is exact rather than approximate.
    const offset = rows.length
    setPageInFlight(true)
    setListFailure(null)
    try {
      const page = await fetchExportReceipts({
        limit: PAGE_SIZE,
        offset,
        // Paging inside a filtered set stays inside it. Dropping the filters
        // here appends rows the filter excluded, and the table then shows a
        // mix with nothing on screen saying so.
        ...queryFor(filters),
      })
      setRows((current) => (current === null ? page.items : [...current, ...page.items]))
      setHasMore(page.has_more)
    } catch (caught) {
      setListFailure(messageOf(caught, 'could not load the next page of receipts'))
    } finally {
      setPageInFlight(false)
    }
  }

  async function exportWorkbook(): Promise<void> {
    setExporting(true)
    setExportFailure(null)
    try {
      await downloadExportWorkbook(queryFor(filters))
      await load(filters)
    } catch (caught) {
      setExportFailure(messageOf(caught, 'the export did not reach the API'))
    } finally {
      setExporting(false)
    }
  }

  if (identity === null) {
    return (
      <main className={styles.screen}>
        <p className={styles.waiting}>
          Waiting for the identity that decides whether this page may offer the export.
        </p>
      </main>
    )
  }

  const isAdmin = identity.role === 'admin'
  const bySource: Record<(typeof FAILURE_ORDER)[number], string | null> = {
    listing: listFailure,
    export: exportFailure,
  }
  const alerts = FAILURE_ORDER.filter((source) => bySource[source] !== null)

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Processed receipts</h1>
      <p className={styles.who}>
        Signed in as {identity.username} ({identity.role}).
      </p>
      {/* Said out loud because the scope is the whole point of this screen and
          nothing on it is otherwise visible: a receipt that is still pending, or
          that was rejected, is absent from this list because it is absent from
          the workbook -- not because anything went wrong. */}
      <p className={styles.scope}>
        Exactly the receipts the export workbook contains. A receipt that is still pending, or
        that was rejected, is out of scope for both.
      </p>

      {/* Labelled with `<label htmlFor>` rather than an `aria-label`, so the
          control is reachable by its visible text -- the same binding
          `MoneyInput` uses. Both are plain `<select>`s: the option sets are
          closed and short, and a combobox would be a new component for three
          values. */}
      <div className={styles.filters}>
        <label className={styles.filterLabel} htmlFor="receipts-filter-status">
          Status
          <select
            id="receipts-filter-status"
            className={styles.filterControl}
            value={filters.status}
            onChange={(event) =>
              applyFilters({ ...filters, status: event.target.value })
            }
          >
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.filterLabel} htmlFor="receipts-filter-confidence">
          Accuracy
          <select
            id="receipts-filter-confidence"
            className={styles.filterControl}
            value={filters.minConfidence}
            onChange={(event) =>
              applyFilters({ ...filters, minConfidence: event.target.value })
            }
          >
            <option value="">Any accuracy</option>
            {CONFIDENCE_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {accuracyPercent(value)} and above
              </option>
            ))}
          </select>
        </label>
      </div>

      {alerts.length === 0 ? null : (
        // One region, every message. See the docstring: a second `role="alert"`
        // is what ADR-0024 forbids, not a second sentence.
        <div className={styles.alert} role="alert">
          {alerts.map((source) => (
            <p className={styles.alertLine} key={source}>
              {bySource[source]}
            </p>
          ))}
        </div>
      )}

      {isAdmin ? (
        <Button
          variant="primary"
          className={styles.exportButton}
          disabled={exporting}
          onClick={() => void exportWorkbook()}
        >
          {exporting ? 'Preparing the export' : 'Export to Excel'}
        </Button>
      ) : (
        // Why the control is absent, rather than a page that silently offers
        // less to one role than to another. Not an alert: nothing failed, and
        // `role="alert"` belongs to the one region above (ADR-0024).
        <p className={styles.note}>
          Only an admin can download the workbook, so this page offers no export.
        </p>
      )}

      {rows === null ? null : rows.length === 0 ? (
        <p className={styles.empty}>No receipts are in scope for the export yet.</p>
      ) : (
        // A horizontal scroller, the shape design section 5.2 sets for the
        // line-items table: five columns must not squeeze to slivers, and the
        // page body must never scroll sideways. `.table`'s `min-width` is what
        // gives this something to scroll.
        <section className={styles.scroller} aria-label="Processed receipts">
          <table className={styles.table}>
            <thead className={styles.head}>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Merchant</th>
                <th scope="col" className={styles.number}>Total</th>
                <th scope="col">Status</th>
                <th scope="col" className={styles.confidence}>Accuracy</th>
                {/* A real header rather than an empty cell: a column with no
                    name is a column a screen reader announces as nothing, and
                    the row's action needs saying once here instead of being
                    inferred from six identical buttons. Safe to add because this
                    table is automatic-layout by design (see the docstring) --
                    the fixed-width arithmetic that collapsed a column in
                    ISSUE-032 has no counterpart here. */}
                <th scope="col" className={styles.detail}>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr className={styles.row} key={row.id}>
                  {/* Four of the five columns are nullable, and every one of
                      them goes through `ui/Value`: `null` is not `0` and is not
                      empty (ADR-0027 decision 5), and a bare `{value}` renders
                      all three states as the same blank cell. */}
                  <td className={styles.date}>
                    <Value value={row.txn_date} kind="text" />
                  </td>
                  <td className={styles.merchant}>
                    <Value value={row.merchant_name_raw} kind="text" />
                  </td>
                  <td className={styles.number}>
                    {/* The code leads and the amount follows, so the digits stay
                        flush right down the column whether or not a row carries
                        a currency. It is rendered whenever the server sent one,
                        independently of the amount: a receipt whose total was
                        not read still has the currency its header printed, and
                        suppressing it would drop a fact the server did send.

                        It does NOT take the not-extracted mark when it is
                        absent. The mark answers for the *value* of a column, and
                        a currency is the unit on one -- two marks in one cell
                        would announce "not extracted" twice for a single missing
                        number. */}
                    {row.currency === null ? null : (
                      <span className={styles.currency}>{row.currency}</span>
                    )}
                    <Value value={row.total} kind="money" align="end" />
                  </td>
                  {/* A `Chip`, on the owner's instruction 2026-08-25, which
                      supersedes two rulings this file used to carry and which
                      are quoted here so the change is legible rather than
                      silent:

                        "There is no `Chip` on the status column either. `Chip`
                        requires an `icon` per tone and which icon each
                        `ReceiptStatus` gets is a design decision nobody has
                        made, so no glyph is invented for it here."

                        "The wire spelling is carried unchanged."

                      The first was a refusal to make a design decision without
                      authority, and it was right to make it. The authority
                      arrived; the glyphs are above. The second falls with it --
                      a badge reading `needs_review` is a badge that leaked its
                      database.

                      **`Value` still owns the empty case.** `receipt_summary`
                      types this `str` and never sends null, but `request<T>` is
                      an unchecked cast, and `''` inside a chip would be a
                      coloured pill with nothing in it. A chip is for a status
                      there IS. */}
                  <td className={styles.status}>
                    {row.status === '' || row.status == null ? (
                      <Value value={row.status} kind="text" />
                    ) : (
                      <Chip tone={chipFor(row.status).tone} icon={chipFor(row.status).icon}>
                        {row.status.replace(/_/g, ' ')}
                      </Chip>
                    )}
                  </td>
                  {/* The banded confidence indicator, the same one the review
                      queue uses, so a re-check reads the same here. A chip reads
                      from the left rather than aligning right like the money
                      column, hence its own cell class. */}
                  <td className={styles.confidence}>
                    <ConfidenceChip confidence={row.confidence} />
                  </td>
                  <td className={styles.detail}>
                    {/* Absent, not disabled, while a receipt is still `pending`:
                        there is no extraction to read and no image to compare it
                        against, and a control that can be pressed for nothing is
                        the complaint this action exists to answer. */}
                    {row.status === PENDING_STATUS ? null : (
                      <button
                        type="button"
                        className={styles.view}
                        onClick={() => setViewing(row.id)}
                      >
                        View
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* `has_more` comes off a `limit + 1` fetch rather than a `COUNT(*)`, so it
          says "there is at least one more row" and never how many -- which is why
          this is a button and not a page count. It is simply absent when the
          server says there is nothing further. */}
      {rows !== null && hasMore ? (
        <Button
          variant="secondary"
          className={styles.more}
          disabled={pageInFlight}
          onClick={() => void loadMore()}
        >
          {pageInFlight ? 'Loading' : 'Load more'}
        </Button>
      ) : null}

      {/* Mounted beside the list rather than in place of it: closing returns to
          the same rows, the same filters and the same scroll position, which is
          the whole reason this is a panel and not a route. `key` forces a fresh
          fetch when a second row is viewed without closing the first. */}
      {viewing !== null ? (
        <ReceiptDetailPanel
          key={viewing}
          receiptId={viewing}
          onClose={() => setViewing(null)}
        />
      ) : null}
    </main>
  )
}
