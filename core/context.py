"""RunContext: everything one pipeline run has produced so far."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from core.events import StageEvent
from core.models import Decision, ExtractedInvoice, Finding


@dataclass
class RunContext:
    run_id: str
    file_bytes: bytes
    file_name: str
    source: str
    rules: dict
    today: date
    file_hash: str = ""
    page_count: int = 0
    text: str = ""
    page_texts: list[str] = field(default_factory=list)
    doc_type: str = ""            # digital | scanned | hybrid
    document_kind: str = "invoice"  # invoice | credit_note | quotation | statement | multi_invoice
    route: str = ""               # text | vision
    text_density: float = 0
    extraction: Optional[ExtractedInvoice] = None
    provider: str = ""
    norm: dict[str, Any] = field(default_factory=dict)
    vendor: Optional[dict] = None
    vendor_match: dict = field(default_factory=dict)
    po: Optional[dict] = None
    po_lines: list[dict] = field(default_factory=list)
    po_ref_invalid: bool = False
    match_method: str = "none"    # explicit | inferred | none
    match_score: float = 0
    candidates: list[dict] = field(default_factory=list)
    po_billed_before: float = 0
    ledger: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    decision: Optional[Decision] = None
    processing_errors: list[tuple[str, str]] = field(default_factory=list)
    events: list[StageEvent] = field(default_factory=list)

    @classmethod
    def new(cls, file_bytes: bytes, file_name: str, source: str, rules: dict, today: date) -> "RunContext":
        return cls(
            run_id=uuid.uuid4().hex[:12],
            file_bytes=file_bytes,
            file_name=file_name,
            source=source,
            rules=rules,
            today=today,
            file_hash=hashlib.sha256(file_bytes).hexdigest(),
        )
