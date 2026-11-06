"""Stage 6 - Match PO: explicit reference first; otherwise score every OPEN PO of the vendor.

score = 0.45 * amount_similarity + 0.35 * line_similarity + 0.20 * date_plausibility
An inferred match is accepted only if score >= min_po_match_score and it beats the runner-up
by po_match_margin. Inferred matches are never auto-approved (see s8_decide).
"""
from __future__ import annotations

from datetime import date

from rapidfuzz import fuzz

from core.db import repo
from core.events import StageResult, StageStatus

NAME = "Match PO"


def billed_against(po_number: str, ledger: list[dict]) -> float:
    """Sum of prior invoices on this PO that still count (approved or pending review; not rejected)."""
    return round(sum(e["total"] for e in ledger if e["po_number"] == po_number and e["outcome"] != "REJECT"), 2)


def line_similarity(inv_lines, po_lines: list[dict]) -> float:
    if not inv_lines or not po_lines:
        return 0.0
    best = [max(fuzz.token_set_ratio(li.description.lower(), pl["description"].lower()) for pl in po_lines) / 100
            for li in inv_lines]
    return sum(best) / len(best)


def score_po(po: dict, po_lines: list[dict], total: float | None, inv_lines, inv_date: date | None,
             billed: float) -> dict:
    remaining = po["total"] - billed
    amount_sim = max(0.0, 1 - abs((total or 0) - remaining) / remaining) if remaining > 0 and total else 0.0
    line_sim = line_similarity(inv_lines, po_lines)
    po_date = po["po_date"] if isinstance(po["po_date"], date) else date.fromisoformat(str(po["po_date"]))
    date_ok = 1.0 if inv_date and 0 <= (inv_date - po_date).days <= 120 else 0.0
    score = 0.45 * amount_sim + 0.35 * line_sim + 0.20 * date_ok
    return {"po_number": po["po_number"], "score": round(score, 3), "amount_similarity": round(amount_sim, 3),
            "line_similarity": round(line_sim, 3), "date_plausibility": date_ok, "remaining": round(remaining, 2)}


def run(ctx) -> StageResult:
    n = ctx.norm
    pos = {p["po_number"]: p for p in repo.purchase_orders()}
    ctx.ledger = repo.ledger(exclude_run=ctx.run_id)
    cfg = ctx.rules["confidence"]

    ref = n.get("po_ref")
    if ref and ref in pos:
        ctx.po, ctx.match_method, ctx.match_score = pos[ref], "explicit", 1.0
    else:
        ctx.po_ref_invalid = bool(ref)
        if ctx.vendor:
            cands = [p for p in pos.values() if p["vendor_id"] == ctx.vendor["vendor_id"] and p["status"] == "OPEN"]
            scored = sorted((score_po(p, repo.po_lines(p["po_number"]), n.get("total"),
                                      ctx.extraction.line_items, n.get("invoice_date"),
                                      billed_against(p["po_number"], ctx.ledger)) for p in cands),
                            key=lambda c: -c["score"])
            ctx.candidates = scored[:3]
            if scored:
                best = scored[0]
                runner = scored[1]["score"] if len(scored) > 1 else 0.0
                if best["score"] >= cfg["min_po_match_score"] and best["score"] - runner >= cfg["po_match_margin"]:
                    ctx.po, ctx.match_method, ctx.match_score = pos[best["po_number"]], "inferred", best["score"]

    if ctx.po:
        ctx.po_lines = repo.po_lines(ctx.po["po_number"])
        ctx.po_billed_before = billed_against(ctx.po["po_number"], ctx.ledger)
    details = {"match_method": ctx.match_method, "match_score": ctx.match_score, "po_reference": ref,
               "po_ref_invalid": ctx.po_ref_invalid, "candidates": ctx.candidates, "po": ctx.po,
               "po_lines": ctx.po_lines, "billed_before": ctx.po_billed_before}
    if ctx.match_method == "explicit":
        return StageResult(StageStatus.OK, f"{ctx.po['po_number']} (explicit reference '{n.get('po_ref_raw')}')", details)
    if ctx.match_method == "inferred":
        runner = ctx.candidates[1]["score"] if len(ctx.candidates) > 1 else 0
        return StageResult(StageStatus.WARN, f"Inferred {ctx.po['po_number']} (score {ctx.match_score:.2f}, "
                                             f"runner-up {runner:.2f})", details)
    why = f"reference '{ref}' not found; " if ref else "no PO reference; "
    why += "ambiguous candidates" if ctx.candidates else "no open POs for this vendor"
    return StageResult(StageStatus.WARN, f"No PO matched ({why})", details)
