"""Обработка событий: бота добавили/удалили из чата, новые участники."""
from aiogram import Bot, F, Router
from aiogram.types import ChatMemberUpdated, Message
from aiogram.enums import ChatMemberStatus
from sqlalchemy import select

from config import settings
from database import async_session_maker, Chat, User
from utils import log

router = Router()


@router.my_chat_member()
async def on_bot_membership_change(event: ChatMemberUpdated, bot: Bot):
    """
    Срабатывает когда бота добавляют/удаляют из чата или меняют его статус.
    """
    chat = event.chat
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status

    log.info(
        f"Bot membership changed in chat {chat.id} ({chat.title}): "
        f"{old_status} -> {new_status}"
    )

    async with async_session_maker() as session:
        # Находим чат или создаём
        result = await session.execute(
            select(Chat).where(Chat.chat_id == chat.id)
        )
        db_chat = result.scalar_one_or_none()

        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
            # Бота добавили или сделали админом
            if db_chat is None:
                db_chat = Chat(chat_id=chat.id, title=chat.title, is_active=True)
                session.add(db_chat)
                await session.commit()

                # Уведомляем владельца если известен
                if settings.owner_telegram_id:
                    try:
                        await bot.send_message(
                            settings.owner_telegram_id,
                            f"✅ Подключён к чату\n\n"
                            f"📍 {chat.title}\n"
                            f"🆔 {chat.id}",
                        )
                    except Exception as e:
                        log.warning(f"Couldn't notify owner: {e}")

                # Приветствие в чате
                try:
                    await bot.send_message(
                        chat.id,
                        "👋 Привет! Я Бишоп, новый член команды.\n\n"
                        "Чем полезен:\n"
                        "• Напоминания по задачам — пишите @bishoprb <кому> <что> <когда>\n"
                        "• Поиск по истории чата — @bishoprb <вопрос>\n\n"
                        "Чтобы я мог писать вам напоминания — напишите мне в личку /start.\n"
                        "Подробнее — напишите мне /что_ты_знаешь в личке.",
                    )
                except Exception as e:
                    log.warning(f"Couldn't send greeting: {e}")
            else:
                db_chat.is_active = True
                db_chat.title = chat.title
                await session.commit()

        elif new_status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
        ):
            if db_chat:
                db_chat.is_active = False
                await session.commit()
                log.info(f"Bot removed from chat {chat.id}")
