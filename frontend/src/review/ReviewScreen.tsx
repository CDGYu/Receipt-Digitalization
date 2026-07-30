import { useCallback, useEffect, useState } from 'react'
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
 */
type Phase =
  | { readonly kind: 'loading' }
  | { readonly kind: 'empty' }
  | { readonly kind: 'failed'; readonly message: string }
  | { readonly kind: 'claimed'; readonly task: ReviewTask; readonly receipt: ReceiptDetail }

export function ReviewScreen() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })

  const loadNext = useCallback(async () => {
    setPhase({ kind: 'loading' })
    try {
      const next = await fetchNext()
      // `?? null` rather than `=== null`: an empty queue is `{"task": null}`
      // (review/api.py:500), but `request` is an unchecked cast, so a body that
      // omits the key must take the same branch instead of reaching
      // `task.receipt_id` and throwing.
      const task = next?.task ?? null
      if (task === null) {
        setPhase({ kind: 'empty' })
        return
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
    void loadNext()
  }, [loadNext])

  if (phase.kind === 'failed') {
    return (
      <main>
        <p role="alert">{phase.message}</p>
        <button type="button" onClick={() => void loadNext()}>
          Try again
        </button>
      </main>
    )
  }
  if (phase.kind === 'empty') {
    return (
      <main>
        <p>The review queue is empty.</p>
        <button type="button" onClick={() => void loadNext()}>
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
