import { useEffect, useState } from 'react'
import { fetchProgress } from '../api/upload'
import type { ProgressReport } from '../api/upload'
import styles from './ProcessingView.module.css'

/** The one status a receipt wears while the pipeline still has it.
 *
 * `POST /upload` answers `status: "pending"` and `ReceiptStatus.PENDING` is
 * where the word is defined (src/receipts/score/confidence.py). There is no
 * status enum on this side of the wire -- `api/types.ts` types every `status`
 * as `string` -- so the word is written once, here, and read by the one
 * function that decides the wait is over.
 */
const PENDING = 'pending'

/** How long the default seam waits between asks. */
const POLL_MS = 1500

/** The terminal status this receipt reached, or `null` while it has not.
 *
 * **Progress is narration; `status` is truth.** The wait ends when the server
 * says the receipt is no longer `pending`, and never when `stage` goes quiet: a
 * worker that dies stops writing progress while the row is still `pending`, so a
 * view that waited for a terminal *stage* would wait for narration that is not
 * coming (the design's decision 3). `tests/upload-screen.test.tsx` pins it from
 * both sides -- a terminal status with no stage stops, and a null stage with a
 * `pending` status does not.
 *
 * A `null` status is not terminal. It is the absence of an answer rather than an
 * answer -- the route reports it when the receipt row carries no status at all
 * -- and ending the wait on the reading that says least is the same mistake as
 * ending it on a silent stage.
 */
function terminalStatus(report: ProgressReport | null): string | null {
  if (report === null || report.status === null || report.status === PENDING) {
    return null
  }
  return report.status
}

/** Ask again every so often, until the caller stops it. The default `poll`.
 *
 * A seam rather than a `setInterval` written into the effect, so the tests drive
 * ticks by hand and no test needs fake timers. The same move `AdminScreen` makes
 * with `now`: the thing that would otherwise make a component a function of the
 * clock is a parameter with a live default.
 */
function everyFewSeconds(fn: () => void): () => void {
  const handle = setInterval(fn, POLL_MS)
  return () => clearInterval(handle)
}

/** What this view has watched happen, so far.
 *
 * `seen` is what was **observed**, not what ran. The route reports one current
 * stage, so a stage that begins and ends between two asks leaves no row here --
 * which is why the pane is headed by what it is (the steps this page has seen)
 * rather than by a promise to show the pipeline.
 */
interface Narration {
  /** Stages in the order they were first seen. Deduplicated, because the
   *  pipeline enters `persist` more than once and a stage that is still running
   *  is reported by every ask until it ends. */
  readonly seen: readonly string[]
  /** The last report that arrived, or `null` before the first one does. A failed
   *  ask leaves the previous one standing. */
  readonly latest: ProgressReport | null
}

const NOTHING_YET: Narration = { seen: [], latest: null }

function watched(previous: Narration, report: ProgressReport): Narration {
  const stage = report.stage
  if (stage === null || previous.seen.includes(stage)) {
    return { seen: previous.seen, latest: report }
  }
  return { seen: [...previous.seen, stage], latest: report }
}

export interface ProcessingViewProps {
  readonly receiptId: string
  /** The name of the file this came from. The server does not send it back, and
   *  a person watching wants to see which of their photographs is in the
   *  pipeline rather than an id they have never seen before. */
  readonly fileName: string
  /** Injected so tests never touch `fetch`. Defaults to the real call. */
  readonly progress?: (receiptId: string) => Promise<ProgressReport>
  /** Takes a callback, returns its cancel. Injected for the reason
   *  `everyFewSeconds` records. */
  readonly poll?: (fn: () => void) => () => void
}

/** The wait, narrated -- what a person watches for the ~25-60s a receipt takes.
 *
 * ## Two panes, in the review screen's positions
 *
 * Receipt left, steps right. `ReviewScreen.module.css` splits its grid
 * `minmax(0, 1fr) minmax(0, 1.35fr)` at the same page width and the same
 * padding, so the left-hand pane here sits where the review screen puts the
 * photograph: when this screen gives way to that one, the receipt's column does
 * not move.
 *
 * **This view renders no photograph.** Its inputs are a receipt id and a file
 * name; the image is a separate signed-URL call (`GET /receipts/{id}/image`,
 * which `ReviewScreen` reaches by handing `fetchImageUrl` to `ImagePane`) and
 * this view does not make it. So the left pane names the receipt, and the
 * design's decision 9 -- HEIC degrading to a chip instead of a broken image --
 * has nothing to bite on here.
 *
 * ## No elapsed figure, and no clock
 *
 * The design asks for an elapsed time beside a completed stage, labelled elapsed
 * and never latency (decision 10). Nothing this view is given can produce one.
 * `ProgressEvent` carries a stage and a detail and no timestamp
 * (src/receipts/progress.py), and `POST /upload` queues the receipt for a worker
 * to pick up whenever it gets to it -- so the only interval measurable here is
 * how long *this page* has been watching, which for the first stage it sees is
 * not that stage's duration at all. That would be a number about the browser
 * wearing the label of a number about the pipeline -- and decision 10 records
 * one such figure being invented and then deleted in an earlier milestone. So
 * there is none here, and the gap is written down rather than filled.
 *
 * ## What a failed ask does
 *
 * Nothing visible. A poll that throws leaves the last narration on screen and
 * the next tick still scheduled: a receipt processing perfectly well behind a
 * flaky read would otherwise be stranded on a screen announcing a failure that
 * is not its own.
 */
