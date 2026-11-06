"""Process Invoice: upload or pick a sample, then watch the eight stages run live."""
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

MANIFEST = yaml.safe_load((config.SAMPLES_DIR / "manifest.yaml").read_text())
SAMPLE_DIR = config.SAMPLES_DIR / "invoices"

up_col, sample_col = st.columns([1, 1])
with up_col:
    upload = st.file_uploader("Drag & drop an invoice PDF", type=["pdf"])
    run_upload = st.button("Run", type="primary", disabled=upload is None)
with sample_col:
    labels = {m["label"] + f"  (expect {m['expected']})": m for m in MANIFEST}
    choice = st.selectbox("…or pick a sample", list(labels))
    s1, s2 = st.columns(2)
    run_sample = s1.button("Run sample")
    run_all = s2.button("Reset & run all samples in order", help="Reseeds the DB (clears history) first; the "
                                                                "split-invoice and duplicate cases need this order")


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
elif run_sample:
    m = labels[choice]
    st.session_state["last_runs"] = [live_run((SAMPLE_DIR / m["file"]).read_bytes(), m["file"], "sample")]
elif run_all:
    seed()
    ids, bar = [], st.progress(0.0, "Running samples…")
    for i, m in enumerate(MANIFEST):
        with st.container(border=True):
            ids.append(live_run((SAMPLE_DIR / m["file"]).read_bytes(), m["file"], "sample"))
        bar.progress((i + 1) / len(MANIFEST), f"{i + 1}/{len(MANIFEST)} samples")
    st.session_state["last_runs"] = ids
    rows = [(m["file"], m["expected"], repo.get_run(r)["outcome"]) for m, r in zip(MANIFEST, ids)]
    ok = sum(e == g for _, e, g in rows)
    (st.success if ok == len(rows) else st.error)(f"{ok}/{len(rows)} samples matched their expected decision")
    st.dataframe([{"file": f, "expected": e, "got": g, "match": "yes" if e == g else "NO"} for f, e, g in rows],
                 hide_index=True)

for rid in st.session_state.get("last_runs", [])[-1:]:
    run = repo.get_run(rid)
    if run:
        st.divider()
        st.subheader(f"Decision · {run['file_name']}")
        render_run(run, show_preview=False)
