from __future__ import annotations

import json
from typing import Protocol
from urllib.parse import urlparse

import httpx


class ChatModel(Protocol):
    async def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 400) -> str: ...


def completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def ollama_chat_url(base_url: str) -> str | None:
    """Return native Ollama /api/chat URL when the configured base looks like Ollama."""
    raw = base_url.strip().rstrip("/")
    lower = raw.lower()
    if "ollama" not in lower and ":11434" not in lower:
        return None
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/api/chat"


def _strip_think_blocks(text: str) -> str:
    out = text
    while True:
        start = out.find("<think>")
        if start < 0:
            break
        end = out.find("</think>", start)
        if end < 0:
            out = out[:start].strip()
            break
        out = (out[:start] + out[end + len("</think>") :]).strip()
    return out


class OpenAICompatible(ChatModel):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 900,
        *,
        disable_thinking: bool | None = None,
    ) -> None:
        self.openai_url = completions_url(base_url)
        self.ollama_url = ollama_chat_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = httpx.Timeout(timeout, connect=20.0)
        if disable_thinking is None:
            disable_thinking = self.ollama_url is not None
        self.disable_thinking = disable_thinking

    async def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 400) -> str:
        if self.ollama_url is not None:
            return await self._complete_ollama(messages, max_tokens=max_tokens)
        return await self._complete_openai(messages, max_tokens=max_tokens)

    async def _complete_openai(self, messages: list[dict[str, str]], *, max_tokens: int) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
        if self.disable_thinking:
            # Harmless on non-thinking providers; Ollama OpenAI-compat may honor it.
            payload["think"] = False
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = await self._post(self.openai_url, headers=headers, payload=payload)
        try:
            content = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Model response has an unexpected shape.") from exc
        return _strip_think_blocks(content)

    async def _complete_ollama(self, messages: list[dict[str, str]], *, max_tokens: int) -> str:
        assert self.ollama_url is not None
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.4,
                "num_predict": max_tokens,
            },
        }
        data = await self._post(self.ollama_url, headers={"Content-Type": "application/json"}, payload=payload)
        message = data.get("message") if isinstance(data, dict) else None
        if not isinstance(message, dict):
            raise RuntimeError("Model response has an unexpected shape.")
        content = str(message.get("content") or "").strip()
        return _strip_think_blocks(content)

    async def _post(self, url: str, *, headers: dict[str, str], payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Model timed out after {self.timeout.read}s. "
                "Local qwen3:14b on CPU can take several minutes on the first answer — "
                "retry, or raise LLM_TIMEOUT (e.g. 1200)."
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not reach the model at {url}: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:240]
            raise RuntimeError(f"Model returned {response.status_code}: {detail}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Model returned non-JSON.") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Model response has an unexpected shape.")
        return data


def parse_facts(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    facts = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list):
        return []
    cleaned: list[str] = []
    for item in facts[:3]:
        if not isinstance(item, str):
            continue
        fact = " ".join(item.split())
        if 8 <= len(fact) <= 400:
            cleaned.append(fact)
    return cleaned
