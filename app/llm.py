from __future__ import annotations

import json
from typing import Protocol

import httpx


class ChatModel(Protocol):
    async def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str: ...


def completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


class OpenAICompatible(ChatModel):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 300) -> None:
        self.url = completions_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = httpx.Timeout(timeout, connect=15.0)

    async def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Model timed out after {self.timeout.read}s. Local qwen3:14b on CPU can take a few minutes — retry, or set LLM_TIMEOUT=600."
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not reach the model at {self.url}: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:240]
            raise RuntimeError(f"Model returned {response.status_code}: {detail}")
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Model response has an unexpected shape.") from exc


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
