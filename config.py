"""Конфигурация из переменных окружения."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    anthropic_api_key: str

    # ID владельца (для эскалаций по умолчанию и команд управления)
    owner_telegram_id: int = 0  # Заполнится после первого /start владельца

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


settings = Settings()
