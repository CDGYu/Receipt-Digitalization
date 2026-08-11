import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ThemeControl } from '../src/ThemeControl'
import { THEME_STORAGE_KEY } from '../src/theme'

/** The theme control, as a reviewer meets it.
 *
 * Nothing here asserts a class name. Vitest runs with `css: false`, so a
 * `.module.css` import returns a proxy whose keys echo back -- a renamed class
 * would ship as `class="undefined"` with every one of these green. What the
 * stylesheet contains is guarded by `stylesheets.test.ts` reading it as text.
 */

function reset(): void {
  window.localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
}

beforeEach(reset)
afterEach(() => {
  cleanup()
  reset()
})

describe('ThemeControl', () => {
  it('offers exactly the three states, labelled for a person', () => {
    render(<ThemeControl />)

    const select = screen.getByLabelText('Theme')
    const options = Array.from(select.querySelectorAll('option'))

    expect(options.map((o) => o.value)).toEqual(['system', 'light', 'dark'])
    // "Match system" rather than "System": the option says what it does.
    expect(options.map((o) => o.textContent)).toEqual(['Match system', 'Light', 'Dark'])
  })

  it('opens on "system" when nothing has been chosen', () => {
    render(<ThemeControl />)

    expect((screen.getByLabelText('Theme') as HTMLSelectElement).value).toBe('system')
  })

  it('opens on the stored choice, so the control agrees with the page', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'dark')

    render(<ThemeControl />)

    expect((screen.getByLabelText('Theme') as HTMLSelectElement).value).toBe('dark')
  })

  it('applies and stores a chosen theme', async () => {
    const user = userEvent.setup()
    render(<ThemeControl />)

    await user.selectOptions(screen.getByLabelText('Theme'), 'dark')

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('going back to "system" REMOVES the attribute rather than setting a third value', async () => {
    // The route back to the OS preference. A two-way toggle would not have one,
    // which is why ADR-0038 chose three states.
    const user = userEvent.setup()
    render(<ThemeControl />)
    await user.selectOptions(screen.getByLabelText('Theme'), 'dark')

    await user.selectOptions(screen.getByLabelText('Theme'), 'system')

    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('system')
  })

  it('an explicit light choice is stored, not treated as "no choice"', async () => {
    // ADR-0027's `:root:not([data-theme='light'])` exists so an explicit light
    // beats an OS dark. That only means anything if light is actually recorded
    // as a choice rather than collapsing back to the default.
    const user = userEvent.setup()
    render(<ThemeControl />)

    await user.selectOptions(screen.getByLabelText('Theme'), 'light')

    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })
})
