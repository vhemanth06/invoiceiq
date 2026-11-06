"""Local Ollama (optional, offline). Vision if the configured model supports it."""
from __future__ import annotations

import base64
import json
import urllib.request

from core import config
from core.llm.base import Provider, ProviderError


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self):
        self.model = config.env("OLLAMA_MODEL", "llama3.2-vision")
        self.url = config.env("OLLAMA_URL", "http://localhost:11434")
        self.supports_vision = "vision" in self.model or "llava" in self.model

    def available(self) -> bool:
        try:
            urllib.request.urlopen(self.url + "/api/tags", timeout=1)
            return True
        except Exception:
            return False

    def complete(self, prompt, images, history):
        msgs = [{"role": "user", "content": prompt, "images": [base64.b64encode(i).decode() for i in images]}]
        for i, h in enumerate(history):
            msgs.append({"role": "assistant" if i % 2 == 0 else "user", "content": h})
        body = json.dumps({"model": self.model, "messages": msgs, "stream": False, "format": "json",
                           "options": {"temperature": 0}}).encode()
        req = urllib.request.Request(self.url + "/api/chat", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())["message"]["content"]
        except Exception as e:
            raise ProviderError(f"ollama: {e}") from e
