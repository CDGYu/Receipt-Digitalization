import { useId } from 'react'
import styles from './MoneyInput.module.css'

export interface MoneyInputProps {
  readonly label: string
  /** Render the label to assistive technology only.
   *
   *  For a money cell inside a table whose column header ALREADY says "Unit
   *  price": painting it again in every row repeats the header once per line
   *  item. Left visible in a form, where the label is the only thing naming the
   *  field.
   *
   *  Clipped rather than `display: none` or `visibility: hidden`. Both of those
   *  take the text out of the accessibility tree, which would leave the input
   *  with NO accessible name -- the opposite of the intent. */
  readonly labelHidden?: boolean
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
 * **`placeholder="—"` is design §4's input half, and it is the reason this task
 * exists.** `Value` renders the mark for a value that is merely displayed; an
 * editable amount that was never extracted was a blank box until this line, and
 * a blank box is indistinguishable from a field nobody has filled in yet -- on
 * the one screen where a human decides whether the machine's `null` is right.
 * The placeholder is not the accessible name and cannot become one: the
 * `<label htmlFor>` above supplies it, and the accessible-name algorithm reaches
 * a placeholder only when nothing else names the control.
 *
 * Its paint is `--color-null` (`MoneyInput.module.css`), which is the same token
 * `Value` uses for the same glyph, so the two halves of §4 agree by construction
 * rather than by coincidence.
 *
 * **`autoComplete="off"` is §5.1's**, and it is not decoration here: the browser
 * offering a remembered `1000.00` under a total transcribed from a photograph
 * invites a reviewer to accept a number that came from another receipt.
 *
 * What §5.1 also asks for and this file deliberately does **not** do is the
 * currency prefix. §5.1 wants the symbol "outside the input"; the markup is
 * `<label>{label}<input/></label>`, so outside the input is *inside the label*,
 * and a prefix span there joins the field's accessible name by exactly the
 * name-from-content walk documented below -- `Total` would become `Total ₱`.
 * Controller ruling, user-approved 2026-08-06: the prefix is parked as an open
 * design question rather than implemented against the measurement.
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
export function MoneyInput({ label, labelHidden, value, onChange, error }: MoneyInputProps) {
  const id = useId()
  const errorId = useId()
  const active = error != null
  return (
    <>
      <label className={styles.field} htmlFor={id}>
        <span className={labelHidden === true ? styles.labelHidden : undefined}>{label}</span>
        <input
          id={id}
          className={active ? `${styles.input} ${styles.invalid}` : styles.input}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder="—"
          value={value ?? ''}
          aria-describedby={active ? errorId : undefined}
          onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        />
      </label>
      {active ? (
        <p className={styles.error} role="alert" id={errorId}>
          {error}
        </p>
      ) : null}
    </>
  )
}
