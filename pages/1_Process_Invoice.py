"""Process Invoice: upload a PDF and watch the eight stages run live, or run the sample set as a demo."""
import streamlit as st
import yaml

from core import config
from core.db import repo
from core.db.seed import ensure_seeded, seed
from core.pipeline import STAGE_NAMES, run_pipeline
from ui import theme
from ui.components import document_preview, fields_table, render_run, stage_card_html
from ui.sidebar import controls

st.set_page_config(page_title="Process Invoice · InvoiceIQ", layout="wide")
theme.inject()
ensure_seeded()
controls()
st.title("Process Invoice")

upload = st.file_uploader("Drag & drop an invoice PDF", type=["pdf"])
run_upload = st.button("Run", type="primary", disabled=upload is None)


def live_run(file_bytes: bytes, name: str, source: str) -> str:
    """Run the pipeline, updating one card per stage as each stage actually finishes."""
    st.subheader(name)
    left, right = st.columns([1, 1.25])
    with left:
        st.caption("PIPELINE (live)")
        slots = {n: st.empty() for n in STAGE_NAMES}
        for i, n in enumerate(STAGE_NAMES, 1):
            slots[n].markdown(stage_card_html(i, n), unsafe_allow_html=True)
    with right:
        st.caption("DOCUMENT")
        doc_slot, fields_slot = st.container(), st.container()

    def on_event(ev):
        i = STAGE_NAMES.index(ev.stage) + 1
        slots[ev.stage].markdown(stage_card_html(i, ev.stage, ev.status.value, ev.summary, ev.duration_ms),
                                 unsafe_allow_html=True)
        if ev.stage == "Ingest" and ev.status.value == "ok":
            with doc_slot:
                document_preview(ev.details["file_path"])
        if ev.stage == "Extract" and ev.status.value in ("ok", "warn"):
            with fields_slot:
                st.caption("EXTRACTED FIELDS")
                fields_table(ev.details["extraction"])

    return run_pipeline(file_bytes, name, source, on_event=on_event).run_id


if run_upload and upload:
    st.session_state["last_runs"] = [live_run(upload.getvalue(), upload.name, "upload")]

st.divider()
st.subheader("Demo: run the sample invoices")
MANIFEST = yaml.safe_load((config.SAMPLES_DIR / "manifest.yaml").read_text())
SAMPLE_DIR = config.SAMPLES_DIR / "invoices"
results = st.session_state.get("sample_results", {})
st.dataframe([{"#": i, "sample": m["file"], "scenario": m["label"], "expected": m["expected"],
               "got": results.get(m["file"], {}).get("got", ""),
               "match": results.get(m["file"], {}).get("match", "")} for i, m in enumerate(MANIFEST, 1)],
             hide_index=True, width="stretch")
sure = st.checkbox("Reset demo data first (deletes all runs, findings and the invoice ledger)")
if st.button("Run all samples", type="primary", disabled=not sure):
    seed()
    results, bar = {}, st.progress(0.0)
    for i, m in enumerate(MANIFEST):
        bar.progress(i / len(MANIFEST), f"Running {m['file']} ({i + 1}/{len(MANIFEST)})")
        path = SAMPLE_DIR / m["file"]
        if not path.exists():
            results[m["file"]] = {"got": "missing file", "match": "NO"}
            continue
        ctx = run_pipeline(path.read_bytes(), m["file"], "sample")
        got = ctx.decision.outcome.value
        results[m["file"]] = {"got": got, "match": "yes" if got == m["expected"] else "NO", "run_id": ctx.run_id}
    bar.progress(1.0, "Done")
    st.session_state["sample_results"] = results
    st.session_state["last_runs"] = []
    st.rerun()
if results:
    ok = sum(r["match"] == "yes" for r in results.values())
    (st.success if ok == len(MANIFEST) else st.error)(
        f"{ok}/{len(MANIFEST)} samples got their expected decision. Open any run on the Audit Trail page.")


for rid in st.session_state.get("last_runs", [])[-1:]:
    run = repo.get_run(rid)
    if run:
        st.divider()
        st.subheader(f"Decision · {run['file_name']}")
        render_run(run, show_preview=False)
