"""BishopRB — внутренний AI-помощник команды RBR."""
import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database import init_db
from handlers import get_main_router
from services.reminder_service import setup_scheduler
from utils import log


async def main():
    log.info("Starting BishopRB...")

    # --- Диагностика ключей ---
    raw_key = os.getenv("ANTHROPIC_API_KEY", "")
    key_from_settings = settings.anthropic_api_key
    log.info(f"ANTHROPIC_API_KEY (from env): length={len(raw_key)}, "
             f"prefix='{raw_key[:12]}', "
             f"suffix='{raw_key[-4:] if len(raw_key) > 4 else ''}', "
             f"starts_with_sk_ant={raw_key.startswith('sk-ant-')}, "
             f"has_whitespace={any(c.isspace() for c in raw_key)}, "
             f"has_equals={'=' in raw_key[:5]}")
    log.info(f"ANTHROPIC_API_KEY (from settings): length={len(key_from_settings)}, "
             f"prefix='{key_from_settings[:12]}', "
             f"starts_with_sk_ant={key_from_settings.startswith('sk-ant-')}")
    # Пробуем синхронный тестовый запрос к Claude
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=settings.anthropic_api_key)
        test = client.messages.create(
            model=settings.claude_model,
            max_tokens=10,
            messages=[{"role": "user", "content": "say ok"}],
        )
        log.info(f"Anthropic API test: OK, response={test.content[0].text[:20]}")
    except Exception as e:
        log.error(f"Anthropic API test FAILED: {e}")
    # --- Конец диагностики ---

    await init_db()
    log.info("Database initialized")

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )

    me = await bot.get_me()
    log.info(f"Bot started: @{me.username} ({me.first_name})")

    dp = Dispatcher()
    dp.include_router(get_main_router())

    scheduler = setup_scheduler(bot)
    scheduler.start()
    log.info("Reminder scheduler started (runs every 15 minutes)")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
