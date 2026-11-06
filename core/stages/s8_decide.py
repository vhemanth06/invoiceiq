"""Stage 8 - Decide & explain.

The decision is a deterministic matrix over findings. The LLM only writes the prose, from the
findings alone, and its text is discarded if it cites any number not present in those facts.
"""
from __future__ import annotations

import json
import re

from core import config
from core.events import StageResult, StageStatus
from core.llm import router
from core.llm.base import parse_json
from core.llm.prompts import EXPLANATION_PROMPT
from core.models import Decision, DecisionType, Finding, Severity

NAME = "Decide"
SEV_ORDER = {Severity.BLOCK: 0, Severity.WARN: 1, Severity.INFO: 2}

ACTIONS = {
    "R00": "Ask the vendor to resend a readable, unprotected PDF.",
    "R09": "Return to vendor: they are not an approved vendor; complete onboarding/KYC first.",
    "R19": "Do not pay: return to vendor as a duplicate of an invoice already processed.",
    "R14": "Return to vendor: the PO quoted belongs to a different vendor.",
    "R13": "Return to vendor: the PO is closed; ask the requester whether a new PO is needed.",
    "R16": "Hold payment and request a credit note or a PO amendment for the excess.",
    "R01": "Request a corrected invoice with all mandatory fields.",
    "R11": "Verify the bank change by calling the vendor on the number in the vendor master before paying.",
    "R20": "Compare with the earlier invoice and confirm with the vendor before paying.",
    "R23": "Route to the credit-note process; do not pay this as an invoice.",
    "R02": "Verify the low-confidence fields against the document before paying.",
    "R12": "Confirm the purchase order with the requester before paying.",
    "R15": "Check quantities and prices with the requester; request a revised invoice if over-billed.",
    "R18": "Ask the vendor to bill at PO prices or get a PO amendment.",
    "R21": "Clarify the pricing difference with the vendor.",
    "R24": "Convert at the contracted rate and confirm the PO currency before paying.",
    "R22": "Route to an approver with the required authority limit.",
    "R10": "Confirm the vendor's GSTIN; input tax credit is at risk.",
    "R17": "Confirm with the requester that partial billing is acceptable.",
    "R06": "Ask the vendor to correct the GST split (CGST/SGST vs IGST).",
}


def decide(findings: list[Finding], ctx, cfg=None) -> DecisionType:
    failed = [f for f in findings if not f.passed]
    if any(f.severity == Severity.BLOCK for f in failed):
        return DecisionType.REJECT
    if any(f.severity == Severity.WARN for f in failed):
        return DecisionType.REVIEW
    if ctx.match_method != "explicit" or ctx.processing_errors:
        return DecisionType.REVIEW  # never auto-approve an inferred match or a run that hit an error
    return DecisionType.APPROVE


def confidence(ctx) -> float:
    if not ctx.extraction:
        return 0.0
    fields = ctx.rules["confidence"]["critical_fields"]
    c = min(getattr(ctx.extraction, f).confidence for f in fields)
    return round(min(c, ctx.match_score) if ctx.po else c, 2)


