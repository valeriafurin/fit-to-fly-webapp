from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from f2f.config import Settings

log = logging.getLogger(__name__)


class GenAIError(RuntimeError):
    pass


class GenAIClient:
    """OpenAI-compatible chat client for the Adyen GenAI Platform (LiteLLM)."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = settings.genai_platform_api_key
        self._base = settings.genai_base_url.rstrip("/")
        self._model = settings.genai_model
        self._timeout = settings.genai_timeout_seconds
        self._transport = transport

    @property
    def available(self) -> bool:
        return bool(self._key)

    async def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        if not self._key:
            raise GenAIError("GENAI_PLATFORM_API_KEY is not set")
        payload = {
            "model": self._model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(
                    f"{self._base}/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            log.warning("GenAI request failed: %s", type(exc).__name__)
            raise GenAIError("GenAI request failed") from exc
        if resp.status_code != 200:
            log.warning("GenAI returned HTTP %s", resp.status_code)
            raise GenAIError(f"GenAI returned HTTP {resp.status_code}")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise GenAIError("Unexpected GenAI response") from exc
        if not isinstance(content, str) or not content.strip():
            raise GenAIError("Empty GenAI response")
        return _strip_reasoning(content).strip()

    async def chat_json(self, system: str, user: str) -> dict[str, Any]:
        text = await self.chat(system + "\nRespond with a single JSON object and nothing else.", user)
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise GenAIError("GenAI response contained no JSON object")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise GenAIError("GenAI response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise GenAIError("GenAI JSON was not an object")
        return data


def _strip_reasoning(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S)
