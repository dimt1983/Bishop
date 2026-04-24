"""Личная переписка с Бишопом: /start, /что_ты_знаешь, готово, перенеси."""
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import settings
from database import async_session_maker, Chat, Task, TaskAssignee, User
from services import claude_service, task_service
from handlers.messages import _ensure_user
from utils import log

router = Router()
TZ = ZoneInfo(settings.timezone)


@router.message(F.chat.type == "private", Command("start"))
async def cmd_start(message: Message):
    async with async_session_maker() as session:
        user = await _ensure_user(session, message.from_user)
        user.has_started_dm = True
        await session.commit()

    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я Бишоп — помощник команды RBR.\n\n"
        "Теперь я смогу писать тебе напоминания по задачам.\n\n"
        "Что я умею:\n"
        "• Напоминаю о твоих задачах (заранее и в день дедлайна)\n"
        "• Принимаю твои ответы: \"готово\", \"перенеси на ...\"\n"
        "• Ищу по истории рабочих чатов\n\n"
        "Команды:\n"
        "/мои_задачи — список открытых задач\n"
        "/что_ты_знаешь — что я читаю и как работаю"
    )


@router.message(F.chat.type == "private", Command(commands=["что_ты_знаешь", "help"]))
async def cmd_what_you_know(message: Message):
    async with async_session_maker() as session:
        result = await session.execute(select(Chat).where(Chat.is_active == True))
        chats = result.scalars().all()
        chat_list = "\n".join(f"• {c.title}" for c in chats) or "• (пока нет)"

    await message.answer(
        "🤖 Как я работаю\n\n"
        "Я читаю сообщения в рабочих чатах куда меня добавили:\n"
        f"{chat_list}\n\n"
        "❌ Я НЕ читаю:\n"
        "• Личные переписки сотрудников\n"
        "• Чаты куда меня не добавляли\n\n"
        "📋 Что я делаю:\n"
        "• Запоминаю задачи когда в чате пишут @bishoprb\n"
        "• Напоминаю исполнителям в личку\n"
        "• Ищу по истории чатов по запросу @bishoprb <вопрос>\n"
        "• Эскалирую просроченные задачи постановщику\n\n"
        "Я НЕ выдаю отчёты на конкретных людей. Я помощник, а не надзиратель."
    )


@router.message(F.chat.type == "private", Command("мои_задачи"))
async def cmd_my_tasks(message: Message):
    async with async_session_maker() as session:
        tasks = await task_service.get_pending_tasks_for_user(
            session, message.from_user.id
        )
    if not tasks:
        await message.answer("У тебя нет открытых задач. 🎉")
        return

    lines = ["📋 Твои открытые задачи:\n"]
    for t in tasks:
        lines.append(
            f"#{t.id} — {t.description}\n"
            f"⏰ До: {t.deadline.strftime('%d.%m %H:%M')}\n"
            f"👤 От: {t.creator.display_name}\n"
        )
    lines.append(
        "\nЧтобы закрыть: напиши \"готово #<номер>\" или просто опиши результат."
    )
    await message.answer("\n".join(lines))


@router.message(F.chat.type == "private", ~F.text.startswith("/"))
async def handle_private_text(message: Message, bot: Bot):
    """Обработка произвольных сообщений в личке — через Claude понимаем что хочет."""
    if not message.text:
        return

    async with async_session_maker() as session:
        user = await _ensure_user(session, message.from_user)
        if not user.has_started_dm:
            user.has_started_dm = True
            await session.commit()

        # Собираем открытые задачи пользователя
        tasks = await task_service.get_pending_tasks_for_user(
            session, message.from_user.id
        )

        if not tasks:
            await message.answer(
                "У тебя нет открытых задач. Если нужна помощь — напиши /что_ты_знаешь."
            )
            return

        tasks_info = [
            {
                "id": t.id,
                "description": t.description,
                "deadline": t.deadline.strftime("%Y-%m-%d %H:%M"),
            }
            for t in tasks
        ]

        result = await claude_service.understand_completion_reply(
            message.text, tasks_info
        )
        action = result.get("action")

        if result.get("clarification_needed"):
            list_text = "\n".join(
                f"#{t.id} — {t.description} (до {t.deadline.strftime('%d.%m %H:%M')})"
                for t in tasks
            )
            await message.answer(
                f"У тебя несколько открытых задач. К какой относится сообщение?\n\n"
                f"{list_text}"
            )
            return

        task_id = result.get("task_id")
        if not task_id:
            await message.answer(
                "Не понял к какой задаче относится. Напиши /мои_задачи чтобы увидеть список."
            )
            return

        task = next((t for t in tasks if t.id == task_id), None)
        if not task:
            await message.answer("Не нашёл такую задачу.")
            return

        if action == "complete":
            await task_service.complete_task(session, task.id)
            # Уведомляем постановщика
            try:
                await bot.send_message(
                    task.creator_id,
                    f"✅ Задача закрыта\n\n"
                    f"📋 {task.description}\n"
                    f"👤 Исполнитель: {user.display_name}",
                )
            except Exception as e:
                log.warning(f"Couldn't notify creator: {e}")
            await message.answer(f"✅ Принял, задача закрыта:\n📋 {task.description}")
            return

        if action == "postpone":
            new_deadline_iso = result.get("new_deadline_iso")
            if not new_deadline_iso:
                await message.answer(
                    "Не понял новый дедлайн. Напиши конкретнее, например \"перенеси на пятницу 18:00\"."
                )
                return
            new_deadline = datetime.fromisoformat(new_deadline_iso)
            old_deadline = task.deadline
            await task_service.postpone_task(session, task.id, new_deadline)
            # Уведомляем постановщика
            try:
                await bot.send_message(
                    task.creator_id,
                    f"📅 Перенос дедлайна\n\n"
                    f"📋 {task.description}\n"
                    f"👤 Исполнитель: {user.display_name}\n"
                    f"Было: {old_deadline.strftime('%d.%m %H:%M')}\n"
                    f"Стало: {new_deadline.strftime('%d.%m %H:%M')}\n\n"
                    f"Если хочешь отклонить — напиши мне \"отклонить перенос #{task.id}\".",
                )
            except Exception as e:
                log.warning(f"Couldn't notify creator: {e}")
            await message.answer(
                f"📅 Перенёс дедлайн\n\n"
                f"📋 {task.description}\n"
                f"Новый дедлайн: {new_deadline.strftime('%d.%m %H:%M')}\n\n"
                f"Постановщик уведомлён."
            )
            return

        if action == "question":
            await message.answer(
                "Если есть вопрос по задаче — лучше спроси у постановщика. "
                "Я только напоминаю и принимаю отчёт о выполнении."
            )
            return

        await message.answer(
            "Не понял что ты хочешь. Напиши \"готово\" или \"перенеси на ...\"."
        )
