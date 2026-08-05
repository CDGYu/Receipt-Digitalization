import type { ButtonHTMLAttributes } from 'react'
import styles from './Button.module.css'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant: 'primary' | 'secondary' | 'danger'
}

/** A button. The variant picks the paint; everything else is a native `<button>`.
 *
 * **`type` defaults to `"button"`, not to the platform's `"submit"`.** Measured
 * across `src/`: sixteen `<button>` elements, of which fifteen spell
 * `type="button"` explicitly and exactly one -- `LoginPage.tsx:50`, inside the
 * app's only `<form>` -- spells `type="submit"`. So the codebase's own
 * convention is that a submit button says so and everything else is inert, and
 * this default follows it rather than the platform's.
 *
 * It matters because that one form is real: the review screen's submit chain is
 * a click handler and a Ctrl+Enter listener today, but a primitive that silently
 * defaulted to `submit` would post a half-keyed receipt the moment anyone
 * wrapped the receipt fields the way `LoginPage` already wraps its two. Callers
 * that genuinely want a submit button pass `type` like any other native prop; it
 * is destructured out of `rest`, so the explicit attribute below always wins
 * over a spread.
 *
 * `className` is merged rather than replaced, so a caller can add a layout class
 * without losing the variant's paint.
 */
export function Button({ variant, className, type = 'button', ...rest }: ButtonProps) {
  const classes = [styles.button, styles[variant], className].filter(Boolean).join(' ')
  return <button {...rest} type={type} className={classes} />
}
