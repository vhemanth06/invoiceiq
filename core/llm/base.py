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


class RateLimited(ProviderError):
    """Quota or rate limit hit. `until` = epoch seconds after which the provider may be tried again."""

    def __init__(self, msg: str, until: float):
        super().__init__(msg)
        self.until = until


_DELAY = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s|retrydelay['\"]?\s*:\s*['\"]([\d.]+)s", re.I)


def retry_after(msg: str) -> float | None:
    """Seconds the provider asks us to wait: 'Please retry in 1h59m15.5s' or "retryDelay': '38s'"."""
    m = _DELAY.search(msg)
    if not m:
        return None
    if m.group(4):
        return float(m.group(4))
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3))


def _fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s" if sec >= 60 \
        else f"{sec}s"


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


def with_backoff(fn, attempts: int = 3, max_wait: float = 60):
    """Retry short rate limits, waiting what the server asks (else 1s, 2s, 4s).

    A daily quota or a wait longer than `max_wait` raises RateLimited at once: retrying only burns
    time and quota, and the router then skips that provider until `until`.
    """
    for i in range(attempts + 1):
        try:
            return fn()
        except Exception as e:  # SDKs raise different 429 types; match status or message
            msg = str(e).lower()
            limited = 429 in (getattr(e, "status_code", None), getattr(e, "code", None)) or any(
                k in msg for k in ("429", "rate limit", "rate_limit", "resource_exhausted", "quota"))
            if not limited:
                raise
            wait = retry_after(str(e))
            daily = "per day" in msg or "perday" in msg
            if daily or (wait or 0) > max_wait or i == attempts:
                wait = wait or 60
                what = "daily free-tier quota used up" if daily else "rate limited"
                raise RateLimited(f"{what} (retry in {_fmt(wait)})", time.time() + wait) from e
            time.sleep(wait or 2 ** i)


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
        except RateLimited:
            raise  # a repair call would only hit the same limit
        except Exception as e:  # bad JSON from us or the SDK (e.g. Groq json_validate_failed): one repair try
            raw2 = with_backoff(lambda: self.complete(prompt, images, [raw or "(no valid JSON returned)",
                                                                         REPAIR_PROMPT.format(error=e)]))
            try:
                return ExtractedInvoice.model_validate(parse_json(raw2))
            except (ValidationError, ValueError) as e2:
                raise ProviderError(f"invalid JSON after repair: {e2}") from e2

    def text(self, prompt: str) -> str:
        return with_backoff(lambda: self.complete(prompt, [], []))
