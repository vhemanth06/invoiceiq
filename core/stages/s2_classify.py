"""Stage 2 - Classify: digital vs scanned vs hybrid (text density) and invoice vs other documents."""
from __future__ import annotations

import re

from core.events import StageResult, StageStatus

NAME = "Classify"
KEYWORDS = ("invoice", "total", "gst", "amount", "tax")


def detect_kind(text: str) -> str:
    t = text.lower()
    # match document titles (start of a line), not mentions in terms like "any credit note must quote..."
    if re.search(r"^\s*credit\s+note\b", t, re.M):
        return "credit_note"
    if re.search(r"^\s*(quotation|proforma)\b", t, re.M):
        return "quotation"
    if re.search(r"^\s*statement of account\b", t, re.M):
        return "statement"
    if len(re.findall(r"invoice\s*(no|number|#)", t)) > 1:
        return "multi_invoice"
    return "invoice"


def run(ctx) -> StageResult:
    density = sum(len(t.strip()) for t in ctx.page_texts) / max(ctx.page_count, 1)
    has_kw = sum(k in ctx.text.lower() for k in KEYWORDS) >= 2
    if density > 200 and has_kw:
        ctx.doc_type, ctx.route = "digital", "text"
    elif density < 50:
        ctx.doc_type, ctx.route = "scanned", "vision"
    else:
        ctx.doc_type, ctx.route = "hybrid", "vision"
    ctx.text_density = round(density, 1)
    ctx.document_kind = detect_kind(ctx.text) if ctx.text.strip() else "invoice"
    label = {"digital": "Digital PDF", "scanned": "Scanned", "hybrid": "Hybrid"}[ctx.doc_type]
    status = StageStatus.OK if ctx.document_kind == "invoice" else StageStatus.WARN
    summary = f"{label} ({ctx.text_density:g} chars/page) -> {ctx.route} route"
    if ctx.document_kind != "invoice":
        summary += f"; looks like a {ctx.document_kind.replace('_', ' ')}"
    return StageResult(status, summary, {"doc_type": ctx.doc_type, "route": ctx.route,
                                         "text_density": ctx.text_density, "document_kind": ctx.document_kind})
