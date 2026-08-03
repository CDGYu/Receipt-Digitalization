import { useState } from 'react'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LineItemsTable } from '../src/review/LineItemsTable'
import { ReceiptForm } from '../src/review/ReceiptForm'
import { fieldsFromReceipt } from '../src/review/patch'
import type { FieldMap } from '../src/review/patch'
import type { LineItem, Money, ReceiptDetail } from '../src/api/types'

afterEach(cleanup)

const ITEMS: LineItem[] = [
  {
    position: 0,
    description_raw: 'DIESEL',
    sku: 'D-1',
    qty: '9.800' as Money,
    unit: 'L',
    unit_price: '102.04' as Money,
    line_total: '1000.00' as Money,
    modifiers: [],
    line_confidence: '0.900' as Money,
  },
  {
    position: 1,
    description_raw: 'CAR WASH',
    sku: null,
    qty: null,
    unit: null,
    unit_price: null,
    line_total: '80.00' as Money,
    modifiers: [],
    line_confidence: null,
  },
]

const RECEIPT: ReceiptDetail = {
  id: 'a1',
  status: 'needs_review',
  confidence: '0.620' as Money,
  confidence_reasons: [],
  merchant_name_raw: 'METRO OIL',
  receipt_number: 'INV-88213',
  txn_date: '2026-07-14',
  // Garbled on purpose: an OCR misread of the printed date is the case this
  // field exists to let a reviewer fix.
  date_raw: "  1L/O7/2O26 '~ ",
  txn_time: '14:30:45',
  currency: 'USD',
  created_at: '2026-07-14T09:31:02+00:00',
  payment_method: 'VISA',
  card_last4: '4242',
  is_handwritten: false,
  legibility: 'fair',
  duplicate_of: null,
  receipt_is_inconsistent: true,
  totals: {
    subtotal: '1000.00' as Money,
    tax: '80.00' as Money,
    discount: null,
    total: '1080.00' as Money,
    tender: '1100.00' as Money,
    change: '20.00' as Money,
  },
  line_items: ITEMS,
  findings: [],
}

type Recorder = (path: string, value: string | null) => void

/** Both components are controlled, so a `fields` prop that never changes
 *  discards every edit but the first -- measured: clicking `Handwritten` twice
 *  against a fixed map reports `"true"` both times, because `checked` is
 *  recomputed from the same input each render. This host owns the map the way
 *  `ReviewScreen` does, which is the only configuration in which a second edit
 *  means anything. */
function Host({ what, onChange }: { what: 'form' | 'table'; onChange: Recorder }) {
  const [fields, setFields] = useState<FieldMap>(() => fieldsFromReceipt(RECEIPT))
  const record: Recorder = (path, value) => {
    setFields((previous) => ({ ...previous, [path]: value }))
    onChange(path, value)
  }
  if (what === 'form') {
    return <ReceiptForm fields={fields} onChange={record} />
  }
  return <LineItemsTable items={ITEMS} fields={fields} onChange={record} />
}

function renderForm() {
  const onChange = vi.fn()
  render(<Host what="form" onChange={onChange} />)
  return onChange
}

