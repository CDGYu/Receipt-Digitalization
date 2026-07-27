"""All prompt text for the extraction pipeline.

Nothing outside this module may build a prompt string. Business logic that
concatenates prompt fragments inline becomes impossible to version, diff, or
attribute accuracy changes to.

Rules for editing this file:
  1. Bump PROMPT_VERSION on ANY change to the text below.
  2. Re-run `receipts eval` before merging. An unmeasured prompt change is a
     regression waiting to happen.
  3. Keep SYSTEM_EXTRACTION under ~1200 tokens. Past that, the later rules get
     progressively ignored. Extra guidance belongs in merchant hints, which are
     injected in the user turn where they are close to the image.
  4. No examples in the system prompt. Few-shot examples are merchant-specific
     and belong in the user turn.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .schema import ReceiptExtraction, TriageResult  # noqa: F401  (re-exported)

PROMPT_VERSION = "1.0.0"


# --------------------------------------------------------------------------- #
# System prompt — used for pass 2 (extract) and pass 3 (repair)
# --------------------------------------------------------------------------- #

SYSTEM_EXTRACTION = """\
You are a receipt data extraction engine. You convert photographs of receipts into
structured JSON for an accounting pipeline. In this pipeline, a wrong number is far
worse than a missing number.

RULES, in priority order:

1. TRANSCRIBE - DO NOT INFER.
   Output only what is visibly printed or written on the receipt. If a field is not
   present, is cut off, or you cannot read it, output null.
   - Never compute a value that is not printed. If the subtotal is not shown, do not
     add up the line items to produce one - return null.
   - Never infer a merchant name from a logo you only partly recognise.
   - Never "correct" arithmetic. If the printed numbers do not add up, report them
     exactly as printed and set meta.receipt_is_inconsistent = true.

2. NULL IS A CORRECT ANSWER.
   You are not penalised for nulls. You are heavily penalised for confident wrong
   values. When a character is genuinely ambiguous (a 1 that could be a 7, a 5 that
   could be an S), give your best reading AND add the field's dotted path to
   meta.ambiguous_fields.

3. PRESERVE AS PRINTED.
   - merchant.name: exactly as printed, including punctuation, casing, and legal
     suffixes.
   - line_items[].description_raw: exactly as printed, including abbreviations and
     truncations. "CHKN BRST 1KG" stays "CHKN BRST 1KG" - do not expand it to
     "Chicken Breast 1kg".
   - Do not translate anything. Keep the original language.

4. NUMBERS.
   - All monetary values are JSON numbers, not strings. No currency symbols, no
     thousands separators. "1,234.50" becomes 1234.50.
   - If the receipt uses comma as the decimal separator ("1.234,50"), convert to
     1234.50 and set receipt.decimal_convention = "comma".
   - Refunds, voids, and item-level discounts are NEGATIVE numbers.
   - Never round and never pad. If the receipt prints 3 decimal places, keep 3.
   - If a digit is obscured, do not guess the whole number - null the field.

5. LINE ITEMS.
   - One object per purchasable line, in printed order, position starting at 0.
   - A line that wraps onto two physical rows is ONE line item.
   - Item-level discounts or promos printed beneath an item go into that item's
     modifiers array, NOT as separate line items.
   - Basket-level discounts go in totals.discount, NOT in line_items.
   - Do NOT create line items for: subtotal, tax, total, change, cashier name,
     store slogans, loyalty points, barcodes, or footer text.
   - If quantity is not printed, leave qty null - do not assume 1.

6. DATES AND TIMES.
   - receipt.date must be ISO 8601 YYYY-MM-DD. receipt.time must be HH:MM, 24-hour.
   - If the printed date is ambiguous between conventions (e.g. "03/04/2026" could be
     3 April or 4 March), set receipt.date to null, put the verbatim string in
     receipt.date_raw, and add "receipt.date" to meta.ambiguous_fields.
   - A two-digit year may be expanded only when unambiguous in context.

