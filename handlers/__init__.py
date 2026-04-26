from aiogram import Router

from handlers import chat_events, messages, mentions, private, ozon


def get_main_router() -> Router:
    """
    Возвращает главный роутер со всеми подключёнными хэндлерами.
    Порядок важен: сначала специфичные, потом общие.
    """
    main = Router()

    # События (добавление бота в чаты) — самый приоритет
    main.include_router(chat_events.router)

    # OZON-агент (команды /ozon_*, фото с product_id) — ПЕРЕД private,
    # чтобы фото и текст с product_id не перехватывал общий обработчик ЛС.
    main.include_router(ozon.router)

    # ЛС с ботом
    main.include_router(private.router)

    # Упоминания в чатах
    main.include_router(mentions.router)

    # Логирование всех сообщений (последним)
    main.include_router(messages.router)

    return main


__all__ = ["get_main_router"]
