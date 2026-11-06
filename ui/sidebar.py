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
                               help="not set = no API key in .env")
        os.environ["LLM_PROVIDER_ORDER"] = ",".join(order)
        os.environ["USE_LLM_CACHE"] = str(st.toggle("Use LLM cache", value=config.flag("USE_LLM_CACHE"),
                                                     help="Replay cached extractions; turn off to force a live call"))
        os.environ["USE_LLM_EXPLANATIONS"] = str(st.toggle("LLM-written explanations",
                                                           value=config.flag("USE_LLM_EXPLANATIONS"),
                                                           help="Off = deterministic template explanations"))
        if not any(avail.values()):
            st.caption("No LLM configured: add GROQ_API_KEY and/or GEMINI_API_KEY to .env.")
