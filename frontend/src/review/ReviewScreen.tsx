import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { fetchImageUrl, fetchNext, fetchReceipt } from '../api/review'
import type { ReceiptDetail, ReviewTask } from '../api/types'
import { ConfidenceRail } from './ConfidenceRail'
import { FindingsPanel } from './FindingsPanel'
import { ImagePane } from './ImagePane'

/** Claim a task, load the receipt behind it, and show it.
 *
 * Two calls, not one. `GET /review/next` returns the light `receipt_summary`
 * (id, status, confidence, merchant, date, currency, total -- review/api.py
 * :486-507), which carries neither line items, nor findings, nor the confidence
 * breakdown, so the full `GET /receipts/{id}` follows it. The summary in the
 * first reply is deliberately not read: rendering from it and then swapping in
 * the detail would show a reviewer two versions of the same receipt.
 *
 * One state value, not four independent ones. The plan kept `task`, `receipt`,
 * `empty` and `error` in separate `useState` calls, which lets combinations
 * exist that mean nothing -- "empty from the last load, error from this one",
 * or a task with no receipt -- and leaves the render order deciding which of
 * them wins. There are four states here and exactly one variable holding them.
 *
 * **`fetchNext` is a claiming write, so this component may call it at most once
 * per task in hand.** `next_task` sets `assigned_to` and flips the row to
 * `IN_PROGRESS` (queue.py:198-199) and the route commits (api.py:506). Nothing
 * in the review API puts an `IN_PROGRESS` row back to `OPEN` -- `_claim_stmt`
 * only ever selects `state == OPEN`, and `QueueStats.by_priority` counts open
 * tasks -- so a task claimed and then abandoned leaves the queue silently and
 * does not even show up as backlog. Two guards, both measured in
 * tests/review-screen.test.tsx:
 *
 *   * `started` -- `main.tsx` renders under `<StrictMode>`, which invokes the
 *     mount effect twice. Without it the first thing the app does is claim two
 *     tasks and strand one (measured: 2 calls to `/review/next`, 1 with the
 *     guard).
 *   * `claimed` -- once a task is in hand, a retry resumes *that* task instead
 *     of re-entering `fetchNext`. Without it, `fetchNext` succeeding and
 *     `fetchReceipt` then failing turns every "Try again" into another claim
 *     (measured: 2 calls to `/review/next`, 1 with the guard).
 *
 * A `useRef` rather than state for both: they must be readable and writable
 * without scheduling a render, and `started` in particular has to be true
 * before the second StrictMode invocation runs -- a `setState` would not have
 * landed by then.
 *
 * Whoever adds "complete and move on" (Task 5) must clear `claimed.current`, or
 * the screen will keep re-loading the task it already finished.
 */
type Phase =
  | { readonly kind: 'loading' }
  | { readonly kind: 'empty' }
  | { readonly kind: 'failed'; readonly message: string }
  | { readonly kind: 'claimed'; readonly task: ReviewTask; readonly receipt: ReceiptDetail }

export function ReviewScreen() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  /** The task this reviewer already holds. Non-null means the queue has been
   *  charged for it and `fetchNext` must not be called again. */
  const claimed = useRef<ReviewTask | null>(null)
  /** Whether the mount effect has already run. See the StrictMode note above. */
  const started = useRef(false)

  const load = useCallback(async () => {
    setPhase({ kind: 'loading' })
    try {
      let task = claimed.current
      if (task === null) {
        const next = await fetchNext()
        // `?? null` rather than `=== null`: an empty queue is `{"task": null}`
        // (review/api.py:500), but `request` is an unchecked cast, so a body that
        // omits the key must take the same branch instead of reaching
        // `task.receipt_id` and throwing.
        task = next?.task ?? null
        claimed.current = task
        if (task === null) {
          // Nothing was claimed, so asking the queue again later is free.
          setPhase({ kind: 'empty' })
          return
        }
      }
      setPhase({ kind: 'claimed', task, receipt: await fetchReceipt(task.receipt_id) })
    } catch (caught) {
      // The API's own words when it gave us any, matching `LoginPage`: a 503 from
      // the database handler or a 403 from the queue is worth reading, while a
      // `TypeError: Failed to fetch` from a dev server that is not up is not.
      setPhase({
        kind: 'failed',
        message: caught instanceof ApiError ? caught.message : 'could not load the review queue',
      })
    }
  }, [])

  useEffect(() => {
    if (started.current) {
      return
    }
    started.current = true
    void load()
  }, [load])

  if (phase.kind === 'failed') {
    return (
      <main>
        <p role="alert">{phase.message}</p>
        <button type="button" onClick={() => void load()}>
          Try again
        </button>
      </main>
    )
  }
  if (phase.kind === 'empty') {
    return (
      <main>
        <p>The review queue is empty.</p>
        <button type="button" onClick={() => void load()}>
          Check again
        </button>
      </main>
    )
  }
  if (phase.kind === 'loading') {
    return (
      <main>
        <p>Loading…</p>
      </main>
    )
  }

  const { receipt } = phase
  return (
    <main>
      <h1>{receipt.merchant_name_raw ?? 'Unknown merchant'}</h1>
      {/* Keyed on the receipt id so the pane starts clean for a new receipt
          rather than carrying over a stale link, a spent retry, or a failure. */}
      <ImagePane key={receipt.id} receiptId={receipt.id} fetchUrl={fetchImageUrl} />
      <FindingsPanel findings={receipt.findings} />
      <ConfidenceRail confidence={receipt.confidence} reasons={receipt.confidence_reasons} />
    </main>
  )
}
