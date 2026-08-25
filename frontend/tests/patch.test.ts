import { describe, expect, it } from 'vitest'
import { buildPatch, fieldsFromReceipt, findRewrites } from '../src/review/patch'
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
  // The document's stated tax convention. `null` is the ordinary
  // reading: most receipts do not print one.
  prices_include_tax: null,
  confidence: '0.620' as Money,
  confidence_reasons: [],
  merchant_name_raw: 'METRO OIL',
  // Who the receipt was issued TO, which is not who issued it. Both halves
  // populated here and distinguishable from each other, like every other column
  // in this fixture; the receipt that carries neither is its own test below.
  buyer: { name: 'IDEAL SOURCE', tax_id: '009-123-456-000' },
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
    // No printed VAT bands: this fixture does not exercise a breakdown.
    tax_breakdown: [],
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
      is_template_row: null,
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
      is_template_row: null,
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
    // The read name and the write name differ for many of these, and no count is
    // quoted: the set grows and a number here would rot silently. Transcribed
    // from `_RECEIPT_FIELDS` (src/receipts/persist/repository.py) on the write
    // side and `receipt_detail` (src/receipts/review/serializers.py) on the read
    // side.
    expect(fieldsFromReceipt(RECEIPT)).toMatchObject({
      'merchant.name': 'METRO OIL', // <- merchant_name_raw
      // Nested under `buyer` on the read side, dotted on the write side, and the
      // two spell the same path -- so unlike `merchant.name` this one is a
      // rename of nothing. It is asserted anyway: `buyer` being an object is
      // exactly what a client can get wrong.
      'buyer.name': 'IDEAL SOURCE', // <- buyer.name
      'buyer.tax_id': '009-123-456-000', // <- buyer.tax_id
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

  it('emits exactly the receipt paths _RECEIPT_FIELDS accepts, and every line-item path', () => {
    // Pins the closed set in both directions: an invented path is a 400 naming
    // it, and a missing one is an edit the reviewer cannot make.
    //
    // **This list is a transcription, and it is not what binds the two maps.**
    // It is checked against `fieldsFromReceipt`, never against
    // `_RECEIPT_FIELDS`, so on its own it can be internally consistent and
    // wrong -- which is exactly what happened: it read as complete for 34
    // commits while the server accepted two paths nothing here mentioned. The
    // binding is
    // `test_every_correctable_receipt_path_is_offered_by_the_review_client`
    // (tests/test_repository.py), which parses this file's object literal
    // instead of copying it. What this test still adds is the half that pin
    // deliberately leaves out: the `line_items[i]` paths, and the exact shape
    // of the map rather than only its receipt-level keys.
    expect(Object.keys(fieldsFromReceipt(RECEIPT)).sort()).toEqual(
      [
        'merchant.name',
        'buyer.name',
        'buyer.tax_id',
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
        'line_items[0].is_template_row',
        'line_items[1].description_raw',
        'line_items[1].sku',
        'line_items[1].qty',
        'line_items[1].unit',
        'line_items[1].unit_price',
        'line_items[1].line_total',
        'line_items[1].is_template_row',
      ].sort(),
    )
  })

  it('carries a receipt with no Sold To block as null, never as empty text', () => {
    // Not every BIR form is filled in, and the extractor answers `null` when it
    // cannot read the block. `_coerce_optional_text(None)` is `None` while
    // `_coerce_optional_text('')` is `''`, and they land as different column
    // values -- so a `''` here would turn "nothing was printed" into "an empty
    // string was printed" on a field nobody touched.
    //
    // The keys are still present, which is the other half: `buildPatch` compares
    // by value, so a path missing from `original` reads as `undefined` and every
    // untouched `null` would be sent as an edit nobody made.
    const anonymous: ReceiptDetail = { ...RECEIPT, buyer: { name: null, tax_id: null } }
    const fields = fieldsFromReceipt(anonymous)
    expect(fields['buyer.name']).toBeNull()
    expect(fields['buyer.tax_id']).toBeNull()
    expect(Object.keys(fields)).toContain('buyer.name')
    expect(Object.keys(fields)).toContain('buyer.tax_id')
    expect(buildPatch(fields, fieldsFromReceipt(anonymous))).toEqual({})
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

describe('findRewrites', () => {
  it('reports a value the server rewrote, naming the field and both sides', () => {
    // `redact_pan` masks any 13-19 digit run, which includes plausible printed
    // data -- measured: `redact_pan('20260730123456')` is `'**********3456'`.
    // Without this the reviewer has no way to learn their input did not land.
    expect(
      findRewrites(
        { 'receipt.date_raw': '20260730123456' },
        { 'receipt.date_raw': '**********3456' },
      ),
    ).toEqual([{ path: 'receipt.date_raw', sent: '20260730123456', stored: '**********3456' }])
  })

  it('says nothing when the server kept exactly what was sent', () => {
    expect(findRewrites({ 'merchant.name': 'METRO OIL' }, { 'merchant.name': 'METRO OIL' })).toEqual(
      [],
    )
  })

  it('compares only the paths that were actually sent', () => {
    // Every other field on the receipt is untouched by definition -- the patch
    // omitted it -- so a difference there is not this reviewer's edit.
    expect(
      findRewrites(
        { 'merchant.name': 'METRO OIL' },
        { 'merchant.name': 'METRO OIL', 'totals.total': 'anything at all' },
      ),
    ).toEqual([])
  })

  describe('money: the column scale is not a rewrite', () => {
    // Measured through the real PATCH route -- EVERY money field comes back at
    // the column's scale, always:
    //   sent '1000.00' -> returned '1000.0000'    sent '1000' -> '1000.0000'
    //   sent '892.86'  -> returned '892.8600'     sent '2.5'  -> '2.5000'
    //   sent '-2.50'   -> returned '-2.5000'      sent '0.00' -> '0.0000'
    // A warning that fires on every money edit teaches reviewers to dismiss it,
    // so trailing fractional zeros are normalised away before comparing. The
    // amount is never converted to a number -- trim/indexOf/charAt/slice, and
    // every number in there is a string offset, not a digit (ADR-0001). What
    // establishes that is reading `withoutDisplayScale`; the float guard passes
    // but cannot settle it, having no rule that fires on arithmetic.
    const cases: ReadonlyArray<readonly [string, string, string]> = [
      ['a scale-only difference', '1000.00', '1000.0000'],
      ['no fractional part at all on the way in', '1000', '1000.0000'],
      ['a negative amount', '-2.50', '-2.5000'],
      ['zero', '0.00', '0.0000'],
      ['every fractional digit stripped', '0.000', '0'],
      ['a bare trailing point', '1000.', '1000.0000'],
      ['a quantity', '2.5', '2.5000'],
    ]
    for (const [label, sent, stored] of cases) {
      it(`is silent for ${label}: ${sent} -> ${stored}`, () => {
        expect(findRewrites({ 'totals.total': sent }, { 'totals.total': stored })).toEqual([])
        expect(
          findRewrites({ 'line_items[3].unit_price': sent }, { 'line_items[3].unit_price': stored }),
        ).toEqual([])
      })
    }

    it('never strips zeros to the left of the point', () => {
      // The bug this rules out: normalising `1000` to `1` would hide the server
      // turning a thousand into one.
      expect(findRewrites({ 'totals.total': '1000' }, { 'totals.total': '1' })).toEqual([
        { path: 'totals.total', sent: '1000', stored: '1' },
      ])
      expect(findRewrites({ 'totals.total': '100.00' }, { 'totals.total': '1.0000' })).toEqual([
        { path: 'totals.total', sent: '100.00', stored: '1.0000' },
      ])
    })

    it('still catches a coercion that changed the number', () => {
      // `'1,000.00'` normalises to `'1,000'` and the stored value to `'1000'`:
      // the stripped comma survives the exemption, which is the point of
      // normalising only trailing zeros rather than comparing loosely.
      expect(findRewrites({ 'totals.total': '1,000.00' }, { 'totals.total': '1000.0000' })).toEqual([
        { path: 'totals.total', sent: '1,000.00', stored: '1000.0000' },
      ])
    })

    it('does not extend the exemption to fields that are not money', () => {
      // `receipt.number` is `_coerce_optional_text`; trailing zeros there are
      // characters, not scale.
      expect(findRewrites({ 'receipt.number': '1000.00' }, { 'receipt.number': '1000.0000' })).toEqual(
        [{ path: 'receipt.number', sent: '1000.00', stored: '1000.0000' }],
      )
    })
  })

  it('reports a reformatted date, which is an exact comparison', () => {
    expect(findRewrites({ 'receipt.date': '2026-7-3' }, { 'receipt.date': '2026-07-03' })).toEqual([
      { path: 'receipt.date', sent: '2026-7-3', stored: '2026-07-03' },
    ])
  })

  it('reports a cleared field that came back with a value, and the reverse', () => {
    expect(findRewrites({ 'payment.method': null }, { 'payment.method': 'VISA' })).toEqual([
      { path: 'payment.method', sent: null, stored: 'VISA' },
    ])
    expect(findRewrites({ 'payment.method': 'VISA' }, { 'payment.method': null })).toEqual([
      { path: 'payment.method', sent: 'VISA', stored: null },
    ])
  })

  it('reports a path the reply does not carry at all as stored null', () => {
    // Reachable if a line item moved: `line_items[3].*` addresses a position,
    // so a reply whose items sit elsewhere has no key for it. Absent is not
    // "unchanged", and reporting it is the safe direction.
    expect(findRewrites({ 'line_items[3].sku': 'D-1' }, {})).toEqual([
      { path: 'line_items[3].sku', sent: 'D-1', stored: null },
    ])
  })
})

describe('findRewrites: the ways a reviewer legitimately types an amount', () => {
  // Every pair below was measured through the real PATCH route: the value on the
  // left was sent, the value on the right is what `GET` read back. `_coerce_money`
  // accepts all of them, so they reach the diff -- and `.50` for fifty cents is
  // an ordinary keystroke, not an exotic one. A warning that fires on it trains
  // reviewers to dismiss the warning, which is the failure this whole feature
  // exists to prevent.
  // `['1000.', '1000.0000']` is deliberately absent: it was a verbatim
  // duplicate of the `a bare trailing point` case in the block above, which
  // asserts the same pair *and* the line-item path, so this copy bound nothing
  // the other did not already bind.
  const accepted: ReadonlyArray<readonly [string, string]> = [
    ['.50', '0.5000'],
    ['-.50', '-0.5000'],
    ['1000.00 ', '1000.0000'],
    ['  1000.00  ', '1000.0000'],
    ['+1000.00', '1000.0000'],
  ]
  for (const [sent, stored] of accepted) {
    it(`is silent for ${JSON.stringify(sent)} -> ${stored}`, () => {
      expect(findRewrites({ 'totals.total': sent }, { 'totals.total': stored })).toEqual([])
    })
  }

  it('still reports the two spellings the normalisation deliberately leaves alone', () => {
    // Both measured through the real route: '00100.00' stores as '100.0000' and
    // '-0.00' as '0.0000'. Neither is a normal way to key an amount, and
    // stripping leading zeros is a separate rule with its own edges, so they stay
    // reported rather than guessed at. Pinned so the docblock saying so is bound.
    expect(findRewrites({ 'totals.total': '00100.00' }, { 'totals.total': '100.0000' })).toEqual([
      { path: 'totals.total', sent: '00100.00', stored: '100.0000' },
    ])
    expect(findRewrites({ 'totals.total': '-0.00' }, { 'totals.total': '0.0000' })).toEqual([
      { path: 'totals.total', sent: '-0.00', stored: '0.0000' },
    ])
  })

  it('still reports a representation the server genuinely rewrote', () => {
    // Measured: `PATCH {'totals.total': '1e3'}` is accepted and reads back
    // '1000.0000'. The amount is the same but the text is not what the reviewer
    // typed, and unlike a trailing zero that is worth showing -- it is the
    // server, not the column, that changed the characters.
    expect(findRewrites({ 'totals.total': '1e3' }, { 'totals.total': '1000.0000' })).toEqual([
      { path: 'totals.total', sent: '1e3', stored: '1000.0000' },
    ])
  })
})

describe('findRewrites: a path the reply does not carry', () => {
  it('reports it when a value was sent', () => {
    expect(findRewrites({ 'line_items[3].sku': 'D-1' }, {})).toEqual([
      { path: 'line_items[3].sku', sent: 'D-1', stored: null },
    ])
  })

  it('says nothing when the reviewer cleared it, because absent and null agree', () => {
    // Both mean "no value there". Reporting it would render as "you entered
    // (nothing), the receipt now holds (nothing)", which is not a warning.
    expect(findRewrites({ 'payment.method': null }, {})).toEqual([])
  })
})
