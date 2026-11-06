"""Sidebar controls shared by pages: provider order, cache, LLM explanations."""
import os

import streamlit as st

from core import config
from core.llm.router import PROVIDERS


def controls() -> None:
    with st.sidebar:
        st.subheader("LLM settings")
        avail = {n: PROVIDERS[n]().available() for n in PROVIDERS}
        order = st.multiselect("Provider order", list(PROVIDERS), default=config.provider_order(),
                               format_func=lambda n: f"{n} ({'ready' if avail[n] else 'not set'})",
                               help="not set = not configured (no API key / server). sample_truth only reads the bundled samples.")
        os.environ["LLM_PROVIDER_ORDER"] = ",".join(order)
        os.environ["USE_LLM_CACHE"] = str(st.toggle("Use LLM cache", value=config.flag("USE_LLM_CACHE"),
                                                     help="Replay cached extractions; turn off to force a live call"))
        os.environ["USE_LLM_EXPLANATIONS"] = str(st.toggle("LLM-written explanations",
                                                           value=config.flag("USE_LLM_EXPLANATIONS"),
                                                           help="Off = deterministic template explanations"))
        if not any(avail[n] for n in ("gemini", "groq", "ollama")):
            st.caption("No live LLM configured: add GEMINI_API_KEY / GROQ_API_KEY to .env. "
                       "Bundled samples still run via sample_truth.")
