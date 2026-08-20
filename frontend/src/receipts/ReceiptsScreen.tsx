import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { downloadExportWorkbook, fetchExportReceipts } from '../api/receipts'
import type { Identity } from '../api/admin'
import type { ReceiptSummary } from '../api/types'
import { Button } from '../ui/Button'
import { Value } from '../ui/Value'
import styles from './ReceiptsScreen.module.css'

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
 * server's default moves. */
const PAGE_SIZE = 50

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
 * ## What is deliberately not here
 *
 * No filters, no sorting, no column choice, and **rows are not clickable** --
 * all ruled out of v1. The last one is load-bearing beyond the UI: with no row
 * navigation nothing on this screen is built from receipt data, so no receipt id
 * ever enters a path segment and `route.ts`'s no-dot rule is never approached.
 *
 * There is no `Chip` on the status column either. `Chip` requires an `icon` per
 * tone and which icon each `ReceiptStatus` gets is a design decision nobody has
 * made, so no glyph is invented for it here.
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

  const load = useCallback(async () => {
    setPageInFlight(true)
    try {
      const page = await fetchExportReceipts({ limit: PAGE_SIZE, offset: 0 })
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
    void load()
  }, [identity, load])

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
      const page = await fetchExportReceipts({ limit: PAGE_SIZE, offset })
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
      await downloadExportWorkbook()
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
                <th scope="col">Total</th>
                <th scope="col">Status</th>
                <th scope="col">Confidence</th>
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
                  {/* Plain text rather than a `Chip` -- see the docstring -- and `Value`
                      is how this tree renders plain text. `receipt_summary` types
                      this `str` and never sends null, but `request<T>` is an
                      unchecked cast and `''` is the third state `Value` exists to
                      catch. The wire spelling is carried unchanged. */}
                  <td className={styles.status}>
                    <Value value={row.status} kind="text" />
                  </td>
                  <td className={styles.number}>
                    <Value value={row.confidence} kind="count" align="end" />
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
    </main>
  )
}
