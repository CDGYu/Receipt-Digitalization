import { useId } from 'react'

export interface MoneyInputProps {
  readonly label: string
  readonly value: string | null
  readonly onChange: (next: string | null) => void
}

/** A money field. **Never `type="number"`.**
 *
 * ADR-0015 bans the number input on money fields in the same breath as the float
 * path: `valueAsNumber` is a float or `NaN`, and the browser reformats what it
 * shows. `type="text" inputMode="decimal"` keeps the exact characters the API
 * sent and still brings up a numeric keypad on a phone.
 *
 * The `type` is a literal, not an expression. `tests/no-float-in-money-path.ts`
 * matches a JSX `type` attribute whose value is the string `number` in any
 * spelling, but a computed one (`type={cond ? 'number' : 'text'}`) is not a
 * string literal and is not matched -- measured, see the task report -- so the
 * guard would not catch this file going wrong that way. Keep it a literal.
 *
 * Emptying the box reports `null`, not `""`. Measured: `_coerce_money(None)` is
 * `None` while `_coerce_money('')` raises
 * `ValueError: not a decimal amount: ''`, so "no amount" and "the empty string"
 * are not interchangeable on the way back.
 *
 * `useId` rather than a caller-supplied id: `LineItemsTable` renders one of
 * these per money column per row, and a duplicated `htmlFor` would point every
 * label at the first input.
 */
export function MoneyInput({ label, value, onChange }: MoneyInputProps) {
  const id = useId()
  return (
    <label htmlFor={id}>
      {label}
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      />
    </label>
  )
}
