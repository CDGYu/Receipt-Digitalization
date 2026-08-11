import { useState } from 'react'
import { type ThemePreference, readPreference, setPreference } from './theme'
import styles from './ThemeControl.module.css'

/** Choose the theme: light, dark, or follow the OS (ADR-0038).
 *
 * A `<select>` rather than three buttons or a two-way switch. Three mutually
 * exclusive named options is exactly what a select is, it carries its own label
 * association and keyboard handling, and it stays one control at any width --
 * this sits in a header beside sign-out, and ADR-0027's browser pass found the
 * shell already tight at 1440x900.
 *
 * **The initial value is read once, on mount, and is not synchronised after
 * that.** `index.html`'s pre-paint script has already applied the stored
 * preference before React runs, so this is reading back a decision that is
 * already on the document rather than making one. A second tab changing the
 * value will not move this select, which is honest: nothing else in this app
 * reacts to another tab either.
 *
 * There is no "saved" confirmation. The effect is the entire feedback -- the
 * page changes colour as the option is chosen -- and a toast saying so would
 * be telling a reviewer something their eyes already reported.
 */
export function ThemeControl() {
  const [preference, setLocal] = useState<ThemePreference>(() => readPreference())

  return (
    <span className={styles.control}>
      <label className={styles.label} htmlFor="theme-preference">
        Theme
      </label>
      <select
        id="theme-preference"
        className={styles.select}
        value={preference}
        onChange={(event) => {
          const chosen = event.target.value as ThemePreference
          setLocal(chosen)
          setPreference(chosen)
        }}
      >
        <option value="system">Match system</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </span>
  )
}
