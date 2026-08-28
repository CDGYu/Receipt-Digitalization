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

function statusLabel(status: string): string {
  return status === 'needs_review' ? 'needs reviews' : status
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
  /** Stages in the order they were first seen. Deduplicated, because a stage
   *  that is still running is reported by every ask until it ends. */
  readonly seen: readonly string[]
  /** The last report that arrived, or `null` before the first one does. A failed
   *  ask leaves the previous one standing. */
  readonly latest: ProgressReport | null
  /** What the stage now running has said, oldest first.
   *
   * **This is the sequence, and the sequence is the point** (design section 4).
   * `extract` narrates its own repair loop, and what it writes -- read from
   * `_report` and the best-attempt event in src/receipts/extract/extractor.py --
   * is one line per finished attempt, `attempt N (pass): M error(s)`, and then
   * `kept attempt K of T`. Watching those accumulate is watching the system find
   * its own mistake and try again -- and, when the repair scored worse, keep the
   * earlier answer anyway, since `extract_with_repair` returns the BEST attempt
   * rather than the last. A view holding only the newest line replaces each of
   * them with the next and leaves nothing to watch.
   *
   * (Design section 4 sketches a finer sequence -- validate, findings, repair as
   * separate beats. Those are not separate events today; the error count in each
   * attempt line is what stands in for them. This renders what is emitted.)
   *
   * **This is what was observed, not what ran** -- the caveat `seen` states
   * above, and it bites harder here. Each write overwrites the last
   * (`make_progress_writer`), so several attempts finishing between two asks
   * leave only the newest, and a line the extractor emitted is simply absent.
   * The sequence is the one this page saw.
   *
   * It belongs to the running stage and starts again when the stage does: one
   * stage's narration under another's name would be worse than none. */
  readonly details: readonly string[]
}

const NOTHING_YET: Narration = { seen: [], latest: null, details: [] }

function watched(previous: Narration, report: ProgressReport): Narration {
  const stage = report.stage
  const seen =
    stage === null || previous.seen.includes(stage) ? previous.seen : [...previous.seen, stage]
  // Carried only while the stage is the same one; a new stage starts a new
  // sequence, and so does the stage going quiet.
  const carried = stage !== null && stage === previous.latest?.stage ? previous.details : []
  const detail = report.detail
  // Deduplicated against the PREVIOUS line only, never against the whole list.
  // The route reports whatever detail is current, so an unchanged one arrives
  // again on every ask: consecutive identical lines are one event re-read. A
  // list-wide check would additionally assume no stage ever says the same thing
  // twice -- which happens to hold for today's `extract` lines, because each
  // carries its own attempt number, but that is one emitter's format and not
  // anything this route promises. The narrow rule does not depend on it.
  const repeated = detail === null || detail === carried[carried.length - 1]
  return { seen, latest: report, details: repeated ? carried : [...carried, detail] }
}

export interface ProcessingViewProps {
  readonly receiptId: string
  /** The name of the file this came from. The server does not send it back, and
   *  a person watching wants to see which of their photographs is in the
   *  pipeline rather than an id they have never seen before. */
  readonly fileName: string
  /** How many OTHER receipts the same upload became -- `0` for a photograph,
   *  `n - 1` for an n-page PDF.
   *
   *  This view follows one receipt, and a PDF makes several (ISSUE-027). Saying
   *  so is the whole point of the prop: a person who handed over a twelve-page
   *  invoice and watched one receipt process would otherwise have no way to know
   *  the other eleven exist. Disclosed rather than followed -- eleven more
   *  pollers on one screen is not a design anyone chose. */
  readonly alsoQueued?: number
  /** Injected so tests never touch `fetch`. Defaults to the real call. */
  readonly progress?: (receiptId: string) => Promise<ProgressReport>
  /** Takes a callback, returns its cancel. Injected for the reason
   *  `everyFewSeconds` records. */
  readonly poll?: (fn: () => void) => () => void
}

