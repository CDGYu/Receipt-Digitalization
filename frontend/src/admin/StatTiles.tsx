import { Value } from '../ui/Value'
import type { Metrics } from '../api/admin'
import styles from './StatTiles.module.css'

/** The queue at a glance -- design section 5.7, fed by `GET /metrics`.
 *
 * Four tiles: the open backlog, what is being worked, what is closed, and the
 * auto-approval rate.
 *
 * ## The rate is where section 4's rule bites hardest
 *
 * `auto_approval_rate` is `str | None`, and the null is the API's own decision:
 * the route returns `None` when `auto_approved + needs_review + reviewed == 0`
 * -- an *undefined* rate, not a confident `0` or `1.0` on an empty denominator.
 * A tile that rendered that as `0%` would tell an operator their pipeline
 * approves nothing, on a screen built to answer exactly that question. So it
 * goes through `ui/Value`, which owns the rule, and a null renders as the mark
 * with an accessible name.
 *
 * **The rate is displayed as the ratio the server sent, not as a percentage.**
 * Converting `"0.500"` to `50%` means arithmetic on a decimal string, and every
 * route to a JS number from one is a float (`Number("0.500")` is `0.5`, and the
 * trailing digit the server quantized to is gone). ADR-0001 forbids that path
 * and `tests/no-float-in-money-path.test.ts` enforces it. The tile is labelled
 * with what the number is instead, which costs a reader one unit conversion and
 * costs the system no precision.
 *
 * ## Counts, and why they are converted rather than interpolated
 *
 * `request<T>` is an unchecked cast, so a body missing `queue.open` arrives as
 * `undefined` and `{metrics.queue.open}` would render an empty tile -- a
 * missing number that looks like nothing, which is the failure section 4 names.
 * `countOf` turns anything that is not a number into `null`, so it takes the
 * mark; a real `0` is a real number and renders as `0`.
 */
function countOf(value: number | undefined): string | null {
  return typeof value === 'number' ? String(value) : null
}

function Tile({ label, value }: { label: string; value: string | null }) {
  return (
    <div className={styles.tile}>
      <span className={styles.label}>{label}</span>
      <span className={styles.figure}>
        <Value value={value} kind="count" />
      </span>
    </div>
  )
}

export function StatTiles({ metrics }: { metrics: Metrics }) {
  const queue = metrics.queue as Metrics['queue'] | undefined
  return (
    // A named region rather than a bare wrapper: this is a landmark a screen
    // reader can jump to, and it is what lets a test address the tiles apart
    // from the table below, which repeats two of these words as row states.
    <section className={styles.tiles} aria-label="Queue statistics">
      <p className={styles.caption}>Across all reviewers</p>
      <Tile label="Open backlog" value={countOf(queue?.open)} />
      <Tile label="In progress" value={countOf(queue?.in_progress)} />
      <Tile label="Done" value={countOf(queue?.done)} />
      <Tile label="Auto-approval rate" value={metrics.auto_approval_rate} />
    </section>
  )
}
