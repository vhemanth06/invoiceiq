"""Master Data: vendors, POs and rule thresholds, editable live; plus 'Reset demo data'."""
import streamlit as st

from core import config
from core.db import repo
from core.db.schema import PurchaseOrder, Vendor
from core.db.seed import ensure_seeded, seed
from ui import theme
from ui.sidebar import controls

st.set_page_config(page_title="Master Data · InvoiceIQ", layout="wide")
theme.inject()
ensure_seeded()
controls()
st.title("Master Data")

with st.container(border=True):
    a, b = st.columns([3, 1])
    a.write("**Reset demo data** reseeds vendors and POs from CSV and clears all runs, findings and the invoice "
            "ledger. Do this before a demo: the split-invoice and duplicate cases depend on run order.")
    if b.button("Reset demo data", type="primary"):
        seed()
        st.success("Demo data reset.")

tab_v, tab_p, tab_r = st.tabs(["Vendors", "Purchase orders", "Rules"])
with tab_v:
    v = st.data_editor(repo.vendors(), num_rows="dynamic", width="stretch", key="vendors")
    if st.button("Save vendors"):
        repo.save_master(Vendor, v)
        st.success("Vendors saved.")
with tab_p:
    p = st.data_editor(repo.purchase_orders(), num_rows="dynamic", width="stretch", key="pos")
    if st.button("Save purchase orders"):
        repo.save_master(PurchaseOrder, p)
        st.success("Purchase orders saved.")
    st.caption("PO lines")
    st.dataframe(repo.po_lines(), hide_index=True, width="stretch")
with tab_r:
    r = config.load_rules()
    t, c, d = r["tolerances"], r["confidence"], r["duplicates"]
    st.caption("Changes apply to the next run. Try raising the amount tolerance and re-running a REVIEW invoice.")
    x, y = st.columns(2)
    t["amount_pct"] = x.slider("Amount tolerance (% of PO)", 0.0, 20.0, float(t["amount_pct"]), 0.5)
    t["amount_abs_cap"] = x.number_input("Amount tolerance cap (₹)", 0, 1_000_000, int(t["amount_abs_cap"]), 1000)
    t["line_price_pct"] = x.slider("Line unit-price tolerance (%)", 0.0, 50.0, float(t["line_price_pct"]), 0.5)
    t["cumulative_block_pct"] = x.slider("Cumulative over-billing hard-block above (%)", 0.0, 50.0,
                                         float(t["cumulative_block_pct"]), 1.0)
    c["min_field_confidence"] = y.slider("Min critical-field confidence", 0.0, 1.0, float(c["min_field_confidence"]), .05)
    c["min_po_match_score"] = y.slider("Min inferred PO match score", 0.0, 1.0, float(c["min_po_match_score"]), .05)
    d["date_window_days"] = y.number_input("Duplicate date window (days)", 0, 365, int(d["date_window_days"]))
    r["approval"]["auto_approve_limit"] = y.number_input("Auto-approval limit (₹)", 0, 100_000_000,
                                                         int(r["approval"]["auto_approve_limit"]), 10000)
    if st.button("Save rules", type="primary"):
        config.save_rules(r)
        st.success("rules.yaml saved.")
    with st.expander("rules.yaml"):
        st.code(config.RULES_PATH.read_text(), language="yaml")
