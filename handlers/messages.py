"""Логирование всех сообщений из рабочих чатов для поиска."""
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy import select

from config import settings
from database import async_session_maker, Chat, Message as DBMessage, User
from utils import log

router = Router()
TZ = ZoneInfo(settings.timezone)


async def _ensure_user(session, tg_user) -> User:
    """Создаёт или обновляет пользователя."""
    result = await session.execute(
        select(User).where(User.telegram_id == tg_user.id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        session.add(user)
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
        user.last_name = tg_user.last_name
    await session.commit()
    await session.refresh(user)
    return user


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def log_group_message(message: Message):
    """
    Логирует все сообщения в групповых чатах.
    Важно: этот хэндлер работает ПАРАЛЛЕЛЬНО с @bishoprb хэндлером
    (aiogram поддерживает множественную регистрацию через разные роутеры).
    """
    if not message.text and not message.caption:
        return  # игнорируем медиа без текста
    if message.from_user is None or message.from_user.is_bot:
        return

    text = message.text or message.caption or ""

    async with async_session_maker() as session:
        # Проверяем что чат активен
        result = await session.execute(
            select(Chat).where(Chat.chat_id == message.chat.id)
        )
        chat = result.scalar_one_or_none()
        if chat is None or not chat.is_active:
            return

        # Сохраняем/обновляем пользователя
        user = await _ensure_user(session, message.from_user)

        # Сохраняем сообщение
        db_msg = DBMessage(
            chat_id=message.chat.id,
            telegram_message_id=message.message_id,
            sender_id=message.from_user.id,
            sender_name=user.display_name,
            text=text,
            sent_at=message.date.astimezone(TZ).replace(tzinfo=None),
        )
        session.add(db_msg)
        await session.commit()
