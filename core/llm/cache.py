"""Disk cache for LLM extractions: sha256(file hash + prompt version + model) -> JSON.

Lets the demo replay real extractions when Wi-Fi or free-tier quota fails.
"""
from __future__ import annotations

import hashlib
import json

from core import config
from core.llm.prompts import PROMPT_VERSION

CACHE_DIR = config.DATA_DIR / "llm_cache"


def _key(file_hash: str, provider: str, model: str) -> str:
    return hashlib.sha256(f"{file_hash}|{PROMPT_VERSION}|{provider}|{model}".encode()).hexdigest()


def get(file_hash: str, provider: str, model: str) -> dict | None:
    p = CACHE_DIR / f"{_key(file_hash, provider, model)}.json"
    return json.loads(p.read_text()) if p.exists() else None


def put(file_hash: str, provider: str, model: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{_key(file_hash, provider, model)}.json").write_text(json.dumps(data))
