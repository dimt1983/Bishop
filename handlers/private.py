"""Личная переписка с Бишопом: /start, /что_ты_знаешь, готово, перенеси."""
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import settings
from database import async_session_maker, Chat, Task, TaskAssignee, User
from services import claude_service, task_service, shop_tools
from handlers.messages import _ensure_user
from utils import log

router = Router()
TZ = ZoneInfo(settings.timezone)


PRICE_KEYWORDS = (
    "прайс", "посчит", "посчитай", "прикинь", "сколько будет", "сколько стоит",
    "цена ", "цены ", "позиц", "удали позиц", "покажи прайс", "обнови прайс",
    "добавь моносорт", "добавь микролот", "добавь бленд", "добавь blend",
    "новая позиция", "ещё позиция", "еще позиция",
    # КП по аренде кофейного оборудования
    "аренд", "арендую", "арендовать", "коммерческое предложение", "кп по аренде",
    "nimbus", "нимбус", "wpm", "zd-18", "zd 18", "кофемашин", "кофемолк",
)

GMAIL_KEYWORDS = (
    "почт", "gmail", "имейл", "имэйл", "email", "е-мейл", "e-mail",
    "инбокс", "inbox", "входящ",
    "дайджест", "сводк", "разбер", "разобрать", "разбор",
    "письм", "email", "писем",
    "что в почте", "почистить почту", "от тинькофф", "от сбер", "от альф",
    "от мтс", "от вб", "от ozon", "от озон", "от вайлдб",
    "что нового в", "что от ", "новые письма",
    "сколько спама", "сколько рекламы", "сколько уведомлений",
    "@gmail", "@mail", "@yahoo",
)

SHOP_KEYWORDS = (
    "магазин", "tma", "mini app", "miniapp",
    "добавь в магазин", "добавь в каталог", "в каталог магазина",
    "обнови фото", "поменяй фото", "загрузи фото", "это фото товара",
    "добавь фото", "сменить фото", "новое фото",
    "обнови описание", "поменяй описание",
    "опубликуй", "опубликуй магазин", "опубликовать в магазине",
    "товар в магазине", "позиция в магазине", "удали из магазина",
    "сток в магазине", "остаток в магазине",
    "убери из магазина", "убрать из магазина",
    # Ассортимент (общий прайс — молоко, сиропы, чай Althaus/Niktea, наборы)
    "сироп", "молоко", "топпинг", "ассортимент", "коэф",
    "althaus", "niktea", "альтхаус", "никти",
    "barline", "botanika", "ботаника", "herbarista", "гербариста",
    "sweetshot", "monin", "монин", "vedrenne", "ведренн",
    "набор tasteabrew", "ресторансия",
    # Файловые правки исходников (file-тулы, owner only)
    "открой файл", "покажи файл", "прочитай файл", "прочти файл",
    "поправь файл", "измени файл", "правка файла", "редактируй файл",
    "открой папку", "покажи папку", "содержимое папки",
    "обнови генератор", "поправь скрипт", "измени скрипт",
    "пересобери", "пересоберём", "пересоберем", "пересобрать",
    "убери из прайса", "убери из каталога", "убери из кп",
    "добавь в прайс", "добавь в каталог", "добавь в кп",
    "поправь прайс", "поправь каталог", "поправь кп",
    "поправь шрифт", "поправь цвет", "поменяй текст в",
    # Яндекс.Диск + PDF (yadisk_*, pdf_extract_pages)
    "яндекс", "yandex", "yadisk", "я.диск", "я диск",
    "диск", "облако", "на диске", "в облаке",
    "вытащи из pdf", "извлеки из pdf", "распакуй pdf",
    "pdf", "пдф", "карточки", "макет упаковки",
    "скачай файл", "забери файл", "возьми файл",
)


def _looks_like_price_request(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in PRICE_KEYWORDS)


def _looks_like_shop_request(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in SHOP_KEYWORDS)


def _looks_like_gmail_request(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in GMAIL_KEYWORDS)


