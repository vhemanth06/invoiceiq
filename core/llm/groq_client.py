"""Groq free tier (OpenAI-compatible). Text only."""
from __future__ import annotations

from core import config
from core.llm.base import Provider, ProviderError


class GroqProvider(Provider):
    name = "groq"
    supports_vision = False

    def __init__(self):
        self.key = config.env("GROQ_API_KEY")
        self.model = config.env("GROQ_MODEL", "openai/gpt-oss-120b")
        self._client = None

    def available(self) -> bool:
        return bool(self.key) and self.key != "your_key_here"

    def complete(self, prompt, images, history):
        if not self.available():
            raise ProviderError("GROQ_API_KEY not set")
        from groq import Groq

        self._client = self._client or Groq(api_key=self.key)
        msgs = [{"role": "user", "content": prompt}]
        for i, h in enumerate(history):
            msgs.append({"role": "assistant" if i % 2 == 0 else "user", "content": h})
        resp = self._client.chat.completions.create(model=self.model, messages=msgs, temperature=0,
                                                    response_format={"type": "json_object"})
        return resp.choices[0].message.content or ""
