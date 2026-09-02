import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { ConfidenceRail } from '../src/review/ConfidenceRail'
import type { ConfidenceReason, Money } from '../src/api/types'

// `globals: true` is deliberately absent from vite.config.ts, so
// `@testing-library/react` never installs its auto-cleanup `afterEach` and every
// component test has to unmount its own renders. The plan's version of this file
// had no `afterEach` -- see tests/image-pane.test.tsx, where the same omission
// makes one test fire its event at the previous test's component.
afterEach(cleanup)

const REASONS = [
  { reason: 'validation error R020', penalty: '-0.35' },
  { reason: 'handwritten', penalty: '-0.15' },
] as ConfidenceReason[]

describe('ConfidenceRail', () => {
  it('renders each reason and its penalty verbatim', () => {
    render(<ConfidenceRail confidence={'0.500' as Money} reasons={REASONS} />)
    expect(screen.getByText('validation error R020')).toBeDefined()
    expect(screen.getByText('-0.35')).toBeDefined()
  })

  it('distinguishes "nothing lowered the score" from "not recorded"', () => {
    const empty = render(<ConfidenceRail confidence={'1.000' as Money} reasons={[]} />)
    expect(empty.getByText(/nothing lowered/i)).toBeDefined()
    empty.unmount()

    const missing = render(<ConfidenceRail confidence={null} reasons={null} />)
    expect(missing.getByText(/not recorded/i)).toBeDefined()
  })

  it('reprints trailing zeros and a positive penalty exactly as they arrived', () => {
    // Every string here would change if anything numeric touched it: `0.05`
    // keeps no sign, `-0.160` loses its last zero, `1.000` becomes `1`. The
    // positive one is real -- `BONUS_MERCHANT_PRIOR` is +0.05
    // (src/receipts/score/confidence.py:95), stored through the same `penalty`
    // field as every deduction, so a rail that assumed a leading `-` or
    // reformatted the value would misreport it.
    const reasons = [
      { reason: 'verified merchant prior', penalty: '0.05' },
      { reason: '2 warning finding(s)', penalty: '-0.160' },
    ] as ConfidenceReason[]
    render(<ConfidenceRail confidence={'1.000' as Money} reasons={reasons} />)

    expect(screen.getByText('100%')).toBeDefined()
    expect(screen.getByText('0.05')).toBeDefined()
    expect(screen.getByText('-0.160')).toBeDefined()
  })

  it('shows an em dash for a score that was never recorded, never a zero', () => {
    // The project's own null-is-not-zero rule, on the one line that renders it.
    // `money()` keeps `None` as `null` all the way out (review/serializers.py
    // :65-73) precisely so the UI does not invent a recorded 0.000 here.
    render(<ConfidenceRail confidence={null} reasons={null} />)

    expect(screen.getByText('—')).toBeDefined()
    expect(screen.queryByText('0.000')).toBeNull()
    expect(screen.queryByText('0')).toBeNull()
  })

  it('marks the entry that raises the score, without touching its digits', () => {
    // `verified merchant prior` is the one positive "penalty", and in a bare
    // column it is indistinguishable from a deduction. The `+` is read off the
    // string's first character, never computed, so the digits stay byte-identical.
    const reasons = [
      { reason: 'verified merchant prior', penalty: '0.05' },
      { reason: 'validation errors present', penalty: '-0.35' },
    ] as ConfidenceReason[]
    render(<ConfidenceRail confidence={'1.000' as Money} reasons={reasons} />)

    expect(screen.getByText('0.05')).toBeDefined()
    expect(screen.getByText('-0.35')).toBeDefined()

    const [bonus, deduction] = screen.getAllByRole('listitem')
    expect(bonus.textContent).toBe('verified merchant prior +0.05')
    expect(deduction.textContent).toBe('validation errors present -0.35')
  })

  it('keeps the reasons in the order the API sent them', () => {
    // `_signals` emits them in a fixed, meaningful order -- findings, triage,
    // extraction metadata, missing fields, disputes, then the bonus
    // (src/receipts/score/confidence.py:122-195). Sorting them by size or
    // alphabetically here would present a different explanation from the one
    // the pipeline recorded. This fails if the component sorts at all: the
    // fixture's input order is neither alphabetical nor by magnitude.
    const reasons = [
      { reason: 'validation errors present', penalty: '-0.35' },
      { reason: 'a handwritten receipt', penalty: '-0.15' },
      { reason: 'total is missing', penalty: '-0.30' },
    ] as ConfidenceReason[]
    render(<ConfidenceRail confidence={'0.200' as Money} reasons={reasons} />)

    const shown = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(shown).toEqual([
      'validation errors present -0.35',
      'a handwritten receipt -0.15',
      'total is missing -0.30',
    ])
  })
})