async def _send_long(message: Message, text: str):
    """Telegram режет на 4096; делим по 4000 на всякий."""
    if not text:
        await message.answer("(пустой ответ)")
        return
    chunk = 4000
    for i in range(0, len(text), chunk):
        await message.answer(text[i:i + chunk])


async def _send_shop_photos(message: Message, photos: list[dict]):
    """Отправляет фото или документы. PDF/XLSX уходят как document."""
    for ph in photos:
        path = ph["path"]
        is_doc = path.lower().endswith((".pdf", ".xlsx", ".docx", ".zip", ".csv"))
        try:
            if is_doc:
                await message.answer_document(
                    FSInputFile(path, filename=ph.get("filename")),
                    caption=ph.get("caption") or None,
                )
            else:
                await message.answer_photo(
                    FSInputFile(path),
                    caption=ph.get("caption") or None,
                )
        except Exception as e:
            log.error(f"send shop photo failed for {ph.get('path')}: {e}")
            await message.answer(f"Не смог отправить фото: {e}")


async def _send_price_files(message: Message, files: list[dict]):
    """Шлёт PDF/XLSX чистовики в личку."""
    for f in files:
        try:
            await message.answer_document(
                FSInputFile(f["path"], filename=f.get("filename")),
                caption=f.get("caption") or None,
            )
        except Exception as e:
            log.error(f"send_document failed for {f.get('path')}: {e}")
            await message.answer(f"Не смог отправить файл: {e}")


@router.message(F.chat.type == "private", Command(commands=["price", "prices"]))
async def cmd_price(message: Message):
    claude_service.reset_price_history(message.from_user.id)
    if message.from_user.id == settings.owner_telegram_id:
        await message.answer(
            "🧾 Прайс-режим (владелец). Что умею:\n"
            "• «посчитай моносорт Эфиопия Иргачеффе по $14»\n"
            "• «добавь микролот Кения Нямбени по $18»\n"
            "• «покажи прайс»\n"
            "• «удали позицию Бразилия Судан Руме анаэроб.»\n\n"
            "После расчёта спрошу подтверждение перед записью.\n"
            "Чтобы выйти — /price_off."
        )
    else:
        await message.answer(
            "🧾 Прайс. Спрашивайте:\n"
            "• «покажи прайс»\n"
            "• «есть ли в наличии Эфиопия Иргачеффе»\n"
            "• «сколько стоит Кения АА от 10 кг»\n\n"
            "Расчёт и добавление позиций — только у Дмитрия."
        )


@router.message(F.chat.type == "private", Command(commands=["price_off", "stop_price"]))
async def cmd_price_off(message: Message):
    claude_service.reset_price_history(message.from_user.id)
    await message.answer("Прайс-режим сброшен.")


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


@router.message(F.chat.type == "private", F.photo)
async def handle_private_photo(message: Message, bot: Bot):
    """Сотрудник прислал фото в личку — сохраняем в pending для shop_set_photo_from_telegram.
    Затем если в подписи есть ключ — сразу обрабатываем как магазин-запрос."""
    is_owner = message.from_user.id == settings.owner_telegram_id
    if not is_owner:
        await message.answer("Магазином управляет Дмитрий — фото от тебя я не сохраняю.")
        return
    try:
        # Берём самое большое фото
        file_id = message.photo[-1].file_id
        file = await bot.get_file(file_id)
        buf = await bot.download_file(file.file_path)
        image_bytes = buf.read() if hasattr(buf, "read") else bytes(buf)
        shop_tools.set_pending_photo(message.from_user.id, image_bytes)
        log.info(f"shop pending photo set for user {message.from_user.id}, {len(image_bytes)} bytes")
    except Exception as e:
        log.error(f"failed to download photo: {e}")
        await message.answer(f"Не смог скачать фото: {e}")
        return

    caption = (message.caption or "").strip()
    if not caption:
        await message.answer(
            "📸 Фото получено и ждёт. Теперь напиши к какому товару прикрепить, например:\n"
            "«это фото для Бразилия Серрадо 1 кг»\n"
            "или «обнови фото у NIKTEA Молочный Улун»."
        )
        return
    # Если есть подпись — сразу обрабатываем как shop-запрос
    try:
        answer, photos = await claude_service.shop_chat(
            caption + "\n\n[К сообщению приложено фото — используй shop_set_photo_from_telegram]",
            message.from_user.id, is_owner=True,
        )
    except Exception as e:
        log.error(f"shop_chat with photo failed: {e}")
        answer, photos = f"Ошибка: {e}", []
    if photos:
        await _send_shop_photos(message, photos)
    if answer:
        await _send_long(message, answer)


