from aiogram import Router
from handlers import chat_events, messages, mentions, private

# Пробуем импортировать OZON агента (безопасно)
try:
    from handlers.ozon_agent_aiogram_fixed import ozon_router
    OZON_AVAILABLE = True
except ImportError:
    OZON_AVAILABLE = False

# Импортируем диагностику OZON
try:
    from handlers.ozon_diagnostics import ozon_diag_router
    OZON_DIAG_AVAILABLE = True
except ImportError:
    OZON_DIAG_AVAILABLE = False

# Импортируем OZON 2024

try:
    from handlers.ozon_working_final import ozon_working_new_router
    OZON_WORKING_NEW_AVAILABLE = True
except ImportError:
    OZON_WORKING_NEW_AVAILABLE = False


    
try:
    from handlers.ozon_2024 import ozon_2024_router
    OZON_2024_AVAILABLE = True
except ImportError:
    OZON_2024_AVAILABLE = False

def get_main_router() -> Router:
    """
    Возвращает главный роутер со всеми подключенными хэндлерами.
    Порядок важен: сначала специфичные, потом общие.
    """
    main = Router()
    if OZON_WORKING_NEW_AVAILABLE:
        main.include_router(ozon_working_new_router)
    # События (добавление бота в чаты) — самый приоритет
    main.include_router(chat_events.router)
    
    # ЛС с ботом
    main.include_router(private.router)
    
    # OZON агент (если доступен)
    if OZON_AVAILABLE:
        main.include_router(ozon_router)
    
    # OZON диагностика (если доступна)
    if OZON_DIAG_AVAILABLE:
        main.include_router(ozon_diag_router)
    
    # OZON 2024 API (если доступен)
    if OZON_2024_AVAILABLE:
        main.include_router(ozon_2024_router)
    
    # Упоминания в чатах
    main.include_router(mentions.router)
    
    # Логирование всех сообщений (должно быть последним чтобы не блокировать остальное)
    main.include_router(messages.router)
    
    return main

__all__ = ["get_main_router"]
