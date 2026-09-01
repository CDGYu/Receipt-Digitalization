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
import { ImagePane } from './ImagePane'
import { LineItemsTable } from './LineItemsTable'
import { ReceiptForm } from './ReceiptForm'
import { classifyFailure } from './failure'
import type { Failure } from './failure'
import { buildPatch, fieldsFromReceipt } from './patch'
import type { FieldMap } from './patch'
import { TaxBands } from './TaxBands'
import { clear as clearStash, remember, restore } from './stash'
import styles from './ReviewScreen.module.css'

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
 * `IN_PROGRESS` (see `queue.py`'s `next_task`) and the route commits. Nothing
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
 *     `expected 2 to be 1`. A receipt that fails *every* time would then leave
 *     the reviewer with no way forward at all, which is what `skipHeldTask`
 *     exists for -- see its own note.
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
 * **`claimed.current` is cleared the moment a task is closed**, in `approve`,
 * in `closeTaskOnly` and in `skipHeldTask` -- the three places a `complete`
 * succeeds. Without it the screen never asks for the next task at all:
 * measured by deleting the line, five of the editing tests fail, including the
 * one that pins the whole call chain down to its closing
 * `GET /review/next`, and every wait for the next state times out. It is cleared
 * after `complete` succeeds and never before -- a task whose close failed is
 * still held, which is what the "Close task" button acts on.
 */
type Phase =
  | { readonly kind: 'loading' }
  | { readonly kind: 'empty' }
  | {
      readonly kind: 'failed'
      readonly message: string
      /** The task this reviewer is holding while the load fails, or `null` when
       *  the queue call itself failed and nothing was claimed. Carried in the
       *  phase rather than read from `claimed.current` at render time: a ref
       *  read during render is a value React did not schedule the render for,
       *  and the escape below is offered on the strength of it. */
      readonly heldTask: ReviewTask | null
      /** What kind of failure this is -- backend-down suppresses the Skip
       *  escape, because Skip's own completeTask needs the same database. */
      readonly failure: Failure
    }
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
      readonly failure: Failure
    }
  /** The chain's close was refused in a way no retry can fix: the task was
   *  taken over (403) or deleted (404). The PATCH landed -- the state says
   *  what survived -- and the only exit is an explicit advance. No
   *  auto-advance, for the same measured muscle-memory reason as
   *  `StoredDifferently`; `submittedTask` stays set so the chord is dead. */
  | { readonly kind: 'lost'; readonly flavor: 'taken' | 'gone'; readonly message: string }
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

function submitFailure(caught: unknown, taskId: string, sentPatch: FieldMap): Submit {
  const cause = caught instanceof SubmitError ? caught.cause : caught
  const step = caught instanceof SubmitError ? caught.step : null
  const failure = classifyFailure(cause, {
    // Only the patch step sends a patch, so only its 400 can belong to a field.
    sentPatch: step === 'patch' ? sentPatch : undefined,
    fallback: 'the review could not be submitted',
  })
  if (step === 'complete' && (failure.kind === 'taken' || failure.kind === 'gone')) {
    return { kind: 'lost', flavor: failure.kind, message: failure.message }
  }
  const message = apiMessage(caught)
  if (step === 'complete') {
    return {
      kind: 'failed',
      message: `Saved, but the task is still open: ${message}`,
      openTaskId: taskId,
      failure,
    }
  }
  return { kind: 'failed', message: `Not saved: ${message}`, openTaskId: null, failure }
}

