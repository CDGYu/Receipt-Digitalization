import { useCallback, useEffect, useState } from 'react'
import { fetchTasks } from '../api/admin'
import { ApiError } from '../api/client'
import { claimTask } from '../api/review'
import { fetchReceipts } from '../api/receipts'
import type { ReceiptSummary, ReviewTask } from '../api/types'
import styles from './ReviewQueue.module.css'

/** The review queue as rows a reviewer picks from.
 *
 * ## Why this exists
 *
 * A reviewer could only ever be *handed* work: `GET /review/next` claims the
 * head of the queue and nothing showed what else was waiting. This is the list,
 * and `POST /review/{id}/claim` is what makes picking a row mean anything --
 * without it a button on the third row would have claimed the first.
 *
 * ## Two calls, joined here
 *
 * `GET /review/tasks` carries the queue's own columns -- `reason`, `priority`,
 * `state`, `opened_at` -- and **no receipt content at all**: `_task_summary`
 * returns ids and queue metadata. Merchant, total and confidence come from
 * `GET /receipts`, which is `require_user` and whose `receipt_summary` docstring
 * calls itself "just enough for a reviewer to triage a queue". So the two are
 * fetched together and joined on `receipt_id` here.
 *
 * **A task whose receipt is not on the joined page still renders**, with its
 * queue columns and a muted marker where the money would be. Dropping it would
 * hide a reviewable receipt because a *different* request paginated, and the
 * queue row is the thing that makes it claimable.
 *
 * ## No state filter on the task fetch, deliberately
 *
 * `list_tasks` scopes a reviewer to `state == OPEN` **plus their own rows in any
 * state** (ADR-0026). Asking for `state=open` would therefore hide the task this
 * reviewer is already holding, which is the one row they most need to see. So
 * the fetch is unfiltered and the split happens at RENDER, by exact state:
 * `in_progress` rows go to the top as a resume and `open` rows are the backlog.
 * A `done` row -- their own history, which the same scope also returns --.
 * matches neither and so appears nowhere, because this list is work to pick up.
 *
 * **Two exact-state filters, not one `!== 'done'` filter.** There was a
 * `filter(task => task.state !== 'done')` here first, and it was dead: the two
 * render filters already exclude everything that is not the state they name, so
 * removing it changed no output and no test. It is gone rather than kept as
 * belt-and-braces, because a redundant guard makes the real one untestable --
 * a mutation that breaks one is masked by the other, and the test that claimed
 * to pin this passed with the filter deleted.
 *
 * ## Order
 *
 * Untouched. `list_tasks` orders by `priority, opened_at, id`, the same total
 * order `_claim_stmt` uses, so the first backlog row here is genuinely the row
 * `GET /review/next` would hand out next. Re-sorting in the browser would make
 * the list disagree with the queue.
 */

/** ISO 8601 to a stable, locale-independent minute.
 *
 *  Not `toLocaleString`: its output moves with the runtime's locale and time
 *  zone, which makes it untestable without pinning both, and this column exists
 *  to be *compared between rows* rather than read as a wall clock. Not a
 *  relative "2h ago" either -- that needs `Date.now()` at render time, which is
 *  a value React did not schedule the render for and a moving target in tests.
 */
