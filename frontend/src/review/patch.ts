import type { ReceiptDetail } from '../api/types'

/** A flat map of dotted correction paths to their string values.
 *
 * Dotted rather than nested, and verified rather than assumed. Measured against
 * the real models:
 *
 *     >>> CorrectionPatch.model_validate(
 *     ...     {'totals.total': '1000.00', 'receipt.time': None,
 *     ...      'line_items[0].qty': '9.9', 'meta.is_handwritten': 'true'}
 *     ... ).model_dump(exclude_unset=True, mode='json')
 *     {'totals.total': '1000.00', 'receipt.time': None,
 *      'line_items[0].qty': '9.9', 'meta.is_handwritten': 'true'}
 *     >>> flatten(_)
 *     {'totals.total': '1000.00', 'receipt.time': None,
 *      'line_items[0].qty': '9.9', 'meta.is_handwritten': 'true'}
 *
 * So a flat object reaches `apply_corrections` with its keys untouched, and the
 * client has no nested structure to build. Every value is a string or `null`
 * because that is the only shape `_reject_json_float` (review/schemas.py:107)
 * and `_coerce_money` (persist/repository.py:812) both accept for an amount --
 * ADR-0001's rule, applied at the one place the browser could break it.
 */
export type FieldMap = Record<string, string | null>

/** A nullable boolean column as the text `_coerce_bool` reads.
 *
 * `null` stays `null` rather than becoming `"false"`: the column is nullable and
 * "never recorded" is not "recorded as no". Measured -- `_coerce_bool('true')`
 * is `True`, `_coerce_bool('false')` is `False`, and `_coerce_bool(None)` raises
 * `ValueError: not a boolean: None` -- so a `null` here may only ever be omitted
 * from a patch, never sent.
 */
function boolText(value: boolean | null): string | null {
  if (value === null) {
    return null
  }
  return value ? 'true' : 'false'
}

/** The six correctable fields of one line item. `position` is deliberately
 *  absent -- see `LineItemsTable`. */
function lineItemFields(fields: FieldMap, receipt: ReceiptDetail): void {
  for (const item of receipt.line_items) {
    // `line_items[i]` addresses the item at *position* `i`, not at index `i`:
    // `apply_corrections` resolves it through `items_by_position`
    // (persist/repository.py:1033), so a receipt whose positions have a gap
    // would send every later edit to the wrong row if this used the index.
    const at = `line_items[${item.position}]`
    fields[`${at}.description_raw`] = item.description_raw
    fields[`${at}.sku`] = item.sku
    fields[`${at}.qty`] = item.qty
    fields[`${at}.unit`] = item.unit
    fields[`${at}.unit_price`] = item.unit_price
    fields[`${at}.line_total`] = item.line_total
  }
}

/** The editable state of one receipt, keyed by the path the server writes to.
 *
 * **The read name and the write name differ for six of the seventeen**, which is
 * the one mapping in this task that cannot be guessed. Left of the arrow is
 * `_RECEIPT_FIELDS` (persist/repository.py:905-923, the closed set of paths
 * `apply_corrections` will accept); right is the key `receipt_detail`
 * (review/serializers.py:190-218) returns:
 *
 *     merchant.name                -> merchant_name_raw
 *     receipt.date                 -> txn_date
 *     receipt.time                 -> txn_time
 *     payment.method               -> payment_method
 *     payment.card_last4           -> card_last4
 *     meta.is_handwritten          -> is_handwritten          (no `meta.`)
 *     meta.legibility              -> legibility              (no `meta.`)
 *     meta.receipt_is_inconsistent -> receipt_is_inconsistent (no `meta.`)
 *
 * Values are copied verbatim -- no reformatting, no normalising, no padding.
 * `txn_time` is the sharp case, and it was measured end to end against a stored
 * `time(14, 30, 45)`:
 *
 *     receipt_detail(...)['txn_time']         -> '14:30:45'
 *     PATCH {'receipt.time': '14:30:45'}      -> corrections: []
 *     PATCH {}                                -> corrections: [],  status reviewed
 *     PATCH {'receipt.time': '14:30'}         -> corrections:
 *         [('receipt.time', '14:30:45', '14:30:00')],  stored time now 14:30
 *
 * So the shortened form is *accepted*, not rejected: it destroys the seconds and
 * books a `corrections` row for an edit nobody made. Handing the exact string
 * back is the whole defence, and
 * `it('confirming an untouched receipt produces no corrections at all')` in
 * tests/patch.test.ts is what holds it -- note that a screen-level "the patch was
 * empty" assertion cannot, because both sides of `buildPatch` come from this
 * function and would be reformatted together.
 */
export function fieldsFromReceipt(receipt: ReceiptDetail): FieldMap {
  const fields: FieldMap = {
    'merchant.name': receipt.merchant_name_raw,
    'receipt.number': receipt.receipt_number,
    'receipt.date': receipt.txn_date,
    'receipt.date_raw': receipt.date_raw,
    'receipt.time': receipt.txn_time,
    'receipt.currency': receipt.currency,
    'totals.subtotal': receipt.totals.subtotal,
    'totals.tax': receipt.totals.tax,
    'totals.discount': receipt.totals.discount,
    'totals.total': receipt.totals.total,
    'totals.tender': receipt.totals.tender,
    'totals.change': receipt.totals.change,
    'payment.method': receipt.payment_method,
    'payment.card_last4': receipt.card_last4,
    'meta.is_handwritten': boolText(receipt.is_handwritten),
    'meta.legibility': receipt.legibility,
    'meta.receipt_is_inconsistent': boolText(receipt.receipt_is_inconsistent),
  }
  lineItemFields(fields, receipt)
  return fields
}

