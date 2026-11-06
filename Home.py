"""InvoiceIQ - Streamlit entry point."""
import streamlit as st

from core.db import repo
from core.db.seed import ensure_seeded
from core.pipeline import STAGE_NAMES
from ui import theme
from ui.formatting import inr
from ui.sidebar import controls

st.set_page_config(page_title="InvoiceIQ", layout="wide")
theme.inject()
ensure_seeded()
controls()

st.title("InvoiceIQ")
st.markdown("#### From invoice PDF to a reasoned, auditable **Approve / Review / Reject** decision.")
st.write("Upload a vendor invoice (digital or scanned). An LLM reads it; deterministic procurement rules decide. "
         "Every stage is visible live and stored for replay.")
st.markdown('<div class="iq-flow">' + " → ".join(f'<span class="st">{i} {n}</span>' for i, n in
                                                 enumerate(STAGE_NAMES, 1)) + "</div>", unsafe_allow_html=True)

runs = repo.list_runs()
c = st.columns(4)
c[0].metric("Invoices processed", len(runs))
done = [r for r in runs if r["outcome"]]
c[1].metric("Auto-approve rate", f"{sum(r['outcome'] == 'APPROVE' for r in done) / len(done):.0%}" if done else "—")
review = [r for r in done if r["outcome"] == "REVIEW"]
c[2].metric("In review", len(review), inr(sum(r["total"] or 0 for r in review), paise=False), delta_color="off")
c[3].metric("Rejected", sum(r["outcome"] == "REJECT" for r in done))

st.divider()
l, r = st.columns(2)
with l:
    st.page_link("pages/1_Process_Invoice.py", label="Process an invoice (live run view)")
    st.page_link("pages/2_Dashboard.py", label="Dashboard and review queue")
with r:
    st.page_link("pages/3_Audit_Trail.py", label="Replay any run")
    st.page_link("pages/4_Setup.py", label="Vendors, POs and rule thresholds")