function openedAt(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

interface Row {
  readonly task: ReviewTask
  /** `null` when the task's receipt was not on the joined page. */
  readonly receipt: ReceiptSummary | null
}

export interface ReviewQueueProps {
  /** How to leave for the reviewer once a task is in hand.
   *
   *  Injected rather than calling `window.location.assign` inline so a test can
   *  observe the destination without a jsdom navigation, which jsdom refuses
   *  and reports as an unhandled error rather than a failed assertion. */
  readonly navigate?: (url: string) => void
}

/** Where a claimed task is reviewed. Claiming leaves this screen for that one. */
const REVIEW_PATH = '/app/review'

export function ReviewQueue({ navigate }: ReviewQueueProps = {}) {
  const [rows, setRows] = useState<readonly Row[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** The task whose claim is in flight: drives the clicked row's own label and
   *  disables every button, so a second click cannot start a second claim. */
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
  /** A refused claim, in the API's own words -- a 409 names who holds the row,
   *  or which task is already in this reviewer's hands. Rendered here because
   *  this is where the reviewer is looking when it happens. */
  const [claimError, setClaimError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    setRows(null)
    try {
      const [tasks, receipts] = await Promise.all([
        fetchTasks(),
        fetchReceipts({ status: 'needs_review' }),
      ])
      const byId = new Map((receipts?.items ?? []).map((r) => [r.id, r]))
      // `?? []` rather than trusting the body: `request` is an unchecked cast,
      // so a reply missing `items` would otherwise throw inside `.map` and be
      // reported as a render crash instead of an empty queue.
      const live = tasks?.items ?? []
      setRows(live.map((task) => ({ task, receipt: byId.get(task.receipt_id) ?? null })))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'could not load the review queue')
    }
  }, [])

  /** Claim one named task, then leave for the reviewer.
   *
   *  **Claiming, then navigating, is the whole handoff** -- and it works
   *  because `GET /review/next` *resumes before it claims* (ADR-0016). The
   *  review screen calls that on mount, and a caller already holding an
   *  `IN_PROGRESS` row gets that row back rather than a fresh one off the
   *  queue, so the reviewer arrives at the receipt they picked. Measured, not
   *  assumed: `test_review_claim_answers_in_the_same_shape_as_review_next`
   *  claims by id and then asserts `GET /review/next` returns the same task id.
   *
   *  One handler for both buttons. Re-claiming a task you already hold is
   *  idempotent at the route, so `Resume` on your own in-progress row and
   *  `Review` on an open one are the same call.
   */
  const openTask = useCallback(
    async (taskId: string) => {
      setBusyTaskId(taskId)
      setClaimError(null)
      try {
        const claimed = (await claimTask(taskId))?.task ?? null
        if (claimed === null) {
          setClaimError('That task is no longer available. Refresh the list.')
          return
        }
        ;(navigate ?? ((url: string) => window.location.assign(url)))(REVIEW_PATH)
      } catch (caught) {
        setClaimError(
          caught instanceof ApiError ? caught.message : 'could not open that receipt',
        )
        // Only on failure: after a successful claim the navigation is in
        // flight and re-enabling the buttons would invite a second click on a
        // screen that is leaving.
        setBusyTaskId(null)
      }
    },
    [navigate],
  )

  useEffect(() => {
    void load()
  }, [load])

  if (error !== null) {
    return (
      <main className={styles.screen}>
        <h1 className={styles.heading}>Review queue</h1>
        <div className={styles.queue}>
          <p className={styles.error} role="alert">
            {error}
          </p>
          <button type="button" onClick={() => void load()}>
            Try again
          </button>
        </div>
      </main>
    )
  }

  if (rows === null) {
    return (
      <main className={styles.screen}>
        <h1 className={styles.heading}>Review queue</h1>
        <p className={styles.empty}>Loading the review queue...</p>
      </main>
    )
  }

  const mine = rows.filter((row) => row.task.state === 'in_progress')
  const backlog = rows.filter((row) => row.task.state === 'open')

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Review queue</h1>
      <div className={styles.queue}>
        {claimError !== null ? (
        <p className={styles.error} role="alert">
          {claimError}
        </p>
      ) : null}

      {mine.length > 0 ? (
        <section className={styles.section} aria-labelledby="review-queue-mine">
          <h2 className={styles.sectionHeading} id="review-queue-mine">
            Already in your hands
          </h2>
          <QueueTable
            rows={mine}
            action="Resume"
            onOpen={(taskId) => void openTask(taskId)}
            busyTaskId={busyTaskId}
            highlight
          />
        </section>
      ) : null}

      <section className={styles.section} aria-labelledby="review-queue-backlog">
        <h2 className={styles.sectionHeading} id="review-queue-backlog">
          Receipts waiting for review
        </h2>
        {backlog.length === 0 ? (
          <p className={styles.empty}>
            {mine.length > 0
              ? 'Nothing else is waiting.'
              : 'Nothing is waiting for review right now.'}
          </p>
        ) : (
          <QueueTable
            rows={backlog}
            action="Review"
            onOpen={(taskId) => void openTask(taskId)}
            busyTaskId={busyTaskId}
            highlight={false}
          />
        )}
        </section>
      </div>
    </main>
  )
}

function QueueTable({
  rows,
  action,
  onOpen,
  busyTaskId,
  highlight,
}: {
  readonly rows: readonly Row[]
  readonly action: string
  readonly onOpen: (taskId: string) => void
  readonly busyTaskId: string | null
  readonly highlight: boolean
}) {
  return (
    <div className={styles.scroller}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Merchant</th>
            <th scope="col" className={styles.numeric}>
              Total
            </th>
            <th scope="col" className={styles.numeric}>
              Confidence
            </th>
            <th scope="col">Why</th>
            <th scope="col">Opened</th>
            <th scope="col">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ task, receipt }) => (
            <tr key={task.id} className={highlight ? styles.mine : undefined}>
              <td>
                {receipt === null ? (
                  <span className={styles.unknown}>receipt not on this page</span>
                ) : (
                  (receipt.merchant_name_raw ?? <span className={styles.unknown}>unread</span>)
                )}
              </td>
              <td className={styles.numeric}>
                {receipt?.total === null || receipt === null ? (
                  <span className={styles.unknown}>--</span>
                ) : (
                  `${receipt.currency ?? ''} ${receipt.total}`.trim()
                )}
              </td>
              <td className={styles.numeric}>
                {receipt?.confidence == null ? (
                  <span className={styles.unknown}>--</span>
                ) : (
                  receipt.confidence
                )}
              </td>
              <td className={styles.reason}>{task.reason}</td>
              <td className={styles.opened}>{openedAt(task.opened_at)}</td>
              <td className={styles.action}>
                <button
                  type="button"
                  onClick={() => onOpen(task.id)}
                  disabled={busyTaskId !== null}
                >
                  {busyTaskId === task.id ? 'Opening...' : action}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
