"""Each business rule, on hand-built contexts (no LLM, no PDF)."""
from datetime import date

from core.models import LineItem, TaxBreakdown
from core.stages import s7_rules as R
from tests.conftest import ACME, po


def test_vendor_approved(make_ctx, rules):
    assert R.vendor_approved(make_ctx(vendor=ACME), rules).passed
    f = R.vendor_approved(make_ctx(vendor={**ACME, "approved": False}), rules)
    assert not f.passed and f.severity.value == "block"
    assert not R.vendor_approved(make_ctx(vendor=None), rules).passed


def test_gstin_and_bank(make_ctx, rules):
    assert R.gstin_matches(make_ctx(vendor=ACME), rules).passed
    assert not R.gstin_matches(make_ctx(vendor=ACME, norm={"gstin": "36AAFCD9012M1Z8"}), rules).passed
    assert R.bank_matches(make_ctx(vendor=ACME), rules).passed
    f = R.bank_matches(make_ctx(vendor=ACME, norm={"bank_last4": "9931"}), rules)
    assert not f.passed and f.rule_id == "R11_BANK_MATCH"


def test_po_status_and_vendor(make_ctx, rules):
    assert not R.po_open(make_ctx(po=po(status="CLOSED")), rules).passed
    assert not R.po_vendor_matches(make_ctx(po=po(vendor_id="V002"), vendor=ACME), rules).passed
    assert R.po_vendor_matches(make_ctx(po=po(), vendor=ACME), rules).passed


def test_po_found_variants(make_ctx, rules):
    assert R.po_found(make_ctx(match_method="explicit", po=po()), rules).rule_id == "R12_PO_FOUND"
    f = R.po_found(make_ctx(match_method="inferred", po=po(), match_score=0.86), rules)
    assert f.rule_id == "R12_PO_INFERRED" and not f.passed
    assert R.po_found(make_ctx(match_method="none"), rules).rule_id == "R12_PO_MISSING"


def test_amount_tolerance_uses_min_of_pct_and_cap(make_ctx, rules):
    # PO 1,18,000: 2% = 2,360 < 5,000 cap -> tolerance 2,360
    assert R.amount_within_tolerance(make_ctx(po=po(), total=120000.0, norm={"total": 120000.0}), rules).passed
    f = R.amount_within_tolerance(make_ctx(po=po(), total=121000.0, norm={"total": 121000.0}), rules)
    assert not f.passed and f.evidence["tolerance"] == 2360
    # PO 5,90,000: 2% = 11,800 > cap -> tolerance 5,000
    big = po(total=590000.0, allows_partial=True)
    assert not R.amount_within_tolerance(make_ctx(po=big, norm={"total": 596000.0}), rules).passed


def test_cumulative_po_warn_vs_block(make_ctx, rules):
    big = po(po_number="P", total=590000.0, allows_partial=True)
    ledger = [{"run_id": "a", "po_number": "P", "total": 448400.0, "outcome": "APPROVE"}]
    f = R.cumulative_po_balance(make_ctx(po=big, ledger=ledger, po_billed_before=448400.0,
                                         norm={"total": 191160.0}), rules)
    assert not f.passed and f.severity.value == "warn" and f.evidence["over_pct"] == 8.4
    f = R.cumulative_po_balance(make_ctx(po=big, ledger=ledger, po_billed_before=448400.0,
                                         norm={"total": 220000.0}), rules)
    assert f.severity.value == "block"   # > 10% over
    assert R.cumulative_po_balance(make_ctx(po=big, norm={"total": 236000.0}), rules).passed


def test_partial_not_allowed(make_ctx, rules):
    assert not R.partial_allowed(make_ctx(po=po(), norm={"total": 59000.0}), rules).passed
    assert R.partial_allowed(make_ctx(po=po(allows_partial=True), norm={"total": 59000.0}), rules) is None


