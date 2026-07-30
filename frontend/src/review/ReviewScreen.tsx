import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import {
  SubmitError,
  completeTask,
  fetchImageUrl,
  fetchNext,
  fetchReceipt,
  submitReview,
} from '../api/review'
import type { SubmitOutcome } from '../api/review'
import type { ReceiptDetail, ReviewTask } from '../api/types'
import { ConfidenceRail } from './ConfidenceRail'
import { FindingsPanel } from './FindingsPanel'
import { ImagePane } from './ImagePane'
import { LineItemsTable } from './LineItemsTable'
import { ReceiptForm } from './ReceiptForm'
import { buildPatch, fieldsFromReceipt } from './patch'
import type { FieldMap } from './patch'

/** Claim a task, load the receipt behind it, let a reviewer correct it, and
 *  close it.
 *
 * Two calls to load, not one. `GET /review/next` returns the light
 * `receipt_summary` (id, status, confidence, merchant, date, currency, total --
 * review/api.py:486-518), which carries neither line items, nor findings, nor
 * the confidence breakdown, so the full `GET /receipts/{id}` follows it. The
 * summary in the first reply is deliberately not read: rendering from it and
 * then swapping in the detail would show a reviewer two versions of the same
 * receipt.
 *
 * One state value for the load, not four independent ones. The plan kept `task`,
 * `receipt`, `empty` and `error` in separate `useState` calls, which lets
 * combinations exist that mean nothing -- "empty from the last load, error from
 * this one", or a task with no receipt -- and leaves the render order deciding
 * which of them wins. There are four states here and exactly one variable
 * holding them. `original` and `fields` live inside the `claimed` variant for
 * the same reason: neither means anything without the receipt they came from.
 *
 * **`fetchNext` is a claiming write, so this component may call it at most once
 * per task in hand.** `next_task` sets `assigned_to` and flips the row to
 * `IN_PROGRESS` (queue.py:198-199) and the route commits (api.py:517). Nothing
 * in the review API puts an `IN_PROGRESS` row back to `OPEN` -- `_claim_stmt`
 * only ever selects `state == OPEN`, and `QueueStats.by_priority` counts open
 * tasks -- so a task claimed and then abandoned leaves the queue silently and
 * does not even show up as backlog. Three guards, all measured in
 * tests/review-screen.test.tsx:
 *
 *   * `started` -- `main.tsx` renders under `<StrictMode>`, which invokes the
 *     mount effect twice. Without it the first thing the app does is claim two
 *     tasks and strand one. Re-measured for this task by deleting the guard:
 *     `claims exactly one task when React mounts the tree twice` fails with
 *     `expected 2 to be 1`.
 *   * `claimed` -- once a task is in hand, a retry resumes *that* task instead
 *     of re-entering `fetchNext`. Without it, `fetchNext` succeeding and
 *     `fetchReceipt` then failing turns every "Try again" into another claim.
 *     Re-measured by replacing the read with `null`: `resumes the task it
 *     already holds instead of claiming another` fails with
 *     `expected 2 to be 1`.
 *   * `submittedTask` -- the keyboard listener is re-registered every render and
 *     closes over that render's `phase`, so a second Ctrl+Enter can run against
 *     a closure whose task is already submitted. A plain in-flight boolean does
 *     not cover it: by the time the second key event arrives the first chain has
 *     resolved and released the flag, while the stale closure still believes it
 *     holds a claimed task. Measured twice: a boolean released in a `finally`
 *     gave `expected [ 'PATCH /receipts/a1', ... ] to have a length of 1 but got
 *     2`, and so does clearing this ref on the success path.
 *
 * A `useRef` rather than state for all three: they must be readable and writable
 * without scheduling a render, and `started` in particular has to be true before
 * the second StrictMode invocation runs -- a `setState` would not have landed by
 * then.
 *
 * **`claimed.current` is cleared the moment a task is closed**, in `approve` and
 * in `closeTaskOnly`. Without it the screen never asks for the next task at all:
 * measured by deleting the line, five of the editing tests fail, including the
 * one that pins the whole call chain down to its closing
 * `GET /review/next`, and every wait for the next state times out. It is cleared
 * after `complete` succeeds and never before -- a task whose close failed is
 * still held, which is what the "Close task" button acts on.
 */
type Phase =
  | { readonly kind: 'loading' }
  | { readonly kind: 'empty' }
  | { readonly kind: 'failed'; readonly message: string }
  | {
      readonly kind: 'claimed'
      readonly task: ReviewTask
      readonly receipt: ReceiptDetail
      /** The receipt as it was loaded. Never mutated -- it is the left-hand side
       *  of every `buildPatch`, and an "unchanged" test against a moving target
       *  would send the whole form on every approval. */
      readonly original: FieldMap
      readonly fields: FieldMap
    }

