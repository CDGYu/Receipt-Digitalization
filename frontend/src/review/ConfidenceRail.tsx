import type { ConfidenceReason, Money } from '../api/types'

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

export function ConfidenceRail({ confidence, reasons }: ConfidenceRailProps) {
  return (
    <aside>
      <h2>Confidence</h2>
      {/* The score as the API sent it. An em dash, not "0" or "0.00": a score
          that was never recorded is not a recorded zero (`money()` keeps that
          distinction on the way out, review/serializers.py:65-73). */}
      <p>{confidence ?? '—'}</p>
      {reasons === null ? (
        <p>Breakdown not recorded for this receipt.</p>
      ) : reasons.length === 0 ? (
        <p>Nothing lowered the score.</p>
      ) : (
        <ul>
          {reasons.map((entry, index) => (
            /* Keyed on the index as well as the text. The pipeline emits each
               reason at most once per receipt (`_signals`, score/confidence.py
               :122-195), but this is a JSONB column read verbatim -- a row that
               came from anywhere else can repeat a reason, and duplicate React
               keys are not a failure mode worth inheriting for that. */
            <li key={`${entry.reason}-${index}`}>
              <span>{entry.reason}</span> <span>{entry.penalty}</span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
