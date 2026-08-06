import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { fetchMetrics, fetchTasks, releaseTask } from '../api/admin'
import type { Identity, Metrics, TaskPage } from '../api/admin'
import { StatTiles } from './StatTiles'
import { TaskTable } from './TaskTable'
import styles from './AdminScreen.module.css'

/** The API's own words when it gave us any, and the caller's sentence when not.
 *
 * A `TypeError: Failed to fetch` from a server that is not up carries nothing a
 * reader can act on, while a 403's "requires role admin" is the whole answer.
 * The same split `ReviewScreen` and `LoginPage` already make. */
function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

/** The three things that can fail here, each with the label its message keeps.
 *
 * A fixed list rather than a filtered array of bare strings: two failures really
 * can carry identical text (`request failed (500)` from both routes at once),
 * and keying React's list on the message itself would then be a duplicate key.
 * The source name is unique whatever the servers say. */
const FAILURE_ORDER = ['listing', 'release', 'statistics'] as const

export interface AdminScreenProps {
  readonly identity: Identity | null
  readonly now: number
}

/** The admin surface at `/app/admin` -- design sections 5.6 and 5.7.
 *
 * ## It asks for nothing until it knows who is asking
 *
 * `identity` is `Identity | null`, and the null branch renders a wait rather
 * than an empty table. That is not defensiveness about a race: a reviewer and an
 * admin get **different rows from the same endpoint** (ADR-0026 decision 2), so
 * an identity that has not arrived means the *scope* is unknown, and an empty
 * state that cannot say which list is empty is exactly the failure design
 * section 5.6 exists to prevent. Listing first and labelling later would print
 * "No tasks" over a filtered page for as long as one round trip takes.
 *
 * `session.ts` starts `identity` at `null` for the same reason -- "not yet
 * answered", never "not an admin".
 *
 * ## `now` is a prop
 *
 * The age column is a function of the clock. Passing it in makes the table a
 * function of its inputs; reading `Date.now()` inside it would make the column a
 * race with its own assertion. `main.tsx` passes the live clock.
 *
 * ## One `role="alert"`, whatever went wrong
 *
 * ADR-0024's contract, restated by design section 5.8: **exactly one
 * `role="alert"` region on screen**. Two regions make every single-alert query
 * in the suite ambiguous -- `findByRole('alert')` matches two elements and
 * throws. Three different things can fail here (the listing, the statistics, a
 * release), so the messages are collected into one region as separate lines
 * rather than dropped or raced. Nothing is summarised away and nothing invents
 * copy: the server's own words are what render.
 *
 * ## A release updates the row from its own response
 *
 * `POST /review/{id}/release` answers with `{**_task_summary(task),
 * "released_from": ...}` -- the WHOLE updated summary, not just the field that
 * changed. So the row is replaced from what came back and the queue is not
 * listed a second time. A re-list would also be wrong rather than merely
 * wasteful: between the two calls another admin's release, or a reviewer's
 * claim, would reorder the page under the reader's cursor with no event to
 * explain it.
 *
 * A 403 is reported and **the row is left exactly as it was**. The route takes
 * `Depends(require_role(ROLE_ADMIN))` and the role is re-read per request
 * (ADR-0012), so an account demoted between `/auth/me` and the click gets 403 --
 * and a screen that blanked or dropped the row on that path would be reporting a
 * release the server refused.
 */
export function AdminScreen({ identity, now }: AdminScreenProps) {
  const [page, setPage] = useState<TaskPage | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [listFailure, setListFailure] = useState<string | null>(null)
  const [metricsFailure, setMetricsFailure] = useState<string | null>(null)
  const [releaseFailure, setReleaseFailure] = useState<string | null>(null)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setReleaseFailure(null)
    // Concurrent rather than sequential, and each with its own catch: the
    // statistics failing must not cost the operator the queue, and the queue
    // failing must not cost them the statistics. `Promise.all` over two promises
    // that have already caught cannot reject.
    const listing = fetchTasks().then(
      (next) => {
        setPage(next)
        setListFailure(null)
      },
      (caught: unknown) => {
        // The page is cleared, not kept: a stale table beside a fresh failure
        // reads as a queue that is still being shown.
        setPage(null)
        setListFailure(messageOf(caught, 'could not load the review queue'))
      },
    )
    const stats = fetchMetrics().then(
      (next) => {
        setMetrics(next)
        setMetricsFailure(null)
      },
      (caught: unknown) => {
        setMetrics(null)
        setMetricsFailure(messageOf(caught, 'could not load the queue statistics'))
      },
    )
    await Promise.all([listing, stats])
  }, [])

  /** The identity the current page was loaded for, so `StrictMode`'s second
   *  effect pass -- and every unrelated re-render -- does not list the queue
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

  async function release(taskId: string): Promise<void> {
    setBusyTaskId(taskId)
    setReleaseFailure(null)
    try {
      const released = await releaseTask(taskId)
      setPage((current) =>
        current === null
          ? current
          : { ...current, items: current.items.map((task) => (task.id === taskId ? released : task)) },
      )
    } catch (caught) {
      setReleaseFailure(messageOf(caught, 'the release did not reach the API'))
    } finally {
      setBusyTaskId(null)
    }
  }

  if (identity === null) {
    return (
      <main className={styles.screen}>
        <p className={styles.waiting}>
          Waiting for the identity that decides which tasks this page may show.
        </p>
      </main>
    )
  }

  // `role` is a `string`, not a union: `request<T>` is an unchecked cast, so a
  // union would be a claim about the server that nothing validates. Compare
  // against `'admin'` and treat everything else as the narrow branch -- showing
  // a caller too little rather than too much, which is the direction
  // `list_review_tasks` itself takes.
  const isAdmin = identity.role === 'admin'
  const bySource: Record<(typeof FAILURE_ORDER)[number], string | null> = {
    listing: listFailure,
    release: releaseFailure,
    statistics: metricsFailure,
  }
  const alerts = FAILURE_ORDER.filter((source) => bySource[source] !== null)

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Review queue</h1>
      <p className={styles.who}>
        Signed in as {identity.username} ({identity.role}).
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

      {metrics === null ? null : <StatTiles metrics={metrics} />}

      {page === null ? null : (
        <TaskTable
          tasks={page.items}
          scope={isAdmin ? 'all' : 'mine'}
          canRelease={isAdmin}
          onRelease={(taskId) => void release(taskId)}
          busyTaskId={busyTaskId}
          now={now}
        />
      )}

      {/* `has_more` comes off a `limit + 1` fetch rather than a `COUNT(*)`, so it
          says "there is at least one more row" and never how many -- which is
          why this sentence does not offer a total. Said out loud because a first
          page that looks like the whole queue is the reading an operator will
          take otherwise. It is deliberately NOT an alert: nothing failed. */}
      {page !== null && page.has_more ? (
        <p className={styles.truncated}>
          There are more tasks than this page shows.
        </p>
      ) : null}
    </main>
  )
}
