"""Шедулер напоминаний — запускается раз в 15 минут и проверяет задачи."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from config import settings
from database import async_session_maker, Task, TaskAssignee, User
from services import task_service
from utils import log

TZ = ZoneInfo(settings.timezone)


def _now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


async def send_reminder_for_task(bot: Bot, task: Task) -> None:
    """Шлёт напоминание всем исполнителям задачи."""
    now = _now()
    deadline = task.deadline
    hours_to_deadline = (deadline - now).total_seconds() / 3600

    # Собираем исполнителей
    for assignee in task.assignees:
        user = assignee.user
        if not user.has_started_dm:
            # Не писали в личку — не сможем отправить
            log.warning(f"User {user.telegram_id} didn't /start bot, can't DM")
            continue

        try:
            if hours_to_deadline > 0:
                text = (
                    f"🔔 Напоминание от Бишопа\n\n"
                    f"📋 Задача: {task.description}\n"
                    f"👤 Поставил: {task.creator.display_name}\n"
                    f"⏰ Дедлайн: {deadline.strftime('%d.%m %H:%M')}\n\n"
                    f"Когда закончишь — напиши мне \"готово\".\n"
                    f"Не успеваешь? Напиши \"перенеси на ...\"."
                )
            else:
                overdue_hours = int(-hours_to_deadline)
                text = (
                    f"⚠️ Просроченная задача\n\n"
                    f"📋 {task.description}\n"
                    f"👤 Поставил: {task.creator.display_name}\n"
                    f"⏰ Дедлайн был: {deadline.strftime('%d.%m %H:%M')} "
                    f"(~{overdue_hours}ч назад)\n\n"
                    f"Напиши \"готово\" когда закроешь или \"перенеси на ...\"."
                )
            await bot.send_message(user.telegram_id, text)
            log.info(f"Sent reminder for task {task.id} to user {user.telegram_id}")
        except Exception as e:
            log.error(f"Failed to send reminder to {user.telegram_id}: {e}")

    # Отмечаем что напомнили
    is_overdue = hours_to_deadline < 0
    async with async_session_maker() as session:
        await task_service.mark_reminded(session, task.id, is_overdue)


async def notify_creator_no_response(bot: Bot, task: Task) -> None:
    """После max напоминаний — пишем постановщику."""
    creator = task.creator
    assignee_names = ", ".join(a.user.display_name for a in task.assignees)
    text = (
        f"⚠️ Задача не закрыта после {settings.max_reminders_after_deadline} напоминаний\n\n"
        f"📋 {task.description}\n"
        f"👤 Исполнитель(и): {assignee_names}\n"
        f"⏰ Дедлайн был: {task.deadline.strftime('%d.%m %H:%M')}\n\n"
        f"Я перестал напоминать. Решите как с ней поступить."
    )
    try:
        await bot.send_message(creator.telegram_id, text)
    except Exception as e:
        log.error(f"Failed to notify creator {creator.telegram_id}: {e}")

    async with async_session_maker() as session:
        await task_service.mark_overdue_stopped(session, task.id)


async def check_and_send_reminders(bot: Bot) -> None:
    """Главная функция шедулера — проверяет все задачи и решает кому напомнить."""
    now = _now()
    async with async_session_maker() as session:
        tasks = await task_service.get_tasks_needing_reminder(session)

    for task in tasks:
        deadline = task.deadline
        hours_to_deadline = (deadline - now).total_seconds() / 3600
        last = task.last_reminded_at

        # Логика: когда пора напоминать?
        should_remind = False

        if hours_to_deadline > 0:
            # До дедлайна
            if 23 <= hours_to_deadline <= 25:
                # За сутки — напомнить если не напоминали последние 20ч
                if not last or (now - last).total_seconds() > 20 * 3600:
                    should_remind = True
            elif 0 < hours_to_deadline <= 10 and now.hour >= 9 and now.hour <= 11:
                # Утром в день дедлайна
                if not last or (now - last).total_seconds() > 12 * 3600:
                    should_remind = True
        else:
            # После дедлайна
            if task.overdue_reminders_sent >= settings.max_reminders_after_deadline:
                # Превысили лимит — пишем постановщику и останавливаемся
                await notify_creator_no_response(bot, task)
                continue
            # Интервал N часов между напоминаниями
            interval = settings.overdue_reminder_interval_hours * 3600
            if not last or (now - last).total_seconds() > interval:
                should_remind = True

        if should_remind:
            await send_reminder_for_task(bot, task)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        check_and_send_reminders,
        "interval",
        minutes=15,
        args=[bot],
        id="reminder_check",
        replace_existing=True,
    )
    return scheduler
