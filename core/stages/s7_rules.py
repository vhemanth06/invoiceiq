"""Stage 7 - Business rules. Each rule is a small pure function of (ctx, rules) -> Finding | None.

The docstring of each rule names the business risk it guards against.
"""
from __future__ import annotations

from typing import Callable

from rapidfuzz import fuzz

from core.config import tolerance
from core.events import StageResult, StageStatus
from core.models import Finding, Severity, finding

NAME = "Rules"


def _f(rule_id, sev, passed, title, detail="", **evidence) -> Finding:
    return finding(rule_id, NAME, sev, passed, title, detail, **evidence)


def _is_invoice(ctx) -> bool:
    return ctx.document_kind == "invoice"


def vendor_approved(ctx, cfg):
    """R09 - paying an unknown or un-onboarded (KYC pending) vendor."""
    v = ctx.vendor
    if not v:
        return _f("R09_VENDOR_APPROVED", Severity.BLOCK, False, "Vendor not in vendor master",
                  f"'{ctx.norm.get('vendor_name')}' did not match any vendor (best score {ctx.vendor_match.get('score')})")
    if not v["approved"]:
        return _f("R09_VENDOR_APPROVED", Severity.BLOCK, False, "Vendor is not approved",
                  f"{v['name']} ({v['vendor_id']}) is not an approved vendor (onboarding/KYC pending)",
                  vendor_id=v["vendor_id"])
    return _f("R09_VENDOR_APPROVED", Severity.BLOCK, True, "Vendor approved",
              f"{v['name']} ({v['vendor_id']}) matched by {ctx.vendor_match.get('method', 'master')}", vendor_id=v["vendor_id"])


def gstin_matches(ctx, cfg):
    """R10 - GSTIN on invoice differs from master: wrong entity or forged invoice; also blocks ITC claims."""
    v, g = ctx.vendor, ctx.norm.get("gstin")
    if not v:
        return None
    if not g:
        return _f("R10_GSTIN_MATCH", Severity.WARN, False, "GSTIN missing on invoice", "Input tax credit at risk")
    if not ctx.norm.get("gstin_valid"):
        return _f("R10_GSTIN_MATCH", Severity.WARN, False, "GSTIN format invalid", f"'{g}' is not a valid GSTIN")
    ok = g == v["gstin"]
    return _f("R10_GSTIN_MATCH", Severity.WARN, ok, "GSTIN matches vendor master",
              f"Invoice {g} vs master {v['gstin']}", invoice=g, master=v["gstin"])


def bank_matches(ctx, cfg):
    """R11 - changed bank details on an invoice: the classic payment-diversion fraud. Always escalate."""
    v, b = ctx.vendor, ctx.norm.get("bank_last4")
    if not v or not b:
        return None
    ok = b == v["bank_last4"]
    return _f("R11_BANK_MATCH", Severity.WARN, ok,
              "Bank account matches vendor master" if ok else "Bank account differs from vendor master",
              f"Invoice account ending {b} vs master ending {v['bank_last4']}", invoice=b, master=v["bank_last4"])


def po_found(ctx, cfg):
    """R12 - no PO means no proof the purchase was authorised; an inferred PO must be confirmed by a human."""
    if ctx.match_method == "explicit":
        return _f("R12_PO_FOUND", Severity.WARN, True, "PO found", f"{ctx.po['po_number']} referenced on invoice")
    if ctx.match_method == "inferred":
        runner = ctx.candidates[1]["score"] if len(ctx.candidates) > 1 else 0
        return _f("R12_PO_INFERRED", Severity.WARN, False, "PO inferred, not referenced",
                  f"Likely matches {ctx.po['po_number']} ({ctx.match_score:.0%} match score, runner-up {runner:.0%})",
                  po=ctx.po["po_number"], score=ctx.match_score, runner_up=runner)
    ref = ctx.norm.get("po_ref")
    return _f("R12_PO_MISSING", Severity.WARN, False, "No matching PO",
              (f"Reference '{ref}' does not exist" if ref else "No PO reference on invoice")
              + (f"; candidates: {', '.join(c['po_number'] for c in ctx.candidates)}" if ctx.candidates else ""),
              candidates=ctx.candidates)