export function ReviewScreen() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  const [submit, setSubmit] = useState<Submit>({ kind: 'idle' })
  const [activeLineItemPosition, setActiveLineItemPosition] = useState<number | null>(null)
  /** The dotted path of the header field the reviewer is editing, or `null`.
   *  Drives the header-field highlight on the photo, the receipt-level twin of
   *  `activeLineItemPosition`. */
  const [activeFieldPath, setActiveFieldPath] = useState<string | null>(null)
  /** The task this reviewer already holds. Non-null means the queue has been
   *  charged for it and `fetchNext` must not be called again. */
  const claimed = useRef<ReviewTask | null>(null)
  /** Whether the mount effect has already run. See the StrictMode note above. */
  const started = useRef(false)
  /** The id of the task whose submit chain is in flight or has already
   *  succeeded. Cleared on failure, because a failed submission is exactly the
   *  one a reviewer should be able to run again. See the note above. */
  const submittedTask = useRef<string | null>(null)
  /** The outcome region, when one is on screen. See the focus effect below. */
  const outcomeRef = useRef<HTMLElement | null>(null)

  const load = useCallback(async () => {
    setPhase({ kind: 'loading' })
    setSubmit({ kind: 'idle' })
    setActiveLineItemPosition(null)
    setActiveFieldPath(null)
    try {
      let task = claimed.current
      if (task === null) {
        const next = await fetchNext()
        // `?? null` rather than `=== null`: an empty queue is `{"task": null}`
        // (see `GET /review/next` in review/api.py), but `request` is an
        // unchecked cast, so a body that
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
      // The edits a 401 unmounted, if this is the task they belonged to --
      // ADR-0016 hands the same task back after re-login, and the overlay
      // holds only dirty entries, so untouched paths always show the stored
      // value (design §4.1).
      const overlay = restore(task.id)
      const fields = overlay === null ? { ...original } : { ...original, ...overlay }
      setPhase({ kind: 'claimed', task, receipt, original, fields })
    } catch (caught) {
      // The API's own words when it gave us any, matching `LoginPage`: a 503 from
      // the database handler or a 403 from the queue is worth reading, while a
      // `TypeError: Failed to fetch` from a dev server that is not up is not.
      const failure = classifyFailure(caught, { fallback: 'could not load the review queue' })
      setPhase({
        kind: 'failed',
        message: caught instanceof ApiError ? caught.message : 'could not load the review queue',
        heldTask: claimed.current,
        failure,
      })
    }
  }, [])

  /** Give up on the receipt behind a failed load, so the queue can move on.
   *
   * **Closing the held task, not clearing `claimed.current`.** Clearing the ref
   * and polling again looks like the smaller change and does nothing at all:
   * ADR-0016 makes `GET /review/next` *resume* the caller's own `IN_PROGRESS`
   * task before it draws from the queue, so every poll hands back the same
   * receipt. That is the ADR working as designed -- a reviewer who reloads gets
   * the receipt they were part-way through -- and it is what turned "one
   * receipt is stranded" into "one reviewer is stranded". `POST
   * /review/{task_id}/complete` is the only call in the review API that takes
   * an `IN_PROGRESS` row out of the caller's hands; nothing releases one back
   * to `OPEN`.
   *
   * What that costs, stated plainly because the button spends it: the task is
   * closed over a receipt nobody reviewed, and the receipt keeps
   * `needs_review`. It is still the better end state of the two available --
   * `close_task` writes `DONE`, and `DONE` is the one state `enqueue_review`
   * reopens (`queue.py`'s reopen branch), while the `IN_PROGRESS` row this
   * replaces is the one state nothing in the codebase can recover.
   *
   * Design §5 asks for "surface, re-fetch `next`" on a receipt that will not
   * load. Re-fetching alone stopped meaning anything when ADR-0016 landed; this
   * is that row implemented against the queue as it now behaves -- release
   * first, then re-fetch -- rather than dropped.
   */
  async function skipHeldTask(task: ReviewTask): Promise<void> {
    // Straight to `loading`, which unmounts the button: a second click cannot
    // reach a task that is already being closed, without a flag to release.
    setPhase({ kind: 'loading' })
    try {
      await completeTask(task.id)
    } catch (caught) {
      const failure = classifyFailure(caught, { fallback: 'the request did not reach the API' })
      if (failure.kind === 'gone' || failure.kind === 'taken') {
        // The task is not this reviewer's to release any more -- it was
        // deleted, or an admin moved it. Nothing is held; move on.
        claimed.current = null
        clearStash()
        await load()
        return
      }
      setPhase({
        kind: 'failed',
        message: `could not release this receipt: ${failure.message}`,
        // Still held, so the escape stays on screen. Silence here would leave a
        // reviewer believing they had moved on from a task that is still theirs.
        heldTask: task,
        failure,
      })
      return
    }
    claimed.current = null
    // This task is closed, so the edits that belonged to it are moot.
    clearStash()
    await load()
  }

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

  // Mirror the dirty diff into the stash on every committed change. Runs
  // after render, so it sees the fields React actually kept; idempotent, so
  // StrictMode's double-invocation is harmless.
  //
  // Not once this task's chain is over. `submittedTask.current === task.id` is
  // exactly that: the ref is set when the chain starts and cleared again on
  // every retryable failure, so edits a reviewer can still resubmit do stash,
  // while the states that keep it armed -- a closed task held on
  // `StoredDifferently`, or a `lost` one -- do not. Both leave the form mounted
  // and editable, and an overlay kept for either is unrestorable: ADR-0016
  // resumes only the caller's `IN_PROGRESS` row, and these tasks are done or
  // gone. It is not free to keep, because `hasDirtyEdits` is the sign-out gate
  // (design §4.2) -- a stash re-armed here demands confirmation for edits that
  // confirming cannot recover. The narrow cost: keystrokes landed while the
  // chain is in flight are not mirrored until the next one after it fails,
  // which re-mirrors the whole dirty diff rather than an increment.
  useEffect(() => {
    if (phase.kind === 'claimed' && submittedTask.current !== phase.task.id) {
      remember(phase.task.id, buildPatch(phase.original, phase.fields))
    }
  }, [phase])

  async function approve(): Promise<void> {
    if (phase.kind !== 'claimed' || submittedTask.current === phase.task.id) {
      return
    }
    const { task, receipt, original, fields } = phase
    // Hoisted so the send and the classification see the identical object: a
    // field match reads the paths that actually went up, not a second diff.
    const sentPatch = buildPatch(original, fields)
    submittedTask.current = task.id
    setSubmit({ kind: 'busy' })
    let outcome: SubmitOutcome
    try {
      outcome = await submitReview(receipt.id, task.id, sentPatch)
    } catch (caught) {
      const next = submitFailure(caught, task.id, sentPatch)
      // A lost task cannot be resubmitted -- the guard stays armed and the
      // only exit is the explicit advance. Every other failure is retryable:
      // nothing was written, or only the close failed, and either way this
      // task can be submitted again.
      if (next.kind === 'lost') {
        // And the edits are already in the database: `lost` is reachable only
        // from the `complete` step, so the PATCH landed. ADR-0016 cannot hand
        // this task back to restore an overlay onto -- it resumes only the
        // caller's own `IN_PROGRESS` row, and this one is taken or gone -- so
        // what is stashed is unrestorable, not merely stale. Design §4.1's
        // rule is that the stash is cleared wherever the write landed, and
        // this is such a place: keeping it holds `hasDirtyEdits` true, and
        // that is the sign-out gate (design §4.2), so Sign out would demand
        // confirmation for edits that confirming cannot recover.
        clearStash()
      } else {
        submittedTask.current = null
      }
      setSubmit(next)
      return
    }
    // The task is closed either way -- the write landed. Only the advance waits.
    claimed.current = null
    // The edits are on the receipt now; nothing is left to restore.
    clearStash()
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
      // No `sentPatch`: this call carries no patch at all, so a 400 here cannot
      // belong to a field.
      const failure = classifyFailure(caught, { fallback: 'the review could not be submitted' })
      if (failure.kind === 'taken' || failure.kind === 'gone') {
        // The same dead end the chain's own close reaches, arrived at by the
        // narrower button: the guard stays armed and the only exit is the
        // advance. The patch landed before this button was ever offered, so
        // the stash goes for the reason `approve`'s catch records.
        clearStash()
        setSubmit({ kind: 'lost', flavor: failure.kind, message: failure.message })
        return
      }
      submittedTask.current = null
      setSubmit({
        kind: 'failed',
        message: `Saved, but the task is still open: ${apiMessage(caught)}`,
        openTaskId: taskId,
        failure,
      })
      return
    }
    claimed.current = null
    // The patch had already landed; closing the task ends this receipt.
    clearStash()
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

  /** I5: the outcome renders at the end of a long document -- measured at
   *  y=1195, below the fold at 900, 800 and even 1080 -- and the Ctrl/Cmd+Enter
   *  chord is a `window` listener, so it fires while the reviewer is typing at
   *  the top of the form. Without this the reviewer's screen is identical
   *  before and after a 403, which is the case where the write landed and the
   *  task is gone.
   *
   *  Focus, not `scrollIntoView`: the browser scrolls a focused element into
   *  view by itself, and `scrollIntoView` is `undefined` in jsdom, so a scroll
   *  call would break every rendering test that reached this path.
   *
   *  Keyed on `submit.kind` so a resubmit that fails again (failed -> busy ->
   *  failed) moves focus a second time. An outcome the reviewer has already
   *  been shown is not the same as one they have not. */
  useEffect(() => {
    outcomeRef.current?.focus()
  }, [submit.kind])

  if (phase.kind === 'failed') {
    const held = phase.heldTask
    const backendDown = phase.failure.kind === 'backend-down'
    return (
      <main className={`${styles.notice} ${styles.noticeFailed}`}>
        {/* Deliberately NOT a second `role="alert"`. The server's own words
            below already carry the role and announce beside this sentence, and
            a second alert in the same region makes every single-alert query in
            the suite ambiguous: `findByRole('alert')` then matches two elements
            and throws, so pre-existing tests break on it. User ruling, dated in
            the design doc (§6.1). The sentence is pinned by its text, and the
            absence of the role is asserted outright at both render sites -- by
            text alone the ruling held only by the code agreeing with itself. */}
        {backendDown ? (
          <p className={styles.explanation}>
            Your assigned tasks are unaffected — this is a server problem, not a change to your
            queue.
          </p>
        ) : null}
        <p className={styles.alert} role="alert">
          {phase.message}
        </p>
        <button type="button" className={styles.action} onClick={() => void load()}>
          Try again
        </button>
        {held === null || backendDown ? null : (
          <>
            <button
              type="button"
              className={styles.action}
              onClick={() => void skipHeldTask(held)}
            >
              Skip this receipt
            </button>
            <p className={styles.hint}>
              Closes this receipt&rsquo;s review task without reviewing it, and moves on.
            </p>
          </>
        )}
      </main>
    )
  }
  if (phase.kind === 'empty') {
    return (
      <main className={styles.notice}>
        <p className={styles.message}>The review queue is empty.</p>
        <button type="button" className={styles.action} onClick={() => void load()}>
          Check again
        </button>
      </main>
    )
  }
  if (phase.kind === 'loading') {
    return (
      <main className={styles.notice}>
        <p className={styles.message}>Loading…</p>
      </main>
    )
  }

  const { receipt, fields } = phase
  const busy = submit.kind === 'busy'
  // Hoisted out of the JSX so the `!== null` narrowing survives into the click
  // handler's closure.
  const openTaskId = submit.kind === 'failed' ? submit.openTaskId : null
  // At most one entry, ever, and not necessarily the one a reviewer would pick.
  // `apply_corrections` iterates `sorted(flatten(patch).items())` and raises on
  // the first failure, so the 400 boundary refuses one field at a time and
  // chooses it by **sort order**. Measured: a patch carrying both
  // `totals.total: 'abc'` and `receipt.currency: 'EUROS'` comes back naming
  // `receipt.currency`, because that path sorts first -- not the field the
  // reviewer edited first, and not the one highest on the form. So this screen
  // cannot show every invalid field at once; a reviewer with two bad values
  // learns about the second only after fixing the first and submitting again.
  // Serial discovery across retries is the honest behaviour, not a partial
  // rendering of something richer that is available elsewhere.
  const fieldErrors =
    submit.kind === 'failed' && submit.failure.kind === 'field'
      ? { [submit.failure.path]: submit.failure.message }
      : undefined
  /** The region exists when the reviewer has something to be told. Written as
   *  the *complement* of the two pending states rather than as a list of the
   *  three resolved ones, deliberately: a state added later defaults into the
   *  region and gets focus.
   *
   *  That guarantees the region, not its contents. The three conditionals
   *  inside it are still an enumeration, so a sixth state renders an empty box
   *  that takes focus -- and an outcome its author renders as a sibling of
   *  this region is caught by nothing (measured: a role-less sibling leaves
   *  the suite green). Reduced, not removed; ADR-0041 decision 1. */
  const hasOutcome = submit.kind !== 'idle' && submit.kind !== 'busy'
  const lineItemBoxes = receipt.line_items.map((item) => ({
    position: item.position,
    bbox: item.bbox,
  }))
  return (
    <main className={styles.screen}>
      <h1>{receipt.merchant_name_raw ?? 'Unknown merchant'}</h1>
      {/* Keyed on the receipt id so the pane starts clean for a new receipt
          rather than carrying over a stale link, a spent retry, or a failure. */}
      <ImagePane
        key={receipt.id}
        receiptId={receipt.id}
        fetchUrl={fetchImageUrl}
        lineItemBoxes={lineItemBoxes}
        activeLineItemPosition={activeLineItemPosition}
        fieldBoxes={receipt.field_boxes}
        activeFieldPath={activeFieldPath}
      />
      <ConfidenceRail confidence={receipt.confidence} reasons={receipt.confidence_reasons} />
      <ReceiptForm
        fields={fields}
        onChange={edit}
        errors={fieldErrors}
        onActiveFieldPathChange={setActiveFieldPath}
      />
      <LineItemsTable
        items={receipt.line_items}
        fields={fields}
        onChange={edit}
        errors={fieldErrors}
        activePosition={activeLineItemPosition}
        onActivePositionChange={setActiveLineItemPosition}
      />
      {/* Beneath the items, which is where the summary block sits on the paper.
          `receipt.totals.tax_breakdown` is the list the API sent; `fields`
          carries the editable values under `totals.tax_breakdown[i].*`, so the
          two are read from one render and cannot disagree about how many bands
          there are. */}
      <TaxBands
        bands={receipt.totals.tax_breakdown}
        fields={fields}
        onChange={edit}
        errors={fieldErrors}
      />
      {hasOutcome ? (
        // A <section>, never a <div>: `.screen > div` is the image pane's
        // positional selector and a new div child would become sticky.
        // No `role`: ADR-0024 decision 4 forbids a second alert here.
        <section ref={outcomeRef} tabIndex={-1} className={styles.outcome}>
          {/* Plain, not a second alert, for the reason the failed phase records.
              Suppressed once `openTaskId` is set: that state is reached only
              from the `complete` step, so `apply_corrections` already
              committed, and the edits are in the database and not only on the
              page. Unsuppressed, a 503 on the close renders "Your edits are
              still on this page and have not been discarded." directly above
              "Saved, but the task is still open: database unavailable" --
              speaking for the reviewer's work as though the page were the only
              place it survived. `openTaskId !== null` *is* "the write landed",
              which is why it is the test. */}
          {submit.kind === 'failed' &&
          submit.failure.kind === 'backend-down' &&
          openTaskId === null ? (
            <p className={styles.explanation}>
              Your edits are still on this page and have not been discarded.
            </p>
          ) : null}
          {submit.kind === 'failed' ? (
            <p className={styles.alert} role="alert">
              {submit.message}
            </p>
          ) : null}
          {submit.kind === 'lost' ? (
            <section className={styles.terminal} role="alert">
              <h2 className={styles.terminalHeading}>
                {submit.flavor === 'taken'
                  ? 'Saved, but this task was taken over by someone else'
                  : 'Saved, but this task no longer exists'}
              </h2>
              <p className={styles.message}>{submit.message}</p>
              <button
                type="button"
                className={styles.action}
                onClick={() => {
                  claimed.current = null
                  clearStash()
                  void load()
                }}
              >
                Next receipt
              </button>
            </section>
          ) : submit.kind === 'held' ? (
            // `Next receipt` lives **inside** the notice, not in the Approve
            // slot. Two buttons alternating in one slot are the same DOM node to
            // React, so the relabel used to happen under the reviewer's finger:
            // measured, after clicking Approve,
            // `document.activeElement.textContent` was `"Next receipt"`, it was
            // the identical node (`focused === approve`), and a bare Enter
            // advanced the queue (1 -> 2 calls to /review/next). One keystroke
            // of muscle memory dismissed the warning unread, which is the whole
            // thing this state exists to prevent. The two are now in different
            // parents by construction rather than by this ternary: Approve is a
            // sibling of this region and renders after it, both `Next receipt`
            // buttons render inside it, and they are different children of
            // `.screen` -- so the Approve node unmounts instead of being reused,
            // and focus has nowhere to carry over to.
            <StoredDifferently outcome={submit.outcome} onAcknowledge={() => void load()} />
          ) : null}
        </section>
      ) : null}
      {submit.kind === 'lost' || submit.kind === 'held' ? null : (
        <button
          type="button"
          className={`${styles.action} ${styles.primary}`}
          onClick={() => void approve()}
          disabled={busy}
        >
          Approve
        </button>
      )}
      {openTaskId === null ? null : (
        <button
          type="button"
          className={styles.action}
          onClick={() => void closeTaskOnly(openTaskId)}
          disabled={busy}
        >
          Close task
        </button>
      )}
    </main>
  )
}

