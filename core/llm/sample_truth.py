"""Offline provider for the bundled synthetic samples only.

Returns the generator's ground-truth extraction for a PDF whose SHA-256 is in
samples/truth/index.json. It cannot read any other document. It exists so the demo and
the golden tests run with no API keys; the UI labels it clearly as "sample ground truth".
"""
from __future__ import annotations

import json

from core import config
from core.llm.base import Payload, Provider, ProviderError
from core.models import ExtractedInvoice

TRUTH_DIR = config.SAMPLES_DIR / "truth"


class SampleTruthProvider(Provider):
    name = "sample_truth"
    supports_vision = True
    model = "ground-truth"

    def available(self) -> bool:
        return (TRUTH_DIR / "index.json").exists()

    def extract(self, payload: Payload) -> ExtractedInvoice:
        index = json.loads((TRUTH_DIR / "index.json").read_text()) if self.available() else {}
        name = index.get(payload.file_hash)
        if not name:
            raise ProviderError("not a bundled sample (sample_truth only knows the generated samples)")
        return ExtractedInvoice.model_validate_json((TRUTH_DIR / name).read_text())

    def text(self, prompt: str) -> str:
        raise ProviderError("sample_truth cannot write explanations")