/** A submit that succeeded but has something to say first. */
type Held = Exclude<SubmitOutcome, { kind: 'clean' }>

/** The submit chain's own state, kept apart from `Phase` because a failed
 *  submission must leave the receipt and the reviewer's edits on screen, while a
 *  failed *load* has nothing to show. */
type Submit =
  | { readonly kind: 'idle' }
  | { readonly kind: 'busy' }
  | {
      readonly kind: 'failed'
      readonly message: string
      /** Non-null only when the PATCH landed and the close did not: the receipt
       *  is `reviewed` and this task is still open. */
      readonly openTaskId: string | null
    }
  /** The chain finished -- receipt saved, task closed -- but the server did not
   *  store what was sent, or the reply could not be checked. Nothing is broken
   *  and nothing can be retried; the screen simply must not advance until the
   *  reviewer has had the chance to read it. */
  | { readonly kind: 'held'; readonly outcome: Held }

/** The API's own words when it gave us any.
 *
 * A 400 from `apply_corrections` names the offending path exactly, so quoting
 * the server beats anything composed here. Measured, verbatim:
 *
 *     {'totals.grand_total': '1.00'}  -> cannot apply a correction to unknown
 *                                        field path 'totals.grand_total'
 *     {'line_items[9].qty': '1'}      -> cannot apply a correction to
 *                                        'line_items[9].qty': receipt <id> has
 *                                        no line item at position 9
 *     {'totals.total': 'abc'}         -> not a decimal amount: 'abc'
 *     {'meta.is_handwritten': 'maybe'}-> not a boolean: 'maybe'
 *     {'receipt.date': '14/07/2026'}  -> not an ISO 8601 date (YYYY-MM-DD): ...
 *     {'receipt.time': '2.30pm'}      -> not an ISO 8601 time (HH:MM): '2.30pm'
 *
 * A `TypeError: Failed to fetch` from a dev server that is not up carries
 * nothing worth quoting, and gets a sentence of its own rather than silence.
 */
function apiMessage(caught: unknown): string {
  const cause = caught instanceof SubmitError ? caught.cause : caught
  return cause instanceof ApiError ? cause.message : 'the review could not be submitted'
}

function submitFailure(caught: unknown, taskId: string): Submit {
  const message = apiMessage(caught)
  if (caught instanceof SubmitError && caught.step === 'complete') {
    return {
      kind: 'failed',
      message: `Saved, but the task is still open: ${message}`,
      openTaskId: taskId,
    }
  }
  return { kind: 'failed', message: `Not saved: ${message}`, openTaskId: null }
}

