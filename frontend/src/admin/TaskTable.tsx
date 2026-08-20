import { useState } from 'react'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Value } from '../ui/Value'
import type { ReviewTask } from '../api/types'
import styles from './TaskTable.module.css'

/** The words a priority and a state are named by, and where they come from.
 *
 * Neither map is invented here. `route()` (src/receipts/score/confidence.py)
 * returns the priority and its own name together -- `(NEEDS_REVIEW, 2, "quick
 * verify")` and `(NEEDS_REVIEW, 1, "full re-key")` -- and `queue.py`'s module
 * docstring names the third: "`0` is the urgent case -- validation errors *and*
 * a missing total". The state spellings are `ReviewState`'s wire values, which
 * are lower case (persist/models.py).
 *
 * An unrecognised priority or state is **shown, not swallowed**: `request<T>` is
 * an unchecked cast, so a value this map does not know is a real thing the
 * server sent, and hiding it would be the failure design section 4 names.
 */
const PRIORITY_WORDS: Record<number, string> = {
  0: 'Urgent',
  1: 'Full re-key',
  2: 'Quick verify',
}

const STATE_WORDS: Record<string, string> = {
  open: 'Open',
  in_progress: 'In progress',
  done: 'Done',
}

function priorityWord(priority: number): string | null {
  if (typeof priority !== 'number' || !Number.isFinite(priority)) {
    return null
  }
  return PRIORITY_WORDS[priority] ?? `Priority ${priority}`
}

function stateWord(state: string): string | null {
  if (typeof state !== 'string' || state === '') {
    return null
  }
  return STATE_WORDS[state] ?? state
}

/** How long the task has been open, against the clock the caller supplies.
 *
 * **`now` is a prop, not `Date.now()`.** An age computed from the live clock is
 * a value that changes between the render and the assertion, so it cannot be
 * pinned; injecting it makes the column a function of its inputs.
 *
 * `null` on an unparseable `opened_at`, which is the whole point: `Date.parse`
 * answers `NaN` for anything it does not recognise, and `NaN` formatted into a
 * template literal renders the string "NaN" -- a value that looks like data.
 * Returning null routes it through `ui/Value` and it takes the mark instead.
 *
 * A timestamp in the future is clamped to `0m` rather than marked. It is a clock
 * skew between the server and this browser, not a missing value, and the mark
 * carries the accessible name "not extracted" -- which would be a lie about a
 * field the server did send.
 */
function ageOf(openedAt: string, now: number): string | null {
  const opened = Date.parse(openedAt)
  if (Number.isNaN(opened)) {
    return null
  }
  const minutes = Math.max(0, Math.floor((now - opened) / 60_000))
  if (minutes < 60) {
    return `${minutes}m`
  }
  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return `${hours}h ${minutes % 60}m`
  }
  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}

/* The glyphs. Design section 6 says "SVG icons, never emoji", and names Phosphor
 * outline at `size={20}` -- which is not in the tree and may not be added, since
 * the runtime dependencies are exactly `react`, `react-dom` and the two
 * `@fontsource` packages. These are hand-drawn to the same brief: 20px box,
 * `fill="none"`, `stroke="currentColor"` so each one inherits its chip's tone,
 * and distinct silhouettes so the icon carries the distinction on its own.
 *
 * Every one of them is rendered inside `Chip`'s `aria-hidden` wrapper, so none
 * reaches the accessibility tree and none can collide with the `role="img"` the
 * null mark uses. */
function GlyphOpen() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
    </svg>
  )
}

function GlyphInProgress() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
      <path d="M10 5.25 V10 L13.25 11.75" strokeLinecap="round" />
    </svg>
  )
}

function GlyphDone() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
      <path d="M6.75 10.25 L9 12.5 L13.25 7.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** A three-bar urgency meter: more bars drawn tall, the more urgent the task.
 *
 * `filled` counts the bars raised to full height, so the glyph reads at a glance
 * without relying on the colour it is drawn in -- which is the point, since every
 * chip on this table is painted the same neutral tone. */
function GlyphPriority({ filled }: { filled: number }) {
  const bars = [
    { x: 4.5, tall: filled >= 3 },
    { x: 9.25, tall: filled >= 2 },
    { x: 14, tall: filled >= 1 },
  ]
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      {bars.map((bar) => (
        <path key={bar.x} d={`M${bar.x} 15.5 V${bar.tall ? 5.5 : 11.5}`} strokeLinecap="round" />
      ))}
    </svg>
  )
}

function stateGlyph(state: string) {
  if (state === 'done') {
    return <GlyphDone />
  }
  if (state === 'in_progress') {
    return <GlyphInProgress />
  }
  return <GlyphOpen />
}

export interface TaskTableProps {
  readonly tasks: readonly ReviewTask[]
  /** `all` for an admin, `mine` for a reviewer. Decides the empty state's words,
   *  and nothing else -- the filtering itself happened on the server. */
  readonly scope: 'all' | 'mine'
  readonly canRelease: boolean
  readonly onRelease: (taskId: string) => void
  /** The task whose release is in flight, so every control on the table locks
   *  rather than only the one that was clicked. */
  readonly busyTaskId: string | null
  readonly now: number
}

