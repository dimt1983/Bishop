from aiogram import Router
from handlers import chat_events, messages, mentions, private


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
    # Упоминания в чатах
    main.include_router(mentions.router)
    # Логирование всех сообщений (должно быть последним чтобы не блокировать остальное)
    main.include_router(messages.router)
    return main


__all__ = ["get_main_router"]
