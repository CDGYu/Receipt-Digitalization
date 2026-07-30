import { ApiError, request } from './client'
import type { ReceiptDetail, ReviewNextResponse } from './types'
import type { FieldMap } from '../review/patch'

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

/** Which half of `PATCH` -> `complete` failed. */
export type SubmitStep = 'patch' | 'complete'

/** A failed submission, tagged with the step that failed.
 *
 * The distinction is the whole point: a failed patch wrote nothing and can be
 * retried as-is, while a failed complete means `apply_corrections` already
 * committed -- it sets `receipt.status = REVIEWED` and commits inside its own
 * transaction (persist/repository.py:1060-1061) -- with the queue task still
 * open. The screen must not advance on the second, and must say what survived.
 *
 * `step` and `cause` are declared as fields and assigned in the body rather than
 * written as constructor parameter properties, for the same reason `ApiError`
 * is: `tsconfig.app.json` sets `erasableSyntaxOnly: true`, under which the
 * parameter-property form is
 * `error TS1294: This syntax is not allowed when 'erasableSyntaxOnly' is
 * enabled` -- two of them, one per property. (No line:column here on purpose:
 * they point into this very file, so editing this comment would move them and
 * make the citation a lie. The exact positions are in the task report, measured
 * against the file as it shipped.)
 *
 * **Vitest does not catch this at all.** Measured by rewriting only this class
 * in the parameter-property form and changing nothing else:
 *
 *     $ npx vitest run tests/submit-chain.test.ts   -> 10 passed (10),  exit 0
 *     $ npx vitest run                              -> 125 passed (125), exit 0
 *     $ npm run typecheck                           -> TS1294 x2,       exit 2
 *
 * Not "most tests pass" and not one failure in ten -- the whole suite, all
 * fifteen files, is green while the build is broken, because esbuild strips the
 * syntax happily and `npm test` never type-checks. Nothing in the runner can
 * tell you about this class of defect; only `npm run typecheck` can.
 */
export class SubmitError extends Error {
  readonly step: SubmitStep
  readonly cause: unknown

  constructor(step: SubmitStep, cause: unknown) {
    super(`review submit failed at ${step}`)
    this.step = step
    this.cause = cause
    this.name = 'SubmitError'
  }
}

/** Apply a reviewer's edits. **The reply is the new state.**
 *
 * The route returns `receipt_detail(receipt, findings)` for the row it just
 * committed (review/api.py:392-398), so a follow-up `GET /receipts/{id}` would
 * be a second round trip for data already in hand.
 *
 * `patch` is sent flat. Measured: `CorrectionPatch.model_validate({'totals.total':
 * '1000.00', 'receipt.time': None, 'line_items[0].qty': '9.9'})
 * .model_dump(exclude_unset=True, mode='json')` returns those three keys
 * unchanged, so a dotted top-level key bypasses the typed sub-models and reaches
 * `apply_corrections` as written. What that buys is the error currency: also
 * measured, an unmapped path comes back as `cannot apply a correction to unknown
 * field path 'totals.grand_total'`, which names the field. Not measured here:
 * what shape a `RequestValidationError` on this route would take instead --
 * see `ApiErrorBody` in client.ts, which covers both.
 *
 * `request` is an unchecked cast, so the `ReceiptDetail` here is a claim about
 * the route, not a validation of the body.
 */
export function patchReceipt(id: string, patch: FieldMap): Promise<ReceiptDetail> {
  return request(`/receipts/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

/** Close a review task. **`taskId` is a review task id, not a receipt id.**
 *
 * `POST /review/{task_id}/complete` looks the id up in `review_tasks`
 * (review/api.py:520-547) and answers 403 unless the caller is the assignee or
 * an admin, so passing a receipt id here is a 404 that reads like a
 * permissions problem.
 */
export function completeTask(taskId: string): Promise<unknown> {
  return request(`/review/${encodeURIComponent(taskId)}/complete`, { method: 'POST' })
}

/** Strictly sequential. Nothing advances past a step that failed.
 *
 * The patch is always sent, even when it is `{}`: an empty body is legal and
 * means "no changes, still mark reviewed" (review/schemas.py:222-227), so
 * skipping it for an untouched receipt would close the task and leave the row at
 * `needs_review`.
 *
 * The `ReceiptDetail` the patch returns is deliberately not propagated. The
 * caller's next move after a successful complete is the *next* task, so there is
 * nothing here to render it into; `patchReceipt` is exported separately for a
 * caller that wants it.
 */
export async function submitReview(
  receiptId: string,
  taskId: string,
  patch: FieldMap,
): Promise<void> {
  try {
    await patchReceipt(receiptId, patch)
  } catch (caught) {
    throw new SubmitError('patch', caught)
  }
  try {
    await completeTask(taskId)
  } catch (caught) {
    throw new SubmitError('complete', caught)
  }
}