describe('ReceiptForm', () => {
  it('shows every correctable receipt value under a label a reviewer can find', () => {
    renderForm()
    const shown = (label: string) => (screen.getByLabelText(label) as HTMLInputElement).value
    expect(shown('Merchant')).toBe('METRO OIL')
    expect(shown('Receipt number')).toBe('INV-88213')
    expect(shown('Date (ISO)')).toBe('2026-07-14')
    expect(shown('Printed date')).toBe("  1L/O7/2O26 '~ ")
    expect(shown('Time')).toBe('14:30:45')
    expect(shown('Currency')).toBe('USD')
    expect(shown('Payment method')).toBe('VISA')
    expect(shown('Card last 4')).toBe('4242')
    expect(shown('Subtotal')).toBe('1000.00')
    expect(shown('Tax')).toBe('80.00')
    expect(shown('Discount')).toBe('')
    expect(shown('Total')).toBe('1080.00')
    expect(shown('Tender')).toBe('1100.00')
    expect(shown('Change')).toBe('20.00')
  })

  it('never binds the time to a control that reformats it', () => {
    // `txn_time` arrives as `HH:MM:SS` from `isoformat()`. `<input type="time">`
    // renders and reports `HH:MM`, and `_coerce_time` accepts that rather than
    // rejecting it -- so the seconds would be silently truncated and a
    // `corrections` row written for an edit nobody made. Measured: the source
    // guard tests/no-float-in-money-path.test.ts does NOT catch `type="time"`
    // (it returned `[]` for `<input type="time" value={v} />`), so this is the
    // only thing binding it.
    renderForm()
    const time = screen.getByLabelText('Time') as HTMLInputElement
    expect(time.type).toBe('text')
    expect(time.value).toBe('14:30:45')
  })

  it('reports the write path, not the read key, when a field is edited', async () => {
    const onChange = renderForm()
    await userEvent.type(screen.getByLabelText('Merchant'), '!')
    expect(onChange).toHaveBeenLastCalledWith('merchant.name', 'METRO OIL!')
  })

  it('clears a text field to null rather than to the empty string', async () => {
    const onChange = renderForm()
    await userEvent.clear(screen.getByLabelText('Card last 4'))
    expect(onChange).toHaveBeenLastCalledWith('payment.card_last4', null)
  })

  it('offers exactly the four legibility values the enum has', async () => {
    const onChange = renderForm()
    const select = screen.getByLabelText('Legibility') as HTMLSelectElement
    // `Legibility` (src/receipts/extract/schema.py:23-27). `_coerce_legibility`
    // calls `Legibility(value)`, so a fifth option would be a 400.
    expect([...select.options].map((option) => option.value)).toEqual([
      'good',
      'fair',
      'poor',
      'unreadable',
    ])
    expect(select.value).toBe('fair')
    await userEvent.selectOptions(select, 'poor')
    expect(onChange).toHaveBeenLastCalledWith('meta.legibility', 'poor')
  })

  it('sends a boolean as the text _coerce_bool reads, never as null', async () => {
    const onChange = renderForm()
    const handwritten = screen.getByLabelText('Handwritten') as HTMLInputElement
    expect(handwritten.checked).toBe(false)
    expect((screen.getByLabelText('Receipt is inconsistent') as HTMLInputElement).checked).toBe(
      true,
    )
    await userEvent.click(handwritten)
    expect(onChange).toHaveBeenLastCalledWith('meta.is_handwritten', 'true')
    await userEvent.click(handwritten)
    expect(onChange).toHaveBeenLastCalledWith('meta.is_handwritten', 'false')
  })

  it('offers the printed date as free text, never as a date control', () => {
    // `receipt.date_raw` is what the machine read off the paper, and the model
    // misreads it -- so it is correctable. It must stay free text:
    // `<input type="date">` refuses to display anything that is not a valid
    // `YYYY-MM-DD`, which is precisely the value a reviewer opens this field to
    // repair. Server side it is `_coerce_optional_text` (measured:
    // `'2026-13-45'` in, `'2026-13-45'` out), so free text is what the API
    // expects.
    renderForm()
    const printed = screen.getByLabelText('Printed date') as HTMLInputElement
    expect(printed.type).toBe('text')
    expect(printed.value).toBe("  1L/O7/2O26 '~ ")
  })

  it('sends the corrected printed date verbatim, including its spacing', async () => {
    const onChange = renderForm()
    const printed = screen.getByLabelText('Printed date')
    await userEvent.clear(printed)
    await userEvent.type(printed, ' 14 / 07 / 2026 ')
    expect(onChange).toHaveBeenLastCalledWith('receipt.date_raw', ' 14 / 07 / 2026 ')
  })

  it('clears the printed date to null, not to an empty string', async () => {
    const onChange = renderForm()
    await userEvent.clear(screen.getByLabelText('Printed date'))
    expect(onChange).toHaveBeenLastCalledWith('receipt.date_raw', null)
  })

  it('has no control that is not one of the seventeen it offers', () => {
    // An absence assertion: an eighteenth path would be a 400 naming it, and a
    // stray control is how one gets added by accident. 8 text + 6 money = 14
    // textboxes, plus the legibility select and the two booleans.
    renderForm()
    expect(screen.getAllByRole('textbox')).toHaveLength(14)
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    expect(screen.getAllByRole('combobox')).toHaveLength(1)
  })
})

