"""Обработка упоминаний @bishoprb в рабочих чатах."""
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.types import Message
from sqlalchemy import select

from config import settings
from database import (
    async_session_maker, Chat, Message as DBMessage, PendingTaskClarification,
    User,
)
from services import claude_service, task_service
from handlers.messages import _ensure_user
from utils import log

router = Router()
TZ = ZoneInfo(settings.timezone)


async def _get_bot_username(bot: Bot) -> str:
    me = await bot.get_me()
    return (me.username or "").lower()


async def _reply_in_topic(message: Message, text: str):
    """Отвечает на сообщение с учётом форум-топика."""
    try:
        await message.reply(text)
    except Exception as e:
        log.warning(f"reply() failed, trying send_message with thread: {e}")
        thread_id = getattr(message, "message_thread_id", None)
        try:
            await message.bot.send_message(
                chat_id=message.chat.id,
                text=text,
                message_thread_id=thread_id,
            )
        except Exception as e2:
            log.error(f"Couldn't send reply at all: {e2}")


async def _save_message_to_db(message: Message):
    """Гарантированно сохраняет сообщение и автора в БД.
    Вызывается в самом начале любого обработчика чата (даже если это mention)."""
    if message.from_user is None or message.from_user.is_bot:
        return
    if not (message.text or message.caption):
        return

    async with async_session_maker() as session:
        # Проверяем что чат активен
        chat_result = await session.execute(
            select(Chat).where(Chat.chat_id == message.chat.id)
        )
        chat = chat_result.scalar_one_or_none()
        if chat is None or not chat.is_active:
            return

        # Создаём/обновляем пользователя
        user = await _ensure_user(session, message.from_user)

        # Сохраняем сообщение если ещё нет
        text_for_log = message.text or message.caption or ""
        exists = await session.execute(
            select(DBMessage).where(
                DBMessage.chat_id == message.chat.id,
                DBMessage.telegram_message_id == message.message_id,
            )
        )
        if not exists.scalar_one_or_none():
            db_msg = DBMessage(
                chat_id=message.chat.id,
                telegram_message_id=message.message_id,
                sender_id=message.from_user.id,
                sender_name=user.display_name,
                text=text_for_log,
                sent_at=message.date.astimezone(TZ).replace(tzinfo=None),
            )
            session.add(db_msg)
            await session.commit()
            log.info(f"Saved message from {user.display_name} in chat {message.chat.id}")


async def _get_chat_members_for_parsing(
    session, chat_id: int
) -> list[dict]:
    """Возвращает список пользователей которые писали в этом чате."""
    result = await session.execute(
        select(DBMessage.sender_id)
        .where(DBMessage.chat_id == chat_id)
        .distinct()
    )
    sender_ids = [row[0] for row in result.all()]
    if not sender_ids:
        return []

    result = await session.execute(
        select(User).where(User.telegram_id.in_(sender_ids))
    )
    users = result.scalars().all()
    return [
        {
            "telegram_id": u.telegram_id,
            "name": u.display_name,
            "username": u.username,
        }
        for u in users
    ]


async def _is_mentioned(message: Message, bot: Bot) -> bool:
    if not (message.text or message.caption):
        return False
    text = (message.text or message.caption or "").lower()
    bot_username = await _get_bot_username(bot)
    return f"@{bot_username}" in text


async def _strip_mention(text: str, bot_username: str) -> str:
    import re
    pattern = re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)
    return pattern.sub("", text).strip()


@router.message(F.chat.type.in_({"group", "supergroup"}) & (F.text | F.caption))
async def handle_mention(message: Message, bot: Bot):
    """Главный хэндлер для @bishoprb в чатах (включая форумы с темами)."""
    # ВАЖНО: сохраняем ЛЮБОЕ сообщение в БД (в том числе с упоминанием),
    # чтобы автор всегда попадал в список участников.
    await _save_message_to_db(message)

    if not await _is_mentioned(message, bot):
        return

    bot_username = await _get_bot_username(bot)
    text = (message.text or message.caption or "")
    cleaned = await _strip_mention(text, bot_username)

    if not cleaned:
        await _reply_in_topic(
            message,
            "Напиши что-нибудь после @bishoprb.\n\n"
            "Примеры:\n"
            "• @bishoprb Лена, подготовь прайс к пятнице 18:00\n"
            "• @bishoprb когда мы обсуждали поставщика из Эфиопии?\n"
            "• @bishoprb отмени задачу про прайс",
        )
        return

    lower = cleaned.lower()

    if lower.startswith(("отмени", "отменить", "убери задачу")):
        await _handle_cancel_task(message, cleaned)
        return

    looks_like_task = any(
        marker in lower
        for marker in [
            "завтра", "сегодня", "послезавтра", "к пятниц", "к понедельник",
            "к вторник", "к сред", "к четверг", "к субботе", "к воскресенье",
            "через час", "через день", "через недел", "в пятницу", "в понедельник",
            "до конца", "к концу", "к утру", "к вечеру", "сделай", "подготовь",
            "пришли", "проверь", "закрой", "свяжись", "напиши", "позвони",
            "отправь", "сформируй", "составь",
        ]
    )

    if looks_like_task:
        await _handle_task_creation(message, cleaned, bot)
    else:
        await _handle_search(message, cleaned)


