import { useId, useState } from 'react'
import { MoneyInput } from './MoneyInput'
import type { LineItem } from '../api/types'
import type { FieldMap } from './patch'

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
 * the server's words nowhere at all. */
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
        type="text"
        aria-label={label}
        value={value ?? ''}
        aria-describedby={error !== undefined ? errorId : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {error !== undefined ? (
        <p role="alert" id={errorId}>
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
 */
export function LineItemsTable({ items, fields, onChange, errors }: LineItemsTableProps) {
  const [active, setActive] = useState<number | null>(null)
  return (
    <table>
      <thead>
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
              onFocus={() => setActive(item.position)}
              style={{ background: active === item.position ? '#fffbe6' : undefined }}
            >
              <td>{item.position}</td>
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
              <td>
                {/* `qty` is `_coerce_money`, not `_coerce_int`
                    (repository.py:932) -- "9.800" is a real quantity here. */}
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
              <td>
                <MoneyInput
                  label={`Unit price ${item.position}`}
                  value={fields[`${at}.unit_price`]}
                  error={errors?.[`${at}.unit_price`]}
                  onChange={(value) => onChange(`${at}.unit_price`, value)}
                />
              </td>
              <td>
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
  )
}
