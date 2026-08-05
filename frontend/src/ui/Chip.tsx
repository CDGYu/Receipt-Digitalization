import type { JSX, ReactNode } from 'react'
import styles from './Chip.module.css'

/** A small status badge: severity, confidence band, task state, "cleared".
 *
 * **The tone never travels alone.** "Never colour alone" is a High-severity item
 * in the accessibility contract (§6) and red/green is the exact failure case it
 * names, so the icon and the text are not optional decoration around a coloured
 * pill -- they are the two signals that survive when the colour does not reach
 * the reader. Both are required props for that reason: there is no arrangement
 * of this component that renders a bare colour, because the type does not permit
 * one. `tests/value.test.tsx` reverts each of the two separately.
 *
 * The icon is wrapped `aria-hidden`, which is not a contradiction of the above:
 * the icon carries the signal *visually*, and the text carries it to a screen
 * reader. Left announceable, a decorative glyph beside its own word reads the
 * state twice, and Phosphor's outline set (§6 -- SVG icons, never emoji) ships
 * no accessible name to announce in the first place.
 */
export function Chip({ tone, icon, children }: {
  tone: 'error' | 'warn' | 'info' | 'positive' | 'neutral'
  icon: JSX.Element
  children: ReactNode
}) {
  return (
    <span className={`${styles.chip} ${styles[tone]}`}>
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
      {children}
    </span>
  )
}
