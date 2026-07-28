"""Canonical extraction schema.

This is the contract between the VLM and the rest of the pipeline. Every other
module depends on these types; nothing here depends on anything else.

Money is ALWAYS Decimal. See §18 of the spec — a single float in the arithmetic
path produces tolerance failures that look like model errors.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class Legibility(str, Enum):
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNREADABLE = "unreadable"


class DocumentType(str, Enum):
    POS_RECEIPT = "pos_receipt"
    HANDWRITTEN_RECEIPT = "handwritten_receipt"
    INVOICE = "invoice"
    DELIVERY_NOTE = "delivery_note"
    NOT_A_RECEIPT = "not_a_receipt"


class PrintType(str, Enum):
    THERMAL = "thermal"
    DOT_MATRIX = "dot_matrix"
    LASER = "laser"
    HANDWRITTEN = "handwritten"
    MIXED = "mixed"


# --------------------------------------------------------------------------- #
# Extraction models
# --------------------------------------------------------------------------- #

_MODEL_CONFIG = ConfigDict(extra="ignore", validate_assignment=False)


class Modifier(BaseModel):
    """An item-level discount, promo, or adjustment printed under a line item.

    `amount` is SIGNED: discounts are negative, surcharges positive.
    """

    model_config = _MODEL_CONFIG

    label: str
    amount: Decimal | None = None


class LineItem(BaseModel):
    model_config = _MODEL_CONFIG

    position: int = 0
    description_raw: str = ""
    sku: str | None = None
    qty: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    modifiers: list[Modifier] = Field(default_factory=list)
    bbox: list[float] | None = Field(
        default=None, description="[x0,y0,x1,y1] normalised 0-1 if model supports grounding"
    )

    def net_total(self) -> Decimal | None:
        """line_total plus signed modifier amounts. None if line_total is None."""
        if self.line_total is None:
            return None
        adj = sum((m.amount for m in self.modifiers if m.amount is not None), Decimal(0))
        return self.line_total + adj


class Merchant(BaseModel):
    model_config = _MODEL_CONFIG

    name: str | None = None
    branch: str | None = None
    address: str | None = None
    tax_id: str | None = None
    phone: str | None = None


class ReceiptMeta(BaseModel):
    model_config = _MODEL_CONFIG

    number: str | None = None
    date: str | None = Field(default=None, description="ISO 8601 YYYY-MM-DD")
    date_raw: str | None = Field(default=None, description="Verbatim, kept when ambiguous")
    time: str | None = Field(default=None, description="HH:MM 24h")
    currency: str | None = Field(default=None, description="ISO 4217")
    decimal_convention: Literal["point", "comma"] = "point"
    cashier: str | None = None
    terminal: str | None = None


class TaxBand(BaseModel):
    model_config = _MODEL_CONFIG

    label: str | None = None
    base: Decimal | None = None
    rate: Decimal | None = None
    amount: Decimal | None = None


class Totals(BaseModel):
    """NOTE ON SIGN CONVENTION:

    `discount` is stored as a POSITIVE MAGNITUDE (the amount taken off), even
    though the model is told to emit discounts as negative numbers. The
    normalisation layer flips the sign. Validation rules defensively use
    abs() so they behave correctly under either convention.

    NOTE ON TAX CONVENTION:

    `prices_include_tax` records whether the line-item Amount column is gross or
    net. It changes which figure the line items are expected to sum to, so R020
    and R024 read it. It is NOT money — it is the document's stated convention,
    and null (the usual case) means the document does not state one.
    """

    model_config = _MODEL_CONFIG

    subtotal: Decimal | None = None
    tax: Decimal | None = None
    tax_breakdown: list[TaxBand] = Field(default_factory=list)
    discount: Decimal | None = None
    total: Decimal | None = None
    tender: Decimal | None = None
    change: Decimal | None = None
    prices_include_tax: bool | None = Field(
        default=None,
        description=(
            "Whether the line-item amounts already include tax. true = tax-inclusive, "
            "so the line amounts sum to total (common on tax invoices, e.g. a "
            "Philippine BIR SALES INVOICE, where subtotal is the net-of-VAT tax "
            "base). false = amounts are net of tax, so they sum to subtotal. "
            "null if the receipt does not state which - do not guess."
        ),
    )


class Payment(BaseModel):
    model_config = _MODEL_CONFIG

    method: str | None = None
    card_last4: str | None = None


class ExtractionMeta(BaseModel):
    model_config = _MODEL_CONFIG

    is_handwritten: bool = False
    is_refund: bool = Field(
        default=False,
        description="Set when the document is a refund/void, so a negative total is legal.",
    )
    legibility: Legibility = Legibility.GOOD
    ambiguous_fields: list[str] = Field(default_factory=list)
    unreadable_regions: list[str] = Field(default_factory=list)
    receipt_is_inconsistent: bool = Field(
        default=False,
        description="The PRINTED receipt genuinely does not add up. Not an extraction error.",
    )
    notes: str | None = None


class ReceiptExtraction(BaseModel):
    model_config = _MODEL_CONFIG

    merchant: Merchant = Field(default_factory=Merchant)
    receipt: ReceiptMeta = Field(default_factory=ReceiptMeta)
    line_items: list[LineItem] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    payment: Payment = Field(default_factory=Payment)
    meta: ExtractionMeta = Field(default_factory=ExtractionMeta)


# --------------------------------------------------------------------------- #
# Pass 1 (triage) and self-consistency
# --------------------------------------------------------------------------- #


class TriageResult(BaseModel):
    model_config = _MODEL_CONFIG

    is_receipt: bool = True
    document_type: DocumentType = DocumentType.POS_RECEIPT
    print_type: PrintType = PrintType.THERMAL
    legibility: Legibility = Legibility.GOOD
    estimated_line_item_count: int = 0
    merchant_name_guess: str | None = None
    language: str | None = None
    issues: list[str] = Field(default_factory=list)

    @property
    def is_handwritten(self) -> bool:
        return (
            self.document_type is DocumentType.HANDWRITTEN_RECEIPT
            or self.print_type in (PrintType.HANDWRITTEN, PrintType.MIXED)
        )


class ConsistencyResult(BaseModel):
    """Output of running extraction n times and diffing the results."""

    model_config = _MODEL_CONFIG

    runs: int = 1
    consensus: ReceiptExtraction = Field(default_factory=ReceiptExtraction)
    agreement: dict[str, float] = Field(default_factory=dict)
    disputed: list[str] = Field(default_factory=list)
    values_by_path: dict[str, list[Any]] = Field(default_factory=dict)
