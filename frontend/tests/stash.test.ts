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
