from __future__ import annotations

from html import escape

from aiohttp import web

from app.config import Settings
from app.conversation import Conversation
from app.db import Database
from app.sources import fetch_url, index_text, scan_directory
from app.textutil import content_hash

SETTINGS: web.AppKey[Settings] = web.AppKey("settings", Settings)
DATABASE: web.AppKey[Database] = web.AppKey("db", Database)
CONVERSATION: web.AppKey[Conversation] = web.AppKey("conversation", Conversation)
USERNAME: web.AppKey[str] = web.AppKey("telegram_username", str)


def build_app(
    settings: Settings,
    db: Database,
    conversation: Conversation,
    telegram_username: str = "",
) -> web.Application:
    app = web.Application()
    app[SETTINGS] = settings
    app[DATABASE] = db
    app[CONVERSATION] = conversation
    app[USERNAME] = telegram_username
    app.router.add_get("/health", health)
    app.router.add_get("/", dashboard)
    app.router.add_post("/zrodla", add_source)
    return app


async def health(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS]
    db = request.app[DATABASE]
    return web.json_response(
        {
            "ok": True,
            "service": "kontekst",
            "telegram": settings.telegram_ready,
            "telegram_username": request.app[USERNAME],
            "llm": settings.llm_ready,
            "model": settings.llm_model if settings.llm_ready else "",
            "sources": await db.source_count(),
            "memories": await db.memory_count(),
            "messages": await db.message_count(),
        }
    )


async def dashboard(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS]
    db = request.app[DATABASE]
    sources = await db.list_sources()
    rows = "".join(
        "<li><strong>{title}</strong><br><span>{origin}</span></li>".format(
            title=escape(item["title"]),
            origin=escape(item["origin"]),
        )
        for item in sources
    ) or "<li>No sources yet. Drop a .md file into the sources folder or paste a URL below.</li>"
    telegram = "connected" if settings.telegram_ready else "missing token"
    llm = f"ready ({escape(settings.llm_model)})" if settings.llm_ready else "missing API key"
    username = escape(request.app[USERNAME] or "—")
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kontekst</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; font-family: "Iowan Old Style", Palatino, Georgia, serif; background: #f3efe6; color: #1d1a16; }}
    main {{ max-width: 42rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }}
    h1 {{ font-weight: 500; font-size: 2.4rem; margin-bottom: 0.25rem; }}
    p.lead {{ font-family: "Avenir Next", "Segoe UI", sans-serif; line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin: 1.5rem 0; }}
    .card {{ background: #fffdf8; border: 1px solid #e2d8c8; border-radius: 12px; padding: 0.9rem 1rem; }}
    .card span {{ display: block; font-family: "Avenir Next", "Segoe UI", sans-serif; font-size: 0.78rem; letter-spacing: 0.04em; text-transform: uppercase; color: #6d6458; }}
    .card strong {{ font-size: 1.15rem; font-weight: 560; }}
    form {{ display: grid; gap: 0.6rem; background: #fffdf8; border: 1px solid #e2d8c8; border-radius: 12px; padding: 1rem; }}
    label {{ font-family: "Avenir Next", "Segoe UI", sans-serif; font-size: 0.92rem; }}
    input, textarea {{ font: inherit; padding: 0.55rem 0.65rem; border-radius: 8px; border: 1px solid #d5cbbd; background: #fff; }}
    button {{ font-family: "Avenir Next", "Segoe UI", sans-serif; background: #0f6e56; color: white; border: 0; border-radius: 8px; padding: 0.7rem 1rem; cursor: pointer; }}
    ul {{ padding-left: 1.1rem; }}
    li {{ margin: 0.55rem 0; }}
    li span {{ color: #6d6458; font-size: 0.92rem; }}
    .note {{ font-family: "Avenir Next", "Segoe UI", sans-serif; color: #6d6458; }}
    @media (max-width: 640px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Kontekst</h1>
    <p class="lead">This Telegram bot keeps chat history, memory, and project sources on this machine. Replies come from a cloud or local model, so a GPU is optional.</p>
    <div class="grid">
      <div class="card"><span>Telegram</span><strong>{telegram}</strong></div>
      <div class="card"><span>Bot</span><strong>@{username}</strong></div>
      <div class="card"><span>Model</span><strong>{llm}</strong></div>
      <div class="card"><span>Memory</span><strong>{await db.memory_count()} facts</strong></div>
    </div>
    <h2>Project sources</h2>
    <ul>{rows}</ul>
    <form method="post" action="/zrodla">
      <label>Admin password<br><input name="token" type="password" autocomplete="current-password" required></label>
      <label>Source URL<br><input name="url" type="url" placeholder="https://example.com/docs"></label>
      <label>or paste text<br><textarea name="text" rows="5" placeholder="Paste a project notes snippet"></textarea></label>
      <label>Note title<br><input name="title" type="text" placeholder="Note"></label>
      <button type="submit">Add to project memory</button>
    </form>
    <p class="note">.md and .txt files in the sources folder are indexed automatically. Chats happen in Telegram, not on this page.</p>
  </main>
</body>
</html>"""
    return web.Response(text=page, content_type="text/html")


async def add_source(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS]
    db = request.app[DATABASE]
    data = await request.post()
    token = str(data.get("token", ""))
    if not settings.admin_token or token != settings.admin_token:
        return web.Response(status=401, text="Wrong admin password, or ADMIN_TOKEN is not set.")
    url = str(data.get("url", "")).strip()
    text = str(data.get("text", "")).strip()
    title = str(data.get("title", "")).strip() or "Note"
    try:
        if url:
            fetched_title, body = await fetch_url(url, settings.allow_private_urls)
            state = await index_text(db, f"url:{url}", fetched_title, body)
            message = f"URL saved ({state})."
        elif text:
            state = await index_text(db, f"note:{content_hash(text)}", title, text)
            message = f"Text saved ({state})."
        else:
            message = "Provide a URL or some text."
    except ValueError as exc:
        return web.Response(status=400, text=str(exc))
    return web.Response(text=message + " Return to the status page.", content_type="text/plain")


async def refresh_files(settings: Settings, db: Database) -> list[str]:
    return await scan_directory(db, settings.sources_dir)
