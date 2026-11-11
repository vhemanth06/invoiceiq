"""Colours and CSS. Green = approve/pass, amber = review/warn, red = reject/block, slate = neutral."""
import streamlit as st

COLORS = {"APPROVE": "#16a34a", "REVIEW": "#d97706", "REJECT": "#dc2626", "neutral": "#64748b",
          "ok": "#16a34a", "warn": "#d97706", "fail": "#dc2626", "error": "#dc2626", "running": "#2563eb",
          "skipped": "#94a3b8", "pending": "#94a3b8", "info": "#2563eb", "block": "#dc2626"}

CSS = """
<style>
.block-container {padding-top: 2rem;}
.iq-card {border-left: 5px solid var(--c); border-radius: 8px; padding: .45rem .8rem; margin-bottom: .4rem;
          background: color-mix(in srgb, var(--c) 9%, transparent);}
.iq-card .h {display:flex; justify-content:space-between; font-weight:600;}
.iq-card .dot {display:inline-block; width:.6rem; height:.6rem; border-radius:50%; background:var(--c);
               margin-right:.5rem;}
.iq-card .d {font-size: .78rem; opacity:.7; font-weight:400;}
.iq-card .s {font-size: .85rem; opacity:.9; margin-top:.15rem; overflow-wrap:anywhere;}
.iq-banner {border-radius: 10px; padding: 1rem 1.2rem; margin: .5rem 0 1rem;
            background: color-mix(in srgb, var(--c) 14%, transparent); border: 2px solid var(--c);}
.iq-banner .o {font-size: 1.5rem; font-weight: 800; color: var(--c);}
.iq-banner .hl {font-size: 1.1rem; font-weight: 600; margin:.2rem 0 .4rem;}
.iq-pill b {color: var(--c); margin-right:.25rem; font-weight:700;}
.iq-pill {display:inline-block; padding:.15rem .6rem; margin:.15rem; border-radius:999px; font-size:.82rem;
          border:1px solid var(--c); background: color-mix(in srgb, var(--c) 12%, transparent);}
.iq-badge {padding:.1rem .5rem; border-radius:6px; color:white; background:var(--c); font-weight:700; font-size:.8rem;}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
