# BishopRB

Внутренний AI-помощник команды Roastberry на базе Claude — «дирижёр» экосистемы. Подробная карта файлов и ENV — в [CLAUDE.md](./CLAUDE.md).

## Что умеет

- 📋 Постановки задач через `@bishoprb <кому> <что> <когда>` в чатах + напоминания/эскалации в личку
- 🛒 Управление магазином (TMA-каталог, фото товаров, публикация → Railway TG-BOT)
- 💰 Прайс-листы (расчёт, добавление позиций, экспорт PDF/XLSX из xlsx)
- 🛠 Сервисная служба (выдача кодов техникам/менеджерам, ссылка на Mini App)
- 🎓 Roastberry Academy (приглашения, доступы, истёкшие)
- 📧 Gmail-инбокс владельца (классификация писем, /inbox, /digest)
- 📊 Ozon Seller-аналитика (продажи, отчёты с Я.Диска)
- 💸 Премия Monkey Grinder (расчёт по выгрузке 1С)
- 📈 Uptime-мониторинг сервисов экосистемы

## Стек

- Python 3.11+, aiogram 3.13, Anthropic SDK
- Claude Sonnet 4.5 (tool-use), Haiku 4.5 (классификатор интентов)
- SQLAlchemy async + SQLite (`bishop.db`)
- APScheduler

## Деплой и запуск

**Прод**: VPS под `systemd`. После правок:
```bash
git pull && systemctl restart bishop.service
journalctl -u bishop.service -f   # логи
```

**Локально**:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, OWNER_TELEGRAM_ID, GMAIL_USER, ADMIN_API_TOKEN
python main.py
```

## Настройка бота в @BotFather

- Group Privacy → **OFF** (обязательно — иначе не видит сообщения в чатах)
- Allow Groups → **ON**
