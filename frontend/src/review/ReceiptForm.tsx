import { MoneyInput } from './MoneyInput'
import type { FieldMap } from './patch'

/** Free-text paths, in the order a reviewer reads a slip.
 *
 * Every left-hand value is a key of `_RECEIPT_FIELDS`
 * (src/receipts/persist/repository.py:905-923); a path that is not in that map
 * is a `ValueError` -> 400 naming it, never a silent no-op.
 *
 * **Every one of these is a plain text box, and the two date-ish ones are the
 * reason the rule is absolute.**
 *
 * `receipt.time` is not `<input type="time">`: that control's `value` is
 * `HH:MM` while the API sends `HH:MM:SS`, and the shortened form is accepted
 * rather than refused -- measured, `PATCH {'receipt.time': '14:30'}` against a
 * stored `14:30:45` writes the correction `('receipt.time', '14:30:45',
 * '14:30:00')` and leaves `14:30` in the column.
 *
 * `receipt.date_raw` is not `<input type="date">` either, and here the reason is
 * sharper: the column holds *what the paper said*, so its normal contents are
 * whatever the model misread -- and a date control cannot even display
 * `"1L/O7/2O26"`. Measured: bound to `type="date"`, the input renders
 * `value === ''` for that string. It does not reformat the value, it loses it,
 * and the value it loses is exactly the one a reviewer opened the field to
 * repair. Nothing here may trim or reformat it either.
 *
 * `receipt.date` keeps the same treatment for consistency with its neighbour;
 * not measured: whether `<input type="date">` would round-trip a valid
 * `YYYY-MM-DD` losslessly.
 *
 * ## Verbatim ends at the wire
 *
 * Every text control here sends exactly what was typed. **It is not what gets
 * stored.** `_plan_change` runs `redact_pan` over every coerced text value, so
 * any 13-19 digit run is masked before it reaches the column -- and the
 * `corrections` row records only the masked form, so the original is not
 * recoverable from the audit trail either. Measured through the real `PATCH`
 * route, reading the value back with `GET /receipts/{id}`:
 *
 *     sent '4111111111111111'      -> read '************1111'
 *     sent '4111 1111 1111 1111'   -> read '************1111'   (separators lost)
 *     sent '378282246310005'       -> read '***********0005'
 *     sent '411111111111'          -> read '411111111111'       (12 digits, kept)
 *     sent '  2026-07-30  '        -> read '  2026-07-30  '     (padding kept)
 *     sent '\t1L/O7/2O26 ~'        -> read '\t1L/O7/2O26 ~'     (tab kept)
 *
 * That is SPEC 18 working as intended and it applies to every text path here,
 * `payment.method` most of all. What it means for this form is narrow but real:
 * the box may go on showing something the database does not hold. The PATCH
 * reply is a full `ReceiptDetail` and already carries the stored value, so
 * echoing it back is possible; whether to is a product decision and is not
 * implemented.
 */
const TEXT_FIELDS: ReadonlyArray<readonly [string, string]> = [
  ['merchant.name', 'Merchant'],
  ['receipt.number', 'Receipt number'],
  // Adjacent on purpose: `date_raw` is the evidence `receipt.date` is checked
  // against, so a reviewer reconciling the two reads them side by side. It used
  // to be rendered as read-only text for that reason; it is now editable
  // because a misread printed date is itself a thing worth correcting, and
  // making it correctable blocks nothing -- an untouched value is omitted from
  // the patch like any other (tests/patch.test.ts pins both halves).
  ['receipt.date', 'Date (ISO)'],
  ['receipt.date_raw', 'Printed date'],
  ['receipt.time', 'Time'],
  ['receipt.currency', 'Currency'],
  ['payment.method', 'Payment method'],
  ['payment.card_last4', 'Card last 4'],
]

/** The six `Numeric` columns, all through `MoneyInput` (ADR-0001). */
const MONEY_FIELDS: ReadonlyArray<readonly [string, string]> = [
  ['totals.subtotal', 'Subtotal'],
  ['totals.tax', 'Tax'],
  ['totals.discount', 'Discount'],
  ['totals.total', 'Total'],
  ['totals.tender', 'Tender'],
  ['totals.change', 'Change'],
]

/** The `Legibility` enum, verbatim (src/receipts/extract/schema.py:23-27).
 *  `_coerce_legibility` calls `Legibility(value)` -- measured:
 *  `_coerce_legibility('excellent')` raises
 *  `ValueError: 'excellent' is not a valid Legibility`, so a fifth entry here
 *  would be a 400. There is no empty option for the same reason:
 *  `_coerce_legibility(None)` raises `'none' is not a valid Legibility`, and the
 *  column is NOT NULL, so `legibility` always arrives as one of these four. */
const LEGIBILITY: readonly string[] = ['good', 'fair', 'poor', 'unreadable']

export interface ReceiptFormProps {
  readonly fields: FieldMap
  readonly onChange: (path: string, value: string | null) => void
}

/** The receipt's own correctable fields: **seventeen controls for the seventeen
 *  paths in `_RECEIPT_FIELDS`**, one each.
 *
 * `receipt.date_raw` is among them. It is still the evidence a reviewer checks
 * `receipt.date` against -- which is why the two sit next to each other in
 * `TEXT_FIELDS` -- but evidence the machine transcribed wrongly is worth
 * repairing, and a correctable field costs nothing when it is left alone:
 * `buildPatch` omits anything the reviewer did not touch, so confirming a
 * receipt with a garbled printed date still sends `{}` (measured, both halves
 * pinned in tests/patch.test.ts and tests/review-screen.test.tsx).
 *
 * An empty text box reports `null`, not `""`. They land as different column
 * values -- measured: `_coerce_optional_text(None)` is `None` -- and
 * `merchant_name_raw` reading `""` where nothing was printed is a wrong answer
 * rather than a missing one.
 *
 * The booleans report `"true"`/`"false"`, which is what `_coerce_bool` reads
 * (measured: `'true'` -> `True`, `'false'` -> `False`, `None` ->
 * `ValueError: not a boolean: None`). A checkbox has no third state, so a column
 * that is `NULL` today stays `NULL` until the reviewer actually clicks it -- at
 * which point they have made a real edit and it is recorded as one.
 */
export function ReceiptForm({ fields, onChange }: ReceiptFormProps) {
  return (
    <section>
      <h2>Receipt</h2>
      {TEXT_FIELDS.map(([path, label]) => (
        <label key={path}>
          {label}
          <input
            type="text"
            value={fields[path] ?? ''}
            onChange={(e) => onChange(path, e.target.value === '' ? null : e.target.value)}
          />
        </label>
      ))}

      {MONEY_FIELDS.map(([path, label]) => (
        <MoneyInput
          key={path}
          label={label}
          value={fields[path]}
          onChange={(value) => onChange(path, value)}
        />
      ))}

      <label>
        Legibility
        <select
          value={fields['meta.legibility'] ?? ''}
          onChange={(e) => onChange('meta.legibility', e.target.value)}
        >
          {LEGIBILITY.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </label>
      <label>
        Handwritten
        <input
          type="checkbox"
          checked={fields['meta.is_handwritten'] === 'true'}
          onChange={(e) => onChange('meta.is_handwritten', String(e.target.checked))}
        />
      </label>
      <label>
        Receipt is inconsistent
        <input
          type="checkbox"
          checked={fields['meta.receipt_is_inconsistent'] === 'true'}
          onChange={(e) => onChange('meta.receipt_is_inconsistent', String(e.target.checked))}
        />
      </label>
    </section>
  )
}
