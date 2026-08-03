import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SignOutControl } from '../src/SignOutControl'
import { setSignedIn, isSignedIn } from '../src/session'
import { clear, hasDirtyEdits, remember, restore } from '../src/review/stash'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  clear()
  setSignedIn(true)
})

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('the sign-out control', () => {
  it('signs out on a 204 and clears the stash', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    // Dirty, so the first click arms the confirm; the discard button completes it.
    await userEvent.click(screen.getByRole('button', { name: 'Discard edits and sign out' }))

    expect(isSignedIn()).toBe(false)
    expect(restore('t1')).toBeNull()
  })

  it('signs out without a confirm step when nothing is dirty', async () => {
    setSignedIn(true)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(isSignedIn()).toBe(false)
  })

  it('cancel keeps the session and the edits', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(fetchMock).not.toHaveBeenCalled()
    expect(isSignedIn()).toBe(true)
    expect(hasDirtyEdits()).toBe(true)
    // The control is back to its resting state.
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy()
  })

  it('stays signed in, keeps the stash, and says why when logout fails', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(503, { error: { message: 'database unavailable' } })),
    )
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Discard edits and sign out' }))

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('database unavailable'),
    )
    expect(isSignedIn()).toBe(true)
    expect(hasDirtyEdits()).toBe(true)
  })

  it('a 401 ends the session client-side and clears the stash', async () => {
    setSignedIn(true)
    remember('t1', { 'totals.total': '99.00' })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: 'not signed in' } })),
    )
    render(<SignOutControl />)

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await userEvent.click(screen.getByRole('button', { name: 'Discard edits and sign out' }))

    // client.ts fired onUnauthorized before throwing, so the session module
    // already flipped; the control's own job is the stash.
    expect(isSignedIn()).toBe(false)
    expect(restore('t1')).toBeNull()
  })
})
