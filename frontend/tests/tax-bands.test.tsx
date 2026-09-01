import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TaxBands } from '../src/review/TaxBands'
import { fieldsFromReceipt } from '../src/review/patch'
import type { Money, ReceiptDetail, TaxBand } from '../src/api/types'

/** The printed tax breakdown, as a reviewer meets it.
 *
 * The gap this closes, in the owner's words: a BIR sales invoice's "Amount: Net
 * of VAT" and "ADD: VAT" never reached the review screen. They were extracted
 * on every run -- the prompt asks for `totals.tax_breakdown` by name -- and
 * then discarded at persistence, because no column held them.
 */

afterEach(() => {
  cleanup()
})

function band(over: Partial<TaxBand> = {}): TaxBand {
  return {
    label: 'VATable Sales',
    base: '1785.71' as Money,
    rate: '12' as Money,
    amount: '214.29' as Money,
    ...over,
  }
}

function receiptWith(bands: TaxBand[]): ReceiptDetail {
  return {
    id: 'r-1',
    status: 'needs_review',
    prices_include_tax: null,
    confidence: '0.410' as Money,
    confidence_reasons: [],
    merchant_name_raw: 'Tesco Express',
    buyer: { name: null, tax_id: null },
    receipt_number: 'OR-1',
    txn_date: '2026-08-20',
    date_raw: null,
    txn_time: null,
    currency: 'PHP',
    created_at: '2026-08-25T09:00:00+00:00',
    payment_method: null,
    card_last4: null,
    is_handwritten: null,
    legibility: 'good',
    duplicate_of: null,
    receipt_is_inconsistent: null,
    totals: {
      subtotal: '1785.71' as Money,
      tax: '214.29' as Money,
      discount: null,
      total: '2000.00' as Money,
      tender: null,
      change: null,
      tax_breakdown: bands,
    },
    line_items: [],
    findings: [],
    current_findings: [],
    not_rechecked: [],
    field_boxes: {},
  }
}

function renderBands(bands: TaxBand[], onChange = vi.fn()) {
  const receipt = receiptWith(bands)
  const fields = fieldsFromReceipt(receipt)
  render(<TaxBands bands={bands} fields={fields} onChange={onChange} errors={null} />)
  return { onChange, fields }
}

describe('the tax breakdown', () => {
  it('shows every printed band', () => {
    renderBands([band(), band({ label: 'VAT-Exempt Sales', base: '0' as Money, amount: null })])

    const rows = within(screen.getByRole('table')).getAllByRole('row')
    // Header plus both bands.
    expect(rows.length).toBe(3)
    expect(screen.getByDisplayValue('VATable Sales')).toBeTruthy()
    expect(screen.getByDisplayValue('VAT-Exempt Sales')).toBeTruthy()
  })

  it('leaves a figure the receipt did not print blank, never zero', () => {
    // "Do not compute bands that are not printed" is the extraction prompt's
    // own rule. A `0` here would be the interface inventing a figure.
    renderBands([band({ amount: null })])

    const amount = screen.getByLabelText('Band 1 amount') as HTMLInputElement
    expect(amount.value).toBe('')
  })

  it('renders the rate exactly as it arrived, without rescaling it', () => {
    // The convention upstream is UNSTATED: `TaxBand.rate` carries no
    // description and the prompt asks only for "rate bands", so 12% may arrive
    // as `12` or as `0.12`. Anything that divided by 100 here would rewrite the
    // document.
    renderBands([band({ rate: '12' as Money })])

    expect((screen.getByLabelText('Band 1 rate') as HTMLInputElement).value).toBe('12')
  })

  it('sends an edit under the correction path the API resolves', async () => {
    // `totals.tax_breakdown[0].amount` was documented in `extract/paths.py` as
    // valid grammar long before anything could apply it. This is the path.
    const { onChange } = renderBands([band()])

    await userEvent.clear(screen.getByLabelText('Band 1 amount'))

    expect(onChange).toHaveBeenCalledWith('totals.tax_breakdown[0].amount', null)
  })

  it('addresses the second band by index one, not by a position it does not have', async () => {
    // Unlike `line_items`, `TaxBand` has no position field for the model to
    // emit -- `_build_tax_bands` numbers by list order -- so the index IS the
    // position and there can be no gap.
    const { onChange } = renderBands([band(), band({ label: 'Zero-Rated' })])

    await userEvent.clear(screen.getByLabelText('Band 2 base'))

    expect(onChange).toHaveBeenCalledWith('totals.tax_breakdown[1].base', null)
  })

  it('says why an empty breakdown may not mean the paper had none', () => {
    // Two different facts arrive as one empty list. A receipt processed before
    // the bands were storable shows none even if the paper printed them, and no
    // backfill was possible because the data was never written.
    renderBands([])

    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByText(/processed before the breakdown was stored/i)).toBeTruthy()
  })

  it('repeats no column header inside its own rows', () => {
    // The defect `LineItemsTable` shipped with: `MoneyInput` paints its label,
    // which is right in a form and wrong in a table whose header already says
    // it. Every band would otherwise read "Band 1 base" beside BASE.
    renderBands([band()])

    // **Not an assertion about `textContent`.** The first version of this test
    // asserted the row did not CONTAIN "Band 1 base" and failed -- correctly.
    // The label is clipped, not removed: it stays in the DOM because it IS the
    // input's accessible name, and `display: none` would leave the control
    // nameless. So the text is present and invisible, and the thing to assert
    // is which of those two the markup asks for.
    const label = screen.getByLabelText('Band 1 base').closest('label')
    const painted = label?.querySelector('span')
    expect(painted?.className).toContain('labelHidden')
    // And the name still reaches assistive technology.
    expect(screen.getByLabelText('Band 1 base')).toBeTruthy()
  })
})

describe('the stylesheet and the component agree', () => {
  it('names no class the stylesheet does not define', () => {
    // Vitest runs with `css: false`, so a `.module.css` import is a proxy that
    // echoes its keys: `styles.typo` renders the string "typo" and every render
    // test stays green while the rule paints nothing. Only reading both files
    // as text can see it.
    const here = dirname(fileURLToPath(import.meta.url))
    const tsx = readFileSync(join(here, '..', 'src', 'review', 'TaxBands.tsx'), 'utf8')
    const css = readFileSync(join(here, '..', 'src', 'review', 'TaxBands.module.css'), 'utf8')
    const defined = new Set([...css.matchAll(/\.([A-Za-z][A-Za-z0-9_-]*)/g)].map((m) => m[1]))
    const used = [...tsx.matchAll(/styles\.([A-Za-z][A-Za-z0-9_]*)/g)].map((m) => m[1])

    expect(used.length).toBeGreaterThan(0)
    for (const name of used) {
      expect(defined.has(name), `styles.${name} has no rule in TaxBands.module.css`).toBe(true)
    }
  })
})