export function ReviewScreen() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  const [submit, setSubmit] = useState<Submit>({ kind: 'idle' })
  /** The task this reviewer already holds. Non-null means the queue has been
   *  charged for it and `fetchNext` must not be called again. */
  const claimed = useRef<ReviewTask | null>(null)
  /** Whether the mount effect has already run. See the StrictMode note above. */
  const started = useRef(false)
  /** The id of the task whose submit chain is in flight or has already
   *  succeeded. Cleared on failure, because a failed submission is exactly the
   *  one a reviewer should be able to run again. See the note above. */
  const submittedTask = useRef<string | null>(null)

  const load = useCallback(async () => {
    setPhase({ kind: 'loading' })
    setSubmit({ kind: 'idle' })
    try {
      let task = claimed.current
      if (task === null) {
        const next = await fetchNext()
        // `?? null` rather than `=== null`: an empty queue is `{"task": null}`
        // (review/api.py:511), but `request` is an unchecked cast, so a body that
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
      const receipt = await fetchReceipt(task.receipt_id)
      const original = fieldsFromReceipt(receipt)
      setPhase({ kind: 'claimed', task, receipt, original, fields: { ...original } })
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

  const edit = useCallback((path: string, value: string | null) => {
    setPhase((current) =>
      current.kind === 'claimed'
        ? { ...current, fields: { ...current.fields, [path]: value } }
        : current,
    )
  }, [])

  async function approve(): Promise<void> {
    if (phase.kind !== 'claimed' || submittedTask.current === phase.task.id) {
      return
    }
    const { task, receipt, original, fields } = phase
    submittedTask.current = task.id
    setSubmit({ kind: 'busy' })
    let outcome: SubmitOutcome
    try {
      outcome = await submitReview(receipt.id, task.id, buildPatch(original, fields))
    } catch (caught) {
      // Nothing was written, or only the close failed; either way this task can
      // be submitted again, so the guard is released.
      submittedTask.current = null
      setSubmit(submitFailure(caught, task.id))
      return
    }
    // The task is closed either way -- the write landed. Only the advance waits.
    claimed.current = null
    if (outcome.kind === 'clean') {
      await load()
      return
    }
    setSubmit({ kind: 'held', outcome })
  }

  /** Close a task whose receipt was already patched. Not a retry of the chain:
   *  re-sending the patch would be harmless -- measured, a PATCH whose value
   *  already matches the stored one writes no `corrections` row -- but it is not
   *  what failed, and the narrower action is the one to offer. */
  async function closeTaskOnly(taskId: string): Promise<void> {
    if (submittedTask.current === taskId) {
      return
    }
    submittedTask.current = taskId
    setSubmit({ kind: 'busy' })
    try {
      await completeTask(taskId)
    } catch (caught) {
      submittedTask.current = null
      setSubmit({
        kind: 'failed',
        message: `Saved, but the task is still open: ${apiMessage(caught)}`,
        openTaskId: taskId,
      })
      return
    }
    claimed.current = null
    await load()
  }

  // No dependency array, on purpose: `approve` closes over `phase` and is a new
  // function every render, so a listener registered once would approve with the
  // fields as they were at mount. Re-binding each render is the cost of the
  // handler always seeing what is on screen.
  //
  // Only Ctrl/Cmd+Enter is intercepted. Tab and plain Enter are left to the
  // browser: Tab order is native, and Enter moving focus on through a form must
  // not submit a half-keyed receipt.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        void approve()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

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

  const { receipt, fields } = phase
  const busy = submit.kind === 'busy'
  // Hoisted out of the JSX so the `!== null` narrowing survives into the click
  // handler's closure.
  const openTaskId = submit.kind === 'failed' ? submit.openTaskId : null
  return (
    <main>
      <h1>{receipt.merchant_name_raw ?? 'Unknown merchant'}</h1>
      {/* Keyed on the receipt id so the pane starts clean for a new receipt
          rather than carrying over a stale link, a spent retry, or a failure. */}
      <ImagePane key={receipt.id} receiptId={receipt.id} fetchUrl={fetchImageUrl} />
      <FindingsPanel findings={receipt.findings} />
      <ConfidenceRail confidence={receipt.confidence} reasons={receipt.confidence_reasons} />
      <ReceiptForm fields={fields} onChange={edit} />
      <LineItemsTable items={receipt.line_items} fields={fields} onChange={edit} />
      {submit.kind === 'failed' ? <p role="alert">{submit.message}</p> : null}
      {submit.kind === 'held' ? <StoredDifferently outcome={submit.outcome} /> : null}
      {submit.kind === 'held' ? (
        // The only way past the notice, and deliberately the only way: the
        // receipt is saved and the task is closed, so there is nothing to retry
        // and nothing to fix here -- but advancing on its own would destroy the
        // one notice a reviewer ever gets that the database does not hold what
        // they typed. So the chain runs to completion and the *advance* waits
        // for a click. Ctrl+Enter is not wired to this on purpose: the chord
        // means "approve", and a reviewer clearing a warning by reflex with the
        // same key they submit with is how the warning stops being read.
        <button type="button" onClick={() => void load()}>
          Next receipt
        </button>
      ) : (
        <button type="button" onClick={() => void approve()} disabled={busy}>
          Approve (⌘↵)
        </button>
      )}
      {openTaskId === null ? null : (
        <button type="button" onClick={() => void closeTaskOnly(openTaskId)} disabled={busy}>
          Close task
        </button>
      )}
    </main>
  )
}

/** What the server stored, where it differs from what was sent.
 *
 * `role="alert"` rather than a quiet note: it is the only signal that a
 * correction did not land as typed, and the reviewer is about to move to another
 * receipt. Both values are shown because neither alone is actionable -- "we
 * changed it" without saying to what leaves nothing to check against the paper.
 */
function StoredDifferently({ outcome }: { outcome: Held }) {
  if (outcome.kind === 'unverified') {
    return (
      <section role="alert">
        <h2>Saved, but not checked</h2>
        <p>{outcome.why}</p>
      </section>
    )
  }
  return (
    <section role="alert">
      <h2>Saved, but the server stored something different</h2>
      <ul>
        {outcome.rewrites.map((rewrite) => (
          <li key={rewrite.path}>
            <strong>{rewrite.path}</strong>: you entered{' '}
            <code>{rewrite.sent ?? '(nothing)'}</code>, the receipt now holds{' '}
            <code>{rewrite.stored ?? '(nothing)'}</code>
          </li>
        ))}
      </ul>
    </section>
  )
}
