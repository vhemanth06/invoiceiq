"""Settings from .env and business rules from data/rules.yaml.

Rules are re-read on every run so Master Data edits apply without a restart.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SAMPLES_DIR = ROOT / "samples"
RULES_PATH = DATA_DIR / "rules.yaml"

load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).split("#")[0].strip()


def db_path() -> Path:
    return Path(env("INVOICEIQ_DB", str(DATA_DIR / "invoiceiq.db")))


def provider_order() -> list[str]:
    return [p.strip() for p in env("LLM_PROVIDER_ORDER", "groq,gemini").split(",") if p.strip()]


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
