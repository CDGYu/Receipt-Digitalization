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

      <section className={styles.counts} aria-label="Queue depth">
        {metrics === null ? (
          <p className={styles.waiting}>
            {failure === null ? 'Reading the queue...' : `The queue count is unavailable: ${failure}`}
          </p>
        ) : (
          <>
            <p className={styles.count}>
              <span className={styles.countLabel}>Open</span>
              <span className={styles.countValue}>{metrics.queue.open}</span>
            </p>
            <p className={styles.count}>
              <span className={styles.countLabel}>In progress</span>
              <span className={styles.countValue}>{metrics.queue.in_progress}</span>
            </p>
            <p className={styles.count}>
              <span className={styles.countLabel}>Done</span>
              <span className={styles.countValue}>{metrics.queue.done}</span>
            </p>
          </>
        )}
      </section>

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