def template(outcome: DecisionType, ctx) -> tuple[str, str, str]:
    """Deterministic explanation built only from findings. Always available."""
    prio = list(ACTIONS)
    failed = sorted([f for f in ctx.findings if not f.passed],
                    key=lambda f: (SEV_ORDER[f.severity], prio.index(f.rule_id[:3]) if f.rule_id[:3] in prio else 99))
    info = [f for f in ctx.findings if f.passed and f.severity == Severity.INFO and f.rule_id.startswith("R")]
    n = ctx.norm
    who = ctx.vendor["name"] if ctx.vendor else (n.get("vendor_name") or "Unknown vendor")
    amt = f"Rs {n['total']:,.2f}" if n.get("total") is not None else "an unreadable amount"
    inv = n.get("invoice_number") or "invoice"
    po = ctx.po["po_number"] if ctx.po else "no PO"
    if outcome == DecisionType.APPROVE:
        headline = f"Approve {inv} from {who} for {amt} against {po}."
        passed = sum(f.passed for f in ctx.findings)
        expl = (f"All {passed} checks passed: the vendor is approved, the invoice is internally consistent, "
                f"and it matches {po} (explicitly referenced) within tolerance with no duplicates found.")
        expl += "".join(f" {f.detail}." for f in info)
        due = n.get("due_date")
        action = f"Schedule payment of {amt}" + (
            (f" by {due:%d %b %Y}." if due >= ctx.today else f" now (due date {due:%d %b %Y} has passed).")
            if due else " per payment terms.")
        return headline, expl, action
    if not failed:  # REVIEW only because of match method or a processing error
        err = ctx.processing_errors[0] if ctx.processing_errors else None
        headline = f"Review: processing error at stage {err[0]}." if err else "Review: PO match must be confirmed."
        expl = (f"The pipeline could not complete: {err[1]}. Nothing was approved automatically." if err
                else f"{inv} from {who} for {amt} could not be tied to a PO by explicit reference.")
        return headline, expl, "Have an AP analyst complete the check manually."
    top = failed[0]
    verb = "Reject" if outcome == DecisionType.REJECT else "Review"
    headline = f"{verb}: {top.title[0].lower() + top.title[1:]}" + (f" (+{len(failed) - 1} more issue{'s' * (len(failed) > 2)})"
                                                 if len(failed) > 1 else "") + "."
    expl = f"{inv} from {who} for {amt} ({po}). " + " ".join(
        f"{f.title}: {f.detail}." for f in failed[:4])
    expl += "".join(f" Note: {f.detail}." for f in info)
    if outcome == DecisionType.REVIEW and ctx.match_method == "inferred":
        expl += " Inferred PO matches are never auto-approved."
    action = ACTIONS.get(top.rule_id[:3], "Have an AP analyst check the flagged items.")
    if top.rule_id == "R16_CUMULATIVE_PO" and top.evidence.get("over_by"):
        action = (f"Hold payment and request a credit note for Rs {top.evidence['over_by']:,.2f} "
                  f"or a PO amendment.")
    if top.rule_id.startswith("R02") and n.get("total") is not None:
        action = f"Verify the low-confidence fields against the document (total read as Rs {n['total']:,.2f})."
    return headline, expl, action


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    out = set()
    for tok in _NUM.findall(text):
        try:
            out.add(round(float(tok.replace(",", "")), 2))
        except ValueError:
            pass
    return out


def numbers_grounded(text: str, facts: str) -> bool:
    """Guardrail: every number in the LLM text must appear in the facts it was given."""
    allowed = _numbers(facts)
    return all(x in allowed for x in _numbers(text))


def llm_explanation(outcome: DecisionType, ctx) -> tuple[str, str, str, str] | None:
    if not config.flag("USE_LLM_EXPLANATIONS"):
        return None
    facts_list = [f.model_dump(mode="json") for f in ctx.findings if not f.passed or f.severity == Severity.INFO]
    facts = json.dumps({"invoice": ctx.norm.get("invoice_number"), "vendor": ctx.vendor["name"] if ctx.vendor else None,
                        "total": ctx.norm.get("total"), "po": ctx.po["po_number"] if ctx.po else None,
                        "findings": facts_list}, default=str)
    res = router.explain(EXPLANATION_PROMPT.format(outcome=outcome.value, facts=facts))
    if not res:
        return None
    try:
        data = parse_json(res[0])
        h, e, a = str(data["headline"]), str(data["explanation"]), str(data["recommended_action"])
    except Exception:
        return None
    if not numbers_grounded(" ".join([h, e, a]), facts):
        return None
    return h, e, a, res[1]


def run(ctx) -> StageResult:
    outcome = decide(ctx.findings, ctx, ctx.rules)
    headline, expl, action = template(outcome, ctx)
    by = "template"
    note = ""
    if outcome != DecisionType.APPROVE or ctx.extraction:
        llm = llm_explanation(outcome, ctx)
        if llm:
            headline, expl, action, by = llm[0], llm[1], llm[2], llm[3]
        elif config.flag("USE_LLM_EXPLANATIONS"):
            note = "LLM explanation unavailable or failed the number guardrail; template used"
    reasons = [f.rule_id for f in ctx.findings if not f.passed]
    if not reasons and outcome == DecisionType.REVIEW:
        reasons = ["PROCESSING_ERROR"] if ctx.processing_errors else ["PO_NOT_EXPLICIT"]
    ctx.decision = Decision(outcome=outcome, reason_codes=reasons, headline=headline, explanation=expl,
                            recommended_action=action, confidence=confidence(ctx), explained_by=by)
    status = {DecisionType.APPROVE: StageStatus.OK, DecisionType.REVIEW: StageStatus.WARN,
              DecisionType.REJECT: StageStatus.FAIL}[outcome]
    return StageResult(status, f"{outcome.value}: {headline}",
                       {"decision": ctx.decision.model_dump(mode="json"), "note": note})
