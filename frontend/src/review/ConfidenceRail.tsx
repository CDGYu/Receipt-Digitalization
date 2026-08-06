import type { ConfidenceReason, Money } from '../api/types'
import { Value } from '../ui/Value'
import styles from './ConfidenceRail.module.css'

/** The stored confidence score and the persisted breakdown behind it.
 *
 * **Read verbatim, never recomputed.** `explain_confidence` needs the
 * `TriageResult` and `receipt.meta.ambiguous_fields`, neither of which is
 * persisted, so a read-time recompute would systematically under-penalize and
 * hand a reviewer a breakdown that disagrees with the score on the row
 * (ADR-0012). The pipeline stores the pairs beside the score it produced and
 * this component prints them as they arrive -- no rounding, no re-ordering, no
 * sign flipping.
 *
 * **The pairs are not an equation, and nothing here presents them as one.**
 * The plan's version of this file claimed the breakdown "provably sums to the
 * stored score (ADR-0012)". It does not, on two counts, both measured:
 *
 *   * the scorer starts at `1.0`, *adds* the signed pairs, then clamps to
 *     `[0, 1]` and quantizes to three places (score/confidence.py:219-225), so
 *     the sum is at best `score - 1.0` and after a clamp is not even that.
 *     Measured on a seven-signal receipt: `sum = -1.20`, `1 + sum = -0.20`,
 *     stored score `0.000`.
 *   * a `penalty` can be **positive**. `verified merchant prior` is
 *     `+0.05` (score/confidence.py:95), stored as the string `"0.05"`;
 *     measured, that receipt's `1 + sum` is `1.05` against a stored `1.000`.
 *
 * So the rail lists reasons. It never adds them up, and it must not start.
 *
 * `null` and `[]` are different facts about the same column and are rendered
 * differently: `null` means the score was never explained (a row written before
 * the column existed, or a run that failed before scoring), `[]` means nothing
 * lowered it. Collapsing the two would tell a reviewer "no reasons" about a
 * receipt that never captured any (review/serializers.py:10-19, ADR-0012).
 */
export interface ConfidenceRailProps {
  readonly confidence: Money | null
  readonly reasons: ConfidenceReason[] | null
}

/** A leading `+` for the one kind of entry that *raises* the score.
 *
 * `verified merchant prior` arrives as `"0.05"` with no sign, in the same bare
 * column as `"-0.35"`, and nothing on the row says which way it moved the
 * number. This adds the missing marker **without touching the value**: the sign
 * is read off the first character of the string that arrived, never computed
 * from it -- no `Number`, no comparison, no arithmetic (ADR-0001). The digits
 * are rendered separately and unchanged.
 *
 * `+` is only added when the string carries no sign of its own, so a hand-written
 * row holding `"+0.05"` cannot come out as `"++0.05"`.
 */
function signPrefixFor(penalty: string): string {
  return penalty.startsWith('-') || penalty.startsWith('+') ? '' : '+'
}

/** The routing cut-offs, **copied** from `src/receipts/score/thresholds.py`.
 *
 * `AUTO_APPROVE_THRESHOLD = Decimal("0.85")` and `REVIEW_THRESHOLD =
 * Decimal("0.60")`, and both tests are "at or above" (`cli.py:1206`:
 * `confidence >= threshold` "is the definition of auto-approval").
 *
 * **This is a duplicate of a number that calibration is meant to move**, which
 * is precisely what that module's own docstring was written to stop -- it exists
 * because the same constants were previously spelled in four places. The
 * authoritative pair is already on the wire: `GET /metrics` returns
 * `thresholds: {auto_approve, review}` as strings, read from
 * `settings.auto_approve_threshold` (`review/api.py:282-285`), so a deployment
 * that overrides either one gets a band here that disagrees with its own
 * routing. Fetching them is a data-flow change this task is not scoped for; the
 * copy is reported as open rather than hidden, and the band is a reading aid for
 * the score beside it, never a claim about what the pipeline did with it.
 */
const AUTO_APPROVE_AT = '0.85'
const REVIEW_AT = '0.60'

/** `left >= right` for two decimal strings, **without arithmetic**.
 *
 * ADR-0001 and ADR-0015 keep money -- and every column that shares `money()`'s
 * serializer, confidence included -- a string end to end, and
 * `tests/no-float-in-money-path.test.ts` is a source scan that fails on
 * `Number(`, `parseFloat(` and a unary `+` anywhere under `frontend/src` --
 * including this file, which it reads as text. So the comparison is
 * done on the digits themselves: integer parts by length then lexically (equal
 * length makes `'9' > '1'` the same order as the values), fraction parts padded
 * to a common width and compared the same way. Exact for every input the
 * predicate below admits, and no value is ever rewritten.
 */
