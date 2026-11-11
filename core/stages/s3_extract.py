"""Stage 3 - Extract: LLM (text or vision) -> validated ExtractedInvoice, then verify its confidence.

Self-reported LLM confidence is not trusted: if the total the model read is inconsistent with
the line items and tax, confidence in `total` is capped.
"""
from __future__ import annotations

import pymupdf

from core.events import StageResult, StageStatus
from core.llm import router
from core.llm.base import Payload
from core.stages.s4_normalize import parse_amount

NAME = "Extract"


def page_images(file_bytes: bytes, dpi: int = 200, max_pages: int = 3) -> list[bytes]:
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    imgs = [doc[i].get_pixmap(dpi=dpi).tobytes("png") for i in range(min(doc.page_count, max_pages))]
    doc.close()
    return imgs


def expected_total(inv) -> float | None:
    if not inv.line_items:
        return None
    lines = sum(li.amount for li in inv.line_items)
    return round(lines if inv.tax.tax_inclusive else lines + inv.tax.total, 2)


def normalise_kind(raw: str) -> str:
    """LLM free text ('Invoice', 'tax_invoice', 'Credit Note') -> invoice | credit_note | quotation | statement."""
    k = str(raw or "invoice").strip().lower().replace(" ", "_")
    for kind in ("credit_note", "quotation", "statement"):
        if k.startswith(kind[:6]):
            return kind
    return "invoice"


def run(ctx) -> StageResult:
    payload = Payload(ctx.file_hash, ctx.route, text=ctx.text)
    if ctx.route == "vision":
        payload.images = page_images(ctx.file_bytes)
    try:
        inv, provider, attempts = router.extract(payload)
    except router.ExtractionFailed as e:
        ctx.processing_errors.append((NAME, str(e)))
        why = [a for a in e.attempts if any(k in a for k in ("failed", "quota", "rate limited"))]
        return StageResult(StageStatus.FAIL, "Manual entry needed: " + ("; ".join(why) or
                                                                        "no provider could read this document"),
                           {"attempts": e.attempts}, halt=True)
    ctx.extraction, ctx.provider = inv, provider

    adjustments = []
    total = parse_amount(inv.total.value)
    exp = expected_total(inv)
    rounding = ctx.rules["tolerances"]["arithmetic_rounding"]
    if total is not None and exp is not None and abs(total - exp) > rounding and inv.total.confidence > 0.5:
        adjustments.append(f"total {total:,.2f} != lines+tax {exp:,.2f}: confidence "
                           f"{inv.total.confidence:.2f} -> 0.50")
        inv.total.confidence = 0.5
    if normalise_kind(inv.document_type) != "invoice" and ctx.document_kind == "invoice":
        ctx.document_kind = normalise_kind(inv.document_type)

    low = [k for k, v in inv if hasattr(v, "confidence") and v.source.value != "missing" and v.confidence < 0.8]
    status = StageStatus.WARN if low else StageStatus.OK
    summary = f"{len(inv.line_items)} line(s) via {provider}" + (f"; low confidence: {', '.join(low)}" if low else "")
    return StageResult(status, summary, {"provider": provider, "attempts": attempts, "route": ctx.route,
                                         "confidence_adjustments": adjustments,
                                         "extraction": inv.model_dump(mode="json")})
