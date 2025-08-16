import os
import time
from typing import Optional
from .util import eprint


class GeminiClient:
    def __init__(self, model: str, temperature: float = 0.0, timeout_s: int = 120):
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s
        self._client = None
        self._ready = False
        self._err: Optional[str] = None
        self._init()

    def _init(self):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            self._err = "Missing GOOGLE_API_KEY for Gemini API"
            return
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=api_key)
            self._client = genai.GenerativeModel(self.model)
            self._ready = True
        except Exception as e:
            self._err = f"Gemini init failed: {e}"

    def ready(self) -> bool:
        return self._ready and self._client is not None

    def error(self) -> Optional[str]:
        return self._err

    def generate(self, system: str, user: str) -> str:
        if not self.ready():
            raise RuntimeError(self._err or "Gemini not ready")
        # google-generativeai supports system via contents with role, but expose simply
        try:
            resp = self._client.generate_content([
                {"role": "system", "parts": [{"text": system}]},
                {"role": "user", "parts": [{"text": user}]},
            ], generation_config={
                "temperature": self.temperature,
                "top_p": 1,
                "top_k": 1,
            })
            # Respect timeout by polling? The SDK handles internally; coarse enforcement
            # Extract text
            if hasattr(resp, "text") and resp.text:
                return resp.text
            # Fallback: join candidates
            try:
                return "\n".join([c.text for c in resp.candidates if getattr(c, "text", None)])
            except Exception:
                return ""
        except Exception as e:
            eprint(f"LLM error: {e}")
            return ""