@router.message(F.chat.type == "private", Command(commands=["shop", "магазин"]))
async def cmd_shop(message: Message):
    claude_service.reset_shop_history(message.from_user.id)
    is_owner = message.from_user.id == settings.owner_telegram_id
    if is_owner:
        await message.answer(
            "🛍️ Магазин-режим (владелец). Команды:\n"
            "• «найди в магазине Бразилия Серрадо»\n"
            "• «обнови цену 1 кг у Кения АА на 2700»\n"
            "• «обнови описание у Эфиопия Иргачиф: <текст>»\n"
            "• «добавь товар: название, категория, цена 1кг, цена 200г»\n"
            "• «обнови фото у X» (потом пришли фото) ИЛИ пришли фото с подписью\n"
            "• «опубликуй магазин» — пушит в Railway, передеплой за 2 мин\n\n"
            "После прайс-добавления (моносорт/микролот/смесь) предложу добавить в магазин.\n"
            "Выйти из режима — /shop_off."
        )
    else:
        await message.answer(
            "🛍️ Магазин. Что я могу:\n"
            "• «найди в магазине X»\n"
            "• «покажи карточку X»\n"
            "• «какие подкатегории чая»\n\n"
            "Изменения — только у Дмитрия."
        )


@router.message(F.chat.type == "private", Command(commands=["shop_off", "магазин_выкл"]))
async def cmd_shop_off(message: Message):
    claude_service.reset_shop_history(message.from_user.id)
    shop_tools.clear_pending_photo(message.from_user.id)
    await message.answer("Магазин-режим сброшен.")


# ─── Gmail-ассистент ────────────────────────────────────────────────────────

@router.message(F.chat.type == "private", Command(commands=["inbox", "почта", "gmail"]))
async def cmd_inbox(message: Message):
    """Показывает последние письма из Gmail (только метаданные).

    Уровень: 🟢 БЕЗОПАСНЫЙ — только просмотр, без удаления и архивации.

    Аргументы:
        /inbox 20 7  — показать 20 писем за 7 дней (по умолчанию: 15 за 3 дня)
    """
    if message.from_user and message.from_user.id != settings.owner_telegram_id:
        return  # доступ только владельцу

    if not settings.gmail_user or not settings.gmail_app_password:
        await message.answer(
            "📭 Gmail не настроен.\n\n"
            "Чтобы подключить:\n"
            "1. Включи 2FA в Gmail\n"
            "2. Создай App Password: https://myaccount.google.com/apppasswords\n"
            "3. Добавь в .env Бишепа:\n"
            "   <code>GMAIL_USER=твоя_почта@gmail.com</code>\n"
            "   <code>GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx</code>\n"
            "4. Перезапусти Бишепа",
            parse_mode="HTML",
        )
        return

    parts = (message.text or "").split()
    try:
        limit = int(parts[1]) if len(parts) > 1 else 15
        since_days = int(parts[2]) if len(parts) > 2 else 3
    except ValueError:
        limit, since_days = 15, 3
    limit = max(1, min(limit, 50))
    since_days = max(1, min(since_days, 30))

    from services.gmail_tools import GmailService, format_inbox_telegram
    gm = GmailService(settings.gmail_user, settings.gmail_app_password)

    status_msg = await message.answer("⏳ Читаю Gmail…")
    try:
        msgs = await gm.list_recent(limit=limit, since_days=since_days)
    except Exception as e:
        log.exception("gmail list_recent failed")
        await status_msg.edit_text(f"❌ Не удалось получить почту: {type(e).__name__}: {str(e)[:200]}")
        return

    # Классифицируем через Claude (whitelisted идут без вызова)
    from services.gmail_classifier import classify_messages, format_inbox_with_categories
    try:
        classes = await classify_messages(msgs)
    except Exception as e:
        log.exception("gmail classify failed")
        # Фолбэк — без категорий
        header = f"📥 Inbox · {settings.gmail_user} · последние {len(msgs)} за {since_days} дн"
        text = format_inbox_telegram(msgs, header=header)
        await status_msg.delete()
        await _send_long(message, text)
        return

    header = f"📥 Inbox · {settings.gmail_user} · {len(msgs)} писем за {since_days} дн"
    text = format_inbox_with_categories(msgs, classes, header=header)
    await status_msg.delete()
    await _send_long(message, text)


