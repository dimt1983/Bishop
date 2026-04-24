"""CRUD и бизнес-логика задач."""
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import Task, TaskAssignee, User
from utils import log

TZ = ZoneInfo(settings.timezone)


async def create_task(
    session: AsyncSession,
    creator_id: int,
    chat_id: int,
    source_message_id: Optional[int],
    description: str,
    original_text: str,
    deadline: datetime,
    assignee_ids: list[int],
    is_shared: bool,
) -> list[Task]:
    """
    Создаёт задачу. Если is_shared=True — одна задача на всех.
    Если False — отдельная задача на каждого исполнителя.
    """
    created = []
    if is_shared or len(assignee_ids) == 1:
        task = Task(
            creator_id=creator_id,
            chat_id=chat_id,
            source_message_id=source_message_id,
            description=description,
            original_text=original_text,
            deadline=deadline.replace(tzinfo=None),
            status="pending",
        )
        for uid in assignee_ids:
            task.assignees.append(TaskAssignee(user_id=uid, is_shared=True))
        session.add(task)
        created.append(task)
    else:
        for uid in assignee_ids:
            task = Task(
                creator_id=creator_id,
                chat_id=chat_id,
                source_message_id=source_message_id,
                description=description,
                original_text=original_text,
                deadline=deadline.replace(tzinfo=None),
                status="pending",
            )
            task.assignees.append(TaskAssignee(user_id=uid, is_shared=False))
            session.add(task)
            created.append(task)
    await session.commit()
    for t in created:
        await session.refresh(t)
    log.info(f"Created {len(created)} task(s) for creator {creator_id}")
    return created


async def get_pending_tasks_for_user(
    session: AsyncSession, user_id: int
) -> list[Task]:
    """Возвращает открытые задачи где user — исполнитель."""
    result = await session.execute(
        select(Task)
        .join(TaskAssignee)
        .where(TaskAssignee.user_id == user_id)
        .where(Task.status == "pending")
        .options(selectinload(Task.assignees).selectinload(TaskAssignee.user))
        .options(selectinload(Task.creator))
    )
    return list(result.scalars().unique())


async def get_task_by_id(
    session: AsyncSession, task_id: int
) -> Optional[Task]:
    result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.assignees).selectinload(TaskAssignee.user))
        .options(selectinload(Task.creator))
    )
    return result.scalar_one_or_none()


async def complete_task(
    session: AsyncSession, task_id: int
) -> Optional[Task]:
    task = await get_task_by_id(session, task_id)
    if not task:
        return None
    task.status = "done"
    task.completed_at = datetime.now(TZ).replace(tzinfo=None)
    await session.commit()
    log.info(f"Task {task_id} completed")
    return task


async def cancel_task(
    session: AsyncSession, task_id: int
) -> Optional[Task]:
    task = await get_task_by_id(session, task_id)
    if not task:
        return None
    task.status = "cancelled"
    await session.commit()
    log.info(f"Task {task_id} cancelled")
    return task


async def postpone_task(
    session: AsyncSession, task_id: int, new_deadline: datetime
) -> Optional[Task]:
    task = await get_task_by_id(session, task_id)
    if not task:
        return None
    task.deadline = new_deadline.replace(tzinfo=None)
    task.overdue_reminders_sent = 0  # Сбрасываем счётчик напоминаний
    await session.commit()
    log.info(f"Task {task_id} postponed to {new_deadline}")
    return task


async def get_tasks_needing_reminder(
    session: AsyncSession,
) -> list[Task]:
    """
    Возвращает задачи которым пора слать напоминание:
    - За 24ч до дедлайна (если ещё не напоминали за последние 20ч)
    - В день дедлайна утром (9:00)
    - Каждые N часов после дедлайна (максимум max_reminders)
    """
    now = datetime.now(TZ).replace(tzinfo=None)
    result = await session.execute(
        select(Task)
        .where(Task.status == "pending")
        .where(Task.overdue_reminders_sent < settings.max_reminders_after_deadline + 2)
        .options(selectinload(Task.assignees).selectinload(TaskAssignee.user))
        .options(selectinload(Task.creator))
    )
    return list(result.scalars().unique())


async def mark_reminded(session: AsyncSession, task_id: int, is_overdue: bool):
    """Фиксируем что напомнили."""
    task = await get_task_by_id(session, task_id)
    if not task:
        return
    task.last_reminded_at = datetime.now(TZ).replace(tzinfo=None)
    if is_overdue:
        task.overdue_reminders_sent += 1
    await session.commit()


async def mark_overdue_stopped(session: AsyncSession, task_id: int):
    task = await get_task_by_id(session, task_id)
    if not task:
        return
    task.status = "overdue_stopped"
    await session.commit()
    log.info(f"Task {task_id} stopped after max reminders")
