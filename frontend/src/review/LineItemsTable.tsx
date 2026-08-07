import { useId, useState } from 'react'
import { MoneyInput } from './MoneyInput'
import type { LineItem } from '../api/types'
import type { FieldMap } from './patch'
import styles from './LineItemsTable.module.css'

export interface LineItemsTableProps {
  readonly items: LineItem[]
  readonly fields: FieldMap
  readonly onChange: (path: string, value: string | null) => void
  /** Server messages keyed by the same dotted paths as `fields`. */
  readonly errors?: Readonly<Record<string, string>>
}

/** One free-text cell, owning its error id. Extracted for the reason
 *  `ReceiptForm`'s `TextField` is: `useId` is a hook and the rows render from a
 *  `.map`.
 *
 * The raw string is handed back rather than a coerced `string | null`, because
 * the three callers do not agree on what an emptied box means -- see
 * `description_raw` at its call site.
 *
 * These cells cannot produce a 400 today (`_coerce_text` and
 * `_coerce_optional_text` never raise), but the slot is uniform: `matchField`
 * blames whichever path it matches, and a hit with nowhere to land would render
 * the server's words nowhere at all.
 *
 * **`placeholder="—"` covers the three text columns of every row** -- design §4's
 * input half, the same mark `ui/Value` renders and the same `--color-null` it is
 * painted in. It is not the accessible name and cannot displace one: `aria-label`
 * is above the placeholder in the accessible-name algorithm, so
 * `getByLabelText('SKU 1')` still resolves. The mark earns its place here more
 * than anywhere: `_coerce_text(None)` returns `''`, so `description_raw` cannot
 * distinguish "never recorded" from "cleared" in the column either, and an
 * unmarked empty cell would say nothing about which. */
