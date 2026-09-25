from __future__ import annotations

from pathlib import Path

import httpx

from app.db import Database
from app.textutil import html_to_text, url_is_allowed

_TEXT_SUFFIXES = {".md", ".txt", ".html", ".htm", ".markdown"}


def _title_from_file(path: Path, body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading[:160]
        if stripped:
            break
    return path.stem.replace("-", " ").replace("_", " ")
_MAX_BYTES = 1_000_000


async def fetch_url(url: str, allow_private: bool) -> tuple[str, str]:
    allowed, reason = url_is_allowed(url, allow_private)
    if not allowed:
        raise ValueError(reason)
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=False,
        headers={"User-Agent": "KontekstBot/1.0"},
    ) as client:
        response = await client.get(url)
    if response.status_code in {301, 302, 303, 307, 308}:
        raise ValueError("The source redirects. Paste the final URL without an intermediate link.")
    if response.status_code >= 400:
        raise ValueError(f"The source returned status {response.status_code}.")
    raw = response.content[:_MAX_BYTES]
    content_type = response.headers.get("content-type", "")
    text = raw.decode(response.encoding or "utf-8", errors="replace")
    if "html" in content_type or text.lstrip().lower().startswith("<!doctype html") or "<html" in text[:400].lower():
        text = html_to_text(text)
    title = url
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        title = lines[0][:120]
    body = text.strip()
    if len(body) < 40:
        raise ValueError("The source has too little text to index.")
    return title, body[:_MAX_BYTES]


async def index_text(db: Database, origin: str, title: str, body: str) -> str:
    if len(body.strip()) < 20:
        raise ValueError("The text is too short.")
    return await db.upsert_source(origin, title.strip()[:160] or origin, body.strip())


async def scan_directory(db: Database, folder: Path) -> list[str]:
    notes: list[str] = []
    if not folder.exists():
        return notes
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if path.name.startswith("."):
            continue
        body = path.read_text(encoding="utf-8", errors="replace").strip()
        if len(body) < 20:
            continue
        title = _title_from_file(path, body)
        state = await db.upsert_source(f"file:{path.name}", title, body)
        if state != "unchanged":
            notes.append(f"{path.name} ({state})")
    return notes
