from __future__ import annotations

from pathlib import Path

import aiosqlite

from app.textutil import chunk_text, content_hash, fts_query, normalize_fact

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    fact TEXT NOT NULL,
    fact_norm TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(chat_id, fact_norm)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    body,
    source_id UNINDEXED,
    tokenize = 'unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    fact,
    memory_id UNINDEXED,
    chat_id UNINDEXED,
    tokenize = 'unicode61'
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Baza nie jest otwarta.")
        return self._conn

    async def add_message(self, chat_id: int, role: str, content: str) -> None:
        await self.conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )
        await self.conn.commit()

    async def recent_messages(self, chat_id: int, limit: int) -> list[dict[str, str]]:
        cursor = await self.conn.execute(
            """
            SELECT role, content FROM (
                SELECT id, role, content FROM messages
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    async def message_count(self, chat_id: int | None = None) -> int:
        if chat_id is None:
            cursor = await self.conn.execute("SELECT COUNT(*) AS n FROM messages")
        else:
            cursor = await self.conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE chat_id = ?",
                (chat_id,),
            )
        row = await cursor.fetchone()
        return int(row["n"])

    async def add_memory(self, chat_id: int, fact: str) -> bool:
        cleaned = " ".join(fact.split())
        if len(cleaned) < 8:
            return False
        norm = normalize_fact(cleaned)
        cursor = await self.conn.execute(
            "INSERT OR IGNORE INTO memories (chat_id, fact, fact_norm) VALUES (?, ?, ?)",
            (chat_id, cleaned, norm),
        )
        await self.conn.commit()
        if cursor.rowcount == 0:
            return False
        memory_id = cursor.lastrowid
        await self.conn.execute(
            "INSERT INTO memories_fts (fact, memory_id, chat_id) VALUES (?, ?, ?)",
            (cleaned, memory_id, chat_id),
        )
        await self.conn.commit()
        return True

    async def list_memories(self, chat_id: int, limit: int = 30) -> list[str]:
        cursor = await self.conn.execute(
            "SELECT fact FROM memories WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [row["fact"] for row in rows]

    async def search_memories(self, chat_id: int, query: str, limit: int = 6) -> list[str]:
        match = fts_query(query)
        if not match:
            return await self.list_memories(chat_id, limit)
        cursor = await self.conn.execute(
            """
            SELECT m.fact FROM memories_fts
            JOIN memories m ON m.id = memories_fts.memory_id
            WHERE memories_fts MATCH ? AND m.chat_id = ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, chat_id, limit),
        )
        rows = await cursor.fetchall()
        found = [row["fact"] for row in rows]
        if found:
            return found
        return await self.list_memories(chat_id, min(limit, 4))

    async def memory_count(self) -> int:
        cursor = await self.conn.execute("SELECT COUNT(*) AS n FROM memories")
        row = await cursor.fetchone()
        return int(row["n"])

    async def clear_chat(self, chat_id: int) -> None:
        await self.conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cursor = await self.conn.execute(
            "SELECT id FROM memories WHERE chat_id = ?",
            (chat_id,),
        )
        ids = [row["id"] for row in await cursor.fetchall()]
        await self.conn.execute("DELETE FROM memories WHERE chat_id = ?", (chat_id,))
        for memory_id in ids:
            await self.conn.execute(
                "DELETE FROM memories_fts WHERE memory_id = ?",
                (memory_id,),
            )
        await self.conn.commit()

    async def upsert_source(self, origin: str, title: str, body: str) -> str:
        digest = content_hash(body)
        cursor = await self.conn.execute(
            "SELECT id, content_hash, title FROM sources WHERE origin = ?",
            (origin,),
        )
        existing = await cursor.fetchone()
        if existing and existing["content_hash"] == digest:
            if existing["title"] != title:
                await self.conn.execute(
                    "UPDATE sources SET title = ? WHERE id = ?",
                    (title, int(existing["id"])),
                )
                await self.conn.commit()
                return "updated"
            return "unchanged"
        if existing:
            source_id = int(existing["id"])
            await self.conn.execute(
                """
                UPDATE sources
                SET title = ?, body = ?, content_hash = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (title, body, digest, source_id),
            )
            await self.conn.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source_id,))
            state = "updated"
        else:
            cursor = await self.conn.execute(
                "INSERT INTO sources (origin, title, body, content_hash) VALUES (?, ?, ?, ?)",
                (origin, title, body, digest),
            )
            source_id = int(cursor.lastrowid)
            state = "added"
        for piece in chunk_text(body):
            await self.conn.execute(
                "INSERT INTO chunks_fts (body, source_id) VALUES (?, ?)",
                (piece, source_id),
            )
        await self.conn.commit()
        return state

    async def list_sources(self) -> list[dict[str, str]]:
        cursor = await self.conn.execute(
            "SELECT origin, title, updated_at FROM sources ORDER BY title COLLATE NOCASE"
        )
        rows = await cursor.fetchall()
        return [
            {"origin": row["origin"], "title": row["title"], "updated_at": row["updated_at"]}
            for row in rows
        ]

    async def source_count(self) -> int:
        cursor = await self.conn.execute("SELECT COUNT(*) AS n FROM sources")
        row = await cursor.fetchone()
        return int(row["n"])

    async def search_sources(self, query: str, limit: int = 4) -> list[str]:
        match = fts_query(query)
        if not match:
            return []
        cursor = await self.conn.execute(
            """
            SELECT s.title, chunks_fts.body AS body
            FROM chunks_fts
            JOIN sources s ON s.id = chunks_fts.source_id
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, limit),
        )
        rows = await cursor.fetchall()
        return [f"{row['title']}: {row['body']}" for row in rows]
