"""Settings from .env and business rules from data/rules.yaml.

Rules are re-read on every run so Setup page edits apply without a restart.
API keys typed into the app override .env for that browser session only (never written to disk).
"""
from __future__ import annotations

import os
import threading
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SAMPLES_DIR = ROOT / "samples"
RULES_PATH = DATA_DIR / "rules.yaml"

load_dotenv(ROOT / ".env")


SESSION_KEYS = ("GROQ_API_KEY",)
_session = threading.local()  # Streamlit runs each browser session's script in its own thread


def set_session_keys(keys: dict[str, str]) -> None:
    """Keys entered in the app for the current session. Empty values fall back to .env."""
    _session.keys = {k: v.strip() for k, v in keys.items() if k in SESSION_KEYS and v and v.strip()}


def session_key_set(name: str) -> bool:
    return name in getattr(_session, "keys", {})


def env(name: str, default: str = "") -> str:
    if session_key_set(name):
        return _session.keys[name]
    return os.getenv(name, default).split("#")[0].strip()


def db_path() -> Path:
    return Path(env("INVOICEIQ_DB", str(DATA_DIR / "invoiceiq.db")))


def provider_order() -> list[str]:
    return [p.strip() for p in env("LLM_PROVIDER_ORDER", "groq").split(",") if p.strip()]


def flag(name: str, default: bool = True) -> bool:
    return env(name, str(default)).lower() in ("1", "true", "yes", "on")


def load_rules(path: Path | None = None) -> dict:
    return yaml.safe_load((path or RULES_PATH).read_text())


def save_rules(rules: dict, path: Path | None = None) -> None:
    (path or RULES_PATH).write_text(yaml.safe_dump(rules, sort_keys=False))


def reference_date(rules: dict) -> date:
    ref = (rules.get("dates") or {}).get("reference_date")
    if not ref:
        return date.today()
    return ref if isinstance(ref, date) else date.fromisoformat(str(ref))


def tolerance(rules: dict, po_total: float) -> float:
    """Amount tolerance = min(amount_pct of PO total, absolute cap)."""
    t = rules["tolerances"]
    return min(po_total * t["amount_pct"] / 100, t["amount_abs_cap"])
