import type { Finding } from '../api/types'

/** What the deterministic validator found **when the receipt was extracted**.
 *
 * These are history, not current state, and the heading says so rather than
 * implying a freshness the data does not have. `save_findings` is the only
 * writer of `validation_findings`, and its only two callers are in the
 * extraction pipeline (pipeline.py:674 and :682) -- verified with
 * `grep -rn "save_findings" src/ tests/`, which finds no call from
 * `apply_corrections` or from any review route. So the moment a reviewer
 * corrects a total, this list still describes the receipt as it arrived: the
 * PATCH marks the row `reviewed` (persist/repository.py:1060) and writes one
 * `corrections` row per changed path, and it neither re-runs validation nor
 * touches a finding.
 *
 * `resolved_by_repair` is therefore the *extraction* run's own repair pass
 * marking an earlier finding fixed, not a reviewer's edit being acknowledged.
 */
export interface FindingsPanelProps {
  readonly findings: Finding[]
}

export function FindingsPanel({ findings }: FindingsPanelProps) {
  return (
    <section>
      <h2>What the machine found at extraction time</h2>
      <p>Not re-checked when you edit -- this is the receipt as it was extracted.</p>
      {findings.length === 0 ? (
        <p>No findings.</p>
      ) : (
        <ul>
          {findings.map((finding, index) => (
            /* Keyed on the index too, because nothing constrains `rule_id` to be
               unique per receipt: `save_findings` appends rows and never
               replaces them, a repair pass calls it a second time in the same
               run (pipeline.py:674 and :682), and `validation_findings` carries
               no unique index over (receipt_id, rule_id). Whether a duplicate
               actually occurs today is not measured -- the key simply does not
               depend on the answer. */
            <li key={`${finding.rule_id}-${index}`}>
              <strong>{finding.rule_id}</strong> <em>{finding.severity}</em> {finding.message}
              {finding.resolved_by_repair ? <span> (resolved by repair)</span> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
