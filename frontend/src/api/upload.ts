import { request } from './client'

/** The suffixes `validate_upload` accepts, minus the one that cannot work.
 *
 * `.pdf` is deliberately ABSENT. The server accepts it -- it is in
 * `_ALLOWED_SUFFIXES` -- and then every PDF dies at `preprocess`, because
 * `expand_pdf` has no caller and `load_image` refuses the suffix (ISSUE-027).
 * Refusing here is stricter than the server on purpose: accepting a file that
 * is guaranteed to fail is the worst of the available behaviours.
 */
export const ACCEPTED_SUFFIXES: readonly string[] = [
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.heic',
  '.heif',
]

/** `settings.max_upload_mb`'s default. The server is the authority; this is a
 *  courtesy check so an oversized file does not cost an upload first. */
export const MAX_UPLOAD_MB = 25

export interface UploadAccepted {
  receipt_id: string
  image_key: string
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
  if (suffix === '.pdf') {
    return 'PDFs cannot be processed yet (ISSUE-027). Upload a photograph instead.'
  }
  if (!ACCEPTED_SUFFIXES.includes(suffix)) {
    return `Accepted types are ${ACCEPTED_SUFFIXES.join(', ')}.`
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `Larger than the ${MAX_UPLOAD_MB} MB limit.`
  }
  return null
}

/** Store one receipt and queue it. One file per request: the route takes one. */
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
  return request<ProgressReport>(`/receipts/${receiptId}/progress`)
}
