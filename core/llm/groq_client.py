"""Groq free tier (OpenAI-compatible). Text model for text PDFs, vision model for scanned pages."""
from __future__ import annotations

import base64

from core import config
from core.llm.base import Provider, ProviderError


class GroqProvider(Provider):
    name = "groq"

    def __init__(self):
        self.key = config.env("GROQ_API_KEY")
        self.text_model = config.env("GROQ_MODEL", "openai/gpt-oss-120b")
        self.vision_model = config.env("GROQ_VISION_MODEL")
        self.supports_vision = bool(self.vision_model)
        self.model = self.text_model  # cache key; vision payloads are keyed separately by route
        self._client = None

    def available(self) -> bool:
        return bool(self.key) and self.key != "your_key_here"

    def complete(self, prompt, images, history):
        if not self.available():
            raise ProviderError("GROQ_API_KEY not set")
        from groq import Groq

        self._client = self._client or Groq(api_key=self.key)
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode()}}
            for i in images[:5]]  # Groq accepts at most 5 images per request
        msgs = [{"role": "user", "content": content if images else prompt}]
        for i, h in enumerate(history):
            msgs.append({"role": "assistant" if i % 2 == 0 else "user", "content": h})
        resp = self._client.chat.completions.create(
            model=self.vision_model if images else self.text_model, messages=msgs, temperature=0,
            response_format={"type": "json_object"})
        return resp.choices[0].message.content or ""
