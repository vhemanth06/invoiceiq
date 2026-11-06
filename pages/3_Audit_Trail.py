"""Audit Trail: replay any historical run's full trace from stored events."""
import streamlit as st

from core.db import repo
from core.db.seed import ensure_seeded
from ui import theme
from ui.components import render_run
from ui.formatting import esc, local, ms
from ui.sidebar import controls

st.set_page_config(page_title="Audit Trail · InvoiceIQ", layout="wide")
theme.inject()
ensure_seeded()
controls()
st.title("Audit Trail")

runs = repo.list_runs()
if not runs:
    st.info("No runs yet.")
    st.stop()
ids = [r["id"] for r in runs]
want = st.query_params.get("run_id") or st.session_state.get("run_id")
label = {r["id"]: f"{local(r['created_at']):%d %b %H:%M:%S} · {r['file_name']} · {r['outcome']}" for r in runs}
rid = st.selectbox("Run", ids, index=ids.index(want) if want in ids else 0, format_func=label.get)
st.session_state["run_id"] = rid
st.query_params["run_id"] = rid

run = repo.get_run(rid)
st.markdown(f"**{esc(run['vendor_name'] or 'Unknown vendor')}** · invoice **{esc(run['invoice_number'] or '—')}** · "
            f"{esc(run['doc_type'] or '—')} PDF · extracted by **{esc(run['provider'] or '—')}** · "
            f"processed in {ms(run['duration_ms'])} · source {esc(run['source'])}")
if run["outcome"] != run["original_outcome"]:
    st.warning(f"Overridden by a reviewer: pipeline said {run['original_outcome']}, now {run['outcome']}. "
               "See the Override event in the timeline.")
render_run(run)
