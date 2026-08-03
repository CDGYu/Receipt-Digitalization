import { useId } from 'react'

export interface MoneyInputProps {
  readonly label: string
  readonly value: string | null
  readonly onChange: (next: string | null) => void
  /** The server's words for this field, verbatim, when the last submit was
   *  refused because of it. Rendering is additive: the summary alert at the
   *  bottom of the screen still carries the same message. */
  readonly error?: string | null
}

/** A money field. **Never `type="number"`.**
 *
 * ADR-0015 bans the number input on money fields in the same breath as the float
 * path: `valueAsNumber` is a float or `NaN`, and the browser reformats what it
 * shows. `type="text" inputMode="decimal"` keeps the exact characters the API
 * sent and still brings up a numeric keypad on a phone.
 *
 * The `type` is a literal, not an expression.
 * `tests/no-float-in-money-path.test.ts` matches a JSX `type` attribute whose
 * value is the string `number` in any spelling, but a computed one
 * (`type={cond ? 'number' : 'text'}`) is not a string literal and is not
 * matched -- measured, see the task report -- so the guard would not catch this
 * file going wrong that way. Keep it a literal.
 *
 * Emptying the box reports `null`, not `""`. Measured: `_coerce_money(None)` is
 * `None` while `_coerce_money('')` raises
 * `ValueError: not a decimal amount: ''`, so "no amount" and "the empty string"
 * are not interchangeable on the way back.
 *
 * `useId` rather than a caller-supplied id: `LineItemsTable` renders one of
 * these per money column per row, and a duplicated `htmlFor` would point every
 * label at the first input.
 *
 * **The error paragraph sits outside the `<label>`, not inside it.** It is
 * linked by `aria-describedby`, which is an id reference and needs no
 * containment. Nested, it silently renames the field: a label's text is
 * everything under it that is not itself a form control (`getTextContent`,
 * @testing-library/dom 10.4.1 `label-helpers.js`), so an error inside makes the
 * label read `Total` + the server's sentence. Measured, with the paragraph
 * nested: `screen.getByLabelText('Total')` throws `TestingLibraryElementError:
 * Unable to find a label with the text of: Total`. That is not a test artefact
 * -- the same concatenation is what a screen reader announces as the field's
 * name, and the message would then be read twice, once as the name and once as
 * the description.
 */
export function MoneyInput({ label, value, onChange, error }: MoneyInputProps) {
  const id = useId()
  const errorId = useId()
  const active = error != null
  return (
    <>
      <label htmlFor={id}>
        {label}
        <input
          id={id}
          type="text"
          inputMode="decimal"
          value={value ?? ''}
          aria-describedby={active ? errorId : undefined}
          onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        />
      </label>
      {active ? (
        <p role="alert" id={errorId}>
          {error}
        </p>
      ) : null}
    </>
  )
}