7. TAX.
   - Populate totals.tax with the total tax charged.
   - If the receipt prints a tax breakdown (taxable base, exempt, zero-rated, rate
     bands), fill totals.tax_breakdown with one object per band. Do not compute
     bands that are not printed.

8. OUTPUT.
   Return exactly one JSON object matching the provided schema. No markdown code
   fences. No prose before or after. No explanation.
"""


# --------------------------------------------------------------------------- #
# Pass 1 - triage
# --------------------------------------------------------------------------- #

TRIAGE_PROMPT = """\
Classify this image. Do NOT extract any amounts, item names, or totals.

Return exactly one JSON object:

{
  "is_receipt": boolean,
  "document_type": "pos_receipt" | "handwritten_receipt" | "invoice" |
                   "delivery_note" | "not_a_receipt",
  "print_type": "thermal" | "dot_matrix" | "laser" | "handwritten" | "mixed",
  "legibility": "good" | "fair" | "poor" | "unreadable",
  "estimated_line_item_count": integer,
  "merchant_name_guess": string | null,
  "language": string | null,
  "issues": array of any of
            ["blurry","glare","folded","faded","cropped","partial","low_resolution",
             "obstructed","multiple_receipts","not_flat"]
}

Guidance:
- "mixed" print_type means a pre-printed form filled in by hand. This is common and
  should be classified as "handwritten_receipt" for document_type.
- legibility "unreadable" means a human could not reliably read the totals either.
- If more than one receipt appears in the frame, include "multiple_receipts" in
  issues and set is_receipt to true.
- estimated_line_item_count is a count of purchasable item rows only. Do not count
  subtotal, tax, total, or footer rows.

JSON only.
"""


# --------------------------------------------------------------------------- #
# Pass 2 - extraction
# --------------------------------------------------------------------------- #

EXTRACTION_PROMPT_TEMPLATE = """\
Extract this receipt into the schema.
{merchant_hints}{few_shots}
Reminders for this receipt:
- Print type: {print_type}
- Expected line items: roughly {expected_items}
- Known issues with this image: {issues}
{addendum}
Work top to bottom through the receipt. Before returning, verify:
  (a) every line item you listed is a purchasable item, not a subtotal or footer line
  (b) you have not invented any number that is not printed
  (c) every field you were unsure about is listed in meta.ambiguous_fields

Return JSON only.
"""

MERCHANT_HINTS_TEMPLATE = """
This receipt appears to be from {merchant_name}. Known characteristics:
{hint_lines}
Use these as guidance only. If what you see contradicts them, trust the image.
"""

FEW_SHOT_HEADER = """
Below are {n} verified extraction(s) from this same merchant, shown as
image followed by the correct JSON. Match their conventions, but extract only
what is on the CURRENT receipt.
"""

HANDWRITING_ADDENDUM = """
This receipt is handwritten. Additional rules:

- Handwritten digits are the primary risk. 1/7, 0/6, 3/8, 5/S, and 4/9 are commonly
  confused. When a digit is ambiguous, null the ENTIRE number rather than guessing a
  digit, and record the field path in meta.ambiguous_fields.
- Do not normalise handwritten item names into retail product names. Transcribe the
  characters you actually see.
- Handwritten receipts frequently omit subtotal, tax, or quantity entirely. Leave
  those null. Do not derive them.
- Currency symbols are often omitted. Leave receipt.currency null unless a symbol or
  code is actually written.
- If the writer crossed something out and rewrote it, transcribe the final value and
  note the correction in meta.notes.
"""


# --------------------------------------------------------------------------- #
# Pass 3 - repair
# --------------------------------------------------------------------------- #

REPAIR_PROMPT_TEMPLATE = """\
You previously extracted this receipt as:

{previous_json}

Automated validation found these problems:

{findings}

Re-examine the image and return a corrected JSON object in the same schema.

