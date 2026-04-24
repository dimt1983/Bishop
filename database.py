"""Модели БД и сессии SQLAlchemy."""
from datetime import datetime
from typing import AsyncGenerator, Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
)
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    """Сотрудники и все пользователи взаимодействующие с ботом."""
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255))
    # Написал ли /start боту в личку (нужно для отправки ему напоминаний)
    has_started_dm: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def display_name(self) -> str:
        if self.first_name:
            name = self.first_name
            if self.last_name:
                name += f" {self.last_name}"
            return name
        if self.username:
            return f"@{self.username}"
        return f"id{self.telegram_id}"


class Chat(Base):
    """Рабочие чаты к которым подключён Бишоп."""
    __tablename__ = "chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    # Активен ли Бишоп в этом чате (False если его исключили)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    """Архив сообщений из рабочих чатов для поиска."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer)
    sender_id: Mapped[int] = mapped_column(BigInteger, index=True)
    sender_name: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Task(Base):
    """Задача созданная через @bishoprb."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Кто поставил
    creator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    # В каком чате
    chat_id: Mapped[int] = mapped_column(BigInteger)
    # Сообщение с постановкой
    source_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    # Описание задачи
    description: Mapped[str] = mapped_column(Text)
    # Оригинальный текст постановки
    original_text: Mapped[str] = mapped_column(Text)
    # Дедлайн
    deadline: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Статус: pending / done / cancelled / overdue_stopped
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # Сколько напоминаний после дедлайна отправлено
    overdue_reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    # Время последнего напоминания
    last_reminded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    creator: Mapped["User"] = relationship(foreign_keys=[creator_id])
    assignees: Mapped[list["TaskAssignee"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskAssignee(Base):
    """Исполнители задачи (может быть несколько)."""
    __tablename__ = "task_assignees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    # Если задача общая (shared) — закрывает любой. Если individual — каждый свою часть.
    is_shared: Mapped[bool] = mapped_column(Boolean, default=True)

    task: Mapped["Task"] = relationship(back_populates="assignees")
    user: Mapped["User"] = relationship()


class PendingTaskClarification(Base):
    """Постановки которые требуют уточнения (например, один/несколько исполнителей)."""
    __tablename__ = "pending_clarifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[Optional[int]] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(Text)
    # Что именно уточняем: "shared_or_individual"
    clarification_type: Mapped[str] = mapped_column(String(64))
    # Сериализованный JSON с частично распарсенными данными
    parsed_data_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


engine = create_async_engine(settings.database_url, echo=False)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Создание таблиц при первом запуске."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
