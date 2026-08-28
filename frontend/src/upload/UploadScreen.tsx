import { useRef, useState } from 'react'
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

/** One receipt the pipeline is now following, and the name to call it by.
 *
 * The file name is held because the server does not send it back and the
 * processing view shows it: a person watching a pipeline work wants to see
 * which of their photographs is in it, not a `receipt_id` they have never seen
 * before.
 *
 * **One entry per RECEIPT, not per file.** A photograph is one receipt; a PDF is
 * one per page (ISSUE-027), so an upload of one file can append several of these
 * -- each with its own id and its own poller -- and the page name carries the
 * page number when it does. `key` is the receipt id, which is unique across the
 * whole session, so React never confuses two rows and two pollers never share
 * state. */
interface Followed {
  readonly receiptId: string
  /** What the processing view calls it: the file name, plus `(page N)` when the
   *  file became more than one receipt. */
  readonly label: string
}

export interface UploadScreenProps {
  /** Injected so tests never touch `fetch`; the same seam `create_app`'s
   *  `submit` uses on the server. Defaults to the real call. */
  readonly upload?: (file: File) => Promise<UploadAccepted>
  /** Handed straight to each `ProcessingView`, which is what asks with it. Left
   *  `undefined` -- as `main.tsx` leaves it -- the view falls back to
   *  `fetchProgress`.
   *
   *  `ProcessingView` also takes a `poll` seam, and that one is deliberately NOT
   *  forwarded: nothing on this screen polls. A test that needs to drive ticks
   *  renders `ProcessingView`, which is where the ticks are. */
  readonly progress?: (receiptId: string) => Promise<ProgressReport>
}

/** The upload screen at `/app/upload` -- where receipts enter the system.
 *
 * ## Many files, and the chooser never leaves
 *
 * A reviewer with a stack of receipts hands them over in a batch and comes back
 * when the queue has worked through them. So the chooser accepts **several files
 * at once** (`multiple`, and a drop reads every file it carries), and it stays
 * on screen after each upload rather than being replaced -- every accepted
 * receipt is appended to a list below it, each following its own progress, and a
 * person can keep adding while the earlier ones process. This is the change from
 * the first version, which took one file and swapped the whole screen for a
 * single receipt's processing view: a batch could not be queued without
 * navigating back and forth, which is the friction this removes.
 *
 * Uploads run concurrently and independently -- one file's failure refuses that
 * file and no other -- so `sending` is a COUNT of in-flight uploads, not a
 * boolean lock. There is no single-file lockout any more: the whole point is to
 * accept the next file while the last is still going.
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
 * There is **one** `role="alert"` region (ADR-0024) holding the most recent
 * refusal. Choosing more files clears it: a message about files the person has
 * already moved past reads as a refusal of the ones they are now adding.
 *
 * ## The `accept` attribute is a picker hint, not a gate
 *
 * It is derived from `ACCEPTED_SUFFIXES` rather than retyped, so the list the
 * picker offers cannot drift from the list the screen enforces. It is not
 * trusted: `accept` filters the picker's default view, a person can switch it to
 * "all files", and **a drop ignores it outright** -- so a file `accept` would
 * have hidden really does arrive here, and `rejectionReason` is what refuses it.
 *
 * ## The drop target is the label, and `preventDefault` is the feature
 *
 * The handlers sit on the `<label>` that already wraps the input, so the thing a
 * person aims at and the thing that accepts a drop are one element.
 *
 * **`onDragOver` must call `preventDefault`, and that is not cosmetic:** a
 * browser's default for a dragged file is to navigate to it, replacing the page
 * with the raw image, and the drop handler never runs at all.
 *
 * A drop goes through **the same `offer`** the picker uses. A second
 * accept-then-upload path is how a refusal ends up enforced on one route and not
 * the other -- and since `accept` does not apply to a drop at all, the drop is
 * the route where `rejectionReason` matters most.
 */
/** The chooser card's classes: the drag state, or not.
 *
 * `sending` no longer dims the card -- uploads are concurrent and the chooser
 * stays live for the next file while earlier ones are still in flight, so a
 * busy/disabled state would be lying about what the card will accept. The
 * in-flight count is shown as a line under the chooser instead.
 */
function fieldClass(dragging: boolean): string {
  return [styles.field, dragging ? styles.dragging : null].filter((name) => name !== null).join(' ')
}

/** Turn one accepted upload into the rows to append: one per receipt it became.
 *
 * A photograph is a single receipt and a single row; a PDF is one per page, and
 * the label carries the page number so two rows from `invoice.pdf` are told
 * apart. */
function followedFrom(accepted: UploadAccepted, fileName: string): Followed[] {
  const many = accepted.receipts.length > 1
  return accepted.receipts.map((receipt, index) => ({
    receiptId: receipt.receipt_id,
    label: many ? `${fileName} (page ${index + 1})` : fileName,
  }))
}

