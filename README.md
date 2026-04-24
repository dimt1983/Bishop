# BishopRB

Внутренний AI-помощник команды Roastberry на базе Claude.

## Что умеет (v1)

- 📋 Принимает постановки задач через `@bishoprb <кому> <что> <когда>` в рабочих чатах
- 🔔 Напоминает исполнителям в личку (за сутки, утром дедлайна, каждые 3ч после)
- ✅ Понимает ответы "готово"/"сделал" → закрывает задачу
- 📅 Понимает "перенеси на ..." → двигает дедлайн + уведомляет постановщика
- ⚠️ Эскалирует постановщику после 5 напоминаний без ответа
- 🔍 Ищет по истории чатов по запросу `@bishoprb <вопрос>`
- 🗂 Автоматически регистрирует чаты при добавлении

## Стек

- Python 3.11+
- aiogram 3.x
- Claude Sonnet 4.5 (Anthropic API)
- SQLAlchemy async + SQLite
- APScheduler

## Deploy на Railway

1. Репозиторий должен быть подключён к сервису в Railway
2. Переменные окружения (Variables):
   - `TELEGRAM_BOT_TOKEN` — токен от @BotFather
   - `ANTHROPIC_API_KEY` — ключ Anthropic
   - `OWNER_TELEGRAM_ID` — ваш telegram ID (для эскалаций владельцу)
   - `TIMEZONE` — например `Europe/Moscow` (по умолчанию так же)
3. Railway автоматически использует `Procfile` для запуска

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # и заполнить
python main.py
```

## Настройка бота в @BotFather

- Group Privacy → **OFF** (обязательно)
- Allow Groups → **ON**

## База данных

SQLite файл `bishop.db` в корне. На Railway volume нужно будет подключить чтобы БД не терялась между деплоями (или мигрировать на Postgres — см. TODO).

## TODO (следующие этапы)

- [ ] Интеграция с sync API wahelp-agent (остатки, каталог)
- [ ] Еженедельный дайджест владельцу
- [ ] Выявление клиентских паттернов для wahelp-agent
- [ ] Миграция SQLite → Postgres для продакшна
- [ ] Привязка volume в Railway для персистентности