export function ProcessingView({
  receiptId,
  fileName,
  progress = fetchProgress,
  poll = everyFewSeconds,
}: ProcessingViewProps) {
  const [narration, setNarration] = useState<Narration>(NOTHING_YET)

  useEffect(() => {
    let live = true
    let cancel: (() => void) | null = null
    function stopPolling(): void {
      cancel?.()
      cancel = null
    }

    function ask(): void {
      void progress(receiptId).then(
        (report) => {
          if (!live) {
            return
          }
          setNarration((previous) => watched(previous, report))
          // STOP ON `status`, NEVER ON `stage`. See `terminalStatus`.
          if (terminalStatus(report) !== null) {
            stopPolling()
          }
        },
        () => {
          // A failed ask is not a failed receipt, so nothing is recorded and
          // nothing is cancelled. The tick stays scheduled and the next one
          // asks again.
        },
      )
    }

    // Asked once immediately, and not only on the tick: `POST /upload` has
    // already returned by the time this mounts, so waiting out a first interval
    // would open the wait on an empty pane while the pipeline is already
    // working.
    cancel = poll(ask)
    ask()
    return () => {
      live = false
      stopPolling()
    }
  }, [receiptId, progress, poll])

  const report = narration.latest
  const stage = report?.stage ?? null
  const detail = report?.detail ?? null
  const finished = terminalStatus(report)
  // The active stage is reported by every ask while it runs, so it is in `seen`
  // as well. It is drawn once, with weight, and the rest collapse behind it.
  const past = narration.seen.filter((name) => name !== stage)

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Processing</h1>
      <p className={styles.scope}>
        Each step appears here as this page sees the pipeline reach it. There is nothing to reload
        and nowhere to come back to -- this page stays with the receipt until the server says it is
        done.
      </p>

      <section className={styles.receipt}>
        <h2 className={styles.paneHeading}>Receipt</h2>
        <p className={styles.fileName}>{fileName}</p>
        <p className={styles.receiptId}>{receiptId}</p>
      </section>

      <section className={styles.steps}>
        <h2 className={styles.paneHeading}>Steps</h2>
        <ol className={styles.list}>
          {past.map((name) => (
            <li className={styles.past} key={name}>
              {name}
            </li>
          ))}
          {/* `null` renders as nothing rather than as an empty row (ADR-0027
              decision 5) -- for the stage, and for the detail inside it. */}
          {stage === null ? null : (
            <li className={styles.active}>
              <span className={styles.stage}>{stage}</span>
              {detail === null ? null : <span className={styles.detail}>{detail}</span>}
            </li>
          )}
        </ol>

        {finished === null ? (
          stage === null ? (
            // Quiet, and not an alert: nothing has failed. Said in what is known
            // -- there is no stage in the last report -- rather than in a guess
            // at why, which from here is not decidable: a worker that has not
            // picked the job up yet and a worker that has died look the same
            // from this side.
            <p className={styles.quiet}>No step is reporting right now.</p>
          ) : null
        ) : (
          <>
            <p className={styles.outcome}>
              The pipeline is done with it. The server now calls it{' '}
              <span className={styles.status}>{finished}</span>.
            </p>
            {/* The one real navigation in this flow, and it is deliberate (the
                design's decision 6). It goes to the queue, which claims whatever
                task is next -- not necessarily this receipt -- so it is named as
                the queue. A plain `href`: there is no client-side routing here,
                and the last path segment has no dot, which is what keeps the
                backend serving the app rather than a 404 (`route.ts`). */}
            <a className={styles.next} href="/app/review">
              Open the review queue
            </a>
          </>
        )}
      </section>
    </main>
  )
}
