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


async def send_morning_gmail_digest(bot: Bot) -> None:
    """Отправляет владельцу утренний дайджест почты за прошедшие сутки."""
    if not settings.gmail_user or not settings.gmail_app_password:
        return
    if not settings.owner_telegram_id:
        return
    try:
        from services.gmail_tools import GmailService
        from services.gmail_classifier import classify_messages, format_digest
        gm = GmailService(settings.gmail_user, settings.gmail_app_password)
        msgs = await gm.list_recent(limit=200, since_days=1)
        if not msgs:
            await bot.send_message(
                settings.owner_telegram_id,
                "🌅 <b>Утренний дайджест Gmail</b>\n\nЗа сутки писем нет.",
                parse_mode="HTML",
            )
            return
        classes = await classify_messages(msgs)
        text = format_digest(msgs, classes, period_label="за сутки")
        # Telegram лимит 4096
        await bot.send_message(
            settings.owner_telegram_id, text[:4000], parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.exception("Morning gmail digest failed: %s", e)


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
    # Утренний gmail-дайджест в 9:00 по Europe/Moscow.
    # Если Gmail не настроен — функция тихо ничего не делает.
    scheduler.add_job(
        send_morning_gmail_digest,
        "cron",
        hour=9,
        minute=0,
        args=[bot],
        id="morning_gmail_digest",
        replace_existing=True,
    )
    # Утренняя сводка по заказам магазина в 9:30 по Europe/Moscow.
    from services.shop_digest import send_morning_orders_digest
    scheduler.add_job(
        send_morning_orders_digest,
        "cron",
        hour=9,
        minute=30,
        args=[bot],
        id="morning_orders_digest",
        replace_existing=True,
    )
    # Бизнес-чеки (каталог не пуст, Девид в правильном режиме): каждые 10 мин.
    # Алерт владельцу только при смене состояния.
    from services.business_health import run_health_checks
    scheduler.add_job(
        run_health_checks,
        "interval",
        minutes=10,
        args=[bot],
        id="business_health",
        replace_existing=True,
    )
    # Бонус Monkey Grinder: 1-е число в 11:00 — основной запуск,
    # 2-е и 3-е в 11:00 — повторные попытки если 1-го отчёта не было.
    # Если файл уже посчитан и отправлен — повторно слать не будем
    # (метим через локальный маркер sent в workdir/mg).
    from services.mg_bonus_tools import monthly_bonus_job
    scheduler.add_job(
        _mg_monthly_wrapper,
        "cron",
        day="1-3",
        hour=11,
        minute=0,
        args=[bot],
        id="mg_bonus_monthly",
        replace_existing=True,
    )
    return scheduler


async def _mg_monthly_wrapper(bot: Bot) -> None:
    """1-е число — расчёт + алерт если файла нет.
    2-3 число — повторная попытка ТОЛЬКО если файл появился; алертить
    повторно не нужно (1-го уже сказали)."""
    import json as _json
    from services.mg_bonus_tools import (
        monthly_bonus_job, _tool_check_pending, WORKDIR,
    )
    today = datetime.now(TZ)
    marker = WORKDIR / f"sent_{today.strftime('%Y-%m')}.flag"
    if marker.exists():
        log.info("mg monthly: already sent this month, skipping")
        return

    # 2-3 число — тихо пропускаем если файла всё ещё нет.
    if today.day != 1:
        try:
            check = _json.loads(_tool_check_pending({}))
            if check.get("status") != "ready":
                log.info(f"mg monthly retry day={today.day}: file still missing, skipping")
                return
        except Exception as e:
            log.warning(f"mg monthly retry: check_pending failed: {e}")
            return

    try:
        await monthly_bonus_job(bot)
    except Exception as e:
        log.exception(f"mg monthly job crashed: {e}")
        return

    # После запуска: если файл реально лежит на Я.Диске — ставим маркер,
    # чтобы повторно не отрабатывать (расчёт уже отправлен).
    try:
        check = _json.loads(_tool_check_pending({}))
        if check.get("status") == "ready":
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("sent")
    except Exception:
        pass
