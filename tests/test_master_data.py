"""PO lines edited on the Setup page are cleaned and checked before saving."""
from core.db.repo import po_line_rows, subtotal_gaps

POS = {"PO-2026-1044"}


def test_blank_amount_and_line_no_are_filled():
    rows, errors = po_line_rows([
        {"po_number": "PO-2026-1044", "line_no": 1, "description": "Bearing kit SKF 6205", "quantity": 50,
         "unit_price": 1000, "amount": 50000},
        {"po_number": "PO-2026-1044", "line_no": None, "description": "Grease cartridge", "quantity": 10,
         "unit_price": 250, "amount": None},
        {"po_number": None, "line_no": None, "description": None, "quantity": None, "unit_price": None,
         "amount": None},  # the empty row the editor adds
    ], POS)
    assert not errors and len(rows) == 2
    assert rows[1]["line_no"] == 2 and rows[1]["amount"] == 2500


def test_unknown_po_and_bad_amount_are_rejected():
    _, errors = po_line_rows([
        {"po_number": "PO-2026-9999", "description": "X", "quantity": 1, "unit_price": 1, "amount": 1},
        {"po_number": "PO-2026-1044", "description": "Y", "quantity": 2, "unit_price": 100, "amount": 500},
    ], POS)
    assert len(errors) == 2 and "does not exist" in errors[0] and "not quantity x unit price" in errors[1]


def test_subtotal_gap_warning():
    rows = [{"po_number": "PO-2026-1044", "amount": 52500.0}]
    assert subtotal_gaps(rows, [{"po_number": "PO-2026-1044", "subtotal": 50000.0}]) == [
        ("PO-2026-1044", (52500.0, 50000.0))]
