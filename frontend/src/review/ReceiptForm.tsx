import { MoneyInput } from './MoneyInput'
import type { FieldMap } from './patch'

/** Free-text paths, in the order a reviewer reads a slip.
 *
 * Every left-hand value is a key of `_RECEIPT_FIELDS`
 * (src/receipts/persist/repository.py:905-923); a path that is not in that map
 * is a `ValueError` -> 400 naming it, never a silent no-op.
 *
 * `receipt.time` is plain text, **not `<input type="time">`**. That control's
 * `value` is `HH:MM` while the API sends `HH:MM:SS`, and the shortened form is
 * accepted rather than refused -- measured: `PATCH {'receipt.time': '14:30'}`
 * against a stored `14:30:45` writes the correction
 * `('receipt.time', '14:30:45', '14:30:00')` and leaves `14:30` in the column.
 * `receipt.date` is plain text for symmetry with it; not measured: whether
 * `<input type="date">` would round-trip a `YYYY-MM-DD` value losslessly.
 */
const TEXT_FIELDS: ReadonlyArray<readonly [string, string]> = [
  ['merchant.name', 'Merchant'],
  ['receipt.number', 'Receipt number'],
  ['receipt.date', 'Date (ISO)'],
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

/** The receipt's own correctable fields.
 *
 * Sixteen controls for seventeen paths: `receipt.date_raw` is rendered as
 * evidence rather than as an input. It is what the machine read off the paper,
 * which is what a reviewer checks `receipt.date` *against*; making it editable
 * would let the evidence be rewritten to agree with the correction.
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

      <p>Printed date: {fields['receipt.date_raw'] ?? '—'}</p>

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
