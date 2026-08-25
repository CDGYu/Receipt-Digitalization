import type { FieldMap } from './patch'
import { MoneyInput } from './MoneyInput'
import type { TaxBand } from '../api/types'
import styles from './TaxBands.module.css'

/** The receipt's printed tax breakdown, correctable band by band.
 *
 * ## What this shows, and why it did not exist before
 *
 * The VATABLE SALES / VAT-EXEMPT SALES / zero-rated block a Philippine BIR
 * sales invoice prints beneath its items grid -- "Amount: Net of VAT" and
 * "ADD: VAT" in the owner's own words. The extractor has always read it: the
 * prompt asks for `totals.tax_breakdown` by name and the validation rules
 * reconcile the bands against `totals.tax`. **The database had no column for
 * it**, so it was discarded at persistence and never reached this screen.
 * `d5b8c31e7a04` gave it one.
 *
 * ## Correcting a band
 *
 * Each figure is its own correction path -- `totals.tax_breakdown[0].amount` --
 * which is why the bands are rows in a table and not a JSON blob. The paths
 * come from `fieldsFromReceipt`, so an edit here travels the same
 * `buildPatch` -> `PATCH /receipts/{id}` -> `corrections` route as any other
 * field, and is logged the same way.
 *
 * **The index is the position**, unlike `LineItemsTable`. `TaxBand` has no
 * position field for the model to emit, so `_build_tax_bands` numbers the bands
 * by list order and there can be no gap to fall through.
 *
 * ## What it deliberately does not offer
 *
 * **No add and no remove.** The correction protocol addresses existing paths;
 * `line_items` offers neither either. A band the model missed entirely is not
 * something a reviewer can conjure here, and pretending otherwise with a
 * disabled-looking button would be worse than its absence.
 *
 * `rate` is rendered exactly as it arrived. The convention upstream is
 * **unstated** -- a 12% band may come through as `12` or as `0.12` -- so
 * nothing here rescales it into a reading the document never declared.
 */
export interface TaxBandsProps {
  readonly bands: readonly TaxBand[]
  readonly fields: FieldMap
  readonly onChange: (path: string, value: string | null) => void
  readonly errors?: Readonly<Record<string, string>> | null
}

export function TaxBands({ bands, fields, onChange, errors }: TaxBandsProps) {
  return (
    <section className={styles.panel} aria-labelledby="tax-bands-heading">
      <h2 className={styles.heading} id="tax-bands-heading">
        Tax breakdown
      </h2>
      {bands.length === 0 ? (
        // Two different facts arrive here as one empty list, and saying only
        // "none" would let a reader assume the paper had none. A receipt
        // processed before the bands were storable also lands here.
        <p className={styles.empty}>
          No tax breakdown was read from this receipt. A receipt processed before the breakdown
          was stored will show none even if the paper printed one.
        </p>
      ) : (
        <>
          <p className={styles.hint}>
            As printed. Nothing here is calculated — a band the receipt does not print stays
            blank.
          </p>
          <div className={styles.scroller}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Band</th>
                  <th scope="col" className={styles.numeric}>
                    Base
                  </th>
                  <th scope="col" className={styles.numeric}>
                    Rate
                  </th>
                  <th scope="col" className={styles.numeric}>
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody>
                {bands.map((_band, index) => {
                  const at = `totals.tax_breakdown[${index}]`
                  return (
                    <tr key={at}>
                      <td>
                        <input
                          type="text"
                          autoComplete="off"
                          aria-label={`Band ${index + 1} label`}
                          value={fields[`${at}.label`] ?? ''}
                          onChange={(e) =>
                            onChange(`${at}.label`, e.target.value === '' ? null : e.target.value)
                          }
                        />
                      </td>
                      {/* `labelHidden`, because the column header already says
                          Base / Rate / Amount. Without it every row repeats all
                          three headers -- the defect this component would
                          otherwise reproduce from `LineItemsTable`, which had
                          exactly that until it was fixed. */}
                      <td className={styles.numeric}>
                        <MoneyInput
                          label={`Band ${index + 1} base`}
                          labelHidden
                          value={fields[`${at}.base`]}
                          error={errors?.[`${at}.base`]}
                          onChange={(value) => onChange(`${at}.base`, value)}
                        />
                      </td>
                      <td className={styles.numeric}>
                        <MoneyInput
                          label={`Band ${index + 1} rate`}
                          labelHidden
                          value={fields[`${at}.rate`]}
                          error={errors?.[`${at}.rate`]}
                          onChange={(value) => onChange(`${at}.rate`, value)}
                        />
                      </td>
                      <td className={styles.numeric}>
                        <MoneyInput
                          label={`Band ${index + 1} amount`}
                          labelHidden
                          value={fields[`${at}.amount`]}
                          error={errors?.[`${at}.amount`]}
                          onChange={(value) => onChange(`${at}.amount`, value)}
                        />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
