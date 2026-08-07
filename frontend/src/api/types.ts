/** A decimal that must never become a JS number (ADR-0001).
 *
 * The API serialises every Decimal as a string precisely so a JSON number --
 * which is a float -- never touches the money path. If you find yourself
 * wanting arithmetic, the answer is a server round-trip.
 *
 * **What the brand actually enforces, measured rather than assumed.** It rejects
 * the operators that fail loudly and permits every one that fails silently, so
 * it is a guard rail, not a wall:
 *
 * | Rejected by `tsc`            | Compiles anyway                          |
 * | ---------------------------- | ---------------------------------------- |
 * | `m * 2`, `m - m2`, `m / 2`   | `m1 + m2` -> `"19.995.00"` (concatenates)|
 * | `m += x`                     | `Number(m)`, `parseFloat(m)`, `+m` -> `1000`, trailing zeros gone |
 * | `m.toFixed()`, `Math.abs(m)` | `m1 < m2` -> lexicographic, not numeric  |
 * | `const x: Money = '1.00'`    |                                          |
 *
 * The silent column is why `tests/no-float-in-money-path.test.ts` exists: the
 * brand cannot catch `Number(m)` because its parameter type is `string` and a
 * `Money` is a string. Types stop the loud mistakes; the source scan stops the
 * quiet ones; and the backend's `_coerce_money` refusing a float outright is the
 * last line. All three, not any one.
 */
export type Money = string & { readonly __money: unique symbol }

export interface ConfidenceReason {
  reason: string
  penalty: Money
}

/** An item-level discount, promo, or adjustment printed under a line item.
 *
 * `amount` is SIGNED: discounts negative, surcharges positive. It arrives as a
 * string -- `repository.py` stores `modifier.model_dump(mode="json")`, and
 * pydantic's JSON mode renders a `Decimal` as a string (verified by execution:
 * `Decimal("-2.50")` -> `"-2.50"`).
 */
export interface Modifier {
  label: string
  amount: Money | null
}

export interface LineItem {
  position: number
  description_raw: string | null
  sku: string | null
  qty: Money | null
  unit: string | null
  unit_price: Money | null
  line_total: Money | null
  /** Not correctable. `_LINE_ITEM_FIELDS` (persist/repository.py) deliberately
   *  omits `modifiers` and `bbox`: "they are documents, not scalars, and a
   *  reviewer edits them through the item they belong to." Render, do not edit. */
  modifiers: Modifier[]
  line_confidence: Money | null
}

export interface Finding {
  rule_id: string
  severity: string
  message: string
  context: unknown
  resolved_by_repair: boolean
}

export interface ReceiptDetail {
  id: string
  status: string
  confidence: Money | null
  /** `null` = never recorded. `[]` = nothing lowered the score. Different facts. */
  confidence_reasons: ConfidenceReason[] | null
  merchant_name_raw: string | null
  receipt_number: string | null
  txn_date: string | null
  date_raw: string | null
  /** **`HH:MM:SS`, and it must go back exactly as it came.** Measured against a
   *  stored `time(14, 30, 45)`: `_iso_time` (review/serializers.py:81-97) renders
   *  the column with `isoformat()`, so it arrives here as `"14:30:45"`;
   *  `_coerce_time("14:30")` returns `time(14, 30)` rather than raising, and a
   *  `PATCH {"receipt.time": "14:30"}` writes the correction row
   *  `('receipt.time', '14:30:45', '14:30:00')` for an edit the reviewer never
   *  made. So this string is carried, never reformatted, and never bound to
   *  `<input type="time">`, whose `value` is `HH:MM`. */
  txn_time: string | null
  currency: string | null
  /** ISO 8601, never null -- `receipt.created_at.isoformat()`. */
  created_at: string
  payment_method: string | null
  card_last4: string | null
  is_handwritten: boolean | null
  legibility: string
  /** The id of the receipt this one duplicates, or `null`. A reviewer looking at
   *  a flagged duplicate needs to be able to reach the original. */
  duplicate_of: string | null
  receipt_is_inconsistent: boolean | null
  totals: {
    subtotal: Money | null
    tax: Money | null
    discount: Money | null
    total: Money | null
    tender: Money | null
    change: Money | null
  }
  line_items: LineItem[]
  findings: Finding[]
}

/** One row of `GET /receipts`, and the `receipt` half of `GET /review/next`.
 *
 * **Not derivable from `ReceiptDetail`.** `receipt_summary`
 * (review/serializers.py:80-96) puts `total` at the *top level*, while
 * `receipt_detail` puts every amount under `totals` -- so no `Pick` or `Omit`
 * over `ReceiptDetail` produces this shape, and the two responses genuinely
 * disagree about where the one number a reviewer triages on lives. Read off the
 * serializer, which is the only place that shape is written down.
 *
 * The plan had no type for this at all: `fetchNext` was specified as returning
 * `receipt: unknown`.
 */
export interface ReceiptSummary {
  id: string
  status: string
  confidence: Money | null
  merchant_name_raw: string | null
  txn_date: string | null
  currency: string | null
  /** Top level here; `totals.total` on `ReceiptDetail`. Not a transcription slip. */
  total: Money | null
  /** ISO 8601, never null -- `receipt.created_at.isoformat()`. */
  created_at: string
}

/** `GET /review/next` -- claim the next task for the caller.
 *
 * Two nulls, both load-bearing and both distinct from each other:
 *
 * * `task: null` is an **empty queue**, returned as 200 with a body rather than
 *   204 (review/api.py:496-500), so it is a state to render and not an error to
 *   catch. On that branch the route returns `{"task": None}` and **no `receipt`
 *   key at all** -- hence `receipt` is optional here, not merely nullable.
 * * `receipt: null` alongside a **non-null** task: the route serialises
 *   `receipt_summary(receipt) if receipt is not None else None`
 *   (review/api.py:504), so a claimed task whose receipt row cannot be loaded
 *   arrives with the task present and the receipt missing. `ReviewScreen` does
 *   not read this field -- it re-fetches the full `ReceiptDetail` from
 *   `task.receipt_id`, because the summary carries no line items and no findings.
 */
export interface ReviewNextResponse {
  task: ReviewTask | null
  receipt?: ReceiptSummary | null
}

/** A review-queue task, as `_task_summary` (review/api.py:273-284) returns it.
 *
 * `assigned_to`, `opened_at` and `closed_at` were missing from the plan's
 * version of this interface -- the same omission finding 9 raised against
 * `ReceiptDetail`, and it matters for the same reason: `request<T>` is an
 * unchecked cast, so a missing field reads as absent data rather than failing.
 * `assigned_to` in particular is the field `POST /review/{id}/complete` checks
 * before it will let anyone close a task.
 */
export interface ReviewTask {
  id: string
  receipt_id: string
  reason: string
  priority: number
  /** `null` until `GET /review/next` claims it for a reviewer. */
  assigned_to: string | null
  state: string
  /** ISO 8601, never null. */
  opened_at: string
  /** ISO 8601, or `null` while the task is still open. */
  closed_at: string | null
}
