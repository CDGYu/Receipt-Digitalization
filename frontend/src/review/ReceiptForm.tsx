import { useId } from 'react'
import { MoneyInput } from './MoneyInput'
import type { FieldMap } from './patch'
import styles from './ReceiptForm.module.css'

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
 * a card number in any spelling the table below records is masked before it
 * reaches the column, and the `corrections` row records only the masked form,
 * so the original is not recoverable from the audit trail either. Two distinct
 * categories are deliberately NOT fully masked, and neither is one spelling.
 * **(1) Leak (b) is a class:** ANY run of more than four separated groups keeps
 * everything after its leading four groups in the clear, whatever the groups
 * are -- and when that remainder is itself grouped outside every shape in the
 * alternation, it can be an entire, undetected card number, not merely a short
 * leftover tail. Accepted by ruling rather than closed, because every measured
 * attempt to close it leaked something worse (ADR-0018). **(2) A card grouped
 * outside every shape in the alternation is stored whole outright** -- no match
 * at all, so nothing is masked and nothing is partial. That is the residual
 * ADR-0020 reduced without closing; which shapes it covers, and which groupings
 * are still stored whole, is ADR-0020.
 *
 * **What is masked is exactly the table below, and nothing is generalised from
 * it.** This claim has been wrong twice. The first version was measured on the
 * unseparated form alone and generalised to every separator; at the time, a
 * PAN separated by anything but a space or a hyphen was stored whole. The
 * second was measured on four-group forms with a 1-4 digit tail and
 * generalised to "13-19 digits"; at the time, `4111 1111 1111 11111` and
 * every longer tail was stored whole. Both were found by executing the code,
 * not by reading it. `tests/test_repository.py` is the binding measurement.
 * Re-measured through the real `PATCH` route on `receipt.date_raw`, one fresh
 * receipt per row, reading the value back with `GET /receipts/{id}`:
 *
 *     sent '4111111111111111'        -> read '************1111'
 *     sent '4111 1111 1111 1111'     -> read '************1111'   (separators lost)
 *     sent '4111-1111-1111-1111'     -> read '************1111'
 *     sent '4111.1111.1111.1111'     -> read '************1111'
 *     sent '4111_1111_1111_1111'     -> read '************1111'
 *     sent '4111/1111/1111/1111'     -> read '************1111'
 *     sent '4111,1111,1111,1111'     -> read '************1111'
 *     sent '4111 1111-1111.1111'     -> read '************1111'   (mixed)
 *     sent '4111  1111  1111  1111'  -> read '************1111'   (doubled separator)
 *     sent '378282246310005'         -> read '***********0005'
 *     sent '3782.822463.10005'       -> read '***********0005'
 *     sent '3055 930902 5904'        -> read '**********5904'     (4-6-4, Diners)
 *     sent '6759 4111 00005'         -> read '*********0005'      (4-4-5, Maestro)
 *     sent '41111 1111 1111 2345'    -> read '*************2345'  (5-4-4-4)
 *     sent '411111 1111 1111 2345'   -> read '**************2345' (6-4-4-4)
 *     sent '4111 11111 1111 2345'    -> read '*************2345'  (4-5-4-4)
 *     sent '411111111111'            -> read '411111111111'       (12 digits, kept)
 *     sent '1,000.00'                -> read '1,000.00'
 *     sent '  2026-07-30  '          -> read '  2026-07-30  '     (padding kept)
 *     sent '\t1L/O7/2O26 ~'          -> read '\t1L/O7/2O26 ~'     (tab kept)
 *     sent '4111 1111 1111 11111'    -> read '*************1111'      (4-4-4-5, leak (a), now closed)
 *     sent '4111 1111 1111 1111 111' -> read '************1111 111'   (5 groups, leak (b), accepted -- ADR-0018)
 *
 * `payment.method` reads back identically for every row above; the two paths
 * were measured separately rather than one being inferred from the other.
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
  // Who the receipt was issued TO, next to who issued it, because that is the
  // pair a reviewer is reconciling and the pair the paper makes easy to
  // confuse. On the slip it is the block under the merchant's header, which is
  // where it sits here.
  //
  // **Labelled off the paper, not off the schema.** The column is `buyer` and
  // the path is `buyer.name`, but the form says `SOLD TO`, `Sold to:` or
  // `Registered Name` (extract/prompts.py names all three), and the reviewer is
  // matching a screen against a photograph -- so the screen uses the words that
  // are printed on it.
  //
  // `Sold to TIN` rather than `TIN`: a BIR sales invoice carries **three** TINs
  // -- the merchant's in the header, the buyer's in this block, the printer's
  // in the footer -- and they are three different numbers. A field labelled
  // `TIN` is an invitation to key the wrong one.
  ['buyer.name', 'Sold to'],
  ['buyer.tax_id', 'Sold to TIN'],
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
  /** Server messages keyed by the same dotted paths as `fields`. */
  readonly errors?: Readonly<Record<string, string>>
}