/** What the server stored, where it differs from what was sent, and the only way
 *  past it.
 *
 * `role="alert"` rather than a quiet note: it is the only signal that a
 * correction did not land as typed, and the reviewer is about to move to another
 * receipt. Both values are shown because neither alone is actionable -- "we
 * changed it" without saying to what leaves nothing to check against the paper.
 *
 * The acknowledgement is rendered here, beside what it acknowledges, for two
 * reasons: it is where the reviewer is already looking, and it cannot be the same
 * DOM node React just relabelled from `Approve` (see the call site).
 *
 * The receipt is saved and the task is closed by the time this renders, so there
 * is nothing to retry and nothing to fix -- only an advance to authorise.
 * Ctrl+Enter is deliberately not wired to it: the chord means "approve", and
 * letting it also clear a warning is how a reviewer clears the warning by reflex
 * with the same key they submit with.
 */
function StoredDifferently({
  outcome,
  onAcknowledge,
}: {
  outcome: Held
  onAcknowledge: () => void
}) {
  return (
    <section className={styles.terminal} role="alert">
      {outcome.kind === 'unverified' ? (
        <>
          <h2 className={styles.terminalHeading}>Saved, but not checked</h2>
          <p className={styles.message}>{outcome.why}</p>
        </>
      ) : (
        <>
          <h2 className={styles.terminalHeading}>
            Saved, but the server stored something different
          </h2>
          <ul className={styles.rewrites}>
            {outcome.rewrites.map((rewrite) => (
              <li key={rewrite.path}>
                <strong>{rewrite.path}</strong>: you entered{' '}
                <code>{rewrite.sent ?? '(nothing)'}</code>, the receipt now holds{' '}
                <code>{rewrite.stored ?? '(nothing)'}</code>
              </li>
            ))}
          </ul>
        </>
      )}
      <button type="button" className={styles.action} onClick={onAcknowledge}>
        Next receipt
      </button>
    </section>
  )
}
