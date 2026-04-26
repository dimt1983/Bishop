"""BishopRB — внутренний AI-помощник команды RBR."""
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from config import settings
from database import init_db
from handlers import get_main_router
from handlers.debug_ozon import debug_ozon_router  # Простая отладка
from services.reminder_service import setup_scheduler
from utils import log

# Пробуем подключить OZON агента если файлы есть
try:
    from handlers.ozon_agent_aiogram_fixed import ozon_router
    OZON_AGENT_AVAILABLE = True
    log.info("OZON agent module found")
except ImportError as e:
    OZON_AGENT_AVAILABLE = False
    log.warning(f"OZON agent module not available: {e}")


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
    
    # Простая OZON отладка (всегда работает)
    dp.include_router(debug_ozon_router)
    log.info("OZON debug commands loaded")
    
    # Полный OZON агент (если доступен)
    if OZON_AGENT_AVAILABLE:
        dp.include_router(ozon_router)
        log.info("Full OZON agent loaded")
    
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
