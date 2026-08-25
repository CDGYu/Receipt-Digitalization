import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReceiptDetailPanel } from '../src/receipts/ReceiptDetailPanel'
import type { Money, ReceiptDetail } from '../src/api/types'

/** The Results screen's detail panel -- viewing and correcting a finished
 *  receipt without leaving the list.
 *
 * ## It is a second ENTRY POINT, never a second write path
 *
 * Everything it renders is a `src/review` component and everything it sends
 * goes through `patchReceipt` and `buildPatch`, the same pair `ReviewScreen`
 * uses. That is the whole design: two ways to *reach* an edit, one
 * implementation of the edit. A separate correction path here would have to
 * re-derive the diff, and PAN redaction lives server-side in `_plan_change`,
 * so a second client-side path is exactly how that protection gets lost.
 *
 * ## What this panel must NOT do, and why each is pinned below
 *
 * **It must never complete a review task.** `ReviewScreen.approve()` is a PATCH
 * *plus* a `completeTask`; Results gets the PATCH half only. The receipt shown
 * here was never claimed, so closing a task would close somebody else's -- or
 * none. `patch_receipt` (`review/api.py`) requires only an authenticated user
 * and no claim, which is what makes the PATCH half legitimate on its own.
 *
 * **It must never write to the review stash.** `src/review/stash.ts` holds one
 * module-level slot keyed by `taskId`, and `remember()` overwrites it
 * unconditionally. A Results edit has no task to key by, so stashing would mean
 * inventing a key -- and would silently evict a reviewer's in-flight queue
 * draft. `SignOutControl` also gates sign-out on `hasDirtyEdits()`, so a
 * stashed Results edit would demand confirmation naming a task that does not
 * exist.
 */

const RECEIPT: ReceiptDetail = {
  id: 'a1',
  status: 'needs_review',
  confidence: '0.620' as Money,
  confidence_reasons: [{ reason: 'validation errors present', penalty: '-0.35' as Money }],
  merchant_name_raw: 'Whole Foods Market',
  buyer: { name: 'IDEAL SOURCE', tax_id: null },
  receipt_number: 'WF-100244',
  txn_date: '2026-07-14',
  date_raw: "  1L/O7/2O26 '~ ",
  txn_time: '09:31:02',
  currency: 'USD',
  created_at: '2026-07-14T09:31:02+00:00',
  payment_method: 'VISA',
  card_last4: '4242',
  is_handwritten: false,
  legibility: 'good',
  duplicate_of: null,
  receipt_is_inconsistent: false,
  totals: {
    subtotal: '90.00' as Money,
    tax: '7.43' as Money,
    discount: null,
    total: '97.43' as Money,
    tender: '100.00' as Money,
    change: '2.57' as Money,
  },
  line_items: [],
  findings: [
    {
      rule_id: 'R020',
      severity: 'error',
      message: 'subtotal + tax does not equal total',
      context: null,
      resolved_by_repair: false,
    },
  ],
}

function mount(overrides: Partial<Parameters<typeof ReceiptDetailPanel>[0]> = {}) {
  const patch = vi.fn(async () => RECEIPT)
  const props = {
    receiptId: 'a1',
    onClose: vi.fn(),
    fetchReceipt: vi.fn(async () => RECEIPT),
    fetchImageUrl: vi.fn(async () => '/receipts/a1/image/blob?exp=1&sig=s'),
    patchReceipt: patch,
    ...overrides,
  }
  render(<ReceiptDetailPanel {...props} />)
  return props
}

afterEach(cleanup)

describe('the results detail panel', () => {
  it('shows what was extracted, once the detail arrives', async () => {
    mount()
    // The merchant is the field a person checks first against the photograph,
    // and it arrives from `fetchReceipt` rather than from the list row -- the
    // row carries a summary, this carries every correctable path.
    const merchant = await screen.findByDisplayValue('Whole Foods Market')
    expect(merchant).toBeDefined()
    expect(screen.getByDisplayValue('WF-100244')).toBeDefined()
  })

  it('sends only the path that changed, not the whole form', async () => {
    const props = mount()
    const merchant = await screen.findByDisplayValue('Whole Foods Market')
    await userEvent.clear(merchant)
    await userEvent.type(merchant, 'Whole Foods')
    await userEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => expect(props.patchReceipt).toHaveBeenCalled())
    const [id, sent] = (props.patchReceipt as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(id).toBe('a1')
    // `buildPatch` diffs against the original, so an untouched receipt sends
    // nothing and a one-field edit sends one key. Asserting the whole object
    // rather than just the presence of `merchant.name` is what catches a panel
    // that resends every field it rendered.
    expect(sent).toEqual({ 'merchant.name': 'Whole Foods' })
  })

  it('never completes a review task, and never writes the review stash', () => {
    // Read as source rather than spied on. A spy proves this run did not call
    // `completeTask`; the source proves the panel cannot, on any path, including
    // the error branches a test would have to contrive to reach. `dirname` +
    // `fileURLToPath` because `import.meta.url` is not a file URL under jsdom --
    // `stylesheets.test.ts` and `receipts-screen.test.tsx` read the tree the
    // same way for the same reason.
    const here = dirname(fileURLToPath(import.meta.url))
    const raw = readFileSync(
      join(here, '..', 'src', 'receipts', 'ReceiptDetailPanel.tsx'),
      'utf8',
    )
    // **Comments are stripped first, and that is not a detail.** The panel's
    // own docstring explains at length why it does not call `completeTask` --
    // so a bare `includes` matched the explanation and failed on prose while
    // the code was already correct. Measured: this assertion was red against a
    // file with no such call. A guard that cannot tell a mention from a call
    // reports the documentation as the defect.
    const code = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')

    expect(code.includes('completeTask')).toBe(false)
    // `stash` catches the import, `remember` and `hasDirtyEdits` alike: none of
    // them is reachable without the module name appearing in code.
    expect(code.includes('stash')).toBe(false)
    // Non-vacuity: stripping must not have emptied the file, or both assertions
    // above pass on nothing. `patchReceipt` is the call this panel exists to make.
    expect(code.includes('patchReceipt')).toBe(true)
  })

  it('closes without sending anything when nothing was edited', async () => {
    const props = mount()
    await screen.findByDisplayValue('Whole Foods Market')
    await userEvent.click(screen.getByRole('button', { name: /close/i }))
    expect(props.onClose).toHaveBeenCalled()
    expect(props.patchReceipt).not.toHaveBeenCalled()
  })
})
