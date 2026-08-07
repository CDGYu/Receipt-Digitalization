import type { Finding } from '../api/types'
import styles from './FindingsPanel.module.css'

/** What the deterministic validator found **when the receipt was extracted**.
 *
 * These are history, not current state, and the heading says so rather than
 * implying a freshness the data does not have. `save_findings` is the only
 * writer of `validation_findings`, and its only two callers are in the
 * extraction pipeline (both in pipeline.py) -- verified with
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

/** The `context` payload, disclosed -- design §5.4's expanded half.
 *
 * **Nothing rendered this before.** `Finding.context` is `unknown` on the wire
 * and `validation_findings.context` is a JSONB column the validator fills with
 * whatever the rule had to say, so there is no shape to lay out and no schema to
 * lay it out against. `JSON.stringify(_, null, 2)` in a `<pre>` prints exactly
 * what arrived, which is the same discipline `ConfidenceRail` applies to the
 * breakdown: this panel reports the record, it does not interpret it.
 *
 * `null` is the common case -- most rules record no context at all -- and it
 * gets a sentence rather than an empty box. A disclosure that opens onto nothing
 * is worse than no disclosure: it reads as data that failed to load.
 *
 * `undefined` is folded in with `null` on purpose. `JSON.stringify(undefined)`
 * returns `undefined`, not a string, so a `<pre>` fed it renders empty -- the
 * exact "opens onto nothing" failure, arrived at by a different route.
 */
function FindingContext({ context }: { readonly context: unknown }) {
  if (context === null || context === undefined) {
    return <p className={styles.noContext}>No further detail was recorded for this finding.</p>
  }
  return <pre className={styles.context}>{JSON.stringify(context, null, 2)}</pre>
}

export function FindingsPanel({ findings }: FindingsPanelProps) {
  return (
    <section className={styles.panel}>
      <h2 className={styles.heading}>What the machine found at extraction time</h2>
      <p className={styles.note}>
        Not re-checked when you edit -- this is the receipt as it was extracted.
      </p>
      {findings.length === 0 ? (
        <p className={styles.empty}>No findings.</p>
      ) : (
        <ul className={styles.list}>
          {findings.map((finding, index) => (
            /* Keyed on the index too, because nothing constrains `rule_id` to be
               unique per receipt: `save_findings` appends rows and never
               replaces them, a repair pass calls it a second time in the same
               run (pipeline.py:674 and :682), and `validation_findings` carries
               no unique index over (receipt_id, rule_id). Whether a duplicate
               actually occurs today is not measured -- the key simply does not
               depend on the answer. */
            <li className={styles.finding} key={`${finding.rule_id}-${index}`}>
              {/* §5.4's accordion, as a native `<details>`/`<summary>` pair
                  rather than a button and an `aria-expanded` region: the
                  disclosure pattern is a browser primitive, and hand-rolling it
                  would add the keyboard handling, the state and the ARIA wiring
                  that `<details>` already ships correctly.

                  **The collapsed row keeps everything the flat list showed** --
                  `rule_id`, the severity word, the message and the repair note
                  -- because `review-screen.test.tsx:222` finds `R020` by text on
                  the loaded screen, and more to the point because a reviewer
                  scans this panel without opening anything. Only the `context`
                  payload, which nothing rendered at all before, is behind the
                  disclosure. */}
              <details className={styles.disclosure}>
                <summary className={styles.summary}>
                  <strong className={styles.ruleId}>{finding.rule_id}</strong>{' '}
                  {/* The severity word is always rendered; the class only paints
                      it. `styles[...]` is keyed on the server's own lowercase
                      vocabulary (`error`/`warn`/`info` -- the `Severity` enum
                      in validate/report.py) and paints nothing for anything
                      else, so an unknown severity degrades to the word alone
                      rather than to a wrong colour. */}
                  <em className={`${styles.severity} ${styles[finding.severity] ?? ''}`}>
                    {finding.severity}
                  </em>{' '}
                  {finding.message}
                  {finding.resolved_by_repair ? (
                    <span className={styles.resolved}> (resolved by repair)</span>
                  ) : null}
                </summary>
                <FindingContext context={finding.context} />
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
