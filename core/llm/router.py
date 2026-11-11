"""Provider fallback chain for extraction and explanations, with caching and an OCR fallback."""
from __future__ import annotations

import hashlib
import shutil
import time

from loguru import logger
from pydantic import ValidationError

from core import config
from core.llm import cache
from core.llm.base import Payload, ProviderError, RateLimited
from core.llm.groq_client import GroqProvider
from core.models import ExtractedInvoice, FieldSource

PROVIDERS = {"groq": GroqProvider}


class ExtractionFailed(Exception):
    def __init__(self, msg: str, attempts: list[str]):
        super().__init__(msg)
        self.attempts = attempts


_blocked: dict[str, tuple[float, str]] = {}  # provider -> (until epoch, reason), after a RateLimited


def _skip_blocked(name: str, attempts: list[str] | None = None) -> bool:
    until, why = _blocked.get(name, (0, ""))
    if time.time() >= until:
        return False
    if attempts is not None:
        attempts.append(f"{name}: skipped, {why}")
    return True


def _providers():
    return [PROVIDERS[p]() for p in config.provider_order() if p in PROVIDERS]


def _try_chain(payload: Payload, attempts: list[str], use_cache: bool) -> tuple[ExtractedInvoice, str] | None:
    for prov in _providers():
        if payload.route == "vision" and not prov.supports_vision:
            attempts.append(f"{prov.name}: skipped (no vision)")
            continue
        if not prov.available():
            attempts.append(f"{prov.name}: not configured")
            continue
        if _skip_blocked(prov.name, attempts):
            continue
        cacheable = use_cache
        if cacheable and (hit := cache.get(payload.file_hash + payload.route, prov.name, prov.model)):
            attempts.append(f"{prov.name}: cache hit")
            return ExtractedInvoice.model_validate(hit), f"{prov.name} (cached)"
        try:
            result = prov.extract(payload)
            if cacheable:
                cache.put(payload.file_hash + payload.route, prov.name, prov.model, result.model_dump(mode="json"))
            attempts.append(f"{prov.name}: ok")
            return result, prov.name
        except RateLimited as e:
            _blocked[prov.name] = (e.until, str(e))
            logger.warning(f"{prov.name}: {e}; falling back")
            attempts.append(f"{prov.name}: {e}")
            continue
        except (ProviderError, ValidationError, Exception) as e:
            logger.warning(f"{prov.name} failed: {e}; falling back")
            attempts.append(f"{prov.name}: failed ({str(e)[:120]})")
    return None


def ocr_text(images: list[bytes]) -> str | None:
    """Tesseract OCR of rendered pages, if the binary is installed."""
    if not shutil.which("tesseract"):
        return None
    import io

    import pytesseract
    from PIL import Image

    return "\n".join(pytesseract.image_to_string(Image.open(io.BytesIO(b))) for b in images)


def extract(payload: Payload, use_cache: bool | None = None) -> tuple[ExtractedInvoice, str, list[str]]:
    use_cache = config.flag("USE_LLM_CACHE") if use_cache is None else use_cache
    attempts: list[str] = []
    if res := _try_chain(payload, attempts, use_cache):
        return res[0], res[1], attempts
    if payload.route == "vision":  # last resort: OCR the page images, then a text model
        text = ocr_text(payload.images)
        if text and text.strip():
            attempts.append("tesseract: ok")
            ocr_payload = Payload(payload.file_hash, "text", text=text)
            if res := _try_chain(ocr_payload, attempts, use_cache):
                inv = res[0]
                for name, val in inv:
                    if hasattr(val, "source") and val.source.value != "missing":
                        val.source = FieldSource.OCR
                return inv, f"tesseract+{res[1]}", attempts
        else:
            attempts.append("tesseract: not installed or no text")
    raise ExtractionFailed("manual entry needed: no provider could extract this document", attempts)


def explain(prompt: str) -> tuple[str, str] | None:
    """Free-text completion for explanations. Returns (text, model used) or None if nobody can."""
    key = hashlib.sha256(prompt.encode()).hexdigest()  # same findings -> same note; reruns cost no quota
    for prov in _providers():
        if not prov.available() or _skip_blocked(prov.name):
            continue
        if hit := cache.get(key, prov.name, prov.model):
            return hit["text"], prov.model or prov.name
        try:
            text = prov.text(prompt)
            cache.put(key, prov.name, prov.model, {"text": text})
            return text, prov.model or prov.name  # e.g. "openai/gpt-oss-120b", not "groq"
        except RateLimited as e:
            _blocked[prov.name] = (e.until, str(e))
            logger.warning(f"{prov.name} explanation skipped: {e}")
        except Exception as e:
            logger.warning(f"{prov.name} explanation failed: {e}")
    return None
