import { useCallback, useEffect, useState } from 'react'
import type { JSX } from 'react'
import { fetchTasks } from '../api/admin'
import { ApiError } from '../api/client'
import { claimTask } from '../api/review'
import { fetchReceipts } from '../api/receipts'
import type { ReceiptSummary, ReviewTask } from '../api/types'
import { Chip } from '../ui/Chip'
import styles from './ReviewQueue.module.css'

/** Whether decimal string `a` is `>=` decimal string `b`, WITHOUT going through
 *  a float.
 *
 *  `Number("0.850")` is `0.85` and, worse on the money path generally, drops the
 *  precision ADR-0001 forbids losing -- and the repository's no-float guard
 *  fails on any `Number(...)`/`parseFloat(...)` of a money-path value. Confidence
 *  is such a value (a `Money`-branded decimal string), so the band comparison is
 *  done on the digits instead: split each value into its whole and fraction
 *  parts, right-pad the fractions to equal length, and compare the two parts as
 *  strings. For equal-length numeric strings, lexicographic order IS numeric
 *  order, so no coercion is needed and no precision is invented.
 *
 *  Confidence is always `0.000`..`1.000` here, so the inputs are well-formed;
 *  the parser is still defensive (a missing fraction pads to "0") so a
 *  differently formatted value degrades gracefully rather than throwing. */
function decimalAtLeast(a: string, b: string): boolean {
  const [aWhole, aFrac = ''] = a.split('.')
  const [bWhole, bFrac = ''] = b.split('.')
  const width = Math.max(aFrac.length, bFrac.length)
  const aKey = `${aWhole.padStart(3, '0')}.${aFrac.padEnd(width, '0')}`
  const bKey = `${bWhole.padStart(3, '0')}.${bFrac.padEnd(width, '0')}`
  return aKey >= bKey
}

type ChipTone = 'error' | 'warn' | 'info' | 'positive' | 'neutral'

/** A ring glyph carrying `fill` inside it, so each band's icon differs by more
 *  than its colour (§6 -- never colour alone). `fill` is the fraction of the
 *  ring filled from the bottom, drawn as a chord: 1 is a full disc (lowest
 *  band, loudest), 0 is a bare ring (highest band). A reader who cannot
 *  separate the five tones still sees five different amounts of fill. */
function GlyphGauge({ fill }: { fill: 0 | 1 | 2 | 3 | 4 | 5 }) {
  // Five discrete fills. `d` is a filled path from the bottom of the ring up to
  // the band's level; the empty and full cases are a bare ring and a whole disc.
  const FILLS: Record<0 | 1 | 2 | 3 | 4 | 5, string | null> = {
    0: null,
    1: 'M4 13 A6.25 6.25 0 0 0 16 13 Z',
    2: 'M3.9 10 A6.25 6.25 0 0 0 16.1 10 Z',
    3: 'M3.75 10 A6.25 6.25 0 0 0 16.25 10 L16.25 6.5 A6.25 6.25 0 0 0 3.75 6.5 Z',
    4: 'M4 7 A6.25 6.25 0 0 0 16 7 L16 5 A6.25 6.25 0 0 0 4 5 Z',
    5: 'M10 3.75 A6.25 6.25 0 1 0 10 16.25 A6.25 6.25 0 1 0 10 3.75 Z',
  }
  const d = FILLS[fill]
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
      {d === null ? null : <path d={d} fill="currentColor" stroke="none" />}
    </svg>
  )
}

/** No score to band: a bare ring, the neutral placeholder. */
function GlyphUnknown() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
    </svg>
  )
}

/** The five confidence bands, lowest first -- the order a reviewer works them.
 *
 *  Fixed 0.20-wide ranges (0.00-0.20, 0.21-0.40, 0.41-0.60, 0.61-0.80,
 *  0.81-1.00), each with its own tone and its own amount of gauge fill so it
 *  reads without colour. `min` is the inclusive lower bound as a decimal string;
 *  the band a score falls in is the highest whose `min` it is `>=`, so a value
 *  below every `min` (only `< 0.00`, which cannot happen) would be none. Lowest
 *  is the loudest (error, full gauge) because it most needs a human; highest is
 *  calmest (positive, empty gauge).
 *
 *  This replaced a three-band split keyed on the routing thresholds (0.60 /
 *  0.85). These even 0.20 steps are the owner's chosen buckets for triage and
 *  are deliberately independent of where the pipeline auto-approves. */
