"""PO matcher scoring: clear vs ambiguous inferred matches."""
from datetime import date

from core.models import LineItem
from core.stages.s6_match import billed_against, score_po
from tests.conftest import po

LINES = [LineItem(description="Hosting services - Oct 2026", quantity=1, unit_price=60000, amount=60000)]


def test_clear_match_scores_high():
    s = score_po(po(po_number="A", total=70800, po_date=date(2026, 10, 1)),
                 [{"description": "Cloud hosting services - monthly"}], 70800, LINES, date(2026, 11, 1), 0)
    assert s["score"] >= 0.75 and s["amount_similarity"] == 1


def test_wrong_po_scores_low():
    s = score_po(po(po_number="B", total=17700, po_date=date(2026, 10, 10)),
                 [{"description": "Backup storage add-on 2 TB"}], 70800, LINES, date(2026, 11, 1), 0)
    assert s["score"] < 0.5


def test_date_before_po_is_implausible():
    s = score_po(po(total=70800, po_date=date(2026, 12, 1)), [{"description": "Hosting"}], 70800, LINES,
                 date(2026, 11, 1), 0)
    assert s["date_plausibility"] == 0


def test_billed_against_ignores_rejected():
    ledger = [{"po_number": "P", "total": 100, "outcome": "APPROVE"},
              {"po_number": "P", "total": 50, "outcome": "REVIEW"},
              {"po_number": "P", "total": 999, "outcome": "REJECT"},
              {"po_number": "Q", "total": 7, "outcome": "APPROVE"}]
    assert billed_against("P", ledger) == 150


def test_ambiguous_match_routes_to_none(fresh_db, make_ctx):
    """Two equally plausible POs: no inferred match is accepted, candidates are listed."""
    from core.db import repo
    from core.db.schema import PurchaseOrder
    from core.stages import s6_match
    rows = repo.purchase_orders() + [dict(po(po_number="PO-2026-1042", po_date=date(2026, 9, 3)))]
    repo.save_master(PurchaseOrder, rows)
    ctx = make_ctx(vendor={"vendor_id": "V001"}, norm={"po_ref": None})
    s6_match.run(ctx)
    assert ctx.match_method == "none" and len(ctx.candidates) >= 2
