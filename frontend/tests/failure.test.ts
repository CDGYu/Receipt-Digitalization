import { describe, expect, it } from 'vitest'
import { ApiError } from '../src/api/client'
import { classifyFailure } from '../src/review/failure'

const FALLBACK = 'the review could not be submitted'

describe('classifyFailure', () => {
  it('labels a 503 backend-down with the server words', () => {
    expect(classifyFailure(new ApiError(503, 'database unavailable'), { fallback: FALLBACK })).toEqual({
      kind: 'backend-down',
      message: 'database unavailable',
    })
  })

  it('labels a 403 taken and a 404 gone', () => {
    expect(
      classifyFailure(new ApiError(403, 'only the assignee or an admin may complete this task'), {
        fallback: FALLBACK,
      }).kind,
    ).toBe('taken')
    expect(
      classifyFailure(new ApiError(404, 'no review task with id t1'), { fallback: FALLBACK }).kind,
    ).toBe('gone')
  })

  it('matches a 400 that quotes a sent path', () => {
    // The path-quoting family, pinned server-side in tests/test_api_write.py:
    //   cannot apply a correction to 'line_items[9].qty': receipt <id> has no
    //   line item at position 9
    const failure = classifyFailure(
      new ApiError(400, "cannot apply a correction to 'line_items[9].qty': receipt a1 has no line item at position 9"),
      { sentPatch: { 'line_items[9].qty': '2' }, fallback: FALLBACK },
    )
    expect(failure).toEqual({
      kind: 'field',
      path: 'line_items[9].qty',
      message: "cannot apply a correction to 'line_items[9].qty': receipt a1 has no line item at position 9",
    })
  })

  it('matches a value-quoting 400 to the one dirty field holding that value', () => {
    // "not a decimal amount: 'abc'" quotes only the value -- the classifier
    // finds the field by what was sent.
    const failure = classifyFailure(new ApiError(400, "not a decimal amount: 'abc'"), {
      sentPatch: { 'totals.total': 'abc', 'receipt.time': '14:30:45' },
      fallback: FALLBACK,
    })
    expect(failure).toEqual({ kind: 'field', path: 'totals.total', message: "not a decimal amount: 'abc'" })
  })

  it('matches the currency bound message, whose value sits in parentheses', () => {
    const failure = classifyFailure(
      new ApiError(400, "currency holds at most 3 characters, got 5 ('EUROS')"),
      { sentPatch: { 'receipt.currency': 'EUROS' }, fallback: FALLBACK },
    )
    expect(failure).toEqual({
      kind: 'field',
      path: 'receipt.currency',
      message: "currency holds at most 3 characters, got 5 ('EUROS')",
    })
  })

  it('degrades to other when a message quotes two sent paths', () => {
    // No server message quotes two paths today: the path family is pinned in
    // tests/test_api_write.py and each of its two messages quotes exactly one
    // path (the receipt id and the position are interpolated bare). So this
    // pins the matcher's own tie-break across its whole input space, rather
    // than asserting anything about the API -- an ambiguous match must never
    // guess a field, whatever a future message quotes.
    const failure = classifyFailure(
      new ApiError(400, "cannot reconcile 'totals.total' with 'totals.tax'"),
      { sentPatch: { 'totals.total': '1.00', 'totals.tax': '2.00' }, fallback: FALLBACK },
    )
    expect(failure).toEqual({ kind: 'other', message: "cannot reconcile 'totals.total' with 'totals.tax'" })
  })

  it('degrades to other when two dirty fields hold the rejected value', () => {
    const failure = classifyFailure(new ApiError(400, "not a decimal amount: 'abc'"), {
      sentPatch: { 'totals.total': 'abc', 'totals.tax': 'abc' },
      fallback: FALLBACK,
    })
    expect(failure).toEqual({ kind: 'other', message: "not a decimal amount: 'abc'" })
  })

  it('degrades to other for a 400 with no quoted span matching anything sent', () => {
    const failure = classifyFailure(new ApiError(400, 'not a boolean: None'), {
      sentPatch: { 'totals.total': '1.00' },
      fallback: FALLBACK,
    })
    expect(failure).toEqual({ kind: 'other', message: 'not a boolean: None' })
  })

  it('never matches a field without a sentPatch', () => {
    expect(
      classifyFailure(new ApiError(400, "not a decimal amount: 'abc'"), { fallback: FALLBACK }).kind,
    ).toBe('other')
  })

  it('uses the fallback for anything that is not an ApiError', () => {
    expect(classifyFailure(new TypeError('Failed to fetch'), { fallback: FALLBACK })).toEqual({
      kind: 'other',
      message: FALLBACK,
    })
  })

  it('null values never value-match (the server reprs None unquoted)', () => {
    const failure = classifyFailure(new ApiError(400, "not a decimal amount: 'null'"), {
      sentPatch: { 'totals.total': null },
      fallback: FALLBACK,
    })
    expect(failure.kind).toBe('other')
  })
})
