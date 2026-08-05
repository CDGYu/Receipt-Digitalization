import styles from './Value.module.css'

/** One value, rendered so that **`null` never looks like `0`, and neither looks
 *  like "empty"** -- design §4, and the single place that rule lives.
 *
 * It falls straight out of the prime directive: *prefer `null` over a confident
 * guess; a wrong number is far worse than a missing one*. Every layer below this
 * one already holds it -- `money()` (review/serializers.py) never rewrites `None`
 * to `"0.00"`, and `_coerce_money(None)` stays `None` -- so an unextracted total
 * printed here as `0.00` would destroy the system's central safety property at
 * the last inch, on the one screen where a human decides. `tests/value.test.tsx`
 * pins it rather than leaving it to review.
 *
 * **The mark is an em dash carrying `aria-label="not extracted"`.** The label is
 * what makes the distinction survive into a screen reader: the glyph alone
 * announces as "em dash" or as nothing at all, which is indistinguishable from
 * an empty cell. A sighted reviewer gets the same distinction from the colour
 * *and* the hairline left border -- the scannability half of §4, which lets a
 * reader find every gap in a form without reading a single value, and which is
 * also why the mark is not colour alone.
 *
 * The null branch is deliberately **not** conditioned on `kind`. A missing
 * merchant name and a missing quantity are missing in exactly the same way, and
 * a rule with an exception is a rule someone will land on the wrong side of.
 */
export function Value({ value, kind }: {
  value: string | null
  kind: 'money' | 'text' | 'count'
}) {
  if (value === null) {
    return (
      <span className={styles.notExtracted} aria-label="not extracted">
        —
      </span>
    )
  }
  return <span className={kind === 'text' ? styles.text : styles.numeric}>{value}</span>
}
