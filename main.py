"""BishopRB — внутренний AI-помощник команды RBR."""
import asyncio

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

    # Инициализация БД
    await init_db()
    log.info("Database initialized")

    # Создание бота
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=None),  # Пока без HTML/MD, чтобы не экранировать спецсимволы
    )

    me = await bot.get_me()
    log.info(f"Bot started: @{me.username} ({me.first_name})")

    # Dispatcher и роутеры
    dp = Dispatcher()
    dp.include_router(get_main_router())

    # Шедулер напоминаний
    scheduler = setup_scheduler(bot)
    scheduler.start()
    log.info("Reminder scheduler started (runs every 15 minutes)")

    # Старт polling
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