function TextCell({
  label,
  value,
  error,
  onChange,
}: {
  readonly label: string
  readonly value: string | null
  readonly error: string | undefined
  readonly onChange: (raw: string) => void
}) {
  const errorId = useId()
  return (
    <>
      <input
        className={styles.cell}
        type="text"
        aria-label={label}
        placeholder="—"
        value={value ?? ''}
        aria-describedby={error !== undefined ? errorId : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {error !== undefined ? (
        <p className={styles.error} role="alert" id={errorId}>
          {error}
        </p>
      ) : null}
    </>
  )
}

/** The six correctable columns of each line item, plus its position.
 *
 * **No add and no remove.** `line_items[i]` addresses an item that already
 * exists at *position* `i`, not at index `i` -- measured against a receipt whose
 * single item sits at position 3:
 *
 *     PATCH {'line_items[0].description_raw': 'X'}
 *       -> ValueError: cannot apply a correction to
 *          'line_items[0].description_raw': receipt <id> has no line item at
 *          position 0
 *
 * and neither `_LINE_ITEM_FIELDS` nor any review route can delete a row. A
 * button for either would be a control that cannot work.
 *
 * **`position` is read-only.** It is in `_LINE_ITEM_FIELDS` and the server does
 * accept it -- measured: `PATCH {'line_items[3].position': '4'}` succeeded and
 * moved the item, after which every `line_items[3].*` path in the *same* screen
 * raised `has no line item at position 3`. That is the reason it is not offered:
 * position is the addressing key for every other edit, so changing it
 * invalidates the rest of the form. Not measured: whether swapping two positions
 * in one patch trips the non-deferrable `uq_line_items_receipt_position`
 * (persist/models.py:248) the way `apply_corrections`' docstring says, since the
 * UI never sends one.
 *
 * `modifiers` and `bbox` are absent for the reason `_LINE_ITEM_FIELDS` omits
 * them: they are documents, not scalars.
 *
 * Rows are the highlight unit. `onFocus` on the row rather than on each cell
 * because React's `onFocus` is the bubbling `focusin`, so one handler covers
 * every control in the row.
 *
 * ## The scroller, and why it is a `<section>` rather than a `<div>`
 *
 * Design §5.2 wraps this table in `overflow-x: auto` so a narrow viewport
 * scrolls the table instead of squeezing seven columns into it, and so the page
 * body never scrolls horizontally. That needs a real element around the
 * `<table>`, which is why this component's root is no longer the table itself.
 *
 * **A `<div>` here is measured wrong.** `ReviewScreen.module.css` places the
 * image pane positionally, with `.screen > div`, on the stated ground that the
 * pane is the *only* direct `<div>` child of the review `<main>` -- and
 * `LineItemsTable` is a direct child of that same `<main>`. A `<div>` root would
 * therefore inherit `grid-column: 1; grid-row: 2 / span 4; position: sticky` and
 * silently land the line items on top of the photograph, with every gate green:
 * no rendering test can see a grid placement. `<section>` takes the default
 * `.screen > *` slot instead, and `tests/review-null-rule.test.tsx` pins both the
 * element and the invariant.
 *
 * The obvious alternative -- `display: block; overflow-x: auto` on the `<table>`
 * itself -- stays rejected for the reason the stylesheet records: changing a
 * table's `display` drops its implicit ARIA role in a browser, while Testing
 * Library computes roles from the element and would never notice.
 */
export function LineItemsTable({ items, fields, onChange, errors }: LineItemsTableProps) {
  const [active, setActive] = useState<number | null>(null)
  return (
    <section className={styles.scroller}>
      <table className={styles.table}>
        <thead className={styles.head}>
          <tr>
            <th>#</th>
            <th>Description</th>
            <th>SKU</th>
            <th>Qty</th>
            <th>Unit</th>
            <th>Unit price</th>
            <th>Line total</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const at = `line_items[${item.position}]`
            return (
              <tr
                key={item.position}
                className={styles.row}
                onFocus={() => setActive(item.position)}
                // **The colour is the swap this task owns; the mechanism is not.**
                // `#fffbe6` stood here, and amber is WARN's reserved colour
                // (ADR-0027 §2) -- a yellow row on an accounting screen reads as a
                // warning about that row's numbers rather than as "this is where
                // you are". `--color-surface-active` is the pale blue Task 1 added
                // for exactly this, tied to `--color-ring`.
                //
                // It stays an *inline* style rather than moving to
                // `styles.rowActive`, against the brief, because the class form is
                // measured red: `receipt-form.test.tsx`'s "highlights the whole row
                // when any cell in it takes focus" pins this highlight
                // through `rows[1].style.background`, and with the paint moved to a
                // class that assertion fails with `expected '' not to be ''`. That
                // test is not this task's to edit, so the honest move is the colour
                // swap plus a report. `.rowActive` is declared and ready for
                // whoever is allowed to change the pin.
                style={{
                  background: active === item.position ? 'var(--color-surface-active)' : undefined,
                }}
              >
                <td className={styles.position}>{item.position}</td>
                <td>
                  <TextCell
                    label={`Description ${item.position}`}
                    value={fields[`${at}.description_raw`]}
                    error={errors?.[`${at}.description_raw`]}
                    // `description_raw` is a required column, and it is the one
                    // text path here that does not report `null` when emptied:
                    // measured, `_coerce_text(None)` is `''` rather than an error,
                    // so `null` and `''` would land on the same column value and
                    // sending the string is the honest one.
                    onChange={(raw) => onChange(`${at}.description_raw`, raw)}
                  />
                </td>
                <td>
                  <TextCell
                    label={`SKU ${item.position}`}
                    value={fields[`${at}.sku`]}
                    error={errors?.[`${at}.sku`]}
                    onChange={(raw) => onChange(`${at}.sku`, raw === '' ? null : raw)}
                  />
                </td>
                <td className={styles.money}>
                  {/* `qty` is `_coerce_money`, not `_coerce_int` -- grep
                      `repository.py` for `"qty": ("qty", _coerce_money)`.
                      "9.800" is a real quantity here. */}
                  <MoneyInput
                    label={`Qty ${item.position}`}
                    value={fields[`${at}.qty`]}
                    error={errors?.[`${at}.qty`]}
                    onChange={(value) => onChange(`${at}.qty`, value)}
                  />
                </td>
                <td>
                  <TextCell
                    label={`Unit ${item.position}`}
                    value={fields[`${at}.unit`]}
                    error={errors?.[`${at}.unit`]}
                    onChange={(raw) => onChange(`${at}.unit`, raw === '' ? null : raw)}
                  />
                </td>
                <td className={styles.money}>
                  <MoneyInput
                    label={`Unit price ${item.position}`}
                    value={fields[`${at}.unit_price`]}
                    error={errors?.[`${at}.unit_price`]}
                    onChange={(value) => onChange(`${at}.unit_price`, value)}
                  />
                </td>
                <td className={styles.money}>
                  <MoneyInput
                    label={`Line total ${item.position}`}
                    value={fields[`${at}.line_total`]}
                    error={errors?.[`${at}.line_total`]}
                    onChange={(value) => onChange(`${at}.line_total`, value)}
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
