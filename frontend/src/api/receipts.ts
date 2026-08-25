import { request, requestBlob } from './client'
import type { ReceiptSummary } from './types'

/** The fallback filename, used only when the response carries no
 *  `Content-Disposition`. Fetching a body as a blob means the browser no
 *  longer honours that header, so `download` has to be set explicitly -- and
 *  a hardcoded name here would be a second copy of the server's that can
 *  drift from it, so the header wins when present. */
const FALLBACK_FILENAME = 'receipts-export.xlsx'

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
  /** A `ReceiptStatus` value, or `undefined` for every status. */
  status?: string
  /** A decimal as a **string**, never a `number`: confidence is money-adjacent
   *  and `0.1 + 0.2` is the reason this codebase keeps decimals out of floats
   *  (ADR-0001). The route parses it into a `Decimal`. */
  minConfidence?: string
}): Promise<ExportReceiptPage> {
  const query = new URLSearchParams()
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  if (params?.offset !== undefined) query.set('offset', String(params.offset))
  // The wire names are the route's, not this signature's: `min_confidence`,
  // not `minConfidence`. FastAPI ignores an unrecognised query parameter in
  // silence, so a misspelling here returns an unfiltered page that is
  // indistinguishable from a filter that matched everything.
  //
  // A filter nobody chose is OMITTED, not sent empty. `status=` is not "no
  // status" to `ReceiptStatus | None` -- it fails validation and the page 422s.
  if (params?.status !== undefined) query.set('status', params.status)
  if (params?.minConfidence !== undefined) {
    query.set('min_confidence', params.minConfidence)
  }
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`
  return request<ExportReceiptPage>(`/export/receipts${suffix}`)
}

/** Download the workbook. **Admin-only at the route**, which is the gate:
 *  `export_xlsx` takes `Depends(require_role(ROLE_ADMIN))`, so a reviewer
 *  reaching it gets 403 `insufficient role` and this rejects with an
 *  `ApiError`. Any admin check a caller draws around the button is a courtesy
 *  on top of that, not a substitute for it -- and callers must still handle
 *  the rejection, because the role is re-read per request (ADR-0012).
 */
export async function downloadExportWorkbook(): Promise<void> {
  const { blob, filename } = await requestBlob('/export/xlsx')
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
