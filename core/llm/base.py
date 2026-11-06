"""Provider interface and shared helpers."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from core.llm.prompts import EXTRACTION_PROMPT, REPAIR_PROMPT
from core.models import ExtractedInvoice


class ProviderError(Exception):
    """Provider unavailable, misconfigured, rate-limited past retries, or returned garbage."""


@dataclass
class Payload:
    file_hash: str
    route: str                      # text | vision
    text: str = ""
    images: list[bytes] = field(default_factory=list)  # PNG pages


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ProviderError(f"no JSON object in response: {raw[:200]}")
    return json.loads(m.group(0))


def with_backoff(fn, attempts: int = 3):
    """Retry on rate limits with 1s, 2s, 4s backoff; then give up so the router can fall back."""
    for i in range(attempts + 1):
        try:
            return fn()
        except Exception as e:  # SDKs raise different 429 types; match status or message
            msg = str(e).lower()
            limited = getattr(e, "status_code", None) == 429 or any(
                k in msg for k in ("429", "rate limit", "rate_limit", "resource_exhausted", "quota"))
            if i < attempts and limited:
                time.sleep(2 ** i)
                continue
            raise


class Provider:
    name = "base"
    supports_vision = False
    model = ""

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, images: list[bytes], history: list[str]) -> str:
        raise NotImplementedError

    def extract(self, payload: Payload) -> ExtractedInvoice:
        """Ask for schema-shaped JSON; on validation failure retry once with the error fed back."""
        prompt = EXTRACTION_PROMPT + ("\n\nINVOICE TEXT:\n" + payload.text if payload.route == "text" else "")
        images = payload.images if payload.route == "vision" else []
        raw = ""
        try:
            raw = with_backoff(lambda: self.complete(prompt, images, []))
            return ExtractedInvoice.model_validate(parse_json(raw))
        except Exception as e:  # bad JSON from us or the SDK (e.g. Groq json_validate_failed): one repair try
            raw2 = with_backoff(lambda: self.complete(prompt, images, [raw or "(no valid JSON returned)",
                                                                         REPAIR_PROMPT.format(error=e)]))
            try:
                return ExtractedInvoice.model_validate(parse_json(raw2))
            except (ValidationError, ValueError) as e2:
                raise ProviderError(f"invalid JSON after repair: {e2}") from e2

    def text(self, prompt: str) -> str:
        return with_backoff(lambda: self.complete(prompt, [], []))