function atLeast(left: string, right: string): boolean {
  const trim = (digits: string): string => digits.replace(/^0+(?=\d)/, '')
  const [leftWhole, leftFraction = ''] = left.split('.')
  const [rightWhole, rightFraction = ''] = right.split('.')
  const leftDigits = trim(leftWhole)
  const rightDigits = trim(rightWhole)
  if (leftDigits.length !== rightDigits.length) return leftDigits.length > rightDigits.length
  if (leftDigits !== rightDigits) return leftDigits > rightDigits
  const width = Math.max(leftFraction.length, rightFraction.length)
  return leftFraction.padEnd(width, '0') >= rightFraction.padEnd(width, '0')
}

interface Band {
  /** §5.3's word. It is the primary signal, and the colour is the redundant
   *  one -- never the other way round. */
  readonly word: string
  /** A text glyph, not an icon font: there is no icon set in this project and
   *  adding one is a new dependency. It is a *shape* distinction on top of the
   *  word, which is what makes the band survive greyscale. */
  readonly glyph: string
  /** The class that paints it. Keyed here rather than at the call site so the
   *  three arms cannot drift apart. */
  readonly tone: 'high' | 'middle' | 'low'
}

/** Which band a stored score falls in, or `null` for no claim at all.
 *
 * **`null` in, `null` out, and that is the point.** A band is a judgement about
 * a number; a receipt that was never scored has no number, and inventing "Low"
 * for it would be exactly the null-reads-as-a-value failure design §4 exists to
 * prevent -- on the one panel whose whole job is to report how much the machine
 * trusted itself.
 *
 * Anything that is not a plain non-negative decimal also yields `null`. The
 * column is `Numeric` and `money()` prints it with `str(Decimal)`, so that shape
 * is what arrives; a row that came from anywhere else gets no band rather than a
 * band derived from a string this comparator cannot order.
 */
function bandFor(confidence: string | null): Band | null {
  if (confidence === null || !/^\d+(\.\d+)?$/.test(confidence)) return null
  if (atLeast(confidence, AUTO_APPROVE_AT)) {
    return { word: 'Auto-approve', glyph: '✓', tone: 'high' }
  }
  if (atLeast(confidence, REVIEW_AT)) {
    return { word: 'Review', glyph: '!', tone: 'middle' }
  }
  return { word: 'Low', glyph: '▼', tone: 'low' }
}

export function ConfidenceRail({ confidence, reasons }: ConfidenceRailProps) {
  const band = bandFor(confidence)
  return (
    <aside className={styles.rail}>
      <h2 className={styles.heading}>Confidence</h2>
      {/* The score as the API sent it. An em dash, not "0" or "0.00": a score
          that was never recorded is not a recorded zero (`money()` keeps that
          distinction on the way out, review/serializers.py:65-73).

          Through `Value` rather than through a bare `{confidence ?? '—'}`, which
          is what stood here and was an uncoordinated second copy of half of
          design §4's rule: the same glyph, but with no accessible name, no
          `--color-null` and no hairline border, so a screen reader heard "em
          dash" or nothing at all and a sighted scan had nothing to find. ADR-0027
          names this line as the one place the rule was duplicated. `confidence`
          is `Money | null`, and `Money` is `string & {...}`, so it is assignable
          to `Value`'s `string | null` without a cast. */}
      <p className={styles.score}>
        <Value value={confidence} kind="money" />
      </p>
      {/* §5.3's band. **Never colour alone** -- the tool's Colour Only rule is
          High severity and red/amber/green is the exact failure case it names,
          so the word carries the meaning and the tone class only tints the word
          that is already there. The glyph is a third, shape-based signal for a
          reader who has neither.

          `role="img"` with a name, for the reason `ui/Value` records: a bare
          `<span>` is `role=generic`, for which ARIA 1.2 marks naming
          *prohibited*, so the glyph would announce as "check mark", "down
          triangle" or as nothing at all. The name repeats the word rather than
          describing the shape, because what a screen reader needs from this
          element is the band, not the decoration.

          No band at all when there is no score: see `bandFor`. */}
      {band === null ? null : (
        <p className={`${styles.band} ${styles[band.tone]}`}>
          <span className={styles.bandIcon} role="img" aria-label={`${band.word} band`}>
            {band.glyph}
          </span>
          <span className={styles.bandWord}>{band.word}</span>
        </p>
      )}
      {reasons === null ? (
        <p className={styles.note}>Breakdown not recorded for this receipt.</p>
      ) : reasons.length === 0 ? (
        <p className={styles.note}>Nothing lowered the score.</p>
      ) : (
        <ul className={styles.list}>
          {reasons.map((entry, index) => (
            /* Keyed on the index as well as the text. The pipeline emits each
               reason at most once per receipt (`_signals`, score/confidence.py
               :122-195), but this is a JSONB column read verbatim -- a row that
               came from anywhere else can repeat a reason, and duplicate React
               keys are not a failure mode worth inheriting for that. */
            <li className={styles.reason} key={`${entry.reason}-${index}`}>
              <span className={styles.reasonText}>{entry.reason}</span>{' '}
              <span className={styles.penalty}>
                {signPrefixFor(entry.penalty)}
                {/* Its own element, so the digits stay byte-identical and a test
                    asking for exactly "0.05" still finds them. */}
                <span>{entry.penalty}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