const BANDS: readonly {
  readonly min: string
  readonly tone: ChipTone
  readonly fill: 0 | 1 | 2 | 3 | 4 | 5
  readonly label: string
}[] = [
  { min: '0.81', tone: 'positive', fill: 0, label: '0.81-1.00' },
  { min: '0.61', tone: 'info', fill: 2, label: '0.61-0.80' },
  { min: '0.41', tone: 'neutral', fill: 3, label: '0.41-0.60' },
  { min: '0.21', tone: 'warn', fill: 4, label: '0.21-0.40' },
  { min: '0.00', tone: 'error', fill: 5, label: '0.00-0.20' },
]

/** A confidence score as a tone, a glyph and its band, so a reviewer can see
 *  which receipts to check first without reading every number.
 *
 *  `confidence` arrives as a decimal string (`Money`) or `null`. It is compared
 *  against the band bounds AS A STRING (see `decimalAtLeast`), never coerced to
 *  a float (ADR-0001), and the exact string is what the chip shows -- so no
 *  precision is invented or lost. A `null` is the neutral "--" placeholder
 *  rather than a guessed band. */
function confidenceBand(confidence: string | null): {
  tone: ChipTone
  icon: JSX.Element
  label: string
  value: string
} {
  if (confidence === null) {
    return { tone: 'neutral', icon: <GlyphUnknown />, label: 'no score', value: '--' }
  }
  // The highest band whose lower bound the score meets. `BANDS` runs high to
  // low, so the first match is the right one.
  const band = BANDS.find((candidate) => decimalAtLeast(confidence, candidate.min)) ?? BANDS[BANDS.length - 1]
  return { tone: band.tone, icon: <GlyphGauge fill={band.fill} />, label: band.label, value: confidence }
}

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
 * `state`, `uploaded_at` (the receipt's upload time, shown in the "Uploaded"
 * column) and `opened_at` -- and **no receipt content at all**: `_task_summary`
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
 * ## The title is not "Review queue"
 *
 * `AdminScreen`'s h1 is already "Review queue", and it is the right title
 * there: that screen lists every task in every state with its id and assignee.
 * This one is a reviewer's pick list. Two screens under one title is a thing
 * only a browser shows you -- the measurement that found it was reading `h1`
 * text across four screens for an unrelated reason.
 *
 * ## Order
 *
 * Untouched. `list_tasks` orders by `priority, Receipt.created_at, id` (the
 * receipt's upload time), the same total order `_claim_stmt` uses, so the first
 * backlog row here is genuinely the row `GET /review/next` would hand out next.
 * Re-sorting in the browser would make the list disagree with the queue.
 */

/** ISO 8601 to a stable, locale-independent minute.
 *
 *  Not `toLocaleString`: its output moves with the runtime's locale and time
 *  zone, which makes it untestable without pinning both, and this column exists
 *  to be *compared between rows* rather than read as a wall clock. Not a
 *  relative "2h ago" either -- that needs `Date.now()` at render time, which is
 *  a value React did not schedule the render for and a moving target in tests.
 */
function uploadedAt(iso: string): string {
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
        <h1 className={styles.heading}>Receipts to review</h1>
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
        <h1 className={styles.heading}>Receipts to review</h1>
        <p className={styles.empty}>Loading the review queue...</p>
      </main>
    )
  }

  const mine = rows.filter((row) => row.task.state === 'in_progress')
  const backlog = rows.filter((row) => row.task.state === 'open')

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Receipts to review</h1>
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
            <th scope="col" className={styles.confidence}>
              Confidence
            </th>
            <th scope="col">Why</th>
            <th scope="col">Uploaded</th>
            {/* A visible word, not `className="sr-only"` -- **this app defines
                no such class**, so that span rendered in full while claiming to
                be hidden. Seen in a browser; `grep -rn "sr-only" src
                --include=*.css` returns nothing, which is the proof. A visible
                header is the better answer anyway: the column holds buttons,
                and an empty `th` gives a screen reader nothing to announce. */}
            <th scope="col">Action</th>
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
              <td className={styles.confidence}>
                {(() => {
                  // A receipt not on this page has no confidence to band; keep
                  // the plain muted marker rather than a "no score" chip, which
                  // would claim the receipt was read and scored low.
                  if (receipt === null) {
                    return <span className={styles.unknown}>--</span>
                  }
                  const band = confidenceBand(receipt.confidence)
                  return (
                    <Chip tone={band.tone} icon={band.icon}>
                      {/* The exact score leads -- it is what a reviewer reads off
                          -- and the band range follows in parentheses so the
                          bucket the tone and gauge stand for is spelled out. For
                          a null score there is no range, just the "--" value. */}
                      {band.value === '--' ? band.label : `${band.value} (${band.label})`}
                    </Chip>
                  )
                })()}
              </td>
              <td className={styles.reason}>{task.reason}</td>
              <td className={styles.opened}>{uploadedAt(task.uploaded_at)}</td>
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
