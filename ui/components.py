"""Reusable UI pieces: stage cards, decision banner, finding pills, document preview, full run view.

render_run() is shared by the Process page (after a live run) and Run Detail (replay), so the two
views are built from the same stored events and cannot drift apart.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pymupdf
import streamlit as st

from core.pipeline import STAGE_NAMES
from ui.formatting import STATUS_LABELS, badge, esc, inr, ms
from ui.theme import COLORS

CRITICAL = ("vendor_name", "invoice_number", "invoice_date", "total")


def stage_card_html(idx: int, name: str, status: str = "pending", summary: str = "", duration_ms: int | None = None) -> str:
    c = COLORS.get(status, COLORS["neutral"])
    dur = ms(duration_ms) if duration_ms is not None and status not in ("running", "pending") else ""
    right = STATUS_LABELS.get(status, status) + (f" · {dur}" if dur else "")
    return (f'<div class="iq-card" style="--c:{c}"><div class="h"><span><span class="dot"></span>{idx}. {esc(name)}'
            f'</span><span class="d">{right}</span></div><div class="s">{esc(summary)}</div></div>')


def decision_banner(d: dict) -> None:
    c = COLORS.get(d["outcome"], COLORS["neutral"])
    st.markdown(
        f'<div class="iq-banner" style="--c:{c}"><div class="o">{d["outcome"]}'
        f'<span style="font-size:.85rem;font-weight:500;opacity:.75"> · confidence {d["confidence"]:.2f}'
        f' · explained by {esc(d.get("explained_by", "template"))}</span></div>'
        f'<div class="hl">{esc(d["headline"])}</div><div>{esc(d["explanation"])}</div>'
        f'<div style="margin-top:.5rem"><b>Recommended action:</b> {esc(d["recommended_action"])}</div></div>',
        unsafe_allow_html=True)


def pills(findings: list[dict]) -> None:
    out = []
    for f in sorted(findings, key=lambda f: (f["passed"], {"block": 0, "warn": 1, "info": 2}[f["severity"]])):
        if f["passed"]:
            label, c = ("Info", COLORS["info"]) if f["severity"] == "info" else ("Pass", COLORS["ok"])
        else:
            label, c = ("Block", COLORS["block"]) if f["severity"] == "block" else ("Warn", COLORS["warn"])
        out.append(f'<span class="iq-pill" style="--c:{c}" title="{esc(f["detail"])}"><b>{label}</b> '
                   f'{esc(f["title"])}</span>')
    st.markdown("".join(out), unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def page_png(path: str, dpi: int = 90) -> list[bytes]:
    if not path or not Path(path).exists():
        return []
    try:
        doc = pymupdf.open(path)
        return [p.get_pixmap(dpi=dpi).tobytes("png") for p in list(doc)[:3]]
    except Exception:
        return []


def document_preview(path: str) -> None:
    imgs = page_png(path)
    if not imgs:
        st.info("No preview available (unreadable document).")
    for i, img in enumerate(imgs):
        st.image(img, caption=f"Page {i + 1}", width="stretch")


def fields_table(extraction: dict, threshold: float = 0.8) -> None:
    rows = []
    for k, v in extraction.items():
        if isinstance(v, dict) and "confidence" in v:
            rows.append({"Field": k + (" *" if k in CRITICAL else ""), "Value": "" if v["value"] is None else str(v["value"]),
                         "Confidence": float(v["confidence"]), "Source": v["source"],
                         "Flag": "low" if v["source"] != "missing" and v["confidence"] < threshold else
                         ("missing" if v["source"] == "missing" else "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
    tax = extraction.get("tax", {})
    st.caption(f"Tax: CGST {tax.get('cgst')} · SGST {tax.get('sgst')} · IGST {tax.get('igst')} · rate "
               f"{tax.get('rate_percent')}% · tax-inclusive: {tax.get('tax_inclusive')} · document type: "
               f"{extraction.get('document_type')}   (* = critical field)")
    if extraction.get("line_items"):
        st.dataframe(pd.DataFrame(extraction["line_items"]), hide_index=True, width="stretch")


def findings_table(findings: list[dict]) -> None:
    if not findings:
        st.info("No findings.")
        return
    df = pd.DataFrame([{"Result": "pass" if f["passed"] else f"fail ({f['severity']})",
                        "Rule": f["rule_id"], "Severity": f["severity"], "Stage": f["stage"], "Check": f["title"],
                        "Detail": f["detail"]} for f in findings])
    st.dataframe(df, hide_index=True, width="stretch")


def stage_details(ev: dict) -> None:
    d = json.loads(ev["details_json"]) if isinstance(ev.get("details_json"), str) else ev.get("details", {})
    name = ev["stage"]
    if name == "Normalise" and d.get("before_after"):
        st.dataframe(pd.DataFrame(d["before_after"]).astype(str), hide_index=True, width="stretch")
    elif name in ("Validate", "Rules") and d.get("findings"):
        findings_table(d["findings"])
    elif name == "Match PO":
        st.write(f"Method **{d.get('match_method')}** · score {d.get('match_score')} · billed before "
                 f"{inr(d.get('billed_before'))}")
        if d.get("candidates"):
            st.dataframe(pd.DataFrame(d["candidates"]), hide_index=True, width="stretch",
                         column_config={"score": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
        if d.get("po_lines"):
            st.caption("PO lines")
            st.dataframe(pd.DataFrame(d["po_lines"])[["line_no", "description", "quantity", "unit_price", "amount"]],
                         hide_index=True, width="stretch")
    elif name == "Extract":
        st.write(f"Provider: **{d.get('provider', '—')}** · route {d.get('route', '—')}")
        for a in d.get("attempts", []):
            st.caption(f"• {a}")
        for a in d.get("confidence_adjustments", []):
            st.warning(f"Confidence adjusted: {a}")
    else:
        st.json(d, expanded=False)


def timeline(events: list[dict]) -> None:
    finished = [e for e in events if e["status"] != "running"]
    for e in finished:
        idx = STAGE_NAMES.index(e["stage"]) + 1 if e["stage"] in STAGE_NAMES else "•"
        with st.expander(f"{idx}. {e['stage']} [{STATUS_LABELS.get(e['status'], e['status'])}] — {e['summary'][:110]}  ({ms(e['duration_ms'])})"):
            st.write(e["summary"])
            stage_details(e)


def po_comparison(run: dict) -> None:
    ctx = run["context"]
    po = ctx.get("po")
    if not po:
        st.info("No PO matched.")
        if ctx.get("candidates"):
            st.dataframe(pd.DataFrame(ctx["candidates"]), hide_index=True, width="stretch")
        return
    n = run.get("normalized") or {}
    c1, c2 = st.columns(2)
    c1.markdown(f"**Invoice** {esc(n.get('invoice_number'))}")
    c1.write(f"Total {inr(n.get('total'))}  \nSubtotal {inr(n.get('subtotal'))}  \nTax {inr(n.get('tax_total'))}"
             f"{' (inclusive)' if n.get('tax_inclusive') else ''}")
    c2.markdown(f"**{po['po_number']}** ({po['status']}, {ctx['match_method']} match, score {ctx['match_score']:.2f})")
    c2.write(f"Total {inr(po['total'])}  \nSubtotal {inr(po['subtotal'])} + {po['tax_rate']:g}% GST ({po['tax_mode']})"
             f"  \nBilled before this invoice {inr(ctx.get('po_billed_before'))}  \nPartial invoicing "
             f"{'allowed' if po['allows_partial'] else 'not allowed'}")
    if run.get("extraction") and ctx.get("po_lines"):
        st.caption("Line comparison")
        inv = pd.DataFrame(run["extraction"]["line_items"])[["description", "quantity", "unit_price", "amount"]]
        pol = pd.DataFrame(ctx["po_lines"])[["description", "quantity", "unit_price", "amount"]]
        a, b = st.columns(2)
        a.dataframe(inv, hide_index=True, width="stretch")
        b.dataframe(pol, hide_index=True, width="stretch")
    if ctx.get("candidates"):
        st.caption("Candidate POs considered")
        st.dataframe(pd.DataFrame(ctx["candidates"]), hide_index=True, width="stretch")


def decision_complete(run: dict) -> bool:
    return bool(run.get("decision", {}).get("outcome"))


def render_run(run: dict, show_preview: bool = True) -> None:
    """Full trace of one stored run: banner, pills, then tabs."""
    if not decision_complete(run):
        st.warning("This run did not finish (no decision stored). Events so far:")
        timeline(run["events"])
        return
    decision_banner(run["decision"])
    pills(run["findings"])
    dup = next((f for f in run["findings"] if f["rule_id"].startswith(("R19", "R20")) and not f["passed"]), None)
    tabs = st.tabs(["Timeline", "Extraction", "Matching", "Findings", "Raw JSON"])
    with tabs[0]:
        timeline(run["events"])
    with tabs[1]:
        c1, c2 = st.columns([1, 1.3])
        with c1:
            if show_preview:
                document_preview(run["file_path"])
        with c2:
            if run.get("extraction"):
                fields_table(run["extraction"])
            else:
                st.warning("Nothing was extracted (manual entry needed).")
    with tabs[2]:
        po_comparison(run)
    with tabs[3]:
        findings_table(run["findings"])
        if dup:
            orig = json.loads(dup["evidence_json"]).get("original_run")
            if orig and st.button(f"Open original invoice run {orig}", key=f"orig-{run['id']}"):
                st.session_state["run_id"] = orig
                st.switch_page("pages/3_Run_Detail.py")
    with tabs[4]:
        payload = {k: run[k] for k in ("id", "file_name", "outcome", "decision", "extraction", "normalized", "context")}
        payload["findings"] = run["findings"]
        st.json(payload, expanded=False)
    st.download_button("Download decision JSON", json.dumps(
        {"run_id": run["id"], "file": run["file_name"], "decision": run["decision"], "vendor_id": run["vendor_id"],
         "po_number": run["po_number"], "total": run["total"], "findings": run["findings"]}, indent=2, default=str),
        file_name=f"invoiceiq_{run['id']}.json", mime="application/json", key=f"dl-{run['id']}")
