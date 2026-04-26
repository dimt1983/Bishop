"""BishopRB — внутренний AI-помощник команды RBR с МАКСИМАЛЬНЫМ OZON агентом."""
import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from config import settings
from database import init_db
from handlers import get_main_router
from handlers.max_agent_handler import max_agent_router  # МАКСИМАЛЬНЫЙ агент
from services.reminder_service import setup_scheduler
from services.ozon_scheduler import OzonSchedulerService
from utils import log


async def main():
    log.info("Starting BishopRB with MAXIMUM OZON Agent...")
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
    
    # ========== ПОДКЛЮЧАЕМ МАКСИМАЛЬНОГО АГЕНТА ==========
    dp.include_router(max_agent_router)
    log.info("MAXIMUM OZON Agent loaded - full functionality enabled!")
    
    dp.include_router(get_main_router())
    
    scheduler = setup_scheduler(bot)
    
    # Настраиваем расширенные OZON задачи
    ozon_scheduler = OzonSchedulerService(bot)
    ozon_scheduler.setup_ozon_jobs(scheduler)
    
    scheduler.start()
    log.info("Scheduler started - automation cycles active")
    log.info("OZON MAXIMUM Agent: daily summaries, auto-optimization, smart pricing")
    
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
        log.info("MAXIMUM OZON Agent stopped")


# ========== КОММЕНТАРИИ ДЛЯ РАЗРАБОТЧИКА ==========
"""
МАКСИМАЛЬНЫЙ OZON АГЕНТ - ВОЗМОЖНОСТИ:

🎯 КОМАНДЫ:
/ozon - главное меню агента
/ozon_status - статус всех систем  
/ozon_quick - быстрые действия
/upload_photo - загрузка фото к товару

📱 TELEGRAM ФУНКЦИИ:
- Отправка фото с подписью "product_id:12345" автоматически загружает в карточку
- Интерактивные меню с кнопками
- Автоматические ежедневные сводки в 09:00 МСК

🤖 АВТОМАТИЗАЦИЯ:
- AI-анализ всех товаров 
- Автоулучшение названий и описаний
- Умный репрайсинг цен каждые 15 минут
- SEO-оптимизация карточек
- Автообработка фотографий
- Автоответы на отзывы
- Мониторинг остатков
- Прогнозирование спроса

🎨 ОБРАБОТКА КОНТЕНТА:
- AI-генерация продающих текстов
- Обработка изображений (кроп, улучшение, водяные знаки)
- SEO-анализ и оптимизация
- Расчёт рейтингов и рекомендаций

💰 УПРАВЛЕНИЕ:
- Полный административный доступ к OZON API
- Создание, редактирование, удаление товаров
- Управление ценами и остатками
- Загрузка фотографий
- Ответы на отзывы и вопросы

📊 АНАЛИТИКА:
- Глубокий анализ продаж и трендов
- Выявление проблемных товаров
- AI-инсайты и рекомендации
- Прогнозы на 30 дней
- Конкурентный анализ

ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:
OZON_CLIENT_ID - ID клиента из кабинета OZON
OZON_API_KEY - API ключ из кабинета OZON  
PROXYAPI_KEY - ключ ProxyAPI для Claude
OZON_DAILY_CHAT_ID - ID группы для уведомлений

СТОИМОСТЬ:
- Базовое использование: 300-500₽/месяц
- Активное использование: 1000-2000₽/месяц
- Полная автоматизация: 2000-5000₽/месяц
"""
