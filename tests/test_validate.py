"""Normalisers (stage 4) and internal-consistency checks (stage 5)."""
from datetime import date

import pytest

from core.models import TaxBreakdown
from core.stages.s4_normalize import gstin_valid, invoice_key, parse_amount, parse_date, po_key, resolve_vendor
from core.stages.s5_validate import check_arithmetic, check_dates, check_gst, check_required, money_strings
from tests.conftest import ACME


@pytest.mark.parametrize("raw,expected", [
    ("Rs. 1,18,000/-", 118000.0), ("₹1,18,000.50", 118000.5), ("INR 2,36,000.00", 236000.0),
    ("118000", 118000.0), (70800, 70800.0), ("(1,500.00)", -1500.0), (None, None), ("n/a", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw,expected,ambiguous", [
    ("06/11/2026", date(2026, 11, 6), True), ("6-Nov-26", date(2026, 11, 6), False),
    ("2026-11-06", date(2026, 11, 6), False), ("25/10/2026", date(2026, 10, 25), False),
    ("02 Nov 2026", date(2026, 11, 2), False), ("03/04/2026", date(2026, 4, 3), True),
    ("05/05/2026", date(2026, 5, 5), False), ("garbage", None, False),
])
def test_parse_date(raw, expected, ambiguous):
    assert parse_date(raw) == (expected, ambiguous)


@pytest.mark.parametrize("raw,key", [
    ("INV-1042", "1042"), ("inv 1042", "1042"), ("INV/1042-R", "1042"), ("#1042", "1042"),
    ("INV-1042 COPY", "1042"), ("BLIT/2026/071", "BLIT2026071"), ("NOVA-77", "NOVA77"), ("", ""),
])
def test_invoice_key(raw, key):
    assert invoice_key(raw) == key


def test_po_key():
    known = ["PO-2026-1052", "PO-2026-1041"]
    assert po_key("PO 1052", known) == "PO-2026-1052"
    assert po_key("#1052", known) == "PO-2026-1052"
    assert po_key("P.O. 2026/1041", known) == "PO-2026-1041"
    assert po_key("PO-2026-9999", known) == "PO-2026-9999"
    assert po_key(None, known) is None


def test_gstin():
    assert gstin_valid("36AABCA1234F1Z5")
    assert not gstin_valid("36AABCA1234F1Y5")   # 14th char must be Z
    assert not gstin_valid("99AABCA1234F1Z5")   # bad state code
    assert not gstin_valid(None)


def test_resolve_vendor_by_gstin_then_alias():
    v, m = resolve_vendor("Some other name", "36AABCA1234F1Z5", [ACME])
    assert v["vendor_id"] == "V001" and m["method"] == "gstin"
    v, m = resolve_vendor("ACME INDUSTRIAL", None, [ACME])
    assert v["vendor_id"] == "V001" and m["method"] == "name"
    v, m = resolve_vendor("Totally Unknown Traders", None, [ACME])
    assert v is None


def test_money_strings_indian_grouping():
    assert "1,18,000.00" in money_strings(118000)


def _by_id(findings):
    return {f.rule_id: f for f in findings}


def test_arithmetic_passes(make_ctx):
    f = _by_id(check_arithmetic(make_ctx(lines=[("Gloves", 40, 60000.0), ("Hose", 20, 40000.0)])))
    assert f["R03_LINE_MATH"].passed and f["R04_SUBTOTAL"].passed and f["R05_TOTAL"].passed


def test_total_mismatch_flags_and_detects_misread(make_ctx):
    ctx = make_ctx(total=181000.0, norm={"total": 181000.0})
    ctx.text = "TOTAL Rs. 1,18,000.00/-"     # the right number is on the page
    f = _by_id(check_arithmetic(ctx))
    assert not f["R05_TOTAL"].passed
    assert "misread" in f["R05_TOTAL"].detail
    assert ctx.extraction.total.confidence <= 0.5


def test_tax_inclusive_total_not_flagged(make_ctx):
    ctx = make_ctx(lines=[(None, None, 94080.0)], subtotal=94080.0, total=94080.0,
                   tax=TaxBreakdown(cgst=5040, sgst=5040, rate_percent=12, tax_inclusive=True))
    assert _by_id(check_arithmetic(ctx))["R05_TOTAL"].passed


def test_gst_structure(make_ctx):
    assert check_gst(make_ctx()).passed                                         # Telangana -> Telangana, CGST+SGST
    assert not check_gst(make_ctx(tax=TaxBreakdown(igst=18000))).passed         # IGST on intra-state
    ctx = make_ctx(tax=TaxBreakdown(igst=18000), norm={"gstin": "29AAKFB5678K1Z2"})
    assert check_gst(ctx).passed                                                # Karnataka -> Telangana, IGST


def test_dates(make_ctx):
    assert check_dates(make_ctx()).passed
    assert not check_dates(make_ctx(norm={"invoice_date": date(2026, 1, 1)})).passed    # > 180 days old
    assert not check_dates(make_ctx(norm={"invoice_date": date(2026, 11, 20)})).passed  # future
    assert not check_dates(make_ctx(norm={"invoice_date": None})).passed


def test_required_and_confidence(make_ctx):
    ctx = make_ctx()
    ctx.extraction.total.value = None
    f = _by_id(check_required(ctx))
    assert not f["R01_REQUIRED_FIELDS"].passed and f["R01_REQUIRED_FIELDS"].severity.value == "block"
    ctx = make_ctx()
    ctx.extraction.total.confidence = 0.55
    f = _by_id(check_required(ctx))
    assert not f["R02_CONFIDENCE"].passed and "total" in f["R02_CONFIDENCE"].evidence["low_fields"]
