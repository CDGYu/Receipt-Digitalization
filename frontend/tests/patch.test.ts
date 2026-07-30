import { describe, expect, it } from 'vitest'
import { buildPatch, fieldsFromReceipt } from '../src/review/patch'
import type { Money, ReceiptDetail } from '../src/api/types'

/** A receipt with every correctable column populated and distinguishable.
 *
 * `txn_time` is `"14:30:45"` on purpose: `_iso_time`
 * (src/receipts/review/serializers.py:81-97) renders the column with
 * `isoformat()`, so seconds reach the browser and must go back unchanged.
 */
const RECEIPT: ReceiptDetail = {
  id: 'a1',
  status: 'needs_review',
  confidence: '0.620' as Money,
  confidence_reasons: [],
  merchant_name_raw: 'METRO OIL',
  receipt_number: 'INV-88213',
  txn_date: '2026-07-14',
  // Deliberately garbled, with padding. `date_raw` is whatever the model read
  // off the paper -- an OCR misread is the normal case, not the exotic one, and
  // it is exactly what a reviewer opens this field to fix.
  date_raw: "  1L/O7/2O26 '~ ",
  txn_time: '14:30:45',
  currency: 'USD',
  created_at: '2026-07-14T09:31:02+00:00',
  payment_method: 'VISA',
  card_last4: '4242',
  is_handwritten: false,
  legibility: 'good',
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
  line_items: [
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
  ],
  findings: [],
}

describe('buildPatch', () => {
  it('emits only the paths that changed', () => {
    const original = { 'totals.total': '1000.00', 'merchant.name': 'METRO OIL' }
    const edited = { 'totals.total': '1000.00', 'merchant.name': 'METRO OIL SUBIC' }
    expect(buildPatch(original, edited)).toEqual({ 'merchant.name': 'METRO OIL SUBIC' })
  })

  it('is empty when nothing changed, which is a legal "confirmed" patch', () => {
    const same = { 'totals.total': '1000.00' }
    expect(buildPatch(same, { ...same })).toEqual({})
  })

  it('carries an explicit null through as a cleared field', () => {
    expect(buildPatch({ 'receipt.time': '13:45' }, { 'receipt.time': null })).toEqual({
      'receipt.time': null,
    })
  })

  it('uses the dotted line-item grammar the server parses', () => {
    const original = { 'line_items[0].qty': '9.8' }
    const edited = { 'line_items[0].qty': '9.9' }
    expect(buildPatch(original, edited)).toEqual({ 'line_items[0].qty': '9.9' })
  })

  it('leaves an untouched null alone rather than re-sending it', () => {
    // The distinction the server draws with `exclude_unset`: omitted means
    // "never mentioned", present-and-null means "clear this". A discount that
    // was already null must take the first branch, or every confirmation would
    // book a correction for a field nobody edited.
    expect(buildPatch({ 'totals.discount': null }, { 'totals.discount': null })).toEqual({})
  })

  it('sends a value whose path the original never carried', () => {
    // `original` and `edited` are built by the same function from the same
    // receipt, so their key sets match in this app. The rule when they do not
    // is comparison by value: an absent key reads as `undefined`, which differs
    // from every `string | null`, so the edit is sent rather than dropped. A
    // dropped edit is the failure mode `_RECEIPT_FIELDS` being a closed map
    // exists to prevent.
    expect(buildPatch({}, { 'merchant.name': 'METRO OIL' })).toEqual({
      'merchant.name': 'METRO OIL',
    })
  })

  it('preserves trailing zeros rather than normalising the amount', () => {
    expect(buildPatch({ 'totals.total': '1000' }, { 'totals.total': '1000.00' })).toEqual({
      'totals.total': '1000.00',
    })
  })
})

