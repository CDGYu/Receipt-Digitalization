/** A decimal that must never become a JS number (ADR-0001).
 *
 * The API serialises every Decimal as a string precisely so a JSON number --
 * which is a float -- never touches the money path. No arithmetic is defined
 * on this type; if you find yourself wanting some, the answer is a server
 * round-trip, not a parseFloat.
 */
export type Money = string & { readonly __money: unique symbol }

export interface ConfidenceReason {
  reason: string
  penalty: Money
}

export interface LineItem {
  position: number
  description_raw: string | null
  sku: string | null
  qty: Money | null
  unit: string | null
  unit_price: Money | null
  line_total: Money | null
  line_confidence: Money | null
}

export interface Finding {
  rule_id: string
  severity: string
  message: string
  context: unknown
  resolved_by_repair: boolean
}

export interface ReceiptDetail {
  id: string
  status: string
  confidence: Money | null
  /** `null` = never recorded. `[]` = nothing lowered the score. Different facts. */
  confidence_reasons: ConfidenceReason[] | null
  merchant_name_raw: string | null
  txn_date: string | null
  date_raw: string | null
  currency: string | null
  card_last4: string | null
  is_handwritten: boolean | null
  legibility: string
  receipt_is_inconsistent: boolean | null
  totals: {
    subtotal: Money | null
    tax: Money | null
    discount: Money | null
    total: Money | null
    tender: Money | null
    change: Money | null
  }
  line_items: LineItem[]
  findings: Finding[]
}

export interface ReviewTask {
  id: string
  receipt_id: string
  reason: string
  priority: number
  state: string
}
