"""BishopRB — внутренний AI-помощник команды RBR."""
import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from config import settings
from database import init_db
from handlers import get_main_router
from handlers.ozon_agent_aiogram import ozon_router
from services.reminder_service import setup_scheduler
from services.ozon_scheduler import OzonSchedulerService
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
    
    # Подключаем OZON router
    dp.include_router(ozon_router)
    
    dp.include_router(get_main_router())
    
    scheduler = setup_scheduler(bot)
    
    # Настраиваем OZON задачи
    ozon_scheduler = OzonSchedulerService(bot)
    ozon_scheduler.setup_ozon_jobs(scheduler)
    
    scheduler.start()
    log.info("Reminder scheduler started (runs every 15 minutes)")
    log.info("OZON daily summary scheduled for 9:00 MSK")
    
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
