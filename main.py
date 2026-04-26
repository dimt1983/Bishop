"""BishopRB — внутренний AI-помощник команды RBR."""
import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from database import init_db
from handlers import get_main_router
from handlers.ozon import send_daily_report
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

    # Существующий планировщик напоминаний
    reminder_scheduler = setup_scheduler(bot)
    reminder_scheduler.start()
    log.info("Reminder scheduler started (runs every 15 minutes)")

    # Планировщик OZON: утренняя сводка в 9:00 МСК (= 6:00 UTC)
    ozon_chat_id = os.getenv("OZON_DAILY_CHAT_ID")
    ozon_scheduler = AsyncIOScheduler(timezone="UTC")
    if ozon_chat_id:
        ozon_scheduler.add_job(
            send_daily_report,
            CronTrigger(hour=6, minute=0),  # 09:00 МСК
            args=[bot, ozon_chat_id],
            id="ozon_daily_report",
            replace_existing=True,
        )
        ozon_scheduler.start()
        log.info(f"OZON daily report scheduled for chat {ozon_chat_id} at 09:00 MSK")
    else:
        log.warning("OZON_DAILY_CHAT_ID is not set — daily report disabled")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        reminder_scheduler.shutdown()
        if ozon_scheduler.running:
            ozon_scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
