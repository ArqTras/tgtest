from __future__ import annotations

import asyncio
import logging

from app.db import Database
from app.llm import ChatModel, parse_facts
from app.prompts import LEARN, SYSTEM, build_context_block

log = logging.getLogger("kontekst.conversation")

MISSING_KEY = (
    "I am saving this chat locally, but I have no model API key, so I cannot answer yet. "
    "Set LLM_API_KEY in the config and restart the container. "
    "You can still store a fact with /remember."
)


class Conversation:
    def __init__(self, db: Database, model: ChatModel | None, *, max_history: int, learn_every: int) -> None:
        self.db = db
        self.model = model
        self.max_history = max_history
        self.learn_every = learn_every

    async def reply(self, chat_id: int, user_text: str, *, learn: bool = True) -> str:
        text = " ".join(user_text.split())
        if not text:
            return "Send a message or use /help."
        await self.db.add_message(chat_id, "user", text)
        answer = await self._answer(chat_id, text)
        await self.db.add_message(chat_id, "assistant", answer)
        if (
            learn
            and self.model is not None
            and not answer.startswith("Could not")
        ):
            count = await self.db.message_count(chat_id)
            if count % (self.learn_every * 2) == 0:
                # Do not block the Telegram reply on a second slow local-model call.
                self._last_learn_task = asyncio.create_task(self._learn_safe(chat_id, text, answer))
        return answer

    async def drain_learning(self) -> None:
        task = getattr(self, "_last_learn_task", None)
        if task is not None:
            await task

    async def _learn_safe(self, chat_id: int, user_text: str, answer: str) -> None:
        try:
            await self.learn_from_exchange(chat_id, user_text, answer)
        except Exception:
            log.exception("Background learning failed")

    async def _answer(self, chat_id: int, user_text: str) -> str:
        if self.model is None:
            return MISSING_KEY
        sources = await self.db.search_sources(user_text)
        memories = await self.db.search_memories(chat_id, user_text)
        history = await self.db.recent_messages(chat_id, self.max_history)
        messages = [
            {"role": "system", "content": SYSTEM + "\n\n" + build_context_block(sources, memories)},
            *history,
        ]
        try:
            answer = await self.model.complete(messages)
        except RuntimeError as exc:
            return f"Could not get a model reply. {exc}"
        return _fit_telegram(answer or "I do not have an answer right now.")

    async def learn_from_exchange(self, chat_id: int, user_text: str, answer: str) -> list[str]:
        if self.model is None:
            return []
        prompt = (
            f"User: {user_text}\nAssistant: {answer}\n"
            "Return JSON with facts worth remembering."
        )
        try:
            raw = await self.model.complete(
                [
                    {"role": "system", "content": LEARN},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=250,
            )
        except RuntimeError:
            return []
        saved: list[str] = []
        for fact in parse_facts(raw):
            if await self.db.add_memory(chat_id, fact):
                saved.append(fact)
        return saved

    async def remember(self, chat_id: int, fact: str) -> bool:
        return await self.db.add_memory(chat_id, fact)

    async def summarize(self, chat_id: int) -> str:
        history = await self.db.recent_messages(chat_id, 30)
        if not history:
            return "There is nothing to summarize in this chat yet."
        if self.model is None:
            return MISSING_KEY
        transcript = "\n".join(f"{item['role']}: {item['content']}" for item in history)
        try:
            raw = await self.model.complete(
                [
                    {"role": "system", "content": LEARN},
                    {"role": "user", "content": transcript},
                ],
                max_tokens=300,
            )
        except RuntimeError as exc:
            return f"Could not summarize the chat. {exc}"
        saved = []
        for fact in parse_facts(raw):
            if await self.db.add_memory(chat_id, fact):
                saved.append(fact)
        if not saved:
            return "I reviewed the recent messages and found no new lasting fact."
        lines = "\n".join(f"• {fact}" for fact in saved)
        return f"Remembered:\n{lines}"


def _fit_telegram(text: str) -> str:
    if len(text) <= 4000:
        return text
    return text[:3950].rstrip() + "\n\n[truncated to Telegram limit]"