/** The review queue as a table -- design section 5.6, fed by `GET /review/tasks`.
 *
 * ## The empty state names the scope, because the endpoint does not
 *
 * `GET /review/tasks` is guarded by `require_user`, not `require_role`: an admin
 * sees every row and a reviewer sees `state == OPEN` OR
 * `assigned_to == <caller>` (ADR-0026 decision 2). The two responses have the
 * same shape, so nothing downstream can tell a genuinely empty queue from a
 * scoped-empty page -- and a bare "No tasks" over a filtered list states
 * something the server never said. `scope` is therefore a required prop rather
 * than a default: there is no honest empty state to render without it.
 *
 * ## Never colour alone
 *
 * The accessibility contract (design section 6, High severity) says severity,
 * confidence band and task state each carry an icon AND a word. So `state` and
 * `priority` are `ui/Chip`s -- a component whose *type* forbids a bare coloured
 * pill, since both the icon and the children are required props.
 *
 * **Both chips are painted `neutral` (or `positive`), never a severity tone.**
 * ADR-0027 section 2 reserves error red, warn amber and info blue outright:
 * "nothing decorative may use" them, because if a task state borrows amber then
 * a WARN finding has no colour left to mean WARN. A priority-0 row is urgent and
 * says the word "Urgent"; what it must not do is repaint the palette that the
 * findings panel two screens over depends on.
 */
export function TaskTable({
  tasks,
  scope,
  canRelease,
  onRelease,
  busyTaskId,
  now,
}: TaskTableProps) {
  /** Which row is asking for confirmation. Local to the table because it is
   *  transient view state -- the screen above owns the request, not the prompt. */
  const [confirming, setConfirming] = useState<string | null>(null)

  if (tasks.length === 0) {
    return (
      <p className={styles.empty}>
        {scope === 'all' ? 'No tasks' : 'No open tasks, and none assigned to you'}
      </p>
    )
  }

  const busy = busyTaskId !== null

  return (
    // A horizontal scroller, the shape design section 5.2 sets for the line-items
    // table: six columns must not squeeze to slivers, and the page body must
    // never scroll sideways. `.table`'s `min-width` is what gives this something
    // to scroll.
    <section className={styles.scroller} aria-label="Review tasks">
      <table className={styles.table}>
        <thead className={styles.head}>
          <tr>
            <th scope="col">Priority</th>
            <th scope="col">Reason</th>
            <th scope="col">Assigned to</th>
            <th scope="col">State</th>
            <th scope="col">Age</th>
            {canRelease ? <th scope="col">Release</th> : null}
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => {
            const holder = task.assigned_to
            const priority = priorityWord(task.priority)
            const state = stateWord(task.state)
            return (
              <tr className={styles.row} key={task.id}>
                <td>
                  {priority === null ? (
                    <Value value={null} kind="text" />
                  ) : (
                    <Chip tone="neutral" icon={<GlyphPriority filled={3 - Math.min(task.priority, 2)} />}>
                      {priority}
                    </Chip>
                  )}
                </td>
                <td className={styles.reason}>
                  <Value value={task.reason} kind="text" />
                </td>
                <td className={styles.assignee}>
                  <Value value={holder} kind="text" />
                </td>
                <td>
                  {state === null ? (
                    <Value value={null} kind="text" />
                  ) : (
                    <Chip tone={task.state === 'done' ? 'positive' : 'neutral'} icon={stateGlyph(task.state)}>
                      {state}
                    </Chip>
                  )}
                </td>
                <td className={styles.age}>
                  <Value value={ageOf(task.opened_at, now)} kind="count" align="end" />
                </td>
                {canRelease ? (
                  <td className={styles.action}>
                    {/* Nothing to release on a row nobody holds. `released_from`
                        is null on that path anyway -- the route is idempotent and
                        writes nothing -- so the control would offer a no-op. */}
                    {holder === null ? null : confirming === task.id ? (
                      <div className={styles.confirm}>
                        <p className={styles.prompt}>Return this task to the open queue?</p>
                        {/* **The holder is named in the accessible name, not in
                            the prompt.** Design section 5.6 asks the confirm to
                            name the current holder; the row's own "Assigned to"
                            cell already prints it two columns to the left, and
                            repeating it here as visible text would put the same
                            name in two elements of one table. So the name
                            travels on `aria-label`, where it reaches a screen
                            reader that cannot see the adjacent cell -- and it
                            *contains* the visible word "Release", which is what
                            WCAG 2.5.3 (Label in Name) requires.

                            **Nothing in the test suite constrains this choice,
                            and an earlier version of this comment said it did.**
                            Corrected 2026-08-07 at the milestone's close. That
                            version claimed the release round-trip in
                            `admin-screen.test.tsx` asks `getByText(/carol/)` of
                            the *confirmed row*, so naming the holder visibly
                            would throw "Found multiple elements". Measured: the
                            query is scoped to `within(table)`, not to the
                            confirm, and the assignee cell two columns left
                            already satisfies it -- so it passes whether or not
                            the confirm names anybody, and passes even if it is
                            moved above the click. A scoped query, or
                            `getAllByText(...).length === 2`, would satisfy a
                            visible name and the test at once. **The choice above
                            is a design judgement about not printing one name
                            twice in one table. It is not forced, and it should
                            not be defended as if it were.** */}
                        <Button
                          variant="danger"
                          aria-label={`Release from ${holder}`}
                          disabled={busy}
                          onClick={() => onRelease(task.id)}
                        >
                          Release
                        </Button>
                        <Button variant="secondary" disabled={busy} onClick={() => setConfirming(null)}>
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() => setConfirming(task.id)}
                      >
                        Release
                      </Button>
                    )}
                  </td>
                ) : null}
              </tr>
            )
          })}
        </tbody>
      </table>
      {canRelease ? null : (
        <p className={styles.note}>
          Only an admin can release a task, so this table shows no release control.
        </p>
      )}
    </section>
  )
}
