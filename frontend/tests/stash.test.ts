import { afterEach, describe, expect, it } from 'vitest'
import { clear, hasDirtyEdits, remember, restore } from '../src/review/stash'

// Module state, so every test starts from nothing (same discipline as
// session.test.ts applies to session.ts's module state).
afterEach(() => {
  clear()
})

describe('the edit stash', () => {
  it('returns the overlay for the task that stored it', () => {
    remember('t1', { 'totals.total': '99.00' })
    expect(restore('t1')).toEqual({ 'totals.total': '99.00' })
  })

  it('returns null for a different task', () => {
    remember('t1', { 'totals.total': '99.00' })
    expect(restore('t2')).toBeNull()
  })

  it('is non-consuming: a second restore still answers', () => {
    // A second 401 before any new edit must not lose what the first kept.
    remember('t1', { 'totals.total': '99.00' })
    restore('t1')
    expect(restore('t1')).toEqual({ 'totals.total': '99.00' })
  })

  it('hands out copies, not its own object', () => {
    const overlay = { 'totals.total': '99.00' }
    remember('t1', overlay)
    overlay['totals.total'] = 'mutated'
    const first = restore('t1')!
    first['totals.total'] = 'also mutated'
    expect(restore('t1')).toEqual({ 'totals.total': '99.00' })
  })

  it('a later remember replaces the earlier one, whatever the task', () => {
    remember('t1', { 'totals.total': '99.00' })
    remember('t2', { 'totals.tax': '1.00' })
    expect(restore('t1')).toBeNull()
    expect(restore('t2')).toEqual({ 'totals.tax': '1.00' })
  })

  it('a later remember for the SAME task replaces it too -- it does not merge', () => {
    // The overlay is the dirty diff, rebuilt from scratch on every committed
    // change, so a path that stops being dirty has to leave it. Merging instead
    // is invisible to every other test here and to the whole suite -- measured
    // -- while its consequence is not cosmetic: a reviewer who types 99.00 into
    // the total, thinks better of it and types the stored value back, would
    // have the abandoned 99.00 *restored onto the form* after a 401. It would
    // also hold `hasDirtyEdits` true, and that is the sign-out gate (design
    // §4.2), so Sign out would demand confirmation over an edit that no longer
    // exists anywhere.
    remember('t1', { 'totals.total': '99.00' })
    remember('t1', {})
    expect(hasDirtyEdits()).toBe(false)
    expect(restore('t1')).toEqual({})
  })

  it('hasDirtyEdits is false when empty, false for an empty overlay, true otherwise', () => {
    expect(hasDirtyEdits()).toBe(false)
    remember('t1', {})
    expect(hasDirtyEdits()).toBe(false)
    remember('t1', { 'totals.total': '99.00' })
    expect(hasDirtyEdits()).toBe(true)
  })

  it('clear forgets everything', () => {
    remember('t1', { 'totals.total': '99.00' })
    clear()
    expect(restore('t1')).toBeNull()
    expect(hasDirtyEdits()).toBe(false)
  })

  it('a null value (a cleared field) survives the round trip', () => {
    remember('t1', { 'merchant.name': null })
    expect(restore('t1')).toEqual({ 'merchant.name': null })
    expect(hasDirtyEdits()).toBe(true)
  })
})