def test_line_prices(make_ctx, rules):
    pl = [{"description": "Industrial safety gloves (box of 100)", "unit_price": 1500.0}]
    ok = make_ctx(lines=[("Industrial safety gloves (box of 100)", 40, 60000.0)], po=po(), po_lines=pl)
    assert R.line_prices(ok, rules).passed
    bad = make_ctx(lines=[("Industrial safety gloves (box of 100)", 40, 61000.0)], po=po(), po_lines=pl)
    assert not R.line_prices(bad, rules).passed   # 1525 vs 1500 = +1.7%
    bundled = make_ctx(po=po(), po_lines=pl)
    bundled.extraction.line_items = [LineItem(description="AMC lump sum", amount=100000, is_bundled=True)]
    assert R.line_prices(bundled, rules) is None


def _ledger(**kw):
    e = {"run_id": "orig", "vendor_id": "V001", "invoice_number": "INV-1042", "invoice_no_key": "1042",
         "invoice_date": date(2026, 10, 5), "total": 118000.0, "po_number": "PO-2026-1041", "file_hash": "h0",
         "lines_sig": "sig", "outcome": "APPROVE"}
    e.update(kw)
    return e


def test_exact_duplicate_on_normalised_key(make_ctx, rules):
    ctx = make_ctx(vendor=ACME, ledger=[_ledger()], norm={"invoice_key": "1042", "invoice_number": "INV/1042-R"})
    f = R.exact_duplicate(ctx, rules)
    assert not f.passed and f.severity.value == "block" and f.evidence["original_run"] == "orig"


def test_rejected_original_is_not_a_duplicate(make_ctx, rules):
    ctx = make_ctx(vendor=ACME, ledger=[_ledger(outcome="REJECT")], norm={"invoice_key": "1042"})
    assert R.exact_duplicate(ctx, rules).passed


def test_probable_duplicate_fuzzy(make_ctx, rules):
    ctx = make_ctx(vendor=ACME, ledger=[_ledger()],
                   norm={"invoice_key": "1042A", "invoice_number": "INV-1042A", "total": 118000.0,
                         "invoice_date": date(2026, 10, 12), "lines_sig": "other"})
    ctx.findings = [R.exact_duplicate(ctx, rules)]
    f = R.probable_duplicate(ctx, rules)
    assert not f.passed and f.rule_id == "R20_PROBABLE_DUPLICATE"


def test_tax_inclusive_reconciled_and_partly_unexplained(make_ctx, rules):
    p = po(po_number="PO-2026-1063", subtotal=84000.0, tax_rate=12.0, total=94080.0)
    inc = TaxBreakdown(cgst=5040, sgst=5040, rate_percent=12, tax_inclusive=True)
    ok = R.tax_mode_reconcile(make_ctx(po=p, tax=inc, norm={"total": 94080.0, "tax_inclusive": True}), rules)
    assert ok.passed and ok.severity.value == "info" and ok.evidence["implied_pre_tax"] == 84000
    hi = R.tax_mode_reconcile(make_ctx(po=p, tax=inc, norm={"total": 97843.2, "tax_inclusive": True}), rules)
    assert not hi.passed and hi.evidence["unexplained"] == 3360   # 12% explained, 4% not
    assert R.tax_mode_reconcile(make_ctx(po=p), rules) is None


def test_authority_limit_and_doc_type(make_ctx, rules):
    assert not R.authority_limit(make_ctx(norm={"total": 350000.0}), rules).passed
    assert not R.document_type(make_ctx(document_kind="credit_note"), rules).passed


def test_rule_crash_becomes_warning(make_ctx, rules, monkeypatch):
    def boom(ctx, cfg):
        raise RuntimeError("bad data")
    monkeypatch.setattr(R, "RULES", [boom])
    [f] = R.run_rules(make_ctx(), rules)
    assert not f.passed and f.severity.value == "warn" and "bad data" in f.detail
