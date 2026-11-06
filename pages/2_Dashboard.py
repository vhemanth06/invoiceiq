"""Dashboard: KPIs, charts, PO utilisation, runs table, and the human review queue."""
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.db import repo
from core.db.seed import ensure_seeded
from ui import theme
from ui.formatting import LOCAL_TZ, inr
from ui.sidebar import controls
from ui.theme import COLORS

st.set_page_config(page_title="Dashboard · InvoiceIQ", layout="wide")
theme.inject()
ensure_seeded()
controls()
st.title("Dashboard")

runs = pd.DataFrame(repo.list_runs())
if runs.empty:
    st.info("No runs yet. Process an invoice or run the samples first.")
    st.page_link("pages/1_Process_Invoice.py", label="Process Invoice")
    st.stop()
# stored as UTC; show local time
runs["created_at"] = pd.to_datetime(runs["created_at"], utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
done = runs[runs["outcome"].notna()]
findings = pd.DataFrame(repo.all_findings())
OUT_COLORS = {k: COLORS[k] for k in ("APPROVE", "REVIEW", "REJECT")}

# ---- KPIs -----------------------------------------------------------------
dups = findings[(findings.rule_id.isin(["R19_EXACT_DUPLICATE", "R20_PROBABLE_DUPLICATE"])) & (~findings.passed)] \
    if not findings.empty else findings
dup_value = done[done.id.isin(dups.run_id) & (done.outcome != "APPROVE")]["total"].fillna(0).sum() if len(dups) else 0
review = done[done.outcome == "REVIEW"]
k = st.columns(6)
k[0].metric("Total runs", len(runs))
k[1].metric("Auto-approve rate", f"{(done.original_outcome == 'APPROVE').mean():.0%}" if len(done) else "—")
k[2].metric("In review", len(review), inr(review["total"].fillna(0).sum(), paise=False), delta_color="off")
k[3].metric("Rejected", int((done.outcome == "REJECT").sum()))
k[4].metric("Duplicates prevented", inr(dup_value, paise=False))
k[5].metric("Avg processing", f"{done.duration_ms.mean() / 1000:.1f} s" if len(done) else "—")

# segmented control (not st.tabs) so the selected section survives reruns from the queue's inputs
SECTIONS = ["Overview", "All runs", "Review queue"]
picked = st.segmented_control("Section", SECTIONS, default=st.session_state.get("dash_last", SECTIONS[0]),
                              format_func=lambda s: f"{s} ({len(review)})" if s == "Review queue" else s,
                              label_visibility="collapsed")
section = st.session_state["dash_last"] = picked or st.session_state.get("dash_last", SECTIONS[0])

if section == SECTIONS[0]:
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Decisions over time")
        by_day = done.assign(day=done.created_at.dt.strftime("%d %b")).groupby(["day", "outcome"]).size().reset_index(name="n")
        st.plotly_chart(px.bar(by_day, x="day", y="n", color="outcome", color_discrete_map=OUT_COLORS)
                        .update_layout(height=300, margin=dict(t=10, b=10), xaxis_title=None, yaxis_title="invoices",
                                       xaxis_type="category"),
                        width="stretch")
    with c2:
        st.caption("Value by outcome")
        val = done.groupby("outcome")["total"].sum().reset_index()
        st.plotly_chart(px.pie(val, names="outcome", values="total", hole=.55, color="outcome",
                               color_discrete_map=OUT_COLORS).update_layout(height=300, margin=dict(t=10, b=10)),
                        width="stretch")
    c3, c4 = st.columns(2)
    with c3:
        st.caption("Top exception reasons")
        if not findings.empty:
            fail = findings[~findings.passed].groupby("title").size().sort_values().tail(8).reset_index(name="n")
            st.plotly_chart(px.bar(fail, x="n", y="title", orientation="h", color_discrete_sequence=[COLORS["warn"]])
                            .update_layout(height=320, margin=dict(t=10, b=10), xaxis_title=None, yaxis_title=None),
                            width="stretch")
    with c4:
        st.caption("PO utilisation (billed incl. this invoice vs PO total; rejected invoices excluded)")
        pos = pd.DataFrame(repo.purchase_orders())
        led = pd.DataFrame(repo.ledger())
        billed = (led[led.outcome != "REJECT"].groupby("po_number")["total"].sum()
                  if not led.empty else pd.Series(dtype=float))
        pos["billed"] = pos.po_number.map(billed).fillna(0)
        pos = pos[(pos.status == "OPEN") | (pos.billed > 0)]
        pos["pct"] = pos.billed / pos.total * 100
        fig = go.Figure(go.Bar(x=pos.pct, y=pos.po_number, orientation="h",
                               marker_color=[COLORS["fail"] if p > 100 else COLORS["warn"] if p > 90 else COLORS["ok"]
                                             for p in pos.pct],
                               text=[f"{inr(b)} / {inr(t)}" for b, t in zip(pos.billed, pos.total)], textposition="auto"))
        fig.add_vline(x=100, line_dash="dash")
        st.plotly_chart(fig.update_layout(height=320, margin=dict(t=10, b=10), xaxis_title="% of PO billed"),
                        width="stretch")

if section == SECTIONS[1]:
    f1, f2, f3 = st.columns(3)
    outs = f1.multiselect("Outcome", ["APPROVE", "REVIEW", "REJECT"], default=["APPROVE", "REVIEW", "REJECT"])
    vendors = f2.multiselect("Vendor", sorted(done.vendor_name.dropna().unique()))
    q = f3.text_input("Search invoice no.")
    view = done[done.outcome.isin(outs)]
    if vendors:
        view = view[view.vendor_name.isin(vendors)]
    if q:
        view = view[view.invoice_number.fillna("").str.contains(q, case=False, regex=False)]
    table = view[["created_at", "file_name", "vendor_name", "invoice_number", "po_number", "total", "outcome",
                  "confidence", "provider", "duration_ms", "id"]].rename(columns={"created_at": "time"})
    table["total"] = table["total"].map(inr)
    table["outcome"] = table.apply(lambda r: r.outcome + (" (override)" if r.outcome != view.loc[r.name, "original_outcome"]
                                                          else ""), axis=1)
    sel = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                       column_config={"confidence": st.column_config.ProgressColumn(min_value=0, max_value=1,
                                                                                    format="%.2f")})
    st.caption("Select a row to open its full trace.")
    if sel.selection.rows:
        st.session_state["run_id"] = table.iloc[sel.selection.rows[0]]["id"]
        st.switch_page("pages/3_Run_Detail.py")

if section == SECTIONS[2]:
    if review.empty:
        st.success("Review queue is empty.")
    for _, r in review.iterrows():
        d = json.loads(r.decision_json)
        with st.container(border=True):
            a, b = st.columns([3, 2])
            a.markdown(f"**{r.vendor_name or 'Unknown vendor'}** · {r.invoice_number} · {inr(r.total)} · {r.po_number or 'no PO'}")
            a.write(d["headline"])
            a.caption(f"Recommended: {d['recommended_action']}")
            comment = b.text_input("Comment (required)", key=f"c-{r.id}")
            x, y, z = b.columns(3)
            if x.button("Approve", key=f"a-{r.id}", disabled=not comment.strip()):
                repo.override(r.id, "APPROVE", comment)
                st.rerun()
            if y.button("Reject", key=f"r-{r.id}", disabled=not comment.strip()):
                repo.override(r.id, "REJECT", comment)
                st.rerun()
            if z.button("Open", key=f"o-{r.id}"):
                st.session_state["run_id"] = r.id
                st.switch_page("pages/3_Run_Detail.py")
