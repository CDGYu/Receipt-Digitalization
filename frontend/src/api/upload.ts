import { request } from './client'

/** Exactly the suffixes `validate_upload` accepts.
 *
 * **`.pdf` is present again as of ISSUE-027's fix.** It used to be deliberately
 * absent: the server accepted a PDF and then every one of them died at
 * `preprocess`, because `expand_pdf` had no caller. Ingest now rasterises a PDF
 * into one receipt per page, so accepting one here is no longer accepting a file
 * that is guaranteed to fail. `upload-api.test.ts` pins this list against the
 * server's own `_ALLOWED_SUFFIXES`, parsed out of the Python source, so the two
 * cannot drift apart in either direction.
 */
export const ACCEPTED_SUFFIXES: readonly string[] = [
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.pdf',
  '.heic',
  '.heif',
]

/** `settings.max_upload_mb`'s default. The server is the authority; this is a
 *  courtesy check so an oversized file does not cost an upload first.
 *
 *  **A one-way gap, disclosed rather than closed.** This is a literal; the
 *  server reads `settings.max_upload_mb` (`config/settings.py`), which a
 *  deployment can override. Lowering the server's bound is harmless -- the file
 *  is sent, the server refuses it, and `uploadReceipt` surfaces the server's own
 *  reason. **Raising it is not**: this constant then refuses a file the server
 *  would have accepted, which is what the design's decision 7 is named for --
 *  "the client mirrors the server's bounds but never overrules them".
 *  `upload-api.test.ts` pins this against the literal `25`, so
 *  a change on THIS side reddens and a change on the server's side does not.
 *
 *  Closing it needs the bound to arrive from the server -- a field on a config
 *  route, or on the upload route's own error -- which is a decision, not a
 *  tidy-up. Until then the gap is here in writing. */
export const MAX_UPLOAD_MB = 25

/** One receipt the server minted from an upload. */
export interface AcceptedReceipt {
  receipt_id: string
  image_key: string
}

/** What `POST /upload` answers.
 *
 * **A list, because one upload is not always one receipt.** A photograph is one;
 * a PDF is one per page (ISSUE-027). It stayed a scalar for as long as PDFs
 * could not work, and a scalar naming only the first page would hide the rest --
 * which is the silent drop this system forbids, so the shape carries all of
 * them and the screen shows that it did.
 */
export interface UploadAccepted {
  receipts: readonly AcceptedReceipt[]
  status: string
}

export interface ProgressReport {
  status: string | null
  stage: string | null
  detail: string | null
}

/** Why this file will not be sent, or `null` if it will.
 *
 * **A courtesy, never an authority.** This reads a filename; the server sniffs
 * magic bytes. When they disagree the server is right, and `uploadReceipt`
 * surfaces the server's own message rather than a guess made here.
 */
export function rejectionReason(file: { name: string; size: number }): string | null {
  const dot = file.name.lastIndexOf('.')
  const suffix = dot === -1 ? '' : file.name.slice(dot).toLowerCase()
  if (!ACCEPTED_SUFFIXES.includes(suffix)) {
    return `Accepted types are ${ACCEPTED_SUFFIXES.join(', ')}.`
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `Larger than the ${MAX_UPLOAD_MB} MB limit.`
  }
  return null
}

/** Store one file and queue what it becomes. One file per request.
 *
 * One *file*, not one receipt: a PDF comes back as one accepted receipt per
 * page. */
export function uploadReceipt(file: File): Promise<UploadAccepted> {
  const body = new FormData()
  body.append('file', file)
  // No `Content-Type` header: `mergeHeaders` skips its JSON default for a
  // FormData body precisely so the browser can set the multipart boundary.
  return request<UploadAccepted>('/upload', { method: 'POST', body })
}

/** What this receipt is doing, if anything is narrating it.
 *
 * `status` is the truth and `stage` is narration: a caller decides the work is
 * finished from `status`, never from `stage` going quiet. A dead worker stops
 * writing progress, and a screen waiting for a terminal *stage* waits forever.
 */
export function fetchProgress(receiptId: string): Promise<ProgressReport> {
  return request<ProgressReport>(`/receipts/${encodeURIComponent(receiptId)}/progress`)
}
