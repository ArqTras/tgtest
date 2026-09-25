from __future__ import annotations

import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher

from app.config import load_settings
from app.conversation import Conversation
from app.db import Database
from app.http_admin import USERNAME, build_app, refresh_files
from app.llm import OpenAICompatible
from app.bot import register_handlers

log = logging.getLogger("kontekst")


async def _scan_loop(settings, db) -> None:
    while True:
        try:
            notes = await refresh_files(settings, db)
            if notes:
                log.info("Zindeksowane pliki: %s", ", ".join(notes))
        except Exception:
            log.exception("Skan źródeł nie powiódł się")
        await asyncio.sleep(60)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    db = Database(settings.db_path)
    await db.open()
    await refresh_files(settings, db)
    model = (
        OpenAICompatible(
            settings.llm_base_url,
            settings.llm_api_key,
            settings.llm_model,
            timeout=settings.llm_timeout,
        )
        if settings.llm_ready
        else None
    )
    log.info(
        "LLM: ready=%s url=%s model=%s timeout=%ss",
        settings.llm_ready,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_timeout,
    )
    conversation = Conversation(
        db,
        model,
        max_history=settings.max_history,
        learn_every=settings.learn_every,
    )
    http = build_app(settings, db, conversation)
    runner = web.AppRunner(http)
    await runner.setup()
    site = web.TCPSite(runner, settings.http_host, settings.http_port)
    await site.start()
    log.info("Status: http://%s:%s", settings.http_host, settings.http_port)
    scanner = asyncio.create_task(_scan_loop(settings, db))
    try:
        if not settings.telegram_ready:
            log.warning("Brak TELEGRAM_BOT_TOKEN. Serwis statusu działa, bot czeka na konfigurację.")
            await asyncio.Event().wait()
            return
        bot = Bot(settings.telegram_token)
        me = await bot.get_me()
        http[USERNAME] = me.username or ""
        dp = Dispatcher()
        register_handlers(
            dp,
            db=db,
            conversation=conversation,
            allow_private_urls=settings.allow_private_urls,
            username=me.username or "",
            admin_usernames=settings.admin_usernames,
        )
        log.info("Telegram: @%s (admins: %s)", me.username, ",".join(settings.admin_usernames))
        await dp.start_polling(bot)
    finally:
        scanner.cancel()
        await runner.cleanup()
        await db.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