@router.message(F.chat.type == "private", Command(commands=["digest", "сводка", "дайджест"]))
async def cmd_digest(message: Message):
    """Сводка по почте за период с группировкой по категориям.

    Аргументы:
        /digest 7  — за 7 дней (по умолчанию: 1 день)
    """
    if message.from_user and message.from_user.id != settings.owner_telegram_id:
        return
    if not settings.gmail_user or not settings.gmail_app_password:
        await message.answer("Gmail не настроен (см. /inbox)")
        return

    parts = (message.text or "").split()
    try:
        since_days = int(parts[1]) if len(parts) > 1 else 1
    except ValueError:
        since_days = 1
    since_days = max(1, min(since_days, 14))

    from services.gmail_tools import GmailService
    from services.gmail_classifier import classify_messages, format_digest
    gm = GmailService(settings.gmail_user, settings.gmail_app_password)

    status_msg = await message.answer(f"📊 Собираю дайджест за {since_days} дн…")
    try:
        msgs = await gm.list_recent(limit=100, since_days=since_days)
    except Exception as e:
        log.exception("digest fetch failed")
        await status_msg.edit_text(f"❌ Не получил почту: {type(e).__name__}: {str(e)[:200]}")
        return

    if not msgs:
        await status_msg.edit_text(f"📊 За последние {since_days} дн писем нет.")
        return

    try:
        classes = await classify_messages(msgs)
    except Exception as e:
        log.exception("digest classify failed")
        await status_msg.edit_text(f"❌ Классификация упала: {type(e).__name__}: {str(e)[:200]}")
        return

    period_label = f"за {since_days} дн" if since_days > 1 else "за сутки"
    text = format_digest(msgs, classes, period_label=period_label)
    await status_msg.delete()
    await _send_long(message, text)


# ─── Uptime-мониторинг ──────────────────────────────────────────────────────

