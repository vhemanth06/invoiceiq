"""Load master data CSVs into SQLite. `python -m core.db.seed` resets the demo DB."""
from __future__ import annotations

import csv
import threading
from datetime import date

from sqlmodel import Session, SQLModel, delete

from core.config import DATA_DIR
from core.db.schema import POLine, PurchaseOrder, Vendor, get_engine

_TRUE = ("true", "1", "yes")
# Streamlit sessions are threads of one process: only one may create/drop tables or reseed at a time.
_DDL_LOCK = threading.RLock()


def _rows(name: str) -> list[dict]:
    with open(DATA_DIR / name, newline="") as f:
        return list(csv.DictReader(f))


def seed(reset_runs: bool = True) -> None:
    """Reseed master data; with reset_runs also clear runs, events, findings and the ledger."""
    with _DDL_LOCK:
        _seed(reset_runs)


def _seed(reset_runs: bool) -> None:
    engine = get_engine()
    tables = [Vendor, PurchaseOrder, POLine]
    if reset_runs:
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        for t in tables:
            s.exec(delete(t))
        for r in _rows("vendors.csv"):
            s.add(Vendor(vendor_id=r["vendor_id"], name=r["name"], aliases=r["aliases"], gstin=r["gstin"],
                         state=r["state"], approved=r["approved"].lower() in _TRUE,
                         bank_last4=r["bank_last4"], payment_terms_days=int(r["payment_terms_days"])))
        for r in _rows("purchase_orders.csv"):
            s.add(PurchaseOrder(po_number=r["po_number"], vendor_id=r["vendor_id"],
                                po_date=date.fromisoformat(r["po_date"]), status=r["status"],
                                subtotal=float(r["subtotal"]), tax_rate=float(r["tax_rate"]),
                                tax_mode=r["tax_mode"], total=float(r["total"]),
                                allows_partial=r["allows_partial"].lower() in _TRUE))
        for r in _rows("po_lines.csv"):
            s.add(POLine(po_number=r["po_number"], line_no=int(r["line_no"]), description=r["description"],
                         quantity=float(r["quantity"]), unit_price=float(r["unit_price"]),
                         amount=float(r["amount"])))
        s.commit()


def ensure_seeded() -> None:
    """Startup hook: seed master data if the DB is empty (e.g. fresh cloud deploy).

    Tables are (re)created first: a cloud redeploy can delete the DB file while the app keeps running,
    and new connections then open an empty file. create_all only adds missing tables, so this is cheap.
    """
    engine = get_engine()
    with _DDL_LOCK:
        SQLModel.metadata.create_all(engine)
        with Session(engine) as s:
            if s.get(Vendor, "V001") is None:
                _seed(reset_runs=False)


if __name__ == "__main__":
    seed()
    print("Seeded master data and cleared run history.")
