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
 * **The mark is an em dash carrying `aria-label="not extracted"`, on a
 * `role="img"` span.** The label is what makes the distinction survive into a
 * screen reader: the glyph alone announces as "em dash" or as nothing at all,
 * which is indistinguishable from an empty cell. The role is what makes the
 * label *legal* -- a bare `<span>` is `role=generic`, for which ARIA 1.2 marks
 * naming **prohibited**, so `aria-label` on one may be discarded outright (it is
 * what axe-core's `aria-prohibited-attr` fires on). Testing Library's
 * `getByLabelText` reads the attribute off the DOM and never consults the role,
 * so the tests below passed identically without it: the guarantee was asserted
 * and not delivered. `role="img"` is the minimal honest fix -- the mark *is* a
 * glyph standing in for content -- and `getByRole('img', { name: ... })` pins it
 * through the accessibility tree rather than the attribute.
 *
 * A sighted reviewer gets the same distinction from the colour *and* the
 * hairline border -- the scannability half of §4, which lets a reader find
 * every gap in a form without reading a single value, and which is also why the
 * mark is not colour alone.
 *
 * The null branch is deliberately **not** conditioned on `kind`. A missing
 * merchant name and a missing quantity are missing in exactly the same way, and
 * a rule with an exception is a rule someone will land on the wrong side of.
 *
 * ## `align` moves the gutter, and changes nothing about what the mark means
 *
 * The paragraph above still holds: what the mark *is* has no exceptions. What
 * `align` picks is which edge the hairline sits on, and that is a property of
 * the **cell**, not of the value -- so the caller that set `text-align` is the
 * one that declares it. Default `'start'`, so every existing call site is
 * unmoved.
 *
 * **`kind` cannot stand in for it, and that was measured rather than assumed.**
 * Of the five call sites passing a numeric kind, two are left-aligned:
 * `admin/StatTiles.tsx` renders a `count` in a tile whose stylesheet declares no
 * `text-align` at all, and `review/ConfidenceRail.tsx` a `money` in the same
 * shape. Keying the edge off `kind` would move the rule to the wrong side on
 * both of those to fix the third.
 *
 * Why it needs fixing at all: a left-edge gutter works in a form because the
 * fields share a left edge. In a right-aligned money column the span
 * shrink-wraps and is pushed right, so the rule lands at a different x in every
 * row. Seen in a browser on 2026-08-20 (`/app/receipts`, 1440, Chromium,
 * Firefox and WebKit): a receipt with a currency and no total rendered `PHP|—`,
 * the rule falling between the code and the mark.
 *
 * ## The empty string is the third state, and it gets the mark
 *
 * §4 names three states, and `''` is the one the interface does not spell. It is
 * live in this data model rather than hypothetical: `_coerce_text(None)` returns
 * `''`, so `null` and `''` land on the same column for `description_raw`
 * (`LineItemsTable.tsx:117-121`) and the database itself cannot tell "never
 * recorded" from "cleared to empty" there. Rendering `''` as an empty `<span>`
 * is therefore not a neutral default -- it is exactly the failure the §4
 * headline names, a missing value that looks like nothing, on data where
 * "missing" is the common case.
 *
 * So `''` takes the mark. What this component deliberately does **not** do is
 * §4's *distinction* between "never extracted" and "the reviewer cleared it":
 * that is a dirty-state fact, `Value` is fed a `FieldMap` and cannot know it,
 * and §4 puts the "cleared" chip **beside the label** rather than in the value
 * for that reason. The chip belongs to whichever component owns the edit.
 */
export function Value({ value, kind, align = 'start' }: {
  value: string | null
  kind: 'money' | 'text' | 'count'
  align?: 'start' | 'end'
}) {
  if (value === null || value === '') {
    return (
      <span
        className={align === 'end' ? styles.notExtractedEnd : styles.notExtracted}
        role="img"
        aria-label="not extracted"
      >
        —
      </span>
    )
  }
  return <span className={kind === 'text' ? styles.text : styles.numeric}>{value}</span>
}