@router.message(F.chat.type == "private", Command(commands=["monitor", "monitors", "монитор"]))
async def cmd_monitor(message: Message):
    """Управление uptime-мониторами.

    Подкоманды:
        /monitor                       — список всех
        /monitor add <url> [имя]       — добавить
        /monitor pause <id>            — поставить на паузу
        /monitor resume <id>           — снять с паузы
        /monitor remove <id>           — удалить
    """
    if message.from_user and message.from_user.id != settings.owner_telegram_id:
        return

    from services import uptime_service

    parts = (message.text or "").split(maxsplit=3)
    sub = parts[1].lower() if len(parts) > 1 else ""

    if not sub:
        mons = await uptime_service.list_monitors()
        await message.answer(
            uptime_service.format_monitors_for_telegram(mons),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    if sub == "add":
        if len(parts) < 3:
            await message.answer("Использование: <code>/monitor add &lt;url&gt; [имя]</code>", parse_mode="HTML")
            return
        url = parts[2]
        name = parts[3] if len(parts) > 3 else url.replace("https://", "").replace("http://", "").rstrip("/")[:80]
        m = await uptime_service.add_monitor(
            name=name, url=url,
            alert_chat_id=message.chat.id,
            interval_seconds=300,
        )
        await message.answer(
            f"✅ Добавил монитор #{m.id}: <b>{m.name}</b>\n<code>{m.url}</code>\nПервая проверка — в течение минуты.",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    if sub in ("pause", "resume"):
        if len(parts) < 3:
            await message.answer(f"Использование: <code>/monitor {sub} &lt;id&gt;</code>", parse_mode="HTML")
            return
        try:
            mid = int(parts[2])
        except ValueError:
            await message.answer("ID должен быть числом")
            return
        ok = await uptime_service.set_active(mid, sub == "resume")
        if ok:
            await message.answer(f"✅ Монитор #{mid} {'возобновлён' if sub == 'resume' else 'на паузе'}")
        else:
            await message.answer(f"❌ Монитор #{mid} не найден")
        return

    if sub == "remove":
        if len(parts) < 3:
            await message.answer("Использование: <code>/monitor remove &lt;id&gt;</code>", parse_mode="HTML")
            return
        try:
            mid = int(parts[2])
        except ValueError:
            await message.answer("ID должен быть числом")
            return
        ok = await uptime_service.remove_monitor(mid)
        await message.answer(f"{'✅ Удалил' if ok else '❌ Не найден'} монитор #{mid}")
        return

    await message.answer(
        "Подкоманды:\n"
        "<code>/monitor</code> — список\n"
        "<code>/monitor add &lt;url&gt; [имя]</code>\n"
        "<code>/monitor pause &lt;id&gt;</code> / <code>/monitor resume &lt;id&gt;</code>\n"
        "<code>/monitor remove &lt;id&gt;</code>",
        parse_mode="HTML",
    )


@router.message(F.chat.type == "private", Command(commands=["gmail_check", "gmail_test"]))
async def cmd_gmail_check(message: Message):
    """Быстрая проверка подключения к Gmail."""
    if message.from_user and message.from_user.id != settings.owner_telegram_id:
        return
    if not settings.gmail_user or not settings.gmail_app_password:
        await message.answer("Gmail не настроен (см. /inbox)")
        return
    from services.gmail_tools import GmailService
    gm = GmailService(settings.gmail_user, settings.gmail_app_password)
    ok, reason = await gm.check_login()
    if ok:
        await message.answer(f"✅ Gmail подключение работает: {settings.gmail_user}")
    else:
        await message.answer(f"❌ Не подключился к Gmail:\n<code>{reason}</code>", parse_mode="HTML")


@router.message(F.chat.type == "private", ~F.text.startswith("/"))
async def handle_private_text(message: Message, bot: Bot):
    """Обработка произвольных сообщений в личке — через Claude понимаем что хочет."""
    if not message.text:
        return

    is_owner = message.from_user.id == settings.owner_telegram_id

    # Магазин-режим — для владельца. Также для всех если активна история или есть keywords.
    # Gmail-вопросы (только для владельца) идут в этот же режим: shop_chat теперь
    # содержит и gmail_chat_tools, поэтому Claude сам выберет правильный инструмент.
    has_shop_history = claude_service.has_active_shop_history(message.from_user.id)
    gmail_intent = is_owner and _looks_like_gmail_request(message.text)
    if has_shop_history or _looks_like_shop_request(message.text) or gmail_intent:
        try:
            answer, photos = await claude_service.shop_chat(
                message.text, message.from_user.id, is_owner=is_owner,
            )
        except Exception as e:
            log.error(f"shop_chat failed: {e}")
            answer, photos = f"Ошибка: {e}", []
        if photos:
            await _send_shop_photos(message, photos)
        if answer:
            await _send_long(message, answer)
        return

    # Прайс-режим. Owner — полный доступ; остальные — только просмотр.
    has_history = claude_service.has_active_price_history(message.from_user.id)
    if has_history or _looks_like_price_request(message.text):
        try:
            answer, files = await claude_service.price_chat(
                message.text,
                message.from_user.id,
                is_owner=is_owner,
            )
        except Exception as e:
            log.error(f"price_chat failed: {e}")
            answer, files = f"Ошибка: {e}", []
        if files:
            await _send_price_files(message, files)
        if answer:
            await _send_long(message, answer)
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
