"""Конфигурация из переменных окружения."""
import os
import re

from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_owner_id() -> int:
    """
    Терпимый парсер OWNER_TELEGRAM_ID.
    Убирает пробелы, знаки равенства, кавычки и прочий мусор.
    Если не получилось — возвращает 0 (бот работает без уведомлений владельцу).
    """
    raw = os.getenv("OWNER_TELEGRAM_ID", "0")
    # Вытаскиваем только цифры (и минус если вдруг отрицательный ID чата)
    match = re.search(r"-?\d+", raw or "")
    if match:
        try:
            return int(match.group())
        except ValueError:
            return 0
    return 0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    anthropic_api_key: str

    # ID владельца — парсится вручную через _parse_owner_id() ниже
    owner_telegram_id: int = 0

    # БД
    database_url: str = "sqlite+aiosqlite:///bishop.db"

    # Часовой пояс для напоминаний (Moscow по умолчанию)
    timezone: str = "Europe/Moscow"

    # Claude model
    claude_model: str = "claude-sonnet-4-5-20250929"

    # Лимит напоминаний после дедлайна
    max_reminders_after_deadline: int = 5

    # Интервал напоминаний после дедлайна (в часах)
    overdue_reminder_interval_hours: int = 3


# Сначала парсим "грязные" переменные вручную, потом создаём Settings
os.environ["OWNER_TELEGRAM_ID"] = str(_parse_owner_id())

settings = Settings()
