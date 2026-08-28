import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { fetchReceipts } from '../api/receipts'
import type { ReceiptSummary } from '../api/types'
import { Value } from '../ui/Value'
import { ProcessingView } from '../upload/ProcessingView'
import styles from './ProcessingListScreen.module.css'

/** The status a receipt wears while the pipeline still has it.
 *
 * `POST /upload` writes `pending` and the worker leaves it `pending` until it
 * reaches a terminal status, so this is exactly "still processing". The word is
 * the server's (`ReceiptStatus.PENDING`); it is named once here rather than
 * spelled at the call so a second literal cannot drift from it.
 */
const PENDING_STATUS = 'pending'

/** How often the list re-fetches, so a receipt that finishes leaves the list
 *  and a newly uploaded one appears without a manual refresh. Slower than a
 *  single receipt's progress poll: this is the whole list, and the per-row
 *  `ProcessingView` already polls the fine detail. */
const REFRESH_MS = 4000

/** The API's own words when it gave us any, and the caller's sentence when not.
 *
 * The same split `AdminScreen`, `ReceiptsScreen`, `ReviewScreen` and `LoginPage`
 * make: a `TypeError: Failed to fetch` from a server that is down carries
 * nothing a reader can act on, so this screen supplies the sentence; a 4xx/5xx
 * with a message is rendered in the server's own words. */
function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

export interface ProcessingListScreenProps {
  /** Injected so tests never touch `fetch`. Defaults to the real call. */
  readonly load?: (params: { status: string }) => Promise<{ items: ReceiptSummary[] }>
  /** Forwarded to each expanded row's `ProcessingView`. Left `undefined` the
   *  view falls back to the real `fetchProgress`. */
  readonly progress?: (receiptId: string) => Promise<import('../api/upload').ProgressReport>
  /** Takes a callback, returns its cancel. Injected for tests; defaults to a
   *  fixed-interval poller so the list stays current. */
  readonly poll?: (fn: () => void) => () => void
}

/** The default list poller: re-fetch every {@link REFRESH_MS}. A seam, the same
 *  shape `ProcessingView`'s own poller is, so a test can drive ticks by hand. */
function everyFewSeconds(fn: () => void): () => void {
  const handle = setInterval(fn, REFRESH_MS)
  return () => clearInterval(handle)
}

/** The processing landing screen at `/app/processing`.
 *
 * ## What it shows
 *
 * Every receipt still in the pipeline -- `GET /receipts?status=pending`. A
 * receipt is `pending` from the moment `POST /upload` writes its row until the
 * worker gives it a terminal status, so this list IS "what is processing right
 * now". When one finishes it drops off the next refresh; a fresh upload appears
 * on it.
 *
 * ## Expand a row to watch it work
 *
 * Each row can be opened to reveal its live progress -- the same
 * `ProcessingView` the upload screen uses, which polls
 * `GET /receipts/{id}/progress` and narrates the stage the pipeline has reached.
 * Only the open rows poll the fine-grained progress; the list itself re-fetches
 * on a slower clock so the set of pending receipts stays current without a
 * manual refresh. A receipt is expanded by id, so the panel survives the list
 * re-ordering under it.
 *
 * ## Conventions this shares with the rest of the app
 *
 * One `role="alert"` region (ADR-0024); the server's own words for a failure it
 * described, a supplied sentence only when it gave none; nullable fields through
 * `ui/Value` so `null` is neither `0` nor a blank cell (ADR-0027 decision 5);
 * every element placed by class, never by position, and the stylesheet is
 * tokens-only.
 *
 * A failed refresh leaves the last good list standing rather than blanking the
 * screen: a receipt processing perfectly well behind a flaky read should not
 * vanish from view, the same reasoning `ProcessingView` applies to a failed
 * progress poll.
 */
export function ProcessingListScreen({
  load = fetchReceipts,
  progress,
  poll = everyFewSeconds,
}: ProcessingListScreenProps) {
  const [rows, setRows] = useState<ReceiptSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** The receipt ids whose progress panel is open. A set so several can be
   *  watched at once, keyed by id so the list re-ordering under an open panel
   *  never moves it to a different receipt. */
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())

  const refresh = useCallback(async () => {
    try {
      const page = await load({ status: PENDING_STATUS })
      setRows(page.items)
      setError(null)
    } catch (caught) {
      // The rows are NOT cleared: a flaky read must not empty a list of receipts
      // that are still processing. The last good set stays and the alert says a
      // refresh failed.
      setError(messageOf(caught, 'could not load the processing receipts'))
    }
  }, [load])

  useEffect(() => {
    let live = true
    const cancel = poll(() => {
      if (live) {
        void refresh()
      }
    })
    // Asked once immediately, not only on the first tick: waiting out an
    // interval would open the screen blank while there is a list to show.
    void refresh()
    return () => {
      live = false
      cancel()
    }
  }, [poll, refresh])

  function toggle(id: string): void {
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Processing</h1>
      <p className={styles.scope}>
        Receipts still moving through the pipeline. Each leaves this list the moment the server
        gives it a terminal status; open one to watch the step it is on right now.
      </p>

      {error === null ? null : (
        <p className={styles.alert} role="alert">
          {error}
        </p>
      )}

      {rows === null ? (
        <p className={styles.waiting}>Loading the receipts that are still processing.</p>
      ) : rows.length === 0 ? (
        <p className={styles.empty}>
          Nothing is processing right now. Uploaded receipts appear here until the pipeline
          finishes with them.
        </p>
      ) : (
        <ol className={styles.list}>
          {rows.map((row) => {
            const isOpen = open.has(row.id)
            return (
              <li className={styles.item} key={row.id}>
                <button
                  type="button"
                  className={styles.rowButton}
                  aria-expanded={isOpen}
                  onClick={() => toggle(row.id)}
                >
                  {/* The chevron turns when the row opens. Decorative: the
                      button's `aria-expanded` carries the state for a screen
                      reader, so this is hidden from one. */}
                  <span
                    className={isOpen ? `${styles.chevron} ${styles.chevronOpen}` : styles.chevron}
                    aria-hidden="true"
                  >
                    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M7 5 L12 10 L7 15" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                  {/* The merchant if one has been read yet, else the id -- a
                      pending receipt often has no merchant, and the id is the
                      handle it always has. `ui/Value` keeps `null` from
                      rendering as a blank. */}
                  <span className={styles.merchant}>
                    <Value value={row.merchant_name_raw} kind="text" />
                  </span>
                  <span className={styles.rowId}>{row.id}</span>
                </button>

                {/* The live progress for this receipt, mounted only while the row
                    is open so a long list is not one poller per receipt. `key`
                    is the id, so React keeps one view per receipt. `fileName` is
                    the id here: this screen never held the uploaded filename, and
                    the id is what the receipt is known by everywhere else. */}
                {isOpen ? (
                  <div className={styles.panel}>
                    <ProcessingView receiptId={row.id} fileName={row.id} progress={progress} />
                  </div>
                ) : null}
              </li>
            )
          })}
        </ol>
      )}
    </main>
  )
}
