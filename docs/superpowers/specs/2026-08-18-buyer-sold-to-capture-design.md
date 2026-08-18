# Buyer / Sold-To capture, and the receipt-is-ours check

**Status:** design approved 2026-08-18. Not yet implemented.
**Milestone:** M1 (buyer capture). **Spec:** §6 (data model), §10 (validation), §17 (config).
**Blocked on nothing.** Every fact below was derived on 2026-08-18 from the three
golden images and the tree, not from prose.

---

## 1. The gap, and why no gate could have found it

`ReceiptExtraction` has `merchant`, `receipt`, `line_items`, `totals`, `payment`
and `meta`. **It has no concept of the buyer.** `git grep -n -i "buyer\|sold_to"
-- src/receipts/extract/schema.py` returns nothing, and
`RECEIPT_SYSTEM_SPEC.md` never specified one.

So on a BIR sales invoice the **Sold To** — legally, who the invoice was issued
to, and what an input-VAT claim rests on — is read by nobody and stored nowhere.
This was found by a person reading real extraction output. **No gate can notice
the absence of a field nobody defined**, which puts it in the same class as
ADR-0029's blind spots rather than in the class of things a test could catch.

**It is a gap, not a regression.** The current output is correct *for the schema
as written*: all three golden labels carry a note warning that the Sold To is the
buyer and must not be filed as the merchant, and the extractor obeys that.

## 2. What the three golden receipts actually say

Read directly from `eval/golden/images/` on 2026-08-18. **This section is the
evidence the rest of the design rests on; re-derive it before contradicting it.**

| receipt | merchant | buyer label on the form | buyer name | buyer TIN |
|---|---|---|---|---|
| r001 | METRO OIL SUBIC, INC. | `SOLD TO` | `IDEAL SOURCE` | **blank** |
| r002 | SUMMIT FUEL OPC | `SOLD TO` → `Registered Name :` | `Ideal source` | **blank** |
| r003 | SERV CENTRAL, INC. | `Sold to:` | `IDEAL SOURCE` | **blank** |

Three facts follow, and each one changes a decision:

1. **The buyer TIN line exists on every form and is filled on none.** A TIN-first
   buyer match would be **dead code on this corpus**.
2. **The buyer name is handwritten on all three**, on forms whose other fields
   are pre-printed. It is the least legible field on the page.
3. **The label wording differs on every receipt** — `SOLD TO`, `Registered
   Name`, `Sold to:`. A prompt naming only one spelling would miss the others.

The buyer is also **the same entity on all three**, which is expected: these are
invoices issued *to* the operator. That is what makes the validation rule worth
more than the field.

## 3. Decisions

### 3.1 A `Buyer` model with `name` and `tax_id`, parallel to `Merchant`

```python
class Buyer(BaseModel):
    name: str | None = None
    tax_id: str | None = None
```

and `buyer: Buyer = Field(default_factory=Buyer)` on `ReceiptExtraction`.

**No `address`.** The form has a Business Address line and it is blank on all
three. Adding it costs a column and a second fuzzy-match surface for a field
with no consumer and no evidence it is ever filled. Add it when a receipt
carries one.

### 3.2 Two columns on `receipts`, mirroring `merchant_name_raw`

`buyer_name_raw` and `buyer_tax_id`, both `sa.Text`, both nullable. Alembic
revision 3. Nullable because §2 shows the TIN is normally absent and the name
may be unreadable — **a NOT NULL here would turn an ordinary receipt into a
persist-stage failure**, which is the class of defect ADR-0043's milestone shipped
and had to fix.

### 3.3 Two rules, in the presence/identity band

Rule IDs in use: `R001, R010–R013, R020–R025, R030–R033, R040–R045, R050–R053,
R060, R061, R070` (derived from `src/receipts/validate/rules.py`). `R010–R013` is
the presence family, so the next free ID in it is `R014`.

- **`R014` — the buyer was not read.** Fires when `buyer.name` is empty.
  **Severity WARN.** Absent data, not wrong data.
- **`R015` — the buyer does not match the configured buyer.** Severity is
  **split**, see §3.5.

**`R014` keys on `name`, never on `tax_id`.** §2 shows the TIN is blank on the
paper, so a null `buyer.tax_id` is a *correct* extraction of an empty field.
A rule that flagged it would fire on every receipt in the corpus and be
correct about none of them.

### 3.4 Identity is two-phase, and the phases are honestly labelled

`tax_id` first, `name` second — the same shape as ADR-0043 decision 1, and for
the same reason: a TIN is a precise identifier and a name is a guess.

The name comparison reuses **`normalize_merchant_name`**, whose own docstring
says it is "for FINGERPRINTING". No edit distance, no substring, no prefix —
ADR-0043 decision 2's reasoning transfers unchanged.

**But it must be recorded that the TIN branch is unexercised on this corpus.**
All three buyer TINs are blank, so today the name branch does all the work.
Writing TIN-first is still correct — it is right the moment a receipt carries a
buyer TIN — but a claim that it is load-bearing would be false. ADR-0043
decision 3 records the mirror-image failure, where an ordering made `confirm`
permanently dead; this is the same trap seen from the other side, and it is
named here so the implementation does not "simplify" the TIN branch away, nor
claim a test covers it when the corpus cannot reach it.

### 3.5 The severity split, which is the subtlest decision here

| what was compared | outcome | severity |
|---|---|---|
| `tax_id` present on both sides, differs | mismatch | **ERROR** |
| `tax_id` absent, normalized `name` differs | mismatch | **WARN** |
| either matches | pass | — |
| `buyer.name` empty | not read | `R014` WARN |

