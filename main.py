"""BishopRB — внутренний AI-помощник команды RBR."""
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import settings
from database import init_db
from handlers import get_main_router
from services.reminder_service import setup_scheduler
from services.uptime_service import uptime_worker
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

    uptime_task = asyncio.create_task(uptime_worker(bot, tick_seconds=60))
    log.info("Uptime worker started (tick=60s)")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        uptime_task.cancel()
        try:
            await uptime_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
