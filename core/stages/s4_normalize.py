"""Stage 4 - Normalise: dates, amounts, invoice/PO keys, GSTIN, and vendor resolution."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime

from rapidfuzz import fuzz

from core.db import repo
from core.events import StageResult, StageStatus
from core.models import Conf, FieldSource, Finding, Severity

NAME = "Normalise"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GST_STATES = {"07": "Delhi", "27": "Maharashtra", "29": "Karnataka", "33": "Tamil Nadu", "36": "Telangana",
              "37": "Andhra Pradesh", "24": "Gujarat", "19": "West Bengal", "09": "Uttar Pradesh"}
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d-%b-%y", "%d-%b-%Y",
                "%d %b %Y", "%d %B %Y", "%d %b %y", "%b %d, %Y", "%B %d, %Y", "%d-%B-%Y"]


def parse_amount(v) -> float | None:
    """'Rs. 1,18,000.00/-' -> 118000.0 ; also handles INR, the rupee sign and (negatives)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"(?i)rs\.?|inr|₹|/-|\s|[()]", "", s).replace(",", "").lstrip("-")
    m = re.search(r"\d+(\.\d+)?", s)
    if not m:
        return None
    return -float(m.group()) if neg else float(m.group())


def parse_date(v) -> tuple[date | None, bool]:
    """Return (date, ambiguous). Day/month ambiguity resolves to the Indian DD/MM convention."""
    if not v:
        return None, False
    s = str(v).strip().replace("Sept", "Sep")
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}$", s)
        ambiguous = bool(m) and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2)
        return d, ambiguous
    return None, False


def invoice_key(v) -> str:
    """'INV-1042', 'inv 1042', 'INV/1042-R' -> '1042' (resubmission suffixes are stripped)."""
    if not v:
        return ""
    s = str(v).upper().strip()
    s = re.sub(r"[\s\-/#_.]+(R|REV\d*|RESUBMIT(TED)?|COPY|DUP(LICATE)?|REMINDER)$", "", s)
    s = re.sub(r"[\s\-/#_.]", "", s)
    return re.sub(r"^(INVOICE|INV|BILL|NO)+(?=\d)", "", s) or s


def po_key(v, known: list[str]) -> str | None:
    """'PO 1052', '#1052', 'PO-2026-1052' -> 'PO-2026-1052' when it maps to a known PO."""
    if not v:
        return None
    s = str(v).upper()
    m = re.search(r"(\d{4})\D{0,3}(\d{3,4})", s)
    if m and f"PO-{m.group(1)}-{m.group(2)}" in known:
        return f"PO-{m.group(1)}-{m.group(2)}"
    digits = re.findall(r"\d+", s)
    if digits and not any(len(d) == 4 and d.startswith(("19", "20")) for d in digits[:-1]):  # a stated year must match
        tail = digits[-1]
        hits = [p for p in known if p.endswith("-" + tail)]
        if len(hits) == 1:
            return hits[0]
    return s.strip()


def gstin_valid(g) -> bool:
    if not g:
        return False
    g = str(g).upper().replace(" ", "")
    return bool(GSTIN_RE.match(g)) and 1 <= int(g[:2]) <= 38


def resolve_vendor(name, gstin, vendors: list[dict]) -> tuple[dict | None, dict]:
    """GSTIN exact match first (strongest), then name/alias fuzzy match (token_set_ratio >= 88)."""
    g = str(gstin or "").upper().replace(" ", "")
    for v in vendors:
        if g and v["gstin"] == g:
            return v, {"method": "gstin", "score": 100}
    best, best_score = None, 0.0
    for v in vendors:
        for cand in [v["name"]] + [a.strip() for a in v["aliases"].split(";") if a.strip()]:
            sc = fuzz.token_set_ratio(str(name or "").lower(), cand.lower())
            if sc > best_score:
                best, best_score = v, sc
    if best and best_score >= 88:
        return best, {"method": "name", "score": round(best_score, 1)}
    return None, {"method": "none", "score": round(best_score, 1)}


def run(ctx) -> StageResult:
    inv = ctx.extraction
    n = ctx.norm
    rows = []

    def record(field, before, after):
        rows.append({"field": field, "before": before, "after": after})
        return after

    n["vendor_name"] = inv.vendor_name.value
    n["gstin"] = record("GSTIN", inv.vendor_gstin.value, str(inv.vendor_gstin.value or "").upper().replace(" ", "") or None)
    n["gstin_valid"] = gstin_valid(n["gstin"])
    n["invoice_number"] = inv.invoice_number.value
    n["invoice_key"] = record("Invoice no. key", inv.invoice_number.value, invoice_key(inv.invoice_number.value))
    d, amb = parse_date(inv.invoice_date.value)
    n["invoice_date"] = record("Invoice date", inv.invoice_date.value, d)
    n["date_ambiguous"] = amb
    n["due_date"] = record("Due date", inv.due_date.value, parse_date(inv.due_date.value)[0])
    known = [p["po_number"] for p in repo.purchase_orders()]
    n["po_ref_raw"] = inv.po_reference.value
    n["po_ref"] = record("PO reference", inv.po_reference.value, po_key(inv.po_reference.value, known))
    cur = str(inv.currency.value or "INR").upper().strip(" .")
    n["currency"] = record("Currency", inv.currency.value, "INR" if cur in ("RS", "INR", "₹", "RUPEES") else cur)
    n["subtotal"] = record("Subtotal", inv.subtotal.value, parse_amount(inv.subtotal.value))
    if inv.total.value in (None, "") and n["subtotal"] is not None:
        # Unreadable total: derive it at low confidence so R02 routes to a human instead of a hard reject.
        derived = n["subtotal"] + (0 if inv.tax.tax_inclusive else inv.tax.total)
        inv.total = Conf(value=derived, confidence=0.5, source=FieldSource.INFERRED)
    n["total"] = record("Total", inv.total.value, parse_amount(inv.total.value))
    n["tax_total"] = round(inv.tax.total, 2)
    n["tax_inclusive"] = inv.tax.tax_inclusive
    n["bank_last4"] = re.sub(r"\D", "", str(inv.bank_account_last4.value or ""))[-4:] or None
    n["lines_sig"] = hashlib.sha1("|".join(sorted(f"{li.description.lower().strip()}:{li.amount:.2f}"
                                                   for li in inv.line_items)).encode()).hexdigest()[:16]

    ctx.vendor, ctx.vendor_match = resolve_vendor(n["vendor_name"], n["gstin"], repo.vendors())
    record("Vendor", n["vendor_name"], f"{ctx.vendor['vendor_id']} ({ctx.vendor_match['method']}, "
                                       f"{ctx.vendor_match['score']})" if ctx.vendor else "not in vendor master")
    if amb:
        ctx.findings.append(Finding(rule_id="N01_DATE_AMBIGUOUS", stage=NAME, severity=Severity.INFO, passed=True,
                                    title="Ambiguous date read as DD/MM",
                                    detail=f"'{inv.invoice_date.value}' interpreted as {d:%d %b %Y} (Indian DD/MM)",
                                    evidence={"raw": inv.invoice_date.value, "parsed": str(d)}))
    vendor_txt = ctx.vendor["name"] if ctx.vendor else "unknown vendor"
    total_txt = f"Rs {n['total']:,.2f}" if n["total"] is not None else "total unreadable"
    status = StageStatus.OK if ctx.vendor and n["total"] is not None else StageStatus.WARN
    return StageResult(status, f"{vendor_txt} - {n['invoice_number']} - {total_txt}",
                       {"before_after": rows, "vendor_match": ctx.vendor_match, "normalized": n})
