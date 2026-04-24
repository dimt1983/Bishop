"""Конфигурация из переменных окружения."""
import os
import re

from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_owner_id() -> int:
    """Терпимый парсер OWNER_TELEGRAM_ID (чистит пробелы, =, кавычки)."""
    raw = os.getenv("OWNER_TELEGRAM_ID", "0")
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
    # Base URL для Anthropic API (для прокси типа proxyapi.ru).
    # По умолчанию — официальный endpoint Anthropic.
    anthropic_base_url: str = "https://api.anthropic.com"

    owner_telegram_id: int = 0

    database_url: str = "sqlite+aiosqlite:///bishop.db"
    timezone: str = "Europe/Moscow"

    claude_model: str = "claude-sonnet-4-5-20250929"

    max_reminders_after_deadline: int = 5
    overdue_reminder_interval_hours: int = 3


os.environ["OWNER_TELEGRAM_ID"] = str(_parse_owner_id())

settings = Settings()
