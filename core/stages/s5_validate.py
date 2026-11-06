"""Stage 5 - Validate: is the invoice consistent with itself? (arithmetic, GST structure, dates, completeness)"""
from __future__ import annotations

from core.events import StageResult, StageStatus
from core.models import Finding, Severity, finding
from core.stages.s4_normalize import GST_STATES

NAME = "Validate"


def _f(rule_id, sev, passed, title, detail="", **evidence) -> Finding:
    return finding(rule_id, NAME, sev, passed, title, detail, **evidence)


def money_strings(x: float) -> list[str]:
    """Ways an amount may be printed on the page: 118000.00, 118,000.00, 1,18,000.00."""
    whole, frac = f"{x:.2f}".split(".")
    indian = whole
    if len(whole) > 3:
        head, groups = whole[:-3], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        indian = ",".join(([head] if head else []) + groups + [whole[-3:]])
    return [f"{x:.2f}", f"{x:,.2f}", f"{indian}.{frac}"]


def check_arithmetic(ctx) -> list[Finding]:
    inv, n = ctx.extraction, ctx.norm
    r = ctx.rules["tolerances"]["arithmetic_rounding"]
    out = []
    bad = [li.description for li in inv.line_items
           if li.quantity is not None and li.unit_price is not None and abs(li.quantity * li.unit_price - li.amount) > r]
    out.append(_f("R03_LINE_MATH", Severity.WARN, not bad, "Line arithmetic (qty x rate = amount)",
                  f"Mismatched lines: {', '.join(bad)}" if bad else f"{len(inv.line_items)} line(s) consistent",
                  bad_lines=bad))
    lines_sum = round(sum(li.amount for li in inv.line_items), 2)
    sub = n.get("subtotal")
    if sub is not None:
        ok = abs(lines_sum - sub) <= r
        out.append(_f("R04_SUBTOTAL", Severity.WARN, ok, "Line amounts add up to subtotal",
                      f"Lines {lines_sum:,.2f} vs subtotal {sub:,.2f}", lines_sum=lines_sum, subtotal=sub))
    total = n.get("total")
    if total is not None:
        base = sub if sub is not None else lines_sum
        expected = round(base if n["tax_inclusive"] else base + n["tax_total"], 2)
        ok = abs(expected - total) <= r
        detail = (f"{'Lines (tax inclusive)' if n['tax_inclusive'] else 'Subtotal + tax'} = {expected:,.2f} "
                  f"vs total {total:,.2f}")
        if not ok and any(s in ctx.text for s in money_strings(expected)):
            # The correct total is printed on the page: the extractor misread it, not a vendor error.
            inv.total.confidence = min(inv.total.confidence, 0.5)
            detail += f"; {expected:,.2f} is printed on the page, so the total was probably misread"
        out.append(_f("R05_TOTAL", Severity.WARN, ok, "Subtotal + tax = total", detail,
                      expected=expected, total=total, tax=n["tax_total"]))
    return out


def check_gst(ctx) -> Finding:
    tax = ctx.extraction.tax
    if tax.total == 0:
        return _f("R06_GST_STRUCTURE", Severity.WARN, True, "GST structure", "No GST charged")
    vg = ctx.norm.get("gstin") or (ctx.vendor or {}).get("gstin") or ""
    buyer = ctx.rules["company"]["gstin"][:2]
    intra = vg[:2] == buyer
    where = f"{GST_STATES.get(vg[:2], vg[:2])} -> {GST_STATES.get(buyer, buyer)}"
    if intra:
        ok = tax.igst == 0 and tax.cgst > 0 and abs(tax.cgst - tax.sgst) <= 1
        expect = "CGST = SGST, no IGST"
    else:
        ok = tax.igst > 0 and tax.cgst == 0 and tax.sgst == 0
        expect = "IGST only"
    return _f("R06_GST_STRUCTURE", Severity.WARN, ok, "GST structure matches place of supply",
              f"{'Intra' if intra else 'Inter'}-state ({where}): expected {expect}; got CGST {tax.cgst:,.2f}, "
              f"SGST {tax.sgst:,.2f}, IGST {tax.igst:,.2f}",
              cgst=tax.cgst, sgst=tax.sgst, igst=tax.igst, intra_state=intra)


def check_dates(ctx) -> Finding:
    d = ctx.norm.get("invoice_date")
    cfg = ctx.rules["dates"]
    if not d:
        return _f("R08_DATE_SANITY", Severity.WARN, False, "Invoice date sanity", "Invoice date missing or unparseable")
    age = (ctx.today - d).days
    ok = -cfg["allow_future_days"] <= age <= cfg["max_age_days"]
    detail = (f"{d:%d %b %Y} is {age} day(s) old" if age >= 0 else f"{d:%d %b %Y} is {-age} day(s) in the future")
    return _f("R08_DATE_SANITY", Severity.WARN, ok, "Invoice date sanity", detail, age_days=age)


def check_required(ctx) -> list[Finding]:
    inv, cfg = ctx.extraction, ctx.rules["confidence"]
    missing = [f for f in cfg["critical_fields"] if getattr(inv, f).value in (None, "")]
    sev = Severity.BLOCK if "total" in missing else Severity.WARN
    out = [_f("R01_REQUIRED_FIELDS", sev, not missing, "Critical fields present",
              f"Missing: {', '.join(missing)}" if missing else "All critical fields present", missing=missing)]
    low = {f: getattr(inv, f).confidence for f in cfg["critical_fields"]
           if f not in missing and getattr(inv, f).confidence < cfg["min_field_confidence"]}
    out.append(_f("R02_CONFIDENCE", Severity.WARN, not low, "Critical fields read with confidence",
                  ("Low confidence: " + ", ".join(f"{k} {v:.2f}" for k, v in low.items())
                   + f" (threshold {cfg['min_field_confidence']:.2f})") if low else "All critical fields above threshold",
                  low_fields=low, threshold=cfg["min_field_confidence"]))
    return out


def run(ctx) -> StageResult:
    found = check_arithmetic(ctx) + [check_gst(ctx), check_dates(ctx)] + check_required(ctx)  # R02 last: sees misreads
    ctx.findings.extend(found)
    failed = [f for f in found if not f.passed]
    status = StageStatus.FAIL if any(f.severity == Severity.BLOCK for f in failed) else (
        StageStatus.WARN if failed else StageStatus.OK)
    return StageResult(status, f"{len(found) - len(failed)}/{len(found)} checks passed"
                       + (f"; issues: {', '.join(f.rule_id for f in failed)}" if failed else ""),
                       {"findings": [f.model_dump() for f in found]})