/** Only what changed.
 *
 * The server distinguishes "never mentioned" from "explicitly null" -- the route
 * reads the body with `model_dump(exclude_unset=True, mode="json")`
 * (review/api.py:392) -- so an untouched field must be **absent** rather than
 * sent as its current value, and a cleared one must be **present and null**.
 * Sending every field instead would still be accepted, because
 * `_plan_change` writes no `corrections` row for a path whose stored value
 * already matches (persist/repository.py:994-995, read); but it would put a
 * reviewer's whole form through `_coerce_*` on every approval, so one unparsable
 * value the machine wrote and the reviewer never looked at would reject the
 * entire submission.
 *
 * Comparison is by value and does not consult `original`'s key set: a path
 * `original` lacks reads as `undefined`, which differs from every `string |
 * null`, so the edit is sent. Dropping it silently is the failure mode the
 * closed `_RECEIPT_FIELDS` map exists to prevent.
 */
export function buildPatch(original: FieldMap, edited: FieldMap): FieldMap {
  const patch: FieldMap = {}
  for (const [path, value] of Object.entries(edited)) {
    if (original[path] !== value) {
      patch[path] = value
    }
  }
  return patch
}

/** One field the server did not store as it was sent. */
export interface Rewrite {
  readonly path: string
  readonly sent: string | null
  readonly stored: string | null
}

/** The nine correctable paths whose column is `Numeric`, so their text form
 *  carries a scale. Read off `_RECEIPT_FIELDS`/`_LINE_ITEM_FIELDS` by asking
 *  which entries coerce with `_coerce_money`:
 *
 *      receipt  : totals.change discount subtotal tax tender total
 *      line item: line_total qty unit_price
 */
const MONEY_RECEIPT_PATHS: ReadonlySet<string> = new Set([
  'totals.subtotal',
  'totals.tax',
  'totals.discount',
  'totals.total',
  'totals.tender',
  'totals.change',
])
const MONEY_ITEM_FIELDS: ReadonlySet<string> = new Set(['qty', 'unit_price', 'line_total'])
const LINE_ITEM_FIELD = /^line_items\[\d+\]\.([A-Za-z_][A-Za-z0-9_]*)$/

function isMoneyPath(path: string): boolean {
  if (MONEY_RECEIPT_PATHS.has(path)) {
    return true
  }
  const match = LINE_ITEM_FIELD.exec(path)
  return match !== null && MONEY_ITEM_FIELDS.has(match[1])
}

/** An amount with the column's display scale removed: trailing zeros in the
 *  fractional part, and a point left bare by removing them.
 *
 *  **The amount is never converted to a number.** `indexOf`, `charAt` and
 *  `slice`; no `Number`, no `parseFloat`, no unary `+`. There *is* arithmetic
 *  here -- `end -= 1`, `point + 1` -- but it is on string indices, never on the
 *  digits, which is the distinction ADR-0001 draws.
 *  `tests/no-float-in-money-path.test.ts` is the arbiter of whether this
 *  qualifies, and it passes. Digits left of the point are never touched, so
 *  `"1000"` cannot become `"1"`.
 *
 *  Only trailing zeros go. `"1,000.00"` becomes `"1,000"`, not `"1000"`, so a
 *  server that stripped the comma is still reported -- which is the whole reason
 *  this is a narrow normalisation rather than a loose comparison.
 */
function withoutDisplayScale(amount: string): string {
  const point = amount.indexOf('.')
  if (point === -1) {
    return amount
  }
  let end = amount.length
  while (end > point + 1 && amount.charAt(end - 1) === '0') {
    end -= 1
  }
  return amount.slice(0, end === point + 1 ? point : end)
}

function comparable(path: string, value: string | null): string | null {
  if (value === null || !isMoneyPath(path)) {
    return value
  }
  return withoutDisplayScale(value)
}

/** What the server stored that is not what the reviewer sent.
 *
 * `PATCH /receipts/{id}` returns the full `ReceiptDetail` it just wrote, so the
 * reply *is* the new state and this needs no extra request. It catches every
 * server-side rewrite, not only redaction -- though redaction is the one that
 * prompted it: `redact_pan` masks any 13-19 digit run, and measured,
 * `redact_pan('20260730123456')` is `'**********3456'`, which is a plausible
 * thing to read off a receipt.
 *
 * Only the paths that were sent are compared. Everything else was omitted from
 * the patch by definition, so a difference there is not this reviewer's edit.
 *
 * A path the reply does not carry counts as a rewrite with `stored: null`.
 * Absent is not "unchanged", and over-reporting is the safe direction for a
 * warning whose whole job is to say "check this".
 */
export function findRewrites(sent: FieldMap, stored: FieldMap): Rewrite[] {
  const rewrites: Rewrite[] = []
  for (const [path, value] of Object.entries(sent)) {
    const back = stored[path] ?? null
    if (comparable(path, value) !== comparable(path, back)) {
      rewrites.push({ path, sent: value, stored: back })
    }
  }
  return rewrites
}
