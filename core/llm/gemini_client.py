"""Google Gemini (free tier via AI Studio). Text and vision."""
from __future__ import annotations

from core import config
from core.llm.base import Provider, ProviderError


class GeminiProvider(Provider):
    name = "gemini"
    supports_vision = True

    def __init__(self):
        self.key = config.env("GEMINI_API_KEY")
        self.model = config.env("GEMINI_MODEL", "gemini-flash-latest")
        self._client = None

    def available(self) -> bool:
        return bool(self.key) and self.key != "your_key_here"

    def complete(self, prompt, images, history):
        if not self.available():
            raise ProviderError("GEMINI_API_KEY not set")
        from google import genai
        from google.genai import types

        self._client = self._client or genai.Client(api_key=self.key)
        parts = [prompt] + [types.Part.from_bytes(data=img, mime_type="image/png") for img in images] + history
        resp = self._client.models.generate_content(
            model=self.model, contents=parts,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        return resp.text or ""
