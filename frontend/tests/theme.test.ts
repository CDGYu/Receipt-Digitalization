import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  THEME_STORAGE_KEY,
  applyPreference,
  readPreference,
  setPreference,
} from '../src/theme'

/** The theme preference module, and the one thing it duplicates.
 *
 * `dirname(fileURLToPath(import.meta.url))` works under jsdom -- it is the
 * `new URL(specifier, import.meta.url)` *pattern* Vite rewrites, not this one.
 */
const HERE = dirname(fileURLToPath(import.meta.url))

function reset(): void {
  window.localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
}

beforeEach(reset)
afterEach(reset)

describe('readPreference', () => {
  it('is "system" when nothing has been stored', () => {
    expect(readPreference()).toBe('system')
  })

  it.each(['light', 'dark', 'system'] as const)('round-trips %s', (preference) => {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference)

    expect(readPreference()).toBe(preference)
  })

  it('falls back to "system" for a value it does not recognise', () => {
    // The key is shared per-origin, so a user or another tab can set it to
    // anything. The honest answer to `receipts.theme = "purple"` is the default,
    // not a broken header.
    window.localStorage.setItem(THEME_STORAGE_KEY, 'purple')

    expect(readPreference()).toBe('system')
  })
})

describe('applyPreference', () => {
  it.each(['light', 'dark'] as const)('sets data-theme=%s', (preference) => {
    applyPreference(preference)

    expect(document.documentElement.getAttribute('data-theme')).toBe(preference)
  })

  it('REMOVES the attribute for "system" rather than setting a third value', () => {
    // There is no `[data-theme='system']` block in tokens.css. Absence is what
    // lets `prefers-color-scheme` apply, and ADR-0027's
    // `:root:not([data-theme='light'])` is written for exactly this state.
    applyPreference('dark')

    applyPreference('system')

    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })
})

describe('setPreference', () => {
  it('stores and applies in one call', () => {
    setPreference('dark')

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('still applies when storage refuses', () => {
    // Safari's private mode historically threw here, and a browser can disable
    // storage outright. The control has to keep working for the rest of the
    // page load rather than taking the theme down with it.
    const setItem = window.localStorage.setItem
    window.localStorage.setItem = () => {
      throw new Error('QuotaExceededError')
    }

    try {
      setPreference('dark')
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    } finally {
      window.localStorage.setItem = setItem
    }
  })

  it('reads back as "system" when storage refuses reads', () => {
    const getItem = window.localStorage.getItem
    window.localStorage.getItem = () => {
      throw new Error('SecurityError')
    }

    try {
      expect(readPreference()).toBe('system')
    } finally {
      window.localStorage.getItem = getItem
    }
  })
})

describe('the pre-paint script in index.html', () => {
  const html = readFileSync(join(HERE, '..', 'index.html'), 'utf8')

  it('uses the same storage key this module exports', () => {
    // The two cannot import each other: the script must run before the module
    // graph loads, so the key is a literal in both places. This is the pin that
    // makes that duplication safe -- renaming the constant without editing the
    // HTML fails here rather than silently forgetting every stored preference.
    expect(html).toContain(`'${THEME_STORAGE_KEY}'`)
  })

  it('is inline and synchronous, because a deferred script paints too late', () => {
    // `<script type="module">` and `<script defer>` both run after first paint,
    // which is exactly the flash this exists to prevent.
    const tag = html.slice(html.indexOf('<script'), html.indexOf('</script>'))
    expect(tag).not.toContain('type="module"')
    expect(tag).not.toContain('defer')
    expect(tag).not.toContain('async')
  })

  it('sets the attribute only for the two explicit themes', () => {
    // "system" must leave the attribute absent. A script that wrote
    // `data-theme="system"` would match no block in tokens.css and silently
    // defeat the media query.
    expect(html).toContain("t === 'dark' || t === 'light'")
    expect(html).not.toContain("'system'")
  })
})
