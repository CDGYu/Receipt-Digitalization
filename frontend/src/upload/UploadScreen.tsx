import { useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { ApiError } from '../api/client'
import { ACCEPTED_SUFFIXES, MAX_UPLOAD_MB, rejectionReason, uploadReceipt } from '../api/upload'
import type { ProgressReport, UploadAccepted } from '../api/upload'
import { ProcessingView } from './ProcessingView'
import styles from './UploadScreen.module.css'

/** The API's own words when it gave us any, and the caller's sentence when not.
 *
 * A `TypeError: Failed to fetch` from a server that is not up carries nothing a
 * reader can act on, while a 415's "not a receipt image: image/gif" is the whole
 * answer. The same split `AdminScreen`, `ReviewScreen`, `ReceiptsScreen` and
 * `LoginPage` already make. */
function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

/** This client's own refusal, with an internal tracker citation taken out of it.
 *
 * **No refusal carries a citation today, and this stays anyway.** The one that
 * did was `rejectionReason`'s PDF branch -- "PDFs cannot be processed yet
 * (ISSUE-027). Upload a photograph instead." -- and ISSUE-027's fix deleted the
 * branch along with the refusal, because ingest now expands a PDF into one
 * receipt per page. The reasoning it recorded is what survives: a citation is
 * right where it is written, and wrong where it is read out, because a tracker
 * id is a thing a person cannot look up. So the scrub runs at the last step
 * before the DOM and `upload.ts` is left exactly as its own tests pin it.
 *
 * Retiring the guard with the instance that prompted it is how a class of defect
 * comes back. What keeps this honest is that it defends against the *next*
 * citation somebody writes into a refusal, not the one that used to be here.
 *
 * **Only this module's own copy goes through here.** A message from the server
 * is rendered untouched: the client shows the server's own words for anything
 * the server rejected, and a scrub applied there would be the client editing
 * them.
 *
 * The pattern is deliberately narrow -- a parenthesised `ISSUE-n` or `ADR-n`,
 * the two shapes this repository writes -- so it cannot eat real copy. The
 * *property* is the wide one, and it lives in `tests/upload-screen.test.tsx`:
 * nothing matching `[A-Z]{2,}-\d+` reaches the alert region, for any file
 * `rejectionReason` refuses. A citation in a third shape fails there rather than
 * slipping past a defence that only knows two.
 */
function withoutTracker(reason: string): string {
  return reason.replace(/\s*\((?:ISSUE|ADR)-\d+\)/g, '')
}

/** One receipt the server took, and the name of the file it came from.
 *
 * The file name is held because the server does not send it back and the
 * processing view shows it: a person watching a pipeline work wants to see
 * which of their photographs is in it, not a `receipt_id` they have never seen
 * before. */
interface Accepted {
  readonly receipt: UploadAccepted
  readonly fileName: string
}

export interface UploadScreenProps {
  /** Injected so tests never touch `fetch`; the same seam `create_app`'s
   *  `submit` uses on the server. Defaults to the real call. */
  readonly upload?: (file: File) => Promise<UploadAccepted>
  /** Handed straight to `ProcessingView`, which is what asks with it. It is on
   *  these props because this screen is what holds the accepted receipt and
   *  therefore what mounts the view. Left `undefined` -- as `main.tsx` leaves it
   *  -- the view falls back to `fetchProgress`.
   *
   *  `ProcessingView` also takes a `poll` seam, and that one is deliberately NOT
   *  forwarded: nothing on this screen polls. An unread prop is what `progress`
   *  itself was until this task, and threading a second one through here would
   *  be the same seam-that-is-not-a-seam again. A test that needs to drive ticks
   *  renders `ProcessingView`, which is where the ticks are. */
  readonly progress?: (receiptId: string) => Promise<ProgressReport>
}

/** The upload screen at `/app/upload` -- where a receipt enters the system.
 *
 * ## Two refusals, and only one of them is ours
 *
 * `rejectionReason` reads a filename and a size. It is a **courtesy**: it stops
 * a file that cannot possibly work from costing an upload first. The server
 * sniffs magic bytes, and when the two disagree the server is right -- so a
 * failure that came back from `POST /upload` is rendered in the server's own
 * words, never re-worded here. A client that guessed would tell a reader
 * something the server never said.
 *
 * They cannot both be on screen at once, and that is by construction rather
 * than by luck: choosing a file is what produces either one, and it clears
 * whatever the previous choice produced. A message about a file the person has
 * already replaced reads as a refusal of the file they are now looking at, which
 * is worse than no message. So there is **one** `role="alert"` region holding
 * **one** string (ADR-0024), and no ordering to get wrong.
 *
 * ## The `accept` attribute is a picker hint, not a gate
 *
 * It is derived from `ACCEPTED_SUFFIXES` rather than retyped, so the list the
 * picker offers cannot drift from the list the screen enforces. It is not
 * trusted: `accept` filters the picker's default view, a person can switch it to
 * "all files", and **a drop ignores it outright** -- so a file `accept` would
 * have hidden really does arrive here, and `rejectionReason` is what refuses it.
 *
 * *(This paragraph used to end "so a `.pdf` really does arrive here" and named
 * the PDF as the thing refused. `55f9847` -- ISSUE-027, the same day -- added
 * `.pdf` to `ACCEPTED_SUFFIXES` because ingest now expands one into a receipt
 * per page, so the example became the opposite of true while the sentence
 * around it stayed right. The claim is now about `accept` rather than about a
 * suffix, which is the part that does not move.)*
 *
 * ## The drop target is the label, and `preventDefault` is the feature
 *
 * P5.T2's drag-and-drop. The handlers sit on the `<label>` that already wraps
 * the input, so the thing a person aims at and the thing that accepts a drop are
 * one element rather than two that can drift apart.
 *
 * **`onDragOver` must call `preventDefault`, and that is not cosmetic:** a
 * browser's default for a dragged file is to navigate to it, replacing the page
 * with the raw image, and the drop handler never runs at all. The symptom is
 * "drag-and-drop does nothing", which points at the drop handler rather than at
 * the missing line, so it has its own test.
 *
 * A drop goes through **the same `offer`** the picker uses. A second
 * accept-then-upload path is how a refusal ends up enforced on one route and not
 * the other -- and since `accept` does not apply to a drop at all, the drop is
 * the route where `rejectionReason` matters most.
 *
 * ## One receipt, and then this screen becomes the other one
 *
 * `accepted` is a single nullable value rather than a list. The input is gone
 * the moment there is something to watch, so a second file cannot be chosen and
 * a list could never hold two -- and a length-two branch nothing can reach is a
 * screen nobody will ever see, which this project has shipped green before.
 *
 * When it is set, the processing view replaces the chooser **in place**: same
 * route, no navigation, no document load. The beat where a person hands over a
 * receipt and the page goes blank is the one thing this design exists to
 * remove.
 */
/** What the processing view should call the receipt it is following.
 *
 * For a photograph that is the file the person chose. For a PDF it is the file
 * plus which page, because "invoice.pdf" would name three receipts at once and
 * the view follows one.
 */
function pageNameFor(accepted: Accepted): string {
  return accepted.receipt.receipts.length === 1
    ? accepted.fileName
    : `${accepted.fileName} (page 1)`
}

/** The chooser card's classes: the drag state, the in-flight state, or neither.
 *
 * Written as a function rather than a nested ternary in the JSX because the two
 * states are independent and a reader has to be able to see that they compose.
 * They can genuinely coincide -- a drag entered while an upload is in flight
 * sets `dragging` and leaves `sending` set -- and in that case the card must
 * read as busy, because `onDropped` returns early and will discard the file.
 *
 * **The order of the names in this string decides nothing**, and saying it does
 * is the mistake this sentence replaced. CSS precedence is source order in the
 * stylesheet and specificity; the order of tokens in a `class` attribute has
 * never entered into it. The two states compose here because `.busy` and
 * `.dragging` set disjoint properties -- opacity and cursor against border and
 * background -- not because one of them is written second.
 */
function fieldClass(dragging: boolean, sending: boolean): string {
  return [styles.field, dragging ? styles.dragging : null, sending ? styles.busy : null]
    .filter((name) => name !== null)
    .join(' ')
}

export function UploadScreen({ upload = uploadReceipt, progress }: UploadScreenProps) {
  const [error, setError] = useState<string | null>(null)
  const [accepted, setAccepted] = useState<Accepted | null>(null)
  const [sending, setSending] = useState(false)
  const [dragging, setDragging] = useState(false)

  async function offer(file: File): Promise<void> {
    const refusal = rejectionReason(file)
    if (refusal !== null) {
      setError(withoutTracker(refusal))
      return
    }
    setError(null)
    setSending(true)
    try {
      setAccepted({ receipt: await upload(file), fileName: file.name })
    } catch (caught) {
      setError(messageOf(caught, 'the upload did not reach the API'))
    } finally {
      setSending(false)
    }
  }

  /** **`preventDefault` here is not styling — it is the whole feature.**
   *
   *  A browser's default for a dragged file is to navigate to it: without this
   *  the page is replaced by the raw image and `onDropped` never runs. The
   *  failure then reads as "drag-and-drop does nothing", which is why it is
   *  pinned by its own test rather than left to the drop test to imply.
   */
  function onDragOver(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault()
    setDragging(true)
  }

  function onDragLeave(): void {
    setDragging(false)
  }

  function onDropped(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault()
    setDragging(false)
    // The input carries `disabled` while sending; a drop target has no such
    // attribute, so the guard lives here or a second file overtakes the first.
    if (sending) {
      return
    }
    const file = event.dataTransfer.files[0]
    if (file === undefined) {
      // A drag carrying text, not files. `dataTransfer.files` is empty and
      // there is nothing to refuse -- silence is right, because nothing was
      // offered.
      return
    }
    // **The same `offer` the picker uses.** `accept` filters the picker's
    // default view and a drop ignores it outright, so this path MUST go
    // through `rejectionReason` -- a second accept-then-upload path is how a
    // refusal ends up enforced on one route and not the other.
    void offer(file)
  }

  function onChosen(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0]
    // The control is cleared before anything is done with the file. A picker
    // that is cancelled sends no `change` at all, and re-choosing the SAME file
    // after a refusal sends none either while the value still holds it -- which
    // would strand a person who fixed the file and picked it again.
    event.target.value = ''
    if (file === undefined) {
      return
    }
    void offer(file)
  }

  if (accepted !== null) {
    return (
      <ProcessingView
        receiptId={accepted.receipt.receipts[0].receipt_id}
        fileName={pageNameFor(accepted)}
        alsoQueued={accepted.receipt.receipts.length - 1}
        progress={progress}
      />
    )
  }

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Upload a receipt</h1>
      {/* What this page does, said in what it does TODAY. The narration of each
          stage arrives with `ProcessingView`; promising it here first would be
          this screen making a claim the next task has to come true. */}
      {/* Em dashes, not `--`. The pair rendered literally in the browser as two
          hyphens, which is the one typographic tell a display face cannot
          cover; the prose is unchanged. */}
      <p className={styles.scope}>
        One file at a time — a photograph, or a PDF that becomes one receipt per page. It is
        stored and queued straight away, and this page stays with it — there is nothing to
        reload and nowhere to come back to.
      </p>

      {/* Always rendered when there is an error, and absent when there is not
          (ADR-0024). Never emptied to a blank region: an alert with no text is
          announced as an alert and says nothing. */}
      {error === null ? null : (
        <p className={styles.alert} role="alert">
          {error}
        </p>
      )}

      <label
        className={fieldClass(dragging, sending)}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDropped}
      >
        {/* Decorative: the two lines under it say everything this says, so a
            screen reader that announced it would hear the same fact twice.
            `currentColor` and no fill, so it tracks the card's foreground
            through the drag state instead of being repainted for it. */}
        <svg
          className={styles.icon}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M12 16V4" />
          <path d="m7 9 5-5 5 5" />
          <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
        </svg>
        {/* The gesture, named. P5.T2 shipped the drop handlers and this line
            said "Receipt photograph", so the only way to discover a drop was to
            try one. The word "receipt" is load-bearing twice over: it is what a
            person is holding, and it is what `getByLabelText(/receipt/i)` finds
            the control by -- this text IS the input's accessible name. */}
        <span className={styles.prompt}>Drag a receipt here</span>
        <span className={styles.secondary}>
          or <span className={styles.cta}>Choose a file</span>
        </span>
        <input
          className={styles.input}
          type="file"
          accept={ACCEPTED_SUFFIXES.join(',')}
          disabled={sending}
          onChange={onChosen}
        />
      </label>

      {/* Both facts come from the module that enforces them, so the sentence
          cannot outlive what it describes -- which is exactly what saved it:
          `.pdf` joined `ACCEPTED_SUFFIXES` at `55f9847` (ISSUE-027) and this
          line started listing it the same day, with nothing to edit. The
          comment that sat here said `.pdf` was absent and did NOT self-update;
          it has been corrected. */}
      <p className={styles.limits}>
        {ACCEPTED_SUFFIXES.join(', ')} — up to {MAX_UPLOAD_MB} MB.
      </p>

      {sending ? (
        <p className={styles.sending}>
          {/* The sentence carries the message; the spinner carries the fact that
              it is still true. `aria-hidden` so a screen reader hears it once,
              from the words, and `prefers-reduced-motion` stops it moving. */}
          <span className={styles.spinner} aria-hidden="true" />
          Sending the photograph.
        </p>
      ) : null}
    </main>
  )
}