export function UploadScreen({ upload = uploadReceipt, progress }: UploadScreenProps) {
  const [error, setError] = useState<string | null>(null)
  const [followed, setFollowed] = useState<readonly Followed[]>([])
  const [sending, setSending] = useState(0)
  const [dragging, setDragging] = useState(false)
  /** The chooser's input, so "Upload another" can return focus to it and open
   *  the picker without a second control. */
  const inputRef = useRef<HTMLInputElement | null>(null)

  /** Upload one file and append whatever receipts it becomes.
   *
   * Each file is refused or sent on its own, so one bad file in a multi-select
   * does not stop the others. A refusal replaces the alert; a success appends
   * rows. `sending` is bumped around the request so the in-flight line reflects
   * however many are going at once. */
  async function offerOne(file: File): Promise<void> {
    const refusal = rejectionReason(file)
    if (refusal !== null) {
      setError(withoutTracker(refusal))
      return
    }
    setSending((n) => n + 1)
    try {
      const accepted = await upload(file)
      setFollowed((current) => [...current, ...followedFrom(accepted, file.name)])
    } catch (caught) {
      setError(messageOf(caught, 'the upload did not reach the API'))
    } finally {
      setSending((n) => n - 1)
    }
  }

  /** Take everything a picker or a drop delivered. Clears the previous refusal
   *  first -- one gesture, one fresh verdict -- then offers each file. */
  function offer(files: readonly File[]): void {
    if (files.length === 0) {
      return
    }
    setError(null)
    for (const file of files) {
      void offerOne(file)
    }
  }

  /** **`preventDefault` here is not styling — it is the whole feature.**
   *
   *  A browser's default for a dragged file is to navigate to it: without this
   *  the page is replaced by the raw image and `onDropped` never runs.
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
    // Every file the drop carries, not just the first: a person can drag a whole
    // selection onto the card. `accept` does not apply to a drop, so each file
    // still goes through `offer` -> `rejectionReason`.
    const files = Array.from(event.dataTransfer.files)
    if (files.length === 0) {
      // A drag carrying text, not files. Nothing to refuse -- silence is right.
      return
    }
    offer(files)
  }

  function onChosen(event: ChangeEvent<HTMLInputElement>): void {
    const files = Array.from(event.target.files ?? [])
    // The control is cleared before anything is done with the files. A picker
    // that is cancelled sends no `change` at all, and re-choosing the SAME file
    // after a refusal sends none either while the value still holds it -- which
    // would strand a person who fixed the file and picked it again.
    event.target.value = ''
    offer(files)
  }

  /** Return focus to the chooser and open the picker. Wired to the "Upload
   *  another" button beside the receipt list, so following up a batch does not
   *  mean hunting for the card. */
  function uploadAnother(): void {
    inputRef.current?.focus()
    inputRef.current?.click()
  }

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Upload receipts</h1>
      <p className={styles.scope}>
        Drop or choose one or more files — a photograph, or a PDF that becomes one receipt per
        page. Each is stored and queued straight away, and this page keeps a list of everything you
        add, so you can hand over a batch and come back when the queue has worked through it.
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
        className={fieldClass(dragging)}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDropped}
      >
        {/* Decorative: the two lines under it say everything this says, so a
            screen reader that announced it would hear the same fact twice. */}
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
        {/* The gesture, named. The word "receipt" is load-bearing twice over: it
            is what a person is holding, and it is what `getByLabelText(/receipt/i)`
            finds the control by -- this text IS the input's accessible name. */}
        <span className={styles.prompt}>Drag receipts here</span>
        <span className={styles.secondary}>
          or <span className={styles.cta}>Choose files</span>
        </span>
        <input
          ref={inputRef}
          className={styles.input}
          type="file"
          accept={ACCEPTED_SUFFIXES.join(',')}
          multiple
          onChange={onChosen}
        />
      </label>

      {/* Both facts come from the module that enforces them, so the sentence
          cannot outlive what it describes. */}
      <p className={styles.limits}>
        {ACCEPTED_SUFFIXES.join(', ')} — up to {MAX_UPLOAD_MB} MB each.
      </p>

      {sending > 0 ? (
        <p className={styles.sending}>
          {/* The sentence carries the message; the spinner carries the fact that
              it is still true. `aria-hidden` so a screen reader hears it once. */}
          <span className={styles.spinner} aria-hidden="true" />
          {sending === 1 ? 'Sending 1 file.' : `Sending ${sending} files.`}
        </p>
      ) : null}

      {/* The list of receipts this session has handed over, each following its
          own progress. Absent until there is one (ADR-0024). */}
      {followed.length === 0 ? null : (
        <section className={styles.queued}>
          <div className={styles.queuedHead}>
            <h2 className={styles.queuedHeading}>
              {followed.length === 1 ? '1 receipt queued' : `${followed.length} receipts queued`}
            </h2>
            {/* The follow-up affordance the batch flow needs: add more without
                hunting for the card above. It opens the same chooser. */}
            <button type="button" className={styles.another} onClick={uploadAnother}>
              Upload another
            </button>
          </div>
          <ol className={styles.queuedList}>
            {followed.map((item) => (
              <li className={styles.queuedItem} key={item.receiptId}>
                <ProcessingView
                  receiptId={item.receiptId}
                  fileName={item.label}
                  progress={progress}
                />
              </li>
            ))}
          </ol>
          {/* One exit for the whole batch. `ProcessingView` still offers its own
              per-receipt link; this is the batch-level way straight to the queue
              a reviewer heads for once they have handed everything over. A plain
              href for the reason ProcessingView's own link records. */}
          <a className={styles.review} href="/app/review">
            Open the review queue
          </a>
        </section>
      )}
    </main>
  )
}
