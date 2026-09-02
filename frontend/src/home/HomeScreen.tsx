/** The landing screen at `/app/`.
 *
 * Until this existed, `route.ts` returned `review` for every path it did not
 * recognise, so opening the app dropped a signed-in person on the review queue
 * -- and on an empty queue that is the sentence "The review queue is empty."
 * with nothing to do next. An empty screen should be an invitation to act, so
 * this one names the three things a person can do and how much work is waiting.
 *
 * The counts come from `GET /metrics` through `fetchMetrics`, the same call
 * `AdminScreen` makes. Reused rather than restated: the response shape is
 * declared once in `api/admin.ts` and `auto_approval_rate`'s load-bearing null
 * is documented there.
 *
 * **The links do not wait for the counts.** They are static destinations, so
 * they render immediately and stay useful when `/metrics` is slow or fails --
 * the counts are the decoration here and the ways forward are the point. A
 * screen that hid its navigation behind a fetch would be a worse dead end than
 * the one it replaces.
 *
 * No `StrictMode` claim guard, unlike `ReviewScreen`'s: `GET /metrics` is a
 * read, so the double invocation React makes in development costs one extra
 * request and changes nothing. `fetchNext` needed a guard because it *claims* a
 * task; this does not.
 */
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { fetchMetrics } from '../api/admin'
import type { Metrics } from '../api/admin'
import { StatTiles } from '../admin/StatTiles'
import { accuracyPercent } from '../ui/accuracy'
import styles from './HomeScreen.module.css'

interface Destination {
  readonly label: string
  readonly href: string
  readonly hint: string
}

const DESTINATIONS: readonly Destination[] = [
  {
    label: 'Upload a receipt',
    href: '/app/upload',
    hint: 'One photograph at a time. It is stored and queued straight away.',
  },
  {
    label: 'Review the queue',
    href: '/app/review',
    hint: 'Correct what the machine was unsure about, one receipt at a time.',
  },
  {
    label: 'Processed receipts',
    href: '/app/receipts',
    hint: 'Exactly what the export workbook contains.',
  },
]

/** `counts_by_status` as rows, highest count first, zeroes dropped.
 *
 *  Sorted rather than left in object order: JSON object key order is the
 *  server's insertion order, which is a `Record` built from a database GROUP BY
 *  and carries no meaning a reader should infer from position. Highest first is
 *  a claim this screen can defend.
 *
 *  **Zeroes are dropped, not rendered as `0`.** A status with no receipts is not
 *  information on a landing screen; a list of eight statuses of which six are
 *  zero buries the two that are not.
 */
const STATUS_ROWS = (counts: Record<string, number>): readonly (readonly [string, number])[] =>
  Object.entries(counts ?? {})
    .filter(([, count]) => count > 0)
    .sort((left, right) => right[1] - left[1])

export function HomeScreen() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    fetchMetrics()
      .then((next) => {
        if (live) {
          setMetrics(next)
        }
      })
      .catch((caught: unknown) => {
        if (live) {
          setFailure(caught instanceof ApiError ? caught.message : 'could not read the queue')
        }
      })
    return () => {
      live = false
    }
  }, [])

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Receipts</h1>

      {metrics === null ? (
        <section className={styles.counts} aria-label="Queue depth">
          <p className={styles.waiting}>
            {failure === null ? 'Reading the queue...' : `The queue count is unavailable: ${failure}`}
          </p>
        </section>
      ) : (
        <>
          {/* `StatTiles` rather than four hand-rolled figures. It lives under
              `admin/` because that is where it was first needed, not because it
              is admin-only: it takes `metrics` as a prop, renders nothing
              privileged, and its own caption says "System-wide, not only your
              tasks". This screen used to restate three of its four tiles in
              its own markup, minus the auto-approval rate and minus `Value`'s
              null handling -- so a null rate rendered here as the word "null"
              and there as an em dash. One component, one answer. */}
          <StatTiles metrics={metrics} />

          <section className={styles.panel} aria-label="Where the accuracy threshold sits">
            <h2 className={styles.panelHeading}>Auto-approval</h2>
            <p className={styles.thresholds}>
              A receipt is approved without a human at{' '}
              <span className={styles.figure}>
                {accuracyPercent(metrics.thresholds.auto_approve)}
              </span>{' '}
              accuracy or better, and is sent for review below{' '}
              <span className={styles.figure}>
                {accuracyPercent(metrics.thresholds.review)}
              </span>.
            </p>
            {/* The rate is already a tile above; what is NOT above is what it is
                a rate against, and a percentage with no threshold beside it
                cannot be acted on. Raising the bar lowers the rate, and that
                trade is the one decision this screen exists to inform. */}
          </section>

          <section className={styles.panel} aria-label="Receipts by status">
            <h2 className={styles.panelHeading}>Receipts by status</h2>
            {STATUS_ROWS(metrics.counts_by_status).length === 0 ? (
              <p className={styles.waiting}>No receipts have been ingested yet.</p>
            ) : (
              <ul className={styles.statuses}>
                {STATUS_ROWS(metrics.counts_by_status).map(([status, count]) => (
                  <li key={status} className={styles.status}>
                    <span className={styles.statusLabel}>{status.replace(/_/g, ' ')}</span>
                    <span className={styles.statusCount}>{count}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      <nav className={styles.ways} aria-label="Where to go">
        {DESTINATIONS.map((destination) => (
          <a key={destination.href} className={styles.way} href={destination.href}>
            <span className={styles.wayLabel}>{destination.label}</span>
            <span className={styles.wayHint}>{destination.hint}</span>
          </a>
        ))}
      </nav>
    </main>
  )
}
