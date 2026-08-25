import type { Finding } from '../api/types'
import styles from './FindingsPanel.module.css'

export interface FindingsPanelProps {
  /** Extraction-time findings -- history, not current state. */
  readonly findings: Finding[]
  /** Findings re-computed from the receipt as it now stands (after corrections). */
  readonly currentFindings: Finding[]
  /** Rule IDs that could not be re-run at review time. */
  readonly notRechecked: string[]
}

function FindingContext({ context }: { readonly context: unknown }) {
  if (context === null || context === undefined) {
    return <p className={styles.noContext}>No further detail was recorded for this finding.</p>
  }
  return <pre className={styles.context}>{JSON.stringify(context, null, 2)}</pre>
}

function FindingsList({ findings }: { readonly findings: Finding[] }) {
  if (findings.length === 0) {
    return <p className={styles.empty}>No findings.</p>
  }
  return (
    <ul className={styles.list}>
      {findings.map((finding, index) => (
        <li className={styles.finding} key={`${finding.rule_id}-${index}`}>
          <details className={styles.disclosure}>
            <summary className={styles.summary}>
              <strong className={styles.ruleId}>{finding.rule_id}</strong>{' '}
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
  )
}

export function FindingsPanel({ findings, currentFindings, notRechecked }: FindingsPanelProps) {
  return (
    <section className={styles.panel}>
      {/* Current state: what the rules say about the receipt NOW */}
      <h2 className={styles.heading}>Current validation state</h2>
      <p className={styles.note}>
        Re-checked against the receipt as it stands now, after any corrections.
      </p>
      <FindingsList findings={currentFindings} />

      {notRechecked.length > 0 && (
        <p className={styles.notRechecked}>
          Not re-checked (require extraction context):{' '}
          <span className={styles.notRecheckedIds}>
            {notRechecked.join(', ')}
          </span>
        </p>
      )}

      {/* Extraction-time history */}
      <h2 className={`${styles.heading} ${styles.historyHeading}`}>
        What the machine found at extraction time
      </h2>
      <p className={styles.note}>
        Not re-checked when you edit &mdash; this is the receipt as it was extracted.
      </p>
      <FindingsList findings={findings} />
    </section>
  )
}
