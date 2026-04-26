from aiogram import Router
from handlers import chat_events, messages, mentions, private

# Пробуем импортировать OZON агента (безопасно)
try:
    from handlers.ozon_agent_aiogram_fixed import ozon_router
    OZON_AVAILABLE = True
except ImportError:
    OZON_AVAILABLE = False

def get_main_router() -> Router:
    """
    Возвращает главный роутер со всеми подключенными хэндлерами.
    Порядок важен: сначала специфичные, потом общие.
    """
    main = Router()
    
    # События (добавление бота в чаты) — самый приоритет
    main.include_router(chat_events.router)
    
    # ЛС с ботом
    main.include_router(private.router)
    
    # OZON агент (если доступен)
    if OZON_AVAILABLE:
        main.include_router(ozon_router)
    
    # Упоминания в чатах
    main.include_router(mentions.router)
    
    # Логирование всех сообщений (должно быть последним чтобы не блокировать остальное)
    main.include_router(messages.router)
    
    return main

__all__ = ["get_main_router"]