describe('fieldsFromReceipt', () => {
  it('maps every correctable receipt path from the key the API reads it out under', () => {
    // The read and write names differ for six of the seventeen. Transcribed from
    // `_RECEIPT_FIELDS` (src/receipts/persist/repository.py:905-923) on the write
    // side and `receipt_detail` (src/receipts/review/serializers.py:190-218) on
    // the read side.
    expect(fieldsFromReceipt(RECEIPT)).toMatchObject({
      'merchant.name': 'METRO OIL', // <- merchant_name_raw
      'receipt.number': 'INV-88213', // <- receipt_number
      'receipt.date': '2026-07-14', // <- txn_date
      'receipt.date_raw': "  1L/O7/2O26 '~ ", // <- date_raw, verbatim
      'receipt.time': '14:30:45', // <- txn_time
      'receipt.currency': 'USD', // <- currency
      'totals.subtotal': '1000.00',
      'totals.tax': '80.00',
      'totals.discount': null,
      'totals.total': '1080.00',
      'totals.tender': '1100.00',
      'totals.change': '20.00',
      'payment.method': 'VISA', // <- payment_method
      'payment.card_last4': '4242', // <- card_last4
      'meta.is_handwritten': 'false', // <- is_handwritten, no meta. prefix
      'meta.legibility': 'good', // <- legibility, no meta. prefix
      'meta.receipt_is_inconsistent': 'true', // <- receipt_is_inconsistent
    })
  })

  it('emits exactly the seventeen receipt paths and six per line item', () => {
    // Pins the closed set in both directions: an invented path is a 400 naming
    // it, and a missing one is an edit the reviewer cannot make.
    expect(Object.keys(fieldsFromReceipt(RECEIPT)).sort()).toEqual(
      [
        'merchant.name',
        'receipt.number',
        'receipt.date',
        'receipt.date_raw',
        'receipt.time',
        'receipt.currency',
        'totals.subtotal',
        'totals.tax',
        'totals.discount',
        'totals.total',
        'totals.tender',
        'totals.change',
        'payment.method',
        'payment.card_last4',
        'meta.is_handwritten',
        'meta.legibility',
        'meta.receipt_is_inconsistent',
        'line_items[0].description_raw',
        'line_items[0].sku',
        'line_items[0].qty',
        'line_items[0].unit',
        'line_items[0].unit_price',
        'line_items[0].line_total',
        'line_items[1].description_raw',
        'line_items[1].sku',
        'line_items[1].qty',
        'line_items[1].unit',
        'line_items[1].unit_price',
        'line_items[1].line_total',
      ].sort(),
    )
  })

  it('leaves position out, because the UI does not offer it', () => {
    // `position` IS in `_LINE_ITEM_FIELDS` (repository.py:929) and is
    // server-correctable, but this UI keeps it read-only, so it must never
    // appear in a patch.
    expect(Object.keys(fieldsFromReceipt(RECEIPT))).not.toContain('line_items[0].position')
  })

  it('addresses a line item by its position, not by its index in the array', () => {
    // `_LINE_ITEM_PATH` resolves `line_items[i]` through
    // `items_by_position` (repository.py:1033), so `i` is the stored position.
    const gapped: ReceiptDetail = {
      ...RECEIPT,
      line_items: [{ ...RECEIPT.line_items[1], position: 7 }],
    }
    expect(Object.keys(fieldsFromReceipt(gapped))).toContain('line_items[7].line_total')
    expect(Object.keys(fieldsFromReceipt(gapped))).not.toContain('line_items[0].line_total')
  })

  it('renders a null boolean as null rather than as "false"', () => {
    // `is_handwritten` is nullable. "Not recorded" and "recorded as no" are
    // different facts, and `_coerce_bool` (repository.py:861-869) rejects
    // anything that is neither, so collapsing them would either invent an edit
    // or send a 400.
    const unknown: ReceiptDetail = {
      ...RECEIPT,
      is_handwritten: null,
      receipt_is_inconsistent: null,
    }
    const fields = fieldsFromReceipt(unknown)
    expect(fields['meta.is_handwritten']).toBeNull()
    expect(fields['meta.receipt_is_inconsistent']).toBeNull()
  })

  it('confirming an untouched receipt produces no corrections at all', () => {
    // The whole point of the omit-vs-null distinction, end to end. `{}` reaches
    // `apply_corrections` as "no changes, still mark reviewed"
    // (schemas.py:222-227). If any seeded value were reformatted on the way in
    // -- a time truncated to HH:MM, an amount stripped of its trailing zeros --
    // this would come back non-empty and the reviewer would get a `corrections`
    // row for an edit they never made.
    const original = fieldsFromReceipt(RECEIPT)
    expect(buildPatch(original, fieldsFromReceipt(RECEIPT))).toEqual({})
    expect(original['receipt.time']).toBe('14:30:45')
    expect(original['totals.subtotal']).toBe('1000.00')
    // A garbled `date_raw` is still an untouched one. Trimming it, or "helpfully"
    // normalising it on the way in, would put it in the patch and book a
    // correction against a field the reviewer never opened.
    expect(original['receipt.date_raw']).toBe("  1L/O7/2O26 '~ ")
  })

  it('carries an edited printed date out verbatim, whitespace and all', () => {
    // Nothing in this client may trim, pad, or reformat what the reviewer
    // typed: the point of the column is to record what the paper actually said.
    // This is a claim about **transmission** only. Measured through the real
    // PATCH route, the server rewrites some of what it receives -- `redact_pan`
    // runs after `_coerce_optional_text`, so `'4111111111111111'` is read back
    // as `'************1111'`. What leaves here goes verbatim; what lands in
    // the column is the server's business. See `ReceiptForm`'s docblock.
    const original = fieldsFromReceipt(RECEIPT)
    const edited = { ...original, 'receipt.date_raw': '  14 / 07 / 2026  ' }
    expect(buildPatch(original, edited)).toEqual({
      'receipt.date_raw': '  14 / 07 / 2026  ',
    })
  })

  it('clears the printed date to null rather than to an empty string', () => {
    // Measured: `_coerce_optional_text(None)` returns `None` while `''` returns
    // `''`, and `PATCH {'receipt.date_raw': None}` writes the correction
    // `('receipt.date_raw', '  14 / 07 / 2026  ', None)`. "Nothing was printed"
    // and "an empty string was printed" are different facts.
    //
    // Bound by neither of round 2's date_raw mutations -- measured, N3 and N6
    // both leave it green. The mutation that does trip it (`buildPatch` dropping
    // nulls) also trips `carries an explicit null through as a cleared field`
    // above, so this test adds no coverage that one does not already give.
    const original = fieldsFromReceipt(RECEIPT)
    expect(buildPatch(original, { ...original, 'receipt.date_raw': null })).toEqual({
      'receipt.date_raw': null,
    })
  })
})