async def _handle_task_creation(message: Message, text: str, bot: Bot):
    async with async_session_maker() as session:
        creator = await _ensure_user(session, message.from_user)

        members = await _get_chat_members_for_parsing(session, message.chat.id)

        # Гарантируем что постановщик в списке
        creator_in_list = any(m["telegram_id"] == creator.telegram_id for m in members)
        if not creator_in_list:
            members.append({
                "telegram_id": creator.telegram_id,
                "name": creator.display_name,
                "username": creator.username,
            })

        if not members:
            await _reply_in_topic(
                message,
                "Не могу понять кто в этом чате — пока никто не писал при мне. "
                "Подождите пока участники поотвечают в чате, потом попробуйте снова.",
            )
            return

        parsed = await claude_service.parse_task_creation(text, members)

        if not parsed.get("success"):
            await _reply_in_topic(
                message,
                f"❌ Не смог разобрать задачу.\n\n{parsed.get('error', '')}\n\n"
                f"Пример: @bishoprb Лена, подготовь прайс к пятнице 18:00",
            )
            return

        if parsed.get("needs_clarification"):
            question = parsed.get(
                "clarification_question",
                "Это одна общая задача на всех или по одной каждому?",
            )
            import json as _json
            pending = PendingTaskClarification(
                creator_id=creator.telegram_id,
                chat_id=message.chat.id,
                source_message_id=message.message_id,
                original_text=text,
                clarification_type="shared_or_individual",
                parsed_data_json=_json.dumps(parsed, ensure_ascii=False),
            )
            session.add(pending)
            await session.commit()
            await _reply_in_topic(
                message,
                f"❓ {question}\n\n"
                f"Ответьте: @bishoprb общая или @bishoprb каждому",
            )
            return

        deadline = datetime.fromisoformat(parsed["deadline_iso"])
        tasks = await task_service.create_task(
            session=session,
            creator_id=creator.telegram_id,
            chat_id=message.chat.id,
            source_message_id=message.message_id,
            description=parsed["description"],
            original_text=text,
            deadline=deadline,
            assignee_ids=parsed["assignee_ids"],
            is_shared=parsed.get("is_shared", True),
        )

        assignee_names = ", ".join(parsed["assignee_names"])
        dm_warning = await _check_dm_status(session, parsed["assignee_ids"])

        reply = (
            f"✅ Задача принята\n\n"
            f"👤 Исполнитель(и): {assignee_names}\n"
            f"📋 {parsed['description']}\n"
            f"⏰ Дедлайн: {deadline.strftime('%d.%m %H:%M')}\n\n"
        )
        if len(tasks) > 1:
            reply += f"Создано {len(tasks)} отдельные задачи.\n\n"
        reply += "Напомню в личку заранее и в день дедлайна."
        if dm_warning:
            reply += f"\n\n⚠️ {dm_warning}"

        await _reply_in_topic(message, reply)


async def _check_dm_status(session, user_ids: list[int]) -> str:
    result = await session.execute(
        select(User).where(User.telegram_id.in_(user_ids))
    )
    users = result.scalars().all()
    not_started = [u.display_name for u in users if not u.has_started_dm]
    if not_started:
        names = ", ".join(not_started)
        return (
            f"{names} ещё не писал(и) мне в личку — не смогу отправить напоминание. "
            f"Попросите написать мне /start."
        )
    return ""


async def _handle_cancel_task(message: Message, text: str):
    async with async_session_maker() as session:
        from sqlalchemy.orm import selectinload
        from database import Task, TaskAssignee

        result = await session.execute(
            select(Task)
            .where(Task.creator_id == message.from_user.id)
            .where(Task.chat_id == message.chat.id)
            .where(Task.status == "pending")
            .options(selectinload(Task.assignees).selectinload(TaskAssignee.user))
        )
        tasks = list(result.scalars().unique())

        if not tasks:
            await _reply_in_topic(message, "У вас нет открытых задач в этом чате.")
            return

        if len(tasks) == 1:
            task = tasks[0]
            await task_service.cancel_task(session, task.id)
            bot = message.bot
            for a in task.assignees:
                if a.user.has_started_dm:
                    try:
                        await bot.send_message(
                            a.user.telegram_id,
                            f"ℹ️ Задача отменена постановщиком:\n\n📋 {task.description}",
                        )
                    except Exception as e:
                        log.warning(f"Couldn't notify {a.user.telegram_id}: {e}")
            await _reply_in_topic(message, f"✅ Задача отменена:\n📋 {task.description}")
            return

        tasks_info = [
            {
                "id": t.id,
                "description": t.description,
                "deadline": t.deadline.strftime("%d.%m %H:%M"),
            }
            for t in tasks
        ]
        result = await claude_service.understand_completion_reply(
            f"отмени эту задачу: {text}", tasks_info
        )
        if result.get("task_id"):
            task = next((t for t in tasks if t.id == result["task_id"]), None)
            if task:
                await task_service.cancel_task(session, task.id)
                await _reply_in_topic(message, f"✅ Задача отменена:\n📋 {task.description}")
                return

        list_text = "\n".join(
            f"#{t.id} — {t.description} (до {t.deadline.strftime('%d.%m %H:%M')})"
            for t in tasks
        )
        await _reply_in_topic(
            message,
            f"У вас несколько открытых задач. Уточните:\n\n{list_text}\n\n"
            f"Напишите: @bishoprb отмени #<номер>",
        )


async def _handle_search(message: Message, query: str):
    async with async_session_maker() as session:
        result = await session.execute(
            select(DBMessage)
            .where(DBMessage.chat_id == message.chat.id)
            .order_by(DBMessage.sent_at.desc())
            .limit(300)
        )
        msgs = list(result.scalars().all())
        msgs.reverse()

        if not msgs:
            await _reply_in_topic(
                message,
                "В этом чате пока нет истории которую я видел. "
                "Я запоминаю сообщения с момента как меня добавили в чат.",
            )
            return

        messages_data = [
            {
                "sender": m.sender_name,
                "text": m.text,
                "sent_at": m.sent_at.strftime("%d.%m.%Y %H:%M"),
            }
            for m in msgs
        ]

        answer = await claude_service.search_chat_history(query, messages_data)
        await _reply_in_topic(message, answer)