def po_open(ctx, cfg):
    """R13 - billing against a closed PO: the budget is gone and goods were already settled."""
    if not ctx.po:
        return None
    ok = ctx.po["status"] == "OPEN"
    return _f("R13_PO_OPEN", Severity.BLOCK, ok, "PO is open", f"{ctx.po['po_number']} status {ctx.po['status']}")


def po_vendor_matches(ctx, cfg):
    """R14 - invoice quotes someone else's PO: misdirected or fraudulent billing."""
    if not ctx.po or not ctx.vendor:
        return None
    ok = ctx.po["vendor_id"] == ctx.vendor["vendor_id"]
    return _f("R14_PO_VENDOR", Severity.BLOCK, ok, "PO belongs to this vendor",
              f"{ctx.po['po_number']} is for {ctx.po['vendor_id']}, invoice from {ctx.vendor['vendor_id']}")


def amount_within_tolerance(ctx, cfg):
    """R15 - invoice exceeds what is left on the PO (over-billing on a single invoice)."""
    total = ctx.norm.get("total")
    if not ctx.po or total is None or not _is_invoice(ctx):
        return None
    remaining = round(ctx.po["total"] - ctx.po_billed_before, 2)
    tol = tolerance(cfg, ctx.po["total"])
    ok = total <= remaining + tol
    diff = total - remaining
    return _f("R15_AMOUNT_TOLERANCE", Severity.WARN, ok, "Amount within PO remaining balance",
              f"Invoice Rs {total:,.2f} vs PO remaining Rs {remaining:,.2f} (tolerance Rs {tol:,.2f})"
              + (f"; over by Rs {diff:,.2f}" if not ok else ""),
              invoice_total=total, po_remaining=remaining, tolerance=round(tol, 2), difference=round(diff, 2))


def cumulative_po_balance(ctx, cfg):
    """R16 - split invoices that each look fine but together over-bill the PO. Needs the running ledger."""
    total = ctx.norm.get("total")
    if not ctx.po or total is None or not _is_invoice(ctx):
        return None
    po_total = ctx.po["total"]
    prior = [e for e in ctx.ledger if e["po_number"] == ctx.po["po_number"] and e["outcome"] != "REJECT"]
    cumulative = round(ctx.po_billed_before + total, 2)
    over = round(cumulative - po_total, 2)
    pct = over / po_total * 100
    tol = tolerance(cfg, po_total)
    ev = dict(po_total=po_total, billed_before=ctx.po_billed_before, this_invoice=total, cumulative=cumulative,
              over_by=over, over_pct=round(pct, 1), prior_invoices=len(prior),
              prior_runs=[e["run_id"] for e in prior])
    detail = (f"{len(prior) + 1} invoice(s) total Rs {cumulative:,.2f} vs PO Rs {po_total:,.2f}"
              + (f" (+{pct:.1f}%, over by Rs {over:,.2f})" if over > 0 else ""))
    if over <= tol:
        return _f("R16_CUMULATIVE_PO", Severity.WARN, True, "Cumulative billing within PO", detail, **ev)
    sev = Severity.BLOCK if pct > cfg["tolerances"]["cumulative_block_pct"] else Severity.WARN
    return _f("R16_CUMULATIVE_PO", sev, False, "Cumulative billing exceeds PO value", detail, **ev)


def partial_allowed(ctx, cfg):
    """R17 - partial billing on a PO that expects one invoice: may indicate split or premature billing."""
    total = ctx.norm.get("total")
    if not ctx.po or total is None or not _is_invoice(ctx) or ctx.po["allows_partial"]:
        return None
    remaining = ctx.po["total"] - ctx.po_billed_before
    ok = total >= remaining - tolerance(cfg, ctx.po["total"])
    return _f("R17_PARTIAL", Severity.WARN, ok, "Billing pattern allowed on this PO",
              f"PO does not allow partial invoicing; invoice Rs {total:,.2f} vs remaining Rs {remaining:,.2f}")


