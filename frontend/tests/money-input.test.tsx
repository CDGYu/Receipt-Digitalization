import { useState } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MoneyInput } from '../src/review/MoneyInput'

afterEach(cleanup)

/** `MoneyInput` is controlled, so typing into one whose `value` prop never
 *  changes discards every keystroke but the last -- measured: typing `1000.00`
 *  against a fixed `value=""` ends with `onChange("0")`. This host feeds the
 *  reported value back the way `ReceiptForm` does, which is the only
 *  configuration in which a multi-character edit means anything. */
function Controlled({
  label,
  initial,
  onChange,
}: {
  label: string
  initial: string | null
  onChange: (next: string | null) => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <MoneyInput
      label={label}
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange(next)
      }}
    />
  )
}

describe('MoneyInput', () => {
  it('is never a number input (ADR-0001)', () => {
    render(<MoneyInput label="Total" value={'1000.00'} onChange={() => {}} />)
    const input = screen.getByLabelText('Total') as HTMLInputElement
    expect(input.type).toBe('text')
    expect(input.inputMode).toBe('decimal')
  })

  it('reports the typed value as a string, preserving trailing zeros', async () => {
    const onChange = vi.fn()
    render(<Controlled label="Total" initial="" onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('Total'), '1000.00')
    expect(onChange).toHaveBeenLastCalledWith('1000.00')
    expect(onChange).not.toHaveBeenCalledWith(1000)
    // And the box still shows them, which is what a reviewer checks against the
    // photograph. A number input would render 1000 here.
    expect((screen.getByLabelText('Total') as HTMLInputElement).value).toBe('1000.00')
  })

  it('shows a null amount as an empty field rather than as a zero', () => {
    // `money()` (review/serializers.py:66-74) never rewrites `None` to `"0.00"`:
    // an amount that was never recorded is not a recorded zero. The input must
    // not undo that.
    render(<MoneyInput label="Discount" value={null} onChange={() => {}} />)
    expect((screen.getByLabelText('Discount') as HTMLInputElement).value).toBe('')
  })

  it('clears to null, so the field is emptied rather than set to ""', async () => {
    // `_coerce_money(None)` returns `None` (repository.py:828-829) while `""`
    // raises `not a decimal amount`. Emptying the box has to mean the first.
    const onChange = vi.fn()
    render(<MoneyInput label="Change" value={'20.00'} onChange={onChange} />)
    await userEvent.clear(screen.getByLabelText('Change'))
    expect(onChange).toHaveBeenLastCalledWith(null)
  })

  it('gives each instance its own id so two fields do not share a label', async () => {
    const onChange = vi.fn()
    render(
      <>
        <MoneyInput label="Subtotal" value={'90.00'} onChange={() => {}} />
        <MoneyInput label="Tax" value={'7.43'} onChange={onChange} />
      </>,
    )
    await userEvent.type(screen.getByLabelText('Tax'), '9')
    expect(onChange).toHaveBeenLastCalledWith('7.439')
    expect((screen.getByLabelText('Subtotal') as HTMLInputElement).value).toBe('90.00')
  })
})
