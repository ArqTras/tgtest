from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestServer

from app.config import Settings
from app.conversation import MISSING_KEY, Conversation
from app.db import Database
from app.http_admin import build_app
from app.llm import completions_url, parse_facts
from app.sources import scan_directory
from app.textutil import chunk_text, fts_query, url_is_allowed


class ScriptedModel:
    def __init__(self) -> None:
        self.seen: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 700) -> str:
        self.seen.append(messages)
        system = messages[0]["content"]
        if "Extract durable facts" in system:
            return '{"facts":["Beacon keeps notes in the sources folder."]}'
        if "Beacon" not in system:
            raise AssertionError(system)
        return "Beacon keeps notes in the sources folder. I take that from the project sources."


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "kontekst.sqlite")
    await database.open()
    yield database
    await database.close()


def test_chunks_and_query() -> None:
    parts = chunk_text("First paragraph.\n\nSecond paragraph is longer.")
    assert parts == ["First paragraph.\n\nSecond paragraph is longer."]
    assert '"beacon"' in fts_query("Where is Beacon?")
    assert completions_url("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert completions_url("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"


def test_blocks_local_urls() -> None:
    ok, reason = url_is_allowed("http://127.0.0.1/secret", allow_private=False)
    assert not ok
    assert reason
    ok, _ = url_is_allowed("http://169.254.169.254/latest", allow_private=True)
    assert not ok
    ok, _ = url_is_allowed("file:///etc/passwd", allow_private=True)
    assert not ok


def test_parse_facts_from_fence() -> None:
    raw = '```json\n{"facts":["Standup is Tuesday morning.", "x"]}\n```'
    assert parse_facts(raw) == ["Standup is Tuesday morning."]


async def test_file_heading_becomes_the_source_title(db: Database, tmp_path: Path) -> None:
    folder = tmp_path / "sources"
    folder.mkdir()
    (folder / "opis.md").write_text("# Beacon rules\n\nMeetings are on Tuesdays.\n", encoding="utf-8")
    notes = await scan_directory(db, folder)
    assert notes == ["opis.md (added)"]
    rows = await db.list_sources()
    assert rows[0]["title"] == "Beacon rules"
    notes = await scan_directory(db, folder)
    assert notes == []


async def test_reply_uses_source_and_learns(db: Database) -> None:
    await db.upsert_source(
        "file:beacon.md",
        "Beacon",
        "Beacon keeps notes in the sources folder and replies in English.",
    )
    model = ScriptedModel()
    chat = Conversation(db, model, max_history=8, learn_every=1)
    answer = await chat.reply(7, "Where does Beacon keep notes?")
    assert "sources" in answer
    await chat.drain_learning()
    memories = await db.list_memories(7)
    assert memories == ["Beacon keeps notes in the sources folder."]
    again = await chat.remember(7, "Beacon keeps notes in the sources folder.")
    assert again is False


async def test_missing_key_still_stores_the_turn(db: Database) -> None:
    chat = Conversation(db, None, max_history=8, learn_every=1)
    answer = await chat.reply(3, "Please keep this thread.")
    assert answer == MISSING_KEY
    history = await db.recent_messages(3, 10)
    assert [item["role"] for item in history] == ["user", "assistant"]


async def test_status_page_and_admin_gate(db: Database, tmp_path: Path) -> None:
    settings = Settings(
        telegram_token="",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="",
        llm_model="deepseek-chat",
        admin_token="secret",
        data_dir=tmp_path,
        sources_dir=tmp_path / "sources",
        http_host="127.0.0.1",
        http_port=0,
        learn_every=1,
        max_history=8,
        allow_private_urls=False,
        llm_timeout=60.0,
    )
    app = build_app(settings, db, Conversation(db, None, max_history=8, learn_every=1))
    server = TestServer(app)
    await server.start_server()
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(server.make_url("/health")) as response:
                body = await response.json()
            assert body["ok"] is True
            assert body["llm"] is False
            async with session.get(server.make_url("/")) as response:
                page = await response.text()
            assert "Kontekst" in page
            async with session.post(server.make_url("/zrodla"), data={"token": "bad", "text": "x" * 40}) as response:
                assert response.status == 401
            async with session.post(
                server.make_url("/zrodla"),
                data={"token": "secret", "title": "Note", "text": "The project rules mention Tuesday code reviews."},
            ) as response:
                assert response.status == 200
        found = await db.search_sources("Tuesday code reviews")
        assert found and "rules" in found[0].lower()
    finally:
        await server.close()