def line_prices(ctx, cfg):
    """R18 - unit prices creeping above the negotiated PO price."""
    if not ctx.po_lines:
        return None
    rate = ctx.po["tax_rate"]
    pct = cfg["tolerances"]["line_price_pct"]
    rows = []
    for li in ctx.extraction.line_items:
        if li.is_bundled or li.unit_price is None:
            continue
        best = max(ctx.po_lines, key=lambda pl: fuzz.token_set_ratio(li.description.lower(), pl["description"].lower()))
        if fuzz.token_set_ratio(li.description.lower(), best["description"].lower()) < 70:
            continue
        price = li.unit_price / (1 + rate / 100) if ctx.norm.get("tax_inclusive") else li.unit_price
        var = (price - best["unit_price"]) / best["unit_price"] * 100
        rows.append({"invoice_line": li.description, "po_line": best["description"], "invoice_price": round(price, 2),
                     "po_price": best["unit_price"], "variance_pct": round(var, 2)})
    if not rows:
        return None
    bad = [r for r in rows if r["variance_pct"] > pct]
    return _f("R18_LINE_PRICES", Severity.WARN, not bad, "Unit prices match PO",
              "; ".join(f"{r['invoice_line'][:40]}: Rs {r['invoice_price']:,.2f} vs PO Rs {r['po_price']:,.2f} "
                        f"(+{r['variance_pct']:.1f}%)" for r in bad) or f"{len(rows)} line(s) within {pct}%",
              lines=rows)


def _same_vendor_live(ctx):
    return [e for e in ctx.ledger if ctx.vendor and e["vendor_id"] == ctx.vendor["vendor_id"] and e["outcome"] != "REJECT"]


def exact_duplicate(ctx, cfg):
    """R19 - paying the same invoice twice (same vendor + normalised invoice number, or identical file)."""
    if not _is_invoice(ctx):
        return None
    key = ctx.norm.get("invoice_key")
    hits = [e for e in _same_vendor_live(ctx) if key and e["invoice_no_key"] == key]
    hits += [e for e in ctx.ledger if e["file_hash"] == ctx.file_hash and e["outcome"] != "REJECT" and e not in hits]
    if not hits:
        return _f("R19_EXACT_DUPLICATE", Severity.BLOCK, True, "Not a duplicate", f"No prior invoice with key '{key}'")
    h = hits[0]
    how = "identical file" if h["file_hash"] == ctx.file_hash else f"same normalised invoice no. '{key}'"
    return _f("R19_EXACT_DUPLICATE", Severity.BLOCK, False, "Duplicate of an invoice already processed",
              f"'{ctx.norm.get('invoice_number')}' is a duplicate of '{h['invoice_number']}' "
              f"(Rs {h['total']:,.2f}, {h['outcome']}) - {how}",
              original_run=h["run_id"], original_invoice=h["invoice_number"], original_total=h["total"])


def probable_duplicate(ctx, cfg):
    """R20 - re-keyed or re-dated resubmissions that dodge an exact match."""
    if not _is_invoice(ctx) or any(f.rule_id == "R19_EXACT_DUPLICATE" and not f.passed for f in ctx.findings):
        return None
    d = cfg["duplicates"]
    total, inv_date = ctx.norm.get("total"), ctx.norm.get("invoice_date")
    hits = []
    for e in _same_vendor_live(ctx):
        if not total or abs(e["total"] - total) / total * 100 > d["amount_pct"]:
            continue
        sim = fuzz.ratio(str(e["invoice_number"]).upper(), str(ctx.norm.get("invoice_number")).upper())
        near = bool(inv_date and e["invoice_date"] and abs((inv_date - e["invoice_date"]).days) <= d["date_window_days"])
        if near or sim >= d["invoice_no_similarity"] or e["lines_sig"] == ctx.norm.get("lines_sig"):
            hits.append({**e, "similarity": sim})
    if not hits:
        return _f("R20_PROBABLE_DUPLICATE", Severity.WARN, True, "No probable duplicates", "")
    h = hits[0]
    return _f("R20_PROBABLE_DUPLICATE", Severity.WARN, False, "Probable duplicate",
              f"Resembles '{h['invoice_number']}' (Rs {h['total']:,.2f}, number similarity {h['similarity']:.0f})",
              original_run=h["run_id"], original_invoice=h["invoice_number"])