/** One free-text control, owning its ids. Extracted because `useId` is a
 *  hook and the fields render from a `.map`.
 *
 *  The error paragraph is a *sibling* of the label, for the reason `MoneyInput`
 *  records: text nested inside a `<label>` becomes part of the field's name.
 *
 *  **`placeholder="—"` covers every `TEXT_FIELDS` entry from one place** --
 *  design §4's input half, the same mark and the same `--color-null` that
 *  `ui/Value` paints for a displayed value. Every entry rather than a count of
 *  them: the list grows, and a number here is one more thing for whoever grows
 *  it to find. Before it, a merchant name the extractor never
 *  read rendered as an empty box, indistinguishable from a box a reviewer has
 *  not reached yet; `placeholder` appeared **zero** times in `frontend/src`
 *  (measured, `git grep placeholder -- frontend/src`). It cannot become the
 *  field's accessible name: the wrapping `<label>` supplies that, and the
 *  accessible-name algorithm reaches a placeholder only when nothing else names
 *  the control -- `getByLabelText('Merchant')` still resolves. */
function TextField({
  label,
  value,
  error,
  onChange,
}: {
  readonly label: string
  readonly value: string | null
  readonly error: string | undefined
  readonly onChange: (value: string | null) => void
}) {
  const errorId = useId()
  return (
    <>
      <label className={styles.field}>
        {label}
        <input
          className={styles.input}
          type="text"
          placeholder="—"
          value={value ?? ''}
          aria-describedby={error !== undefined ? errorId : undefined}
          onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        />
      </label>
      {error !== undefined ? (
        <p className={styles.error} role="alert" id={errorId}>
          {error}
        </p>
      ) : null}
    </>
  )
}

/** The receipt's own correctable fields: **one control per path in
 *  `_RECEIPT_FIELDS`, and no others**.
 *
 * Stated as a correspondence rather than as a number, deliberately. A number
 * was here, and it was already wrong by the time anyone read it again: it said
 * seventeen, and `_RECEIPT_FIELDS` had since grown.
 *
 * **What holds the correspondence.** tests/patch.test.ts pins the whole
 * `FieldMap` key set and tests/receipt-form.test.tsx counts the rendered
 * controls, so the form and the patch builder cannot drift apart without going
 * red. Neither of those reads `_RECEIPT_FIELDS`; what binds this side to that
 * one is `test_every_correctable_receipt_path_is_offered_by_the_review_client`
 * (tests/test_repository.py), which parses `fieldsFromReceipt`'s object literal
 * and compares it against the imported map. It lives in pytest deliberately:
 * the change that breaks it is a path added on the server, and that is the
 * suite whoever makes that change is already running.
 *
 * Until that pin existed the gap was open, and the number above is what fell
 * through it -- the server accepted `buyer.name` and `buyer.tax_id` across
 * `71405d0..de979e9`, 34 commits and all eight preceding tasks of this plan,
 * before this form grew a control for either, with every gate green throughout.
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
export function ReceiptForm({ fields, onChange, errors }: ReceiptFormProps) {
  return (
    <section className={styles.form}>
      <h2>Receipt</h2>
      {TEXT_FIELDS.map(([path, label]) => (
        <div className={styles.fieldCell} key={path}>
          <TextField
            label={label}
            value={fields[path]}
            error={errors?.[path]}
            onChange={(value) => onChange(path, value)}
          />
        </div>
      ))}

      {MONEY_FIELDS.map(([path, label]) => (
        <div className={styles.fieldCell} key={path}>
          <MoneyInput
            label={label}
            value={fields[path]}
            error={errors?.[path]}
            onChange={(value) => onChange(path, value)}
          />
        </div>
      ))}

      {/* No error slot on the three below: `_coerce_legibility` and
          `_coerce_bool` cannot be reached from a closed option list or a
          checkbox, so neither control has an invalid state to send
          (design §1.3/§10).

          **And no `placeholder` on any of them, for the same shape of reason.**
          A placeholder is the empty state of a free-text box; a closed option
          list has no empty state to show one in, and a checkbox has no third
          state at all. Design §4's mark would be a claim neither control can
          carry. That leaves the null treatment reaching every correctable path
          except these three -- which is the honest statement, and not the
          every-path one ADR-0027's Consequences implies by calling every path an
          `<input>`. The arithmetic is in tests/review-null-rule.test.tsx, which
          reads both counts off the render and asserts the gap is exactly these
          three; repeating the numbers here would only give them somewhere to
          rot. */}
      <label className={styles.field}>
        Legibility
        <select
          className={styles.select}
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
      <label className={styles.check}>
        Handwritten
        <input
          className={styles.checkbox}
          type="checkbox"
          checked={fields['meta.is_handwritten'] === 'true'}
          onChange={(e) => onChange('meta.is_handwritten', String(e.target.checked))}
        />
      </label>
      <label className={styles.check}>
        Receipt is inconsistent
        <input
          className={styles.checkbox}
          type="checkbox"
          checked={fields['meta.receipt_is_inconsistent'] === 'true'}
          onChange={(e) => onChange('meta.receipt_is_inconsistent', String(e.target.checked))}
        />
      </label>
    </section>
  )
}