describe('LineItemsTable', () => {
  function renderTable() {
    const onChange = vi.fn()
    render(<Host what="table" onChange={onChange} />)
    return onChange
  }

  it('shows the seven columns and fills them from the item', () => {
    renderTable()
    const headers = screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    expect(headers).toEqual([
      '#',
      'Description',
      'SKU',
      'Qty',
      'Unit',
      'Unit price',
      'Line total',
    ])
    expect((screen.getByLabelText('Description 0') as HTMLInputElement).value).toBe('DIESEL')
    expect((screen.getByLabelText('Qty 0') as HTMLInputElement).value).toBe('9.800')
    expect((screen.getByLabelText('Line total 1') as HTMLInputElement).value).toBe('80.00')
    expect((screen.getByLabelText('SKU 1') as HTMLInputElement).value).toBe('')
  })

  it('keeps position read-only: six editable cells per row, and the number shown', () => {
    // `position` IS in `_LINE_ITEM_FIELDS` (repository.py:929) and would be
    // accepted, but swapping two of them trips the non-deferrable
    // `uq_line_items_receipt_position` (models.py:248) at flush time -- which
    // `apply_corrections` reports as a `ValueError` about the whole patch, not
    // about the row. So the UI does not offer it.
    renderTable()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    for (const [index, row] of rows.entries()) {
      expect(within(row).getAllByRole('textbox')).toHaveLength(6)
      expect(within(row).getAllByRole('cell')[0].textContent).toBe(String(index))
    }
  })

  it('offers no way to add or remove a row', () => {
    // `line_items[i]` addresses an item that already exists at position `i`;
    // `apply_corrections` raises `receipt ... has no line item at position i`
    // (repository.py:978-981) for anything else, and there is no delete path at
    // all. A button here would be a control that cannot work.
    renderTable()
    expect(within(screen.getByRole('table')).queryAllByRole('button')).toEqual([])
  })

  it('addresses each cell by the item position, in the grammar the server parses', async () => {
    const onChange = renderTable()
    await userEvent.type(screen.getByLabelText('Unit price 1'), '4')
    expect(onChange).toHaveBeenLastCalledWith('line_items[1].unit_price', '4')
    await userEvent.type(screen.getByLabelText('Description 0'), '!')
    expect(onChange).toHaveBeenLastCalledWith('line_items[0].description_raw', 'DIESEL!')
  })

  it('highlights the whole row when any cell in it takes focus', async () => {
    renderTable()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows[1].style.background).toBe('')
    // `.focus()` on its own is a DOM call outside React's act() scope, so the
    // state update it schedules is not flushed before the assertion -- measured:
    // the background was still `''`. `userEvent.click` focuses and flushes.
    await userEvent.click(screen.getByLabelText('Qty 1'))
    expect(rows[1].style.background).not.toBe('')
    expect(rows[0].style.background).toBe('')
  })
})

describe('inline field errors', () => {
  // The whole seventeen-path map plus the two rows' cells, so a path the test
  // does not name is still a rendered control that must stay clean.
  const FIELDS: FieldMap = fieldsFromReceipt(RECEIPT)

  it('renders the server message beside the matched field, linked by aria-describedby', () => {
    render(
      <ReceiptForm
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'totals.total': "not a decimal amount: 'abc'" }}
      />,
    )
    const input = screen.getByLabelText('Total') as HTMLInputElement
    const describedBy = input.getAttribute('aria-describedby')
    expect(describedBy).not.toBeNull()
    const description = document.getElementById(describedBy!)
    expect(description?.textContent).toBe("not a decimal amount: 'abc'")
    expect(description?.getAttribute('role')).toBe('alert')
  })

  it('renders no describedby and no alert for untouched fields', () => {
    render(
      <ReceiptForm
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'totals.total': "not a decimal amount: 'abc'" }}
      />,
    )
    const clean = screen.getByLabelText('Subtotal') as HTMLInputElement
    expect(clean.getAttribute('aria-describedby')).toBeNull()
  })

  it('a text field carries its error the same way', () => {
    render(
      <ReceiptForm
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'receipt.currency': "currency holds at most 3 characters, got 5 ('EUROS')" }}
      />,
    )
    const input = screen.getByLabelText('Currency') as HTMLInputElement
    const describedBy = input.getAttribute('aria-describedby')
    expect(document.getElementById(describedBy!)?.textContent).toContain('at most 3 characters')
  })

  it('lands a line-item money error on the addressed cell and nowhere else', () => {
    render(
      <LineItemsTable
        items={ITEMS}
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'line_items[1].line_total': "not a decimal amount: 'abc'" }}
      />,
    )
    const blamed = screen.getByLabelText('Line total 1') as HTMLInputElement
    const describedBy = blamed.getAttribute('aria-describedby')
    expect(describedBy).not.toBeNull()
    const description = document.getElementById(describedBy!)
    expect(description?.textContent).toBe("not a decimal amount: 'abc'")
    expect(description?.getAttribute('role')).toBe('alert')
    // The same column one row up, and the same row one column across: a slot
    // keyed by anything looser than the full dotted path would light these too.
    expect(
      (screen.getByLabelText('Line total 0') as HTMLInputElement).getAttribute('aria-describedby'),
    ).toBeNull()
    expect(
      (screen.getByLabelText('Unit price 1') as HTMLInputElement).getAttribute('aria-describedby'),
    ).toBeNull()
  })

  it('gives a line-item text cell the same slot, though nothing can fill it today', () => {
    // `_coerce_text`/`_coerce_optional_text` never raise, so `description_raw`
    // cannot produce a 400 as the server stands. The slot is uniform anyway:
    // `classifyFailure` matches on any path that was sent, and a hit with
    // nowhere to land would render the message nowhere at all.
    render(
      <LineItemsTable
        items={ITEMS}
        fields={FIELDS}
        onChange={() => {}}
        errors={{ 'line_items[0].description_raw': 'refused' }}
      />,
    )
    const blamed = screen.getByLabelText('Description 0') as HTMLInputElement
    const describedBy = blamed.getAttribute('aria-describedby')
    expect(describedBy).not.toBeNull()
    expect(document.getElementById(describedBy!)?.textContent).toBe('refused')
    expect((screen.getByLabelText('SKU 0') as HTMLInputElement).getAttribute('aria-describedby')).toBeNull()
  })
})