/** The wait, narrated -- what a person watches while a receipt is processed.
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
 * ## No elapsed figure
 *
 * The design asks for an elapsed time beside a completed stage, labelled elapsed
 * and never latency (decision 10). There is none here, and the reason is
 * narrower than "there is nothing to measure".
 *
 * `ProgressEvent` carries a stage and a detail and no timestamp
 * (src/receipts/progress.py), so any figure here would be built from when this
 * page ASKED. For a stage whose own first sighting and whose successor's first
 * sighting were both observed, that difference **is** its dwell, bracketed by
 * one poll interval -- so the measurement is not impossible, and saying it was
 * would be false.
 *
 * What it is not is uniform, and that is the actual objection. The first stage
 * seen has no observed start: `POST /upload` queues the receipt and a worker
 * takes it whenever it gets there, so the pipeline can already be several asks
 * along when this page first renders. A stage shorter than the poll interval is
 * never seen at all and can carry nothing. So the column would be a measurement
 * where both endpoints were observed, a lower bound on the first stage, and
 * absent for anything too quick to be seen -- different things under one
 * heading, which a reader will average.
 * Decision 10 records one invented figure already deleted here. So: no figure,
 * and the bound written down instead of a number guessed.
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
  alsoQueued = 0,
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
  const finished = terminalStatus(report)
  // The active stage is reported by every ask while it runs, so it is in `seen`
  // as well. It is drawn once, with weight, and the rest collapse behind it.
  const past = narration.seen.filter((name) => name !== stage)

  return (
    // A `<section>`, not a `<main>`: this view is now embedded one-per-receipt
    // inside `UploadScreen`'s own `<main>` list, and a page has one main. The
    // heading is an `<h2>` for the same reason -- it sits under the screen's
    // `<h1>`. The two-column grid, the receipt pane and the steps pane are
    // unchanged; only the outer landmark and the heading level moved, so the
    // narration this file is tested on is untouched.
    <section className={styles.screen}>
      <h2 className={styles.heading}>Processing</h2>
      <p className={styles.scope}>
        Each step appears here as this page sees the pipeline reach it — it stays with the receipt
        until the server says it is done.
      </p>

      <section className={styles.receipt}>
        <h2 className={styles.paneHeading}>Receipt</h2>
        <p className={styles.fileName}>{fileName}</p>
        <p className={styles.receiptId}>{receiptId}</p>
        {/* Absent at zero rather than rendered empty (ADR-0024), and absent is
            the photograph case -- which is every upload that is not a PDF. */}
        {alsoQueued < 1 ? null : (
          <p className={styles.alsoQueued}>
            {alsoQueued === 1
              ? '1 more page of this file was queued as its own receipt.'
              : `${alsoQueued} more pages of this file were queued as their own receipts.`}{' '}
            This view follows the first; the rest are in the review queue when they finish.
          </p>
        )}
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
              {narration.details.length === 0 ? null : (
                <ol className={styles.details}>
                  {narration.details.map((said, index) => (
                    // The list is append-only within a stage -- never reordered,
                    // never spliced, and replaced wholesale when the stage
                    // changes -- so the position is a stable identity. The text
                    // is not used as the key on its own: nothing in the route's
                    // contract says two details differ.
                    <li className={styles.detail} key={`${index}:${said}`}>
                      {said}
                    </li>
                  ))}
                </ol>
              )}
            </li>
          )}
        </ol>

        {finished === null ? (
          stage === null ? (
            // Quiet, and not an alert: nothing has failed. It covers two states
            // that are one state from here -- no report has arrived yet, and a
            // report arrived carrying no stage -- and says only what is true of
            // both. A guess at why would not be decidable on this side anyway: a
            // worker that has not picked the job up and a worker that has died
            // look identical from here.
            <p className={styles.quiet}>No step is reporting right now.</p>
          ) : null
        ) : (
          <p className={styles.outcome}>
            The pipeline is done with it. The server now calls it{' '}
            <span className={styles.status}>{statusLabel(finished)}</span>.
          </p>
        )}

        {/* Rendered in EVERY state, not only the finished one, and that is the
            whole point of it. Decision 3 says the wait never ends on silence, so
            a receipt whose worker never starts is narrated forever -- and while
            this link lived inside the finished branch, forever came with no way
            off the screen at all. That is the failure a live demo is likeliest
            to hit.

            It goes to the queue, which claims whatever task is next -- not
            necessarily this receipt -- so it is named as the queue. A plain
            `href`: there is no client-side routing here, and the last path
            segment has no dot, which is what keeps the backend serving the app
            rather than a 404 (`route.ts`). */}
        <a className={styles.next} href="/app/review">
          Open the review queue
        </a>
      </section>
    </section>
  )
}
