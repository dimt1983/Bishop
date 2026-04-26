"""BishopRB — внутренний AI-помощник команды RBR."""
import asyncio

from handlers.ozon_agent import ozon_handlers, send_daily_summary_to_chat
from datetime import time
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import settings
from database import init_db
from handlers import get_main_router
from services.reminder_service import setup_scheduler
from utils import log


async def main():
    log.info("Starting BishopRB...")
    log.info(f"Anthropic base URL: {settings.anthropic_base_url}")

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

# Добавить OZON обработчики
for handler in ozon_handlers:
    application.add_handler(handler)

# Настроить ежедневные сводки в 9:00 МСК
chat_id = os.getenv("OZON_DAILY_CHAT_ID", "-1003522003335")
job_queue = application.job_queue
job_queue.run_daily(
    send_daily_summary_to_chat,
    time=time(hour=6, minute=0),  # 9:00 MSK = 6:00 UTC
    data={"chat_id": chat_id},
    name="ozon_daily_summary"
)
