/** The theme preference: read it, apply it, persist it (ADR-0038).
 *
 * ADR-0027 shipped dark as a full second theme and no way for a user to choose
 * it. This is that way. Three states, not two, because ADR-0027's precedence
 * rule -- `:root:not([data-theme='light'])` inside the `prefers-color-scheme`
 * block -- exists so an explicit *light* choice beats an OS dark preference. A
 * two-way toggle would make that a one-way door: once a reviewer picked either
 * theme there would be no way back to following the OS.
 *
 * The three map onto exactly one DOM fact:
 *
 *   'system'  ->  no `data-theme` attribute at all, so the media query applies
 *   'light'   ->  `data-theme="light"`
 *   'dark'    ->  `data-theme="dark"`
 *
 * **`'system'` removes the attribute rather than setting it to something.**
 * There is no `data-theme="system"` block in `tokens.css`, and inventing one
 * would mean duplicating both palettes a third time.
 *
 * ## On browser storage
 *
 * ADR-0024 carries a user ruling that nothing enters browser storage. Its
 * stated reason is *"no receipt-adjacent text is written to disk by the
 * browser"*, and the stash it governs holds edited receipt values. **A theme
 * preference is not that**, and the ruling was narrowed on 2026-08-11 to say so
 * -- see ADR-0024's dated note and ADR-0038.
 *
 * What that narrowing permits is exactly this: **one key, holding one of three
 * known words.** Nothing else in this application may write to storage, and
 * `review/stash.ts` still holds its edits in memory and always will.
 */

export type ThemePreference = 'light' | 'dark' | 'system'

/** The one key this application is allowed to write.
 *
 * Namespaced because `localStorage` is shared per-origin, and the review UI is
 * served from the same origin as the API (ADR-0015). Duplicated as a string
 * literal in `index.html`'s pre-paint script, which cannot import this module;
 * `theme.test.ts` reads that file as text and fails if the two ever disagree.
 */
export const THEME_STORAGE_KEY = 'receipts.theme'

const PREFERENCES: readonly ThemePreference[] = ['light', 'dark', 'system']

function isPreference(value: unknown): value is ThemePreference {
  return typeof value === 'string' && (PREFERENCES as readonly string[]).includes(value)
}

/** The stored preference, or `'system'` when there is nothing usable.
 *
 * Anything unrecognised reads as `'system'` rather than throwing: the value is
 * a shared-origin key a user or another tab can set to anything at all, and the
 * honest response to `receipts.theme = "purple"` is to fall back to the default
 * rather than to break the header.
 *
 * `localStorage` itself can throw -- Safari's private mode historically did,
 * and a browser can disable it entirely -- so the access is guarded. A browser
 * that refuses to store gets a working control that forgets, not a broken app.
 */
export function readPreference(): ThemePreference {
  let stored: string | null = null
  try {
    stored = window.localStorage.getItem(THEME_STORAGE_KEY)
  } catch {
    return 'system'
  }
  return isPreference(stored) ? stored : 'system'
}

/** Put `preference` on the document, without storing anything. */
export function applyPreference(preference: ThemePreference): void {
  const root = document.documentElement
  if (preference === 'system') {
    root.removeAttribute('data-theme')
    return
  }
  root.setAttribute('data-theme', preference)
}

/** Store `preference` and apply it.
 *
 * Applying happens even when storing fails, so the control works for the rest
 * of the page load in a browser that refuses to persist.
 */
export function setPreference(preference: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference)
  } catch {
    // Ignored deliberately: see readPreference's docstring.
  }
  applyPreference(preference)
}
