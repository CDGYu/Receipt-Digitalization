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
 * reads the body with `patch.model_dump(exclude_unset=True, mode="json")`
 * (search `review/api.py` for `exclude_unset`) -- so an untouched field must be
 * **absent** rather than
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

/** An amount reduced to the form two spellings of the same figure share: the
 *  column's display scale removed, and the punctuation a reviewer may or may not
 *  type normalised away.
 *
 *  **The amount is never converted to a number.** `trim`, `indexOf`, `charAt`,
 *  `startsWith` and `slice`; no `Number`, no `parseFloat`, no unary `+`. There
 *  *is* arithmetic -- `end -= 1`, `point + 1` -- but every one of those numbers
 *  is a string offset: no character is ever read as a value, and no value is
 *  ever written back out as a character. Every character of the return came out
 *  of the trimmed input, apart from one literal `"0"` that may be inserted in
 *  front of a bare leading point -- **or after the sign**, which is where a
 *  negative one goes. Measured: `withoutDisplayScale('-.50')` is `'-0.5'`,
 *  which is neither a substring of its input nor a substring with a `"0"` in
 *  front. This note said it was one, which is the sort of claim about its own
 *  code that this comment exists to make checkable.
 *
 *  That, read off the statements below, is what establishes it stays inside
 *  ADR-0001; `tests/no-float-in-money-path.test.ts` passes, but it is **not**
 *  evidence either way -- it has no rule that fires on arithmetic of any kind,
 *  and its own `LEGITIMATE` list pins `item.position + 1` as must-not-fire.
 *
 *  Digits left of the point are never touched, so `"1000"` cannot become `"1"`.
 *
 *  The tidying is comparison-only -- nothing here is ever sent or displayed --
 *  and each rule closes a measured false positive. All six were sent through the
 *  real `PATCH` route and read back with `GET`:
 *
 *      '.50'         -> '0.5000'     '1000.00 '    -> '1000.0000'
 *      '-.50'        -> '-0.5000'    '  1000.00  ' -> '1000.0000'
 *      '+1000.00'    -> '1000.0000'  '1000.'       -> '1000.0000'
 *
 *  `.50` for fifty cents is an ordinary keystroke; a warning that fires on it is
 *  a warning reviewers learn to dismiss.
 *
 *  What is deliberately *not* normalised, so the exemption stays narrow: a
 *  thousands separator (`"1,000.00"` becomes `"1,000"`, not `"1000"`) -- though
 *  measured, that one never reaches here, because `_coerce_money` answers
 *  `not a decimal amount: '1,000.00'` and the route 400s. Also not normalised,
 *  and these two do reach here: leading zeros (`'00100.00'` -> stored
 *  `'100.0000'`) and negative zero (`'-0.00'` -> `'0.0000'`), both measured to
 *  still fire. Neither is a normal way to key an amount, and stripping leading
 *  zeros is a separate rule with its own edge cases, so they are left reported
 *  rather than guessed at.
 */
function withoutDisplayScale(amount: string): string {
  let text = amount.trim()
  if (text.startsWith('+')) {
    text = text.slice(1)
  }
  if (text.startsWith('.')) {
    text = `0${text}`
  } else if (text.startsWith('-.')) {
    text = `-0${text.slice(1)}`
  }
  const point = text.indexOf('.')
  if (point === -1) {
    return text
  }
  let end = text.length
  while (end > point + 1 && text.charAt(end - 1) === '0') {
    end -= 1
  }
  return text.slice(0, end === point + 1 ? point : end)
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
 * A path the reply does not carry reads as `null`. So a value the reply omits is
 * reported (`stored: null`), while a field the reviewer *cleared* and the reply
 * omits is not -- measured, `findRewrites({'payment.method': null}, {})` is `[]`.
 * Absent and null are the same fact here ("no value there"), and reporting that
 * pair would render as "you entered (nothing), the receipt now holds
 * (nothing)", which is not a warning. Both cases are pinned in
 * tests/patch.test.ts.
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