def tax_mode_reconcile(ctx, cfg):
    """R21 - avoid false alarms when an invoice quotes tax-inclusive prices against a tax-exclusive PO."""
    total = ctx.norm.get("total")
    if not ctx.po or total is None or not ctx.norm.get("tax_inclusive") or not _is_invoice(ctx):
        return None
    rate = ctx.po["tax_rate"]
    pre_tax = round(total / (1 + rate / 100), 2)
    po_pre_tax = round((ctx.po["total"] - ctx.po_billed_before) / (1 + rate / 100), 2)
    unexplained = round(pre_tax - po_pre_tax, 2)
    tol = tolerance(cfg, ctx.po["total"])
    gap_pct = round((total - po_pre_tax) / po_pre_tax * 100, 1) if po_pre_tax else 0
    ev = dict(invoice_total=total, tax_rate=rate, implied_pre_tax=pre_tax, po_pre_tax=po_pre_tax,
              unexplained=unexplained)
    if abs(unexplained) <= tol:
        return _f("R21_TAX_RECONCILED", Severity.INFO, True, "Tax-inclusive pricing reconciled",
                  f"{gap_pct:g}% difference to PO subtotal is fully explained by {rate:g}% GST included in prices: "
                  f"Rs {total:,.2f} / {1 + rate / 100:g} = Rs {pre_tax:,.2f} = PO Rs {po_pre_tax:,.2f}", **ev)
    return _f("R21_TAX_RECONCILED", Severity.WARN, False, "Tax explains only part of the difference",
              f"After removing {rate:g}% included GST, Rs {pre_tax:,.2f} vs PO Rs {po_pre_tax:,.2f}: "
              f"Rs {unexplained:,.2f} unexplained", **ev)


def currency_check(ctx, cfg):
    """R24 - POs and tolerances are in INR; a foreign-currency invoice must not be compared number-for-number."""
    cur = (ctx.norm.get("currency") or "INR").upper()
    return _f("R24_CURRENCY", Severity.WARN, cur == "INR", "Invoice currency is INR", f"Invoice currency {cur}",
              currency=cur)


def authority_limit(ctx, cfg):
    """R22 - segregation of duties: large invoices need a human approver whatever the checks say."""
    total = ctx.norm.get("total")
    if total is None:
        return None
    limit = cfg["approval"]["auto_approve_limit"]
    return _f("R22_AUTHORITY_LIMIT", Severity.WARN, total <= limit, "Within auto-approval limit",
              f"Rs {total:,.2f} vs auto-approval limit Rs {limit:,.2f}", total=total, limit=limit)


def document_type(ctx, cfg):
    """R23 - credit notes, quotations and statements must never be paid as invoices."""
    ok = ctx.document_kind == "invoice"
    return _f("R23_DOCUMENT_TYPE", Severity.WARN, ok, "Document is a payable invoice",
              "Tax invoice" if ok else f"Document appears to be a {ctx.document_kind.replace('_', ' ')}",
              kind=ctx.document_kind)


RULES: list[Callable] = [
    vendor_approved, gstin_matches, bank_matches, po_found, po_open, po_vendor_matches,
    amount_within_tolerance, cumulative_po_balance, partial_allowed, line_prices,
    exact_duplicate, probable_duplicate, tax_mode_reconcile, currency_check, authority_limit, document_type,
]


def run_rules(ctx, cfg) -> list[Finding]:
    findings = []
    for rule in RULES:
        try:
            f = rule(ctx, cfg)
            if f:
                findings.append(f)
                ctx.findings.append(f)  # later rules (R20) can see earlier ones (R19)
        except Exception as e:
            f = Finding(rule_id=rule.__name__, stage=NAME, severity=Severity.WARN, passed=False,
                        title="Rule could not be evaluated", detail=str(e))
            findings.append(f)
            ctx.findings.append(f)
    return findings


def run(ctx) -> StageResult:
    found = run_rules(ctx, ctx.rules)
    failed = [f for f in found if not f.passed]
    status = StageStatus.FAIL if any(f.severity == Severity.BLOCK for f in failed) else (
        StageStatus.WARN if failed else StageStatus.OK)
    return StageResult(status, f"{len(found) - len(failed)}/{len(found)} rules passed"
                       + (f"; failed: {', '.join(f.rule_id for f in failed)}" if failed else ""),
                       {"findings": [f.model_dump() for f in found]})
