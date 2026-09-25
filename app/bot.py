from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher, F
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.conversation import Conversation
from app.db import Database
from app.sources import fetch_url, index_text

log = logging.getLogger("kontekst.bot")

HELP = """I am Kontekst. I answer from this chat, remembered facts, and project sources.

/source url — fetch and index a page
/sources — list project sources
/remember fact — store a lasting fact
/memory — show facts for this chat
/summarize — extract facts from recent messages
/forget — clear this chat's history and memory
/help — show this help

In a group I reply when you mention me or reply to my message. To let me see the whole group chat, disable privacy mode in BotFather.

Local qwen3:14b on CPU can take 1–3 minutes for the first answer — you will see a typing indicator while it works."""


async def _keep_typing(message: Message) -> None:
    try:
        while True:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        return


def addressed_to_bot(message: Message, username: str) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True
    if message.reply_to_message and message.reply_to_message.from_user:
        replied = message.reply_to_message.from_user
        if replied.is_bot and replied.username and replied.username.lower() == username.lower():
            return True
    text = message.text or ""
    if username and f"@{username}".lower() in text.lower():
        return True
    return False


def strip_mention(text: str, username: str) -> str:
    if not username:
        return text.strip()
    return text.replace(f"@{username}", "").replace(f"@{username.lower()}", "").strip()


def register_handlers(
    dp: Dispatcher,
    *,
    db: Database,
    conversation: Conversation,
    allow_private_urls: bool,
    username: str,
) -> None:
    @dp.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Hi. I keep conversation memory: I learn facts from our exchange and from sources you add.\n\n"
            + HELP
        )

    @dp.message(Command("help", "pomoc"))
    async def help_command(message: Message) -> None:
        await message.answer(HELP)

    @dp.message(Command("sources", "zrodla"))
    async def list_sources(message: Message) -> None:
        rows = await db.list_sources()
        if not rows:
            await message.answer("No project sources yet. Add one with /source or drop a file in the sources folder.")
            return
        lines = "\n".join(f"• {row['title']}" for row in rows[:30])
        await message.answer("Sources:\n" + lines)

    @dp.message(Command("source", "zrodlo"))
    async def add_url(message: Message) -> None:
        payload = (message.text or "").split(maxsplit=1)
        if len(payload) < 2:
            await message.answer("Usage: /source https://example.com")
            return
        url = payload[1].strip()
        try:
            title, body = await fetch_url(url, allow_private_urls)
            state = await index_text(db, f"url:{url}", title, body)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        label = {"added": "added", "updated": "updated"}.get(state, "unchanged")
        await message.answer(f"Source “{title}”: {label}.")

    @dp.message(Command("remember", "zapamietaj"))
    async def remember(message: Message) -> None:
        payload = (message.text or "").split(maxsplit=1)
        if len(payload) < 2:
            await message.answer("Usage: /remember A fact I should keep.")
            return
        saved = await conversation.remember(message.chat.id, payload[1])
        if saved:
            await message.answer("Remembered.")
        else:
            await message.answer("I already know that, or the text is too short.")

    @dp.message(Command("memory", "pamiec"))
    async def show_memory(message: Message) -> None:
        facts = await db.list_memories(message.chat.id, 20)
        if not facts:
            await message.answer("Memory for this chat is empty.")
            return
        await message.answer("I remember:\n" + "\n".join(f"• {fact}" for fact in facts))

    @dp.message(Command("summarize", "podsumuj"))
    async def summarize(message: Message) -> None:
        typing = asyncio.create_task(_keep_typing(message))
        try:
            await message.answer(await conversation.summarize(message.chat.id))
        finally:
            typing.cancel()

    @dp.message(Command("forget", "zapomnij"))
    async def forget(message: Message) -> None:
        await db.clear_chat(message.chat.id)
        await message.answer("This chat's history and memory were cleared. Project sources remain.")

    @dp.message(F.text)
    async def talk(message: Message) -> None:
        if not message.text or message.text.startswith("/"):
            return
        if not addressed_to_bot(message, username):
            await db.add_message(message.chat.id, "user", message.text)
            return
        typing = asyncio.create_task(_keep_typing(message))
        try:
            answer = await conversation.reply(message.chat.id, strip_mention(message.text, username))
            await message.answer(answer)
        except Exception as exc:
            log.exception("Reply failed")
            await message.answer(f"Could not answer right now: {exc}")
        finally:
            typing.cancel()
