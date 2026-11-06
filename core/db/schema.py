"""SQLModel tables: runs, events, extractions, findings, invoice ledger, master data."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine

from core import config


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    id: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "upload"
    file_name: str = ""
    file_hash: str = Field(default="", index=True)
    file_path: str = ""
    doc_type: str = ""
    provider: str = ""
    status: str = "running"  # running / done / error
    outcome: Optional[str] = None
    original_outcome: Optional[str] = None
    confidence: Optional[float] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    po_number: Optional[str] = None
    total: Optional[float] = None
    duration_ms: int = 0
    headline: str = ""
    decision_json: str = "{}"
    context_json: str = "{}"


class RunEvent(SQLModel, table=True):
    __tablename__ = "run_events"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    seq: int
    stage: str
    status: str
    summary: str = ""
    details_json: str = "{}"
    duration_ms: int = 0
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExtractedRecord(SQLModel, table=True):
    __tablename__ = "extracted_invoices"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    run_id: str = Field(primary_key=True)
    extraction_json: str = "{}"
    normalized_json: str = "{}"


class FindingRow(SQLModel, table=True):
    __tablename__ = "findings"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    rule_id: str
    stage: str
    severity: str
    passed: bool
    title: str
    detail: str = ""
    evidence_json: str = "{}"


class LedgerEntry(SQLModel, table=True):
    __tablename__ = "invoice_ledger"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    run_id: str = Field(primary_key=True)
    vendor_id: str = Field(index=True)
    invoice_number: str = ""
    invoice_no_key: str = ""
    invoice_date: Optional[date] = None
    total: float = 0
    po_number: Optional[str] = Field(default=None, index=True)
    file_hash: str = ""
    lines_sig: str = ""
    outcome: str = ""


class Vendor(SQLModel, table=True):
    __tablename__ = "vendors"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    vendor_id: str = Field(primary_key=True)
    name: str
    aliases: str = ""
    gstin: str = ""
    state: str = ""
    approved: bool = True
    bank_last4: str = ""
    payment_terms_days: int = 30


class PurchaseOrder(SQLModel, table=True):
    __tablename__ = "purchase_orders"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    po_number: str = Field(primary_key=True)
    vendor_id: str
    po_date: date
    status: str
    subtotal: float
    tax_rate: float
    tax_mode: str
    total: float
    allows_partial: bool = False


class POLine(SQLModel, table=True):
    __tablename__ = "po_lines"
    __table_args__ = {"extend_existing": True}  # Streamlit hot-reload re-imports this module
    id: Optional[int] = Field(default=None, primary_key=True)
    po_number: str = Field(index=True)
    line_no: int
    description: str
    quantity: float
    unit_price: float
    amount: float


_engines: dict[str, object] = {}


def get_engine():
    path = str(config.db_path())
    if path not in _engines:
        config.db_path().parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        _engines[path] = engine
    return _engines[path]
