import { ApiError, request } from './client'
import type { ReceiptDetail, ReviewNextResponse } from './types'

/** Claim the next review task for the signed-in reviewer.
 *
 * `{"task": null}` on an empty queue is **200 with a body**, not 204
 * (review/api.py:496-500), so there is one shape to parse and no empty-body
 * special case -- see `ReviewNextResponse` for what each of its two nulls means.
 *
 * Not idempotent: `next_task` assigns the task to the caller and commits
 * (review/api.py:497-506). Calling this twice claims two tasks.
 */
export function fetchNext(): Promise<ReviewNextResponse> {
  return request('/review/next')
}

/** The full receipt: `totals`, `line_items`, `findings`, and the confidence
 *  breakdown that `receipt_summary` leaves out.
 *
 *  `id` is encoded even though every id this app holds came from the API as a
 *  UUID: the parameter's type is `string`, and the route parses it as
 *  `uuid.UUID` (review/api.py:202), so anything that is not one is a 422 rather
 *  than a path this function helped build.
 */
export function fetchReceipt(id: string): Promise<ReceiptDetail> {
  return request(`/receipts/${encodeURIComponent(id)}`)
}

/** A freshly signed, expiring link to the receipt image.
 *
 * Two separate URLs are involved and only the first one belongs here.
 * `GET /receipts/{id}/image` returns the JSON envelope `{"url": "..."}` whose
 * value is a **relative** link to `GET /receipts/{id}/image/blob`
 * (review/api.py:427-429). The blob is bytes, and `request` always parses its
 * body as JSON, so the blob must never go through it -- it belongs in an
 * `<img src>`. That link is root-relative, so it resolves against the origin
 * and is unaffected by the SPA's `/app/` base.
 *
 * The link is signed for `image_url_ttl_s` (config/settings.py:131, default
 * 300s), which is why `ImagePane` can need a second call to this function for
 * the same receipt.
 *
 * The `undefined` in the response type is not defensive noise: `request`
 * resolves an empty body to `undefined` rather than throwing, so without this
 * check a body-less 200 would surface as `TypeError: Cannot read properties of
 * undefined` instead of a message a caller can put on screen.
 */
export async function fetchImageUrl(id: string): Promise<string> {
  const body = await request<{ url: string } | undefined>(
    `/receipts/${encodeURIComponent(id)}/image`,
  )
  if (body === undefined || typeof body.url !== 'string') {
    throw new ApiError(200, `no image link in the reply for receipt ${id}`)
  }
  return body.url
}