Rules for this correction pass:
- Change only the fields that are actually wrong when you re-read the image. Leave
  everything else byte-identical.
- Do NOT alter numbers to make the arithmetic work. If the receipt as printed
  genuinely does not add up, keep the printed values and set
  meta.receipt_is_inconsistent = true.
- If re-reading shows a value is not legible after all, set it to null rather than
  keeping your earlier guess.
- If a validation complaint is wrong - the original extraction was right - keep the
  original value and explain briefly in meta.notes.

Return JSON only.
"""


# --------------------------------------------------------------------------- #
# Supporting types
# --------------------------------------------------------------------------- #


@dataclass
class MerchantHints:
    merchant_name: str
    hints: list[str] = field(default_factory=list)


@dataclass
class FewShot:
    """A verified prior extraction used as an in-context example.

    Only build these from receipts with status='reviewed' AND zero rows in the
    corrections table. An unverified example teaches the model your errors.
    """

    image_b64: str
    extraction: ReceiptExtraction
    media_type: str = "image/jpeg"


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def build_triage_prompt() -> str:
    return TRIAGE_PROMPT


def build_extraction_prompt(
    triage: TriageResult | None = None,
    hints: MerchantHints | None = None,
    few_shots: list[FewShot] | None = None,
) -> str:
    """Compose the pass-2 user message.

    The few-shot IMAGES are attached by the caller as separate image blocks;
    this function only emits the framing text and the expected JSON for each.
    """
    few_shots = few_shots or []

    hints_block = ""
    if hints and hints.hints:
        hint_lines = "\n".join(f"- {h}" for h in hints.hints)
        hints_block = MERCHANT_HINTS_TEMPLATE.format(
            merchant_name=hints.merchant_name, hint_lines=hint_lines
        )

    few_shot_block = ""
    if few_shots:
        parts = [FEW_SHOT_HEADER.format(n=len(few_shots))]
        for i, shot in enumerate(few_shots, start=1):
            parts.append(
                f"\nExample {i} expected output:\n"
                f"{shot.extraction.model_dump_json(indent=2, exclude_none=True)}\n"
            )
        few_shot_block = "".join(parts)

    addendum = HANDWRITING_ADDENDUM if (triage and triage.is_handwritten) else ""

    return EXTRACTION_PROMPT_TEMPLATE.format(
        merchant_hints=hints_block,
        few_shots=few_shot_block,
        print_type=triage.print_type.value if triage else "unknown",
        expected_items=triage.estimated_line_item_count if triage else "unknown",
        issues=", ".join(triage.issues) if triage and triage.issues else "none reported",
        addendum=addendum,
    )


def build_repair_prompt(previous: ReceiptExtraction, findings_text: str) -> str:
    """Compose the pass-3 user message.

    `findings_text` comes from ValidationReport.render_for_repair_prompt().
    Nulls are deliberately NOT excluded from the previous JSON — the model needs
    to see which fields it left empty.
    """
    return REPAIR_PROMPT_TEMPLATE.format(
        previous_json=previous.model_dump_json(indent=2),
        findings=findings_text.strip() or "(none)",
    )


# --------------------------------------------------------------------------- #
# Versioning
# --------------------------------------------------------------------------- #


def prompt_hash(text: str) -> str:
    """16-char stable hash, logged to extraction_runs.prompt_hash."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def prompt_bundle_hash() -> str:
    """Hash of every prompt constant. Changes whenever any template changes,
    which is what you group eval results by."""
    bundle = "\x00".join(
        [
            PROMPT_VERSION,
            SYSTEM_EXTRACTION,
            TRIAGE_PROMPT,
            EXTRACTION_PROMPT_TEMPLATE,
            MERCHANT_HINTS_TEMPLATE,
            FEW_SHOT_HEADER,
            HANDWRITING_ADDENDUM,
            REPAIR_PROMPT_TEMPLATE,
        ]
    )
    return prompt_hash(bundle)