**Why not ERROR for both.** The buyer name is handwritten (§2), so it is exactly
the field most likely to be misread. An ERROR blocks auto-approval, so a
name-only ERROR would route most of the corpus to review on the strength of the
least legible field on the page — trading throughput for a check that is mostly
firing on OCR noise.

**Why ERROR at all for the TIN.** A printed TIN that differs is not a misread of
a letter; it is a different registered entity. That is the case worth stopping,
and it is the case a human reviewer cannot spot at a glance.

**Why WARN is enough for the name.** It surfaces in the report and lowers
confidence without asserting fraud. The tri-state is the point: *matched*,
*differs*, and *not read* are three different states and must not collapse into
two — the same `null` ≠ `0` ≠ empty discipline ADR-0027 decision 5 applies to
rendering, applied to a rule.

**This is ONE rule with a per-finding severity, not two rule IDs.** `Rule.finding()`
already takes a `severity` override (`severity=severity or self.severity`), and
**`R011` is the precedent in the same file**: its class severity is WARN and it
emits INFO on the branch where the date is null but `date_raw` was captured —
which is the `[info] R011` line the 2026-08-18 cloud run produced. So `R015`
declares `severity = Severity.WARN` at class level and overrides to ERROR on the
TIN branch. Splitting it into two IDs would make "the buyer does not match" two
concepts in the catalogue when it is one.

### 3.6 Configuration by env var, precedent `DEFAULT_CURRENCY`

`EXPECTED_BUYER_NAME` and `EXPECTED_BUYER_TAX_ID` on `Settings`.

**Both unset → both rules are inert.** The buyer identity is a per-deployment
constant, exactly like `DEFAULT_CURRENCY`, not a tuning knob — so it belongs in
the environment rather than in `config/rules.yaml`, which holds thresholds and
weights. Inert-by-default also means this ships without breaking any corpus
whose receipts are not addressed to the configured operator.

### 3.7 The prompt must name all three spellings, and say what the Sold To is not

The extraction prompt gains the buyer, and must state that the Sold To /
Registered Name / Sold to block is the **buyer**, distinct from the merchant in
the header and from the printer's details in the footer. All three golden labels
already carry that warning as a note to humans; the model has never been told.

**There are three TINs on a BIR invoice** — merchant, buyer and printer — and the
golden notes record that the footer TIN belongs to the printer on every one of
the three. The prompt must say so, or the buyer TIN field becomes a magnet for
the printer's.

### 3.8 The reviewer must be able to correct it

`ReceiptForm` gains buyer name and TIN fields. **Without this, `R015` raises a
finding a reviewer cannot clear**, and an unactionable blocking finding is worse
than no rule. Money-field rules do not apply here — these are text — but
ADR-0027's `null` ≠ empty rendering does.

### 3.9 Two Excel columns

`export/xlsx.py`'s review sheet gains buyer name and buyer TIN. The summary sheet
is unchanged: the buyer is a per-receipt fact, and on this corpus it is constant,
so it summarises to nothing.

## 4. Golden labels

All three gain a `buyer` block: `name` as written on the paper (§2 — note r002 is
`Ideal source`, not `IDEAL SOURCE`; the labels record what the receipt says, not
what the operator is called), and `tax_id: null`.

**This must land with the schema change, not after.** ADR-0040 reads `filled`
from the truth side only, so an unlabelled `buyer` path scores a correct
extraction as a **hallucination**. Adding the field without the labels would make
accuracy appear to drop.

## 5. What this design does NOT do

- **No buyer registry, and no `Merchant`-style table.** The buyer is one
  configured entity, not a set to be discovered. If a second operator ever
  shares the deployment, that is a new design.
- **No fuzzy matching**, for ADR-0043 decision 2's reason.
- **No back-fill.** Existing rows keep NULL buyers. A reprocess populates them;
  nothing rewrites history.
- **No confidence-weight change.** Whether `R014`/`R015` should move the score is
  P3.T6's business, and that is blocked on ISSUE-001's calibration.

## 6. Risks, named so they are decisions rather than surprises

- **The name branch carries the whole rule on this corpus, and it reads
  handwriting.** If `R015`'s WARN proves noisy in practice, the answer is to
  measure the false-positive rate before changing the severity — not to widen the
  matcher, which ADR-0043 decision 2 refused for the merchant side.
- **`normalize_merchant_name` was built for merchant names.** Reusing it for a
  buyer is deliberate, but it is a second caller with different inputs; its
  behaviour on the buyer strings must be pinned by tests rather than assumed.
- **Cloud extraction is not deterministic** (ISSUE-001, 2026-08-18). Two runs of
  the same receipt disagreed. A buyer-match rule will therefore not fire
  identically across runs, and any measurement of its false-positive rate needs
  repeats.

## 7. Testing

- The tri-state pinned in all three directions, each proven red separately —
  matched, differs, not read. ADR-0033's "revert each guarantee separately"
  applies: a single test covering all three proves none of them.
- `R014` proven **not** to fire on a null `tax_id` with a present name, which is
  the whole corpus.
- The TIN-mismatch ERROR path pinned with a synthetic fixture, since §2 shows the
  golden set cannot reach it. **The test must say so**, or a later reader will
  believe the corpus exercises it.
- `normalize_merchant_name` pinned on buyer-shaped inputs.
- Round-trip through `PATCH /receipts/{id}` and the export, so a corrected buyer
  reaches both the row and the workbook.
