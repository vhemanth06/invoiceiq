"""Sidebar controls shared by pages: API keys, provider order, cache, LLM explanations."""
import os

import streamlit as st

from core import config
from core.llm.router import PROVIDERS

KEY_FIELDS = {"GROQ_API_KEY": "Groq API key", "GEMINI_API_KEY": "Gemini API key"}


def _keep(name: str) -> None:
    st.session_state["api_keys"][name] = st.session_state[f"_in_{name}"]


def api_keys() -> None:
    """Optional keys typed in the app. Kept in this browser session only; .env is never changed."""
    store = st.session_state.setdefault("api_keys", {})
    for name in KEY_FIELDS:  # widget state is dropped on page switch; restore it from the session store
        st.session_state[f"_in_{name}"] = store.get(name, "")
    config.set_session_keys(store)
    with st.expander("API keys", expanded=not any(PROVIDERS[n]().available() for n in PROVIDERS)):
        for name, label in KEY_FIELDS.items():
            in_env = bool(os.getenv(name, "").split("#")[0].strip() not in ("", "your_key_here"))
            st.text_input(label, type="password", key=f"_in_{name}", on_change=_keep, args=(name,),
                          placeholder="using key from .env" if in_env else "paste key",
                          help="Used for this browser session only. Not saved to .env or shared with other users.")
        if any(store.values()) and st.button("Clear keys"):
            st.session_state["api_keys"] = {}
            st.rerun()
    config.set_session_keys(st.session_state["api_keys"])


def controls() -> None:
    with st.sidebar:
        st.subheader("LLM settings")
        api_keys()
        avail = {n: PROVIDERS[n]().available() for n in PROVIDERS}

        def label(n: str) -> str:
            if not avail[n]:
                return f"{n} (not set)"
            return f"{n} (ready · app key)" if config.session_key_set(f"{n.upper()}_API_KEY") else f"{n} (ready)"

        order = st.multiselect("Provider order", list(PROVIDERS), default=config.provider_order(),
                               format_func=label, help="not set = no API key in .env or in the API keys box")
        os.environ["LLM_PROVIDER_ORDER"] = ",".join(order)
        os.environ["USE_LLM_CACHE"] = str(st.toggle("Use LLM cache", value=config.flag("USE_LLM_CACHE"),
                                                     help="Replay cached extractions; turn off to force a live call"))
        os.environ["USE_LLM_EXPLANATIONS"] = str(st.toggle("LLM-written explanations",
                                                           value=config.flag("USE_LLM_EXPLANATIONS"),
                                                           help="Off = deterministic template explanations"))
        if not any(avail.values()):
            st.caption("No LLM configured: paste a Groq or Gemini key above, or add one to .env.")
