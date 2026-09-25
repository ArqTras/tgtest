from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    admin_token: str
    data_dir: Path
    sources_dir: Path
    http_host: str
    http_port: int
    learn_every: int
    max_history: int
    allow_private_urls: bool
    llm_timeout: float

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_token.strip())

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kontekst.sqlite"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR", "data")).resolve()
    sources_dir = Path(os.environ.get("SOURCES_DIR", "sources")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("HTTP_PORT", "8787"))
    learn_every = max(1, int(os.environ.get("LEARN_EVERY", "1")))
    max_history = max(4, int(os.environ.get("MAX_HISTORY", "16")))
    base_url = os.environ.get("LLM_BASE_URL", "http://ollama:11434/v1").strip()
    # Local CPU models often need several minutes for the first answer.
    default_timeout = 300.0 if "ollama" in base_url.lower() else 90.0
    llm_timeout = float(os.environ.get("LLM_TIMEOUT", str(default_timeout)))
    return Settings(
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        llm_base_url=base_url,
        llm_api_key=os.environ.get("LLM_API_KEY", "ollama").strip(),
        llm_model=os.environ.get("LLM_MODEL", "qwen3-14b-bot").strip(),
        admin_token=os.environ.get("ADMIN_TOKEN", "").strip(),
        data_dir=data_dir,
        sources_dir=sources_dir,
        http_host=os.environ.get("HTTP_HOST", "0.0.0.0").strip() or "0.0.0.0",
        http_port=port,
        learn_every=learn_every,
        max_history=max_history,
        allow_private_urls=_flag("ALLOW_PRIVATE_URLS", False),
        llm_timeout=max(30.0, llm_timeout),
    )
