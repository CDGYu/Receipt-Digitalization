import { request, requestBlob } from './client'
import type { ReceiptSummary } from './types'

/** The fallback filename, used only when the response carries no
 *  `Content-Disposition`. Fetching a body as a blob means the browser no
 *  longer honours that header, so `download` has to be set explicitly -- and
 *  a hardcoded name here would be a second copy of the server's that can
 *  drift from it, so the header wins when present. */
const FALLBACK_FILENAME = 'receipts-export.xlsx'

interface ExportFilters {
  /** A `ReceiptStatus` value, or `undefined` for every status. */
  status?: string
  /** A decimal as a **string**, never a `number`: confidence is money-adjacent
   *  and `0.1 + 0.2` is the reason this codebase keeps decimals out of floats
   *  (ADR-0001). The route parses it into a `Decimal`. */
  minConfidence?: string
}

function exportQuery(params?: ExportFilters & { limit?: number; offset?: number }): string {
  const query = new URLSearchParams()
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  // The wire names are the route's, not this signature's: `min_confidence`,
  // not `minConfidence`. FastAPI ignores an unrecognised query parameter in
  // silence, so a misspelling here returns an unfiltered page/workbook that is
  // indistinguishable from a filter that matched everything.
  //
  // A filter nobody chose is OMITTED, not sent empty. `status=` is not "no
  // status" to `ReceiptStatus | None` -- it fails validation.
  if (params?.status !== undefined) query.set('status', params.status)
  if (params?.minConfidence !== undefined) {
    query.set('min_confidence', params.minConfidence)
  }
  return query.toString()
}

export interface ExportReceiptPage {
  items: ReceiptSummary[]
  has_more: boolean
}

/** One page of the receipts the export would contain.
 *
 *  Not `GET /receipts`: that route applies no status exclusion, so a list
 *  built on it shows rows the workbook omits.
 */
export function fetchExportReceipts(params?: {
  limit?: number
  offset?: number
} & ExportFilters): Promise<ExportReceiptPage> {
  const rendered = exportQuery(params)
  const suffix = rendered === '' ? '' : `?${rendered}`
  return request<ExportReceiptPage>(`/export/receipts${suffix}`)
}

function exportWorkbookPath(params?: ExportFilters): string {
  const rendered = exportQuery(params)
  return rendered === '' ? '/export/xlsx' : `/export/xlsx?${rendered}`
}

/** Download the workbook. **Admin-only at the route**, which is the gate:
 *  `export_xlsx` takes `Depends(require_role(ROLE_ADMIN))`, so a reviewer
 *  reaching it gets 403 `insufficient role` and this rejects with an
 *  `ApiError`. Any admin check a caller draws around the button is a courtesy
 *  on top of that, not a substitute for it -- and callers must still handle
 *  the rejection, because the role is re-read per request (ADR-0012).
 *
 *  The filters mirror `fetchExportReceipts`: the screen previews the same
 *  scope it downloads, and the server archives exactly the receipts the
 *  workbook contained.
 */
export async function downloadExportWorkbook(params?: ExportFilters): Promise<void> {
  const { blob, filename } = await requestBlob(exportWorkbookPath(params))
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename ?? FALLBACK_FILENAME
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

export interface ReceiptPage {
  items: ReceiptSummary[]
  has_more: boolean
}

/** One page of `GET /receipts`.
 *
 *  The plain list, deliberately, and NOT `fetchExportReceipts`: the export
 *  route applies a status exclusion so its page omits rows the review queue
 *  cares about. Here the caller wants whatever the queue points at, so the
 *  exclusion would silently drop columns for exactly the receipts under
 *  review.
 *
 *  `require_user` at the route, not `require_role` -- a reviewer may call this,
 *  which is what makes it usable as the display half of the review queue.
 */
export function fetchReceipts(params?: {
  limit?: number
  offset?: number
  /** A `ReceiptStatus` value, or `undefined` for every status. */
  status?: string
}): Promise<ReceiptPage> {
  const query = new URLSearchParams()
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  if (params?.status !== undefined) query.set('status', params.status)
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`
  return request<ReceiptPage>(`/receipts${suffix}`)
}
