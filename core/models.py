"""Typed models shared by every stage: extraction schema, findings, decision."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FieldSource(str, Enum):
    TEXT = "text_layer"
    VISION = "vision"
    OCR = "ocr"
    INFERRED = "inferred"
    MISSING = "missing"


class Conf(BaseModel):
    value: Optional[str | float] = None
    confidence: float = Field(default=0, ge=0, le=1)
    source: FieldSource = FieldSource.MISSING


class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: float
    hsn_sac: Optional[str] = None
    is_bundled: bool = False


class TaxBreakdown(BaseModel):
    cgst: float = 0
    sgst: float = 0
    igst: float = 0
    other: float = 0
    rate_percent: Optional[float] = None
    tax_inclusive: bool = False

    @property
    def total(self) -> float:
        return self.cgst + self.sgst + self.igst + self.other


class ExtractedInvoice(BaseModel):
    vendor_name: Conf = Conf()
    vendor_gstin: Conf = Conf()
    invoice_number: Conf = Conf()
    invoice_date: Conf = Conf()
    due_date: Conf = Conf()
    po_reference: Conf = Conf()
    currency: Conf = Conf()
    line_items: list[LineItem] = []
    subtotal: Conf = Conf()
    tax: TaxBreakdown = TaxBreakdown()
    total: Conf = Conf()
    bank_account_last4: Conf = Conf()
    document_type: str = "invoice"  # invoice | credit_note | quotation | statement
    notes: Optional[str] = None


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class Finding(BaseModel):
    rule_id: str
    stage: str
    severity: Severity
    passed: bool
    title: str
    detail: str = ""
    evidence: dict = {}


class DecisionType(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class Decision(BaseModel):
    outcome: DecisionType
    reason_codes: list[str] = []
    headline: str
    explanation: str
    recommended_action: str
    confidence: float
    explained_by: str = "template"


# Title shown when a check fails (rules carry their passing title by default).
FAIL_TITLES = {
    "R01": "Mandatory fields missing", "R02": "Critical field read with low confidence",
    "R03": "Line arithmetic mismatch", "R04": "Lines do not add up to subtotal",
    "R05": "Subtotal + tax does not equal total", "R06": "GST split does not match place of supply",
    "R08": "Invoice date out of range", "R10": "GSTIN does not match vendor master", "R13": "PO is closed",
    "R14": "PO belongs to another vendor", "R15": "Invoice exceeds PO remaining balance",
    "R17": "Partial invoice on a PO that does not allow it", "R18": "Unit prices above PO prices",
    "R22": "Above auto-approval limit", "R24": "Invoice is not in INR", "R23": "Document is not a payable invoice",
}


def finding(rule_id: str, stage: str, sev: Severity, passed: bool, title: str, detail: str = "", **evidence) -> Finding:
    if not passed:
        title = FAIL_TITLES.get(rule_id[:3], title)
    return Finding(rule_id=rule_id, stage=stage, severity=sev, passed=passed, title=title, detail=detail,
                   evidence=evidence)
