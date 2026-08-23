import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { ApiError } from '../api/client'
import { ACCEPTED_SUFFIXES, MAX_UPLOAD_MB, rejectionReason, uploadReceipt } from '../api/upload'
import type { ProgressReport, UploadAccepted } from '../api/upload'
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
 * `rejectionReason`'s PDF branch reads "PDFs cannot be processed yet
 * (ISSUE-027). Upload a photograph instead." The citation is right where it is
 * written -- it is the handle for why the suffix the *server* accepts is refused
 * here -- and wrong where it is read out: a tracker id is a thing a person
 * cannot look up. Measured 2026-08-24 by stripping every comment from every
 * `.ts`, `.tsx` and `.css` file under `frontend/src` and searching what is left
 * for `[A-Z]{2,}-\d+`: **one line matches**, and it is that `return`. So it is
 * removed at the last step before the DOM, and `upload.ts` is left exactly as
 * its own tests pin it.
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
  /** `ProcessingView`'s polling seam (the next task), declared here because
   *  this screen is what holds the accepted receipt and therefore what passes
   *  it down. **Nothing reads it yet** -- there is no polling on this screen
   *  until that view exists. It is on these props rather than added to them
   *  later so that a test injecting it today injects it into the component that
   *  will use it, and no test has to move when the view arrives. */
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
 * trusted: `accept` filters the picker's default view and a person can switch it
 * to "all files", and a drag-and-drop ignores it outright, so a `.pdf` really
 * does arrive here. `rejectionReason` is what refuses it.
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
 *
 * The element below is a placeholder that the next task replaces with
 * `ProcessingView` -- it names the receipt so that the hand-off is visible and
 * so that "the chooser went away and something took its place" is testable
 * today rather than on the day the view lands.
 */
export function UploadScreen({ upload = uploadReceipt }: UploadScreenProps) {
  const [error, setError] = useState<string | null>(null)
  const [accepted, setAccepted] = useState<Accepted | null>(null)
  const [sending, setSending] = useState(false)

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
      <main className={styles.screen}>
        <h1 className={styles.heading}>Processing</h1>
        <p className={styles.placeholder}>
          {accepted.fileName} is with the pipeline as {accepted.receipt.receipt_id}.
        </p>
      </main>
    )
  }

  return (
    <main className={styles.screen}>
      <h1 className={styles.heading}>Upload a receipt</h1>
      {/* What this page does, said in what it does TODAY. The narration of each
          stage arrives with `ProcessingView`; promising it here first would be
          this screen making a claim the next task has to come true. */}
      <p className={styles.scope}>
        One photograph at a time. It is stored and queued straight away, and this page stays with
        it -- there is nothing to reload and nowhere to come back to.
      </p>

      {/* Always rendered when there is an error, and absent when there is not
          (ADR-0024). Never emptied to a blank region: an alert with no text is
          announced as an alert and says nothing. */}
      {error === null ? null : (
        <p className={styles.alert} role="alert">
          {error}
        </p>
      )}

      <label className={styles.field}>
        <span className={styles.label}>Receipt photograph</span>
        <input
          className={styles.input}
          type="file"
          accept={ACCEPTED_SUFFIXES.join(',')}
          disabled={sending}
          onChange={onChosen}
        />
      </label>

      {/* Both facts come from the module that enforces them, so the sentence
          cannot outlive what it describes. `.pdf` is absent from the list for
          the reason `ACCEPTED_SUFFIXES` records, and the refusal says the rest
          when somebody chooses one anyway. */}
      <p className={styles.limits}>
        {ACCEPTED_SUFFIXES.join(', ')} -- up to {MAX_UPLOAD_MB} MB.
      </p>

      {sending ? <p className={styles.sending}>Sending the photograph.</p> : null}
    </main>
  )
}
