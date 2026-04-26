"""
OZON-хендлер для Bishop.

Команды:
    /ozon          — главное меню с кнопками
    /ozon_help     — список команд
    /ozon_check    — проверка соединений (API OZON, ProxyAPI)

Аналитика и заказы:
    /ozon_report   — сводка за вчера (заказы + остатки + AI-анализ)
    /ozon_orders   — заказы за сегодня
    /ozon_products — список товаров
    /ozon_stocks   — остатки на складах
    /ozon_prices   — текущие цены

AI-операции:
    /ozon_seo <product_id>      — улучшить одну карточку
    /ozon_seo_all               — пакетный SEO: пройти по всем товарам
    /ozon_seo_stop              — прервать пакетный SEO
    /ozon_reviews               — необработанные отзывы + AI-ответы
    Фото с подписью product_id:N — загрузить картинку в карточку
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from services.ozon_api import OzonAPI, OzonAPIError
from services.claude_service import ClaudeService, ClaudeError
from services.content_service import ContentService


log = logging.getLogger(__name__)
router = Router(name="ozon")


# ID атрибутов OZON (стандартные для большинства категорий)
ATTR_NAME = 9048
ATTR_DESCRIPTION = 4191


# Кэш черновиков SEO/ответов на отзыв (ожидающих подтверждения кнопкой).
_pending: dict[str, dict] = {}

# Состояние пакетного SEO. Один в момент времени, чтобы не флудить.
_seo_all_active: bool = False
_seo_all_stop: bool = False


# --------------------------------------------------------------------------- #
# Меню
# --------------------------------------------------------------------------- #

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Сводка за вчера", callback_data="ozon:report"),
                InlineKeyboardButton(text="🛒 Заказы сегодня", callback_data="ozon:orders"),
            ],
            [
                InlineKeyboardButton(text="📦 Товары", callback_data="ozon:products"),
                InlineKeyboardButton(text="📍 Остатки", callback_data="ozon:stocks"),
            ],
            [
                InlineKeyboardButton(text="💰 Цены", callback_data="ozon:prices"),
                InlineKeyboardButton(text="💬 Отзывы", callback_data="ozon:reviews"),
            ],
            [
                InlineKeyboardButton(text="✨ SEO всех товаров", callback_data="ozon:seo_all"),
                InlineKeyboardButton(text="📷 Как добавить фото", callback_data="ozon:photo_help"),
            ],
            [
                InlineKeyboardButton(text="🔧 Проверка API", callback_data="ozon:check"),
                InlineKeyboardButton(text="❓ Все команды", callback_data="ozon:help"),
            ],
        ]
    )


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #

@router.message(Command("ozon"))
async def cmd_ozon(message: Message) -> None:
    await message.answer(
        "🤖 <b>OZON-агент Bishop</b>\n\nВыбери действие:",
        reply_markup=main_menu_kb(),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("ozon_help"))
async def cmd_help(message: Message) -> None:
    text = (
        "<b>Команды OZON-агента:</b>\n\n"
        "<b>Меню:</b>\n"
        "/ozon — главное меню с кнопками\n"
        "/ozon_check — проверить подключения\n\n"
        "<b>Аналитика и заказы:</b>\n"
        "/ozon_report — сводка за вчера\n"
        "/ozon_orders — заказы за сегодня\n"
        "/ozon_products — список товаров\n"
        "/ozon_stocks — остатки\n"
        "/ozon_prices — текущие цены\n\n"
        "<b>AI-операции:</b>\n"
        "/ozon_seo &lt;product_id&gt; — улучшить одну карточку\n"
        "/ozon_seo_all — пакетный SEO: пройти по всем товарам\n"
        "/ozon_seo_stop — прервать пакетный SEO\n"
        "/ozon_reviews — отзывы + AI-ответы\n"
        "Фото с подписью <code>product_id:54576571</code> — добавить картинку в карточку"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("ozon_check"))
async def cmd_check(message: Message) -> None:
    await _run_check(message)


@router.message(Command("ozon_report"))
async def cmd_report(message: Message) -> None:
    await _run_report(message)


@router.message(Command("ozon_orders"))
async def cmd_orders(message: Message) -> None:
    await _run_orders_today(message)


@router.message(Command("ozon_products"))
async def cmd_products(message: Message) -> None:
    await _run_products(message)


@router.message(Command("ozon_stocks"))
async def cmd_stocks(message: Message) -> None:
    await _run_stocks(message)


@router.message(Command("ozon_prices"))
async def cmd_prices(message: Message) -> None:
    await _run_prices(message)


@router.message(Command("ozon_seo"))
async def cmd_seo(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "Укажи product_id. Пример:\n<code>/ozon_seo 54576571</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        product_id = int(parts[1])
    except ValueError:
        await message.answer("product_id должен быть числом.")
        return
    await _run_seo(message, product_id)


@router.message(Command("ozon_seo_all"))
async def cmd_seo_all(message: Message, bot: Bot) -> None:
    """Запустить пакетный SEO по всем товарам."""
    global _seo_all_active
    if _seo_all_active:
        await message.answer(
            "⚠️ Пакетный SEO уже выполняется. Дождись завершения "
            "или останови командой /ozon_seo_stop."
        )
        return
    # Запускаем в фоне, чтобы не блокировать остальные команды
    asyncio.create_task(_run_seo_all(message, bot))


@router.message(Command("ozon_seo_stop"))
async def cmd_seo_stop(message: Message) -> None:
    """Остановить пакетный SEO после текущего товара."""
    global _seo_all_stop
    if not _seo_all_active:
        await message.answer("Пакетный SEO сейчас не выполняется.")
        return
    _seo_all_stop = True
    await message.answer("⏸ Остановлю после текущего товара…")


@router.message(Command("ozon_reviews"))
async def cmd_reviews(message: Message) -> None:
    await _run_reviews(message)


# --------------------------------------------------------------------------- #
# Callback от инлайн-кнопок
# --------------------------------------------------------------------------- #

@router.callback_query(F.data.startswith("ozon:"))
async def on_callback(call: CallbackQuery, bot: Bot) -> None:
    if not call.message or not isinstance(call.message, Message):
        await call.answer()
        return
    action = call.data.split(":", 1)[1] if call.data else ""
    await call.answer()

    if action == "report":
        await _run_report(call.message)
    elif action == "orders":
        await _run_orders_today(call.message)
    elif action == "products":
        await _run_products(call.message)
    elif action == "stocks":
        await _run_stocks(call.message)
    elif action == "prices":
        await _run_prices(call.message)
    elif action == "reviews":
        await _run_reviews(call.message)
    elif action == "check":
        await _run_check(call.message)
    elif action == "seo_all":
        global _seo_all_active
        if _seo_all_active:
            await call.message.answer(
                "⚠️ Пакетный SEO уже выполняется. /ozon_seo_stop для остановки."
            )
        else:
            asyncio.create_task(_run_seo_all(call.message, bot))
    elif action == "photo_help":
        await call.message.answer(
            "📷 <b>Как добавить фото в карточку</b>\n\n"
            "<b>Главное:</b> существующие фото <b>сохраняются</b>, новые добавляются в конец. "
            "Лимит OZON — 15 фото на карточку.\n\n"
            "<b>Способ 1 — одно фото с подписью:</b>\n"
            "Прикрепи фото → в подпись напиши <code>product_id:54576571</code>\n\n"
            "<b>Способ 2 — несколько фото пачкой:</b>\n"
            "Выдели в галерее 2+ фото → отправь альбомом → "
            "у первого фото в подписи напиши <code>product_id:54576571</code>\n\n"
            "<b>Способ 3 — пачкой в два шага:</b>\n"
            "1. Пришли несколько фото (по одному или альбомом, без подписи)\n"
            "2. Следующим сообщением: <code>product_id:54576571</code>\n"
            "Бот загрузит все накопленные фото разом.\n\n"
            "<b>Поддерживается:</b> JPG/PNG как фото или как файл (оригинал без сжатия — лучше).",
            parse_mode=ParseMode.HTML,
        )
    elif action == "help":
        await cmd_help(call.message)


@router.callback_query(F.data.startswith("seo:"))
async def on_seo_callback(call: CallbackQuery) -> None:
    """Применить или отклонить улучшение карточки."""
    if not call.message or not isinstance(call.message, Message) or not call.data:
        await call.answer()
        return
    _, action, token = call.data.split(":", 2)
    draft = _pending.pop(token, None)
    await call.answer()

    if not draft:
        await call.message.answer("⚠️ Срок действия черновика истёк, запусти /ozon_seo заново.")
        return

    if action == "cancel":
        await call.message.answer(f"❌ Изменения для <code>{draft.get('offer_id', '?')}</code> отклонены.", parse_mode=ParseMode.HTML)
        return

    try:
        api = OzonAPI()
        items = [
            {
                "offer_id": draft["offer_id"],
                "attributes": [
                    {"complex_id": 0, "id": ATTR_NAME, "values": [{"value": draft["name"]}]},
                    {"complex_id": 0, "id": ATTR_DESCRIPTION, "values": [{"value": draft["description"]}]},
                ],
            }
        ]
        result = await api.update_product_attributes(items)
        await call.message.answer(
            f"✅ <code>{draft['offer_id']}</code> отправлен на модерацию.\n"
            f"task_id: <code>{result.get('task_id', '?')}</code>",
            parse_mode=ParseMode.HTML,
        )
    except OzonAPIError as e:
        await call.message.answer(
            f"❌ OZON отклонил [{e.status}]:\n<code>{e.message[:500]}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await call.message.answer(f"❌ Ошибка: {e}")


@router.callback_query(F.data.startswith("review:"))
async def on_review_callback(call: CallbackQuery) -> None:
    """Опубликовать или отклонить ответ на отзыв."""
    if not call.message or not isinstance(call.message, Message) or not call.data:
        await call.answer()
        return
    _, action, token = call.data.split(":", 2)
    draft = _pending.pop(token, None)
    await call.answer()

    if not draft:
        await call.message.answer("⚠️ Срок действия черновика истёк, запусти /ozon_reviews заново.")
        return

    if action == "cancel":
        await call.message.answer("❌ Ответ не опубликован.")
        return

    try:
        api = OzonAPI()
        await api.reply_to_review(draft["review_id"], draft["text"], mark_as_processed=True)
        await call.message.answer(
            f"✅ Ответ опубликован на отзыв <code>{draft['review_id']}</code>.",
            parse_mode=ParseMode.HTML,
        )
    except OzonAPIError as e:
        await call.message.answer(
            f"❌ OZON отклонил публикацию [{e.status}]:\n<code>{e.message[:500]}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await call.message.answer(f"❌ Ошибка: {e}")


# --------------------------------------------------------------------------- #
# Загрузка фото в карточку
# --------------------------------------------------------------------------- #

# Запоминаем последние фото от пользователя (накопительно).
# Сбрасывается после успешной отправки в OZON или по таймауту.
_pending_photos: dict[tuple[int, int], list[str]] = {}

# Буфер для альбомов: media_group_id → список file_id.
# Telegram присылает альбом несколькими сообщениями подряд с одинаковым media_group_id.
_album_buffer: dict[str, list[str]] = {}


def _add_pending_photo(chat_id: int, user_id: int, file_id: str) -> int:
    key = (chat_id, user_id)
    bucket = _pending_photos.setdefault(key, [])
    if file_id not in bucket:
        bucket.append(file_id)
    return len(bucket)


def _take_pending_photos(chat_id: int, user_id: int) -> list[str]:
    return _pending_photos.pop((chat_id, user_id), [])


@router.message(F.photo & F.caption.regexp(r"product_id\s*:\s*\d+"))
async def on_photo_with_caption(message: Message, bot: Bot) -> None:
    """Фото с подписью `product_id:N` → грузим в карточку (с учётом альбома)."""
    caption = message.caption or ""
    match = re.search(r"product_id\s*:\s*(\d+)", caption)
    if not match or not message.photo:
        return
    product_id = int(match.group(1))
    file_id = message.photo[-1].file_id

    # Если это первое сообщение альбома — будут ещё; собираем все, потом грузим
    if message.media_group_id:
        await _handle_album_photo(message, bot, file_id, product_id)
        return

    await _upload_photo_to_ozon(message, bot, product_id, [file_id])


@router.message(F.photo)
async def on_photo_without_caption(message: Message) -> None:
    """Фото без подписи. Запоминаем; ждём product_id отдельным сообщением."""
    if not message.photo or not message.from_user:
        return
    file_id = message.photo[-1].file_id

    if message.media_group_id:
        # Альбом без подписи — копим в общий буфер пользователя
        await _handle_album_photo(message, None, file_id, product_id=None)
        return

    count = _add_pending_photo(message.chat.id, message.from_user.id, file_id)
    if count == 1:
        await message.answer(
            "📷 Фото получил. Можешь прислать ещё фото или сразу написать:\n"
            "<code>product_id:54576571</code>",
            parse_mode=ParseMode.HTML,
        )


# --- Картинка как ДОКУМЕНТ -------------------------------------------------- #

def _is_image_document(message: Message) -> bool:
    if not message.document:
        return False
    mime = (message.document.mime_type or "").lower()
    return mime.startswith("image/")


@router.message(F.document & F.caption.regexp(r"product_id\s*:\s*\d+"))
async def on_doc_image_with_caption(message: Message, bot: Bot) -> None:
    """Картинка как файл с подписью."""
    if not _is_image_document(message) or not message.document:
        return
    caption = message.caption or ""
    match = re.search(r"product_id\s*:\s*(\d+)", caption)
    if not match:
        return
    product_id = int(match.group(1))
    await _upload_photo_to_ozon(message, bot, product_id, [message.document.file_id])


@router.message(F.document)
async def on_doc_image_without_caption(message: Message) -> None:
    """Картинка как файл без подписи. Накапливаем."""
    if not _is_image_document(message) or not message.document or not message.from_user:
        return
    count = _add_pending_photo(message.chat.id, message.from_user.id, message.document.file_id)
    if count == 1:
        await message.answer(
            "📎 Картинку (файл) получил. Можешь прислать ещё или сразу написать:\n"
            "<code>product_id:54576571</code>",
            parse_mode=ParseMode.HTML,
        )


# --- Команда product_id отдельным сообщением -------------------------------- #

@router.message(F.text.regexp(r"^\s*product_id\s*:\s*\d+\s*$"))
async def on_product_id_after_photo(message: Message, bot: Bot) -> None:
    """Текст `product_id:N` отдельным сообщением — грузим все накопленные фото."""
    if not message.text or not message.from_user:
        return
    match = re.search(r"product_id\s*:\s*(\d+)", message.text)
    if not match:
        return
    product_id = int(match.group(1))

    file_ids = _take_pending_photos(message.chat.id, message.from_user.id)
    if not file_ids:
        await message.answer(
            "📷 В памяти нет фото. Сначала пришли картинку (или несколько), потом этот код.",
            parse_mode=ParseMode.HTML,
        )
        return
    await _upload_photo_to_ozon(message, bot, product_id, file_ids)


# --- Альбом (несколько фото одним сообщением) ------------------------------- #

async def _handle_album_photo(
    message: Message,
    bot: Bot | None,
    file_id: str,
    product_id: int | None,
) -> None:
    """
    Накапливаем фото из media_group и через 1.5 секунды грузим всё пачкой
    (1.5 сек — Telegram отправляет элементы альбома почти одновременно).
    """
    group_id = message.media_group_id or ""
    bucket = _album_buffer.setdefault(group_id, [])
    is_first = len(bucket) == 0
    if file_id not in bucket:
        bucket.append(file_id)

    if not is_first:
        return  # таймер уже запущен первым сообщением альбома

    # Запускаем отложенную обработку альбома
    async def _process_album():
        await asyncio.sleep(1.5)
        ids = _album_buffer.pop(group_id, [])
        if not ids:
            return

        if product_id is not None and bot is not None:
            # Альбом с подписью — сразу грузим в указанный product_id
            await _upload_photo_to_ozon(message, bot, product_id, ids)
        elif message.from_user:
            # Альбом без подписи — складываем в общий буфер пользователя
            for fid in ids:
                _add_pending_photo(message.chat.id, message.from_user.id, fid)
            await message.answer(
                f"📷 Получил альбом: {len(ids)} фото. Пришли отдельным сообщением:\n"
                f"<code>product_id:54576571</code>",
                parse_mode=ParseMode.HTML,
            )

    asyncio.create_task(_process_album())


async def _upload_photo_to_ozon(
    message: Message, bot: Bot, product_id: int, file_ids: list[str]
) -> None:
    """
    Загрузить одну или несколько картинок в карточку OZON.

    ВАЖНО: метод /v1/product/pictures/import заменяет ВСЕ картинки.
    Поэтому сначала достаём существующие и добавляем новые в конец.
    """
    if not file_ids:
        return
    n = len(file_ids)
    await message.answer(
        f"⏳ Загружаю {n} фото в карточку <code>{product_id}</code> "
        f"(сохраняю существующие)…",
        parse_mode=ParseMode.HTML,
    )

    try:
        api = OzonAPI()

        # 1. Достаём текущие картинки, чтобы не затереть их
        existing_urls: list[str] = []
        existing_color: str = ""
        existing_360: list[str] = []
        try:
            current = await api.get_product_pictures([product_id])
            items = current.get("items", []) or current.get("result", []) or []
            if items:
                first = items[0] if isinstance(items, list) else items
                existing_urls = list(first.get("images", []) or [])
                existing_color = first.get("color_image", "") or ""
                existing_360 = list(first.get("images360", []) or [])
        except OzonAPIError as e:
            log.warning(f"Could not fetch existing pictures for {product_id}: {e}")
            # Продолжаем — лучше хоть как-то загрузить, чем не загрузить вовсе
        except Exception as e:
            log.warning(f"Unexpected error fetching pictures for {product_id}: {e}")

        # 2. Готовим URL новых файлов из Telegram
        new_urls: list[str] = []
        for fid in file_ids:
            file = await bot.get_file(fid)
            if not file.file_path:
                continue
            new_urls.append(f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}")

        if not new_urls:
            await message.answer("❌ Не удалось получить файлы из Telegram.")
            return

        # 3. Объединяем: существующие + новые. OZON лимит — 15 картинок на товар.
        combined = existing_urls + new_urls
        if len(combined) > 15:
            combined = combined[-15:]  # оставляем последние 15
            await message.answer(
                f"⚠️ В карточке уже было {len(existing_urls)} фото. "
                f"OZON лимит — 15, оставлю самые свежие."
            )

        # 4. Грузим
        log.info(
            f"OZON pictures upload: product_id={product_id}, "
            f"existing={len(existing_urls)}, new={len(new_urls)}, "
            f"combined={len(combined)}, has_color={bool(existing_color)}, "
            f"has_360={len(existing_360)}"
        )
        result = await api.upload_product_pictures(
            product_id=product_id,
            images=combined,
            color_image=existing_color,
            images360=existing_360,
        )
    except OzonAPIError as e:
        log.warning(f"OZON pictures upload failed [{e.status}]: {e.message}")
        # Дружелюбное объяснение известных кодов
        hint = ""
        if e.status == 400 and "VALIDATION" in e.message.upper():
            hint = (
                "\n\n💡 Возможные причины:\n"
                "• Telegram-ссылка истекла (попробуй ещё раз — у каждой загрузки свой URL)\n"
                "• Картинка слишком большая или нестандартный формат\n"
                "• Превышен лимит 15 фото на карточку"
            )
        await message.answer(
            f"❌ OZON отклонил загрузку [{e.status}]:\n<code>{_html_escape(e.message[:500])}</code>{hint}",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        log.exception("Pictures upload error")
        await message.answer(f"❌ Ошибка: {e}")
        return

    # OZON в ответе возвращает массив с pictureId/state
    pictures = result.get("result", {}).get("pictures", []) or result.get("pictures", []) or []
    total_in_card = len(combined)
    await message.answer(
        f"✅ Загружено новых: <b>{n}</b>\n"
        f"Всего в карточке после загрузки: <b>{total_in_card}</b>\n"
        f"product_id: <code>{product_id}</code>\n\n"
        f"Картинки уйдут на модерацию OZON, появятся через несколько часов.",
        parse_mode=ParseMode.HTML,
    )


# --------------------------------------------------------------------------- #
# Реализация команд
# --------------------------------------------------------------------------- #

async def _run_check(message: Message) -> None:
    lines = ["🔧 <b>Проверка подключений</b>\n"]
    try:
        api = OzonAPI()
        result = await api.get_products_list(limit=1)
        total = result.get("result", {}).get("total", "?")
        lines.append(f"✅ OZON API: товаров в магазине ~{total}")
    except OzonAPIError as e:
        lines.append(f"❌ OZON API [{e.status}]: {e.endpoint}")
    except Exception as e:
        lines.append(f"❌ OZON API: {e}")

    try:
        claude = ClaudeService()
        answer = await claude.ask("Скажи одним словом: ок?", max_tokens=20)
        lines.append(f"✅ Claude (ProxyAPI): {answer.strip()[:50]}")
    except ClaudeError as e:
        lines.append(f"❌ Claude: {e}")
    except Exception as e:
        lines.append(f"❌ Claude: {e}")

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def _run_orders_today(message: Message) -> None:
    await message.answer("⏳ Загружаю заказы за сегодня…")
    try:
        api = OzonAPI()
        msk = timezone(timedelta(hours=3))
        now_msk = datetime.now(msk)
        since = now_msk.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        to = datetime.now(timezone.utc)
        data = await api.get_fbs_orders(since=since, to=to, limit=100)
    except OzonAPIError as e:
        await message.answer(
            f"❌ Ошибка OZON [{e.status}]:\n<code>{e.endpoint}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    postings = _extract_postings(data)
    if not postings:
        await message.answer("📭 Сегодня заказов FBS пока нет.")
        return
    text = _format_orders(postings, header=f"🛒 <b>Заказы FBS за сегодня</b> ({len(postings)} шт.)")
    await message.answer(text, parse_mode=ParseMode.HTML)


async def _run_products(message: Message) -> None:
    await message.answer("⏳ Загружаю товары…")
    try:
        api = OzonAPI()
        data = await api.get_products_list(limit=20)
    except OzonAPIError as e:
        await message.answer(
            f"❌ Ошибка OZON [{e.status}]:\n<code>{e.endpoint}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    items = data.get("result", {}).get("items", []) or []
    total = data.get("result", {}).get("total", len(items))
    if not items:
        await message.answer("📭 Товаров не найдено.")
        return

    lines = [f"📦 <b>Товары</b> (всего ~{total}, показаны первые {len(items)}):\n"]
    for i, p in enumerate(items, 1):
        offer = p.get("offer_id", "?")
        pid = p.get("product_id", "?")
        lines.append(f"{i}. <code>{offer}</code> — id <code>{pid}</code>")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def _run_stocks(message: Message) -> None:
    await message.answer("⏳ Загружаю остатки…")
    try:
        api = OzonAPI()
        data = await api.get_stock_on_warehouses(limit=100)
    except OzonAPIError as e:
        await message.answer(
            f"❌ Ошибка OZON [{e.status}]:\n<code>{e.endpoint}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    rows = data.get("result", {}).get("rows", []) or []
    if not rows:
        await message.answer("📭 Остатков на складах нет (товары не отгружены на FBO).")
        return

    lines = [f"📍 <b>Остатки на складах</b> ({len(rows)} позиций):\n"]
    rows_sorted = sorted(rows, key=lambda r: -(r.get("free_to_sell_amount") or 0))
    for r in rows_sorted[:20]:
        sku = r.get("item_code") or r.get("offer_id") or "?"
        wh = r.get("warehouse_name", "?")
        free = r.get("free_to_sell_amount", 0)
        lines.append(f"• <code>{sku}</code> @ {wh}: <b>{free}</b> шт.")
    if len(rows_sorted) > 20:
        lines.append(f"\n…и ещё {len(rows_sorted) - 20} позиций")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


async def _run_prices(message: Message) -> None:
    await message.answer("⏳ Загружаю цены…")
    try:
        api = OzonAPI()
        data = await api.get_prices(limit=50)
    except OzonAPIError as e:
        await message.answer(
            f"❌ Ошибка OZON [{e.status}]:\n<code>{e.endpoint}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    items = data.get("result", {}).get("items", []) or []
    if not items:
        await message.answer("📭 Цен не найдено.")
        return

    lines = [f"💰 <b>Цены</b> (показано {min(20, len(items))} из {len(items)}):\n"]
    for it in items[:20]:
        offer = it.get("offer_id", "?")
        price = (it.get("price") or {}).get("price", "?")
        old_price = (it.get("price") or {}).get("old_price", "")
        marketing_price = (it.get("price") or {}).get("marketing_price", "")
        old = f" (было {old_price})" if old_price and old_price != "0" else ""
        mp = f" • акция {marketing_price}" if marketing_price and marketing_price != "0" else ""
        lines.append(f"• <code>{offer}</code>: <b>{price} ₽</b>{old}{mp}")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# --------------------------------------------------------------------------- #
# SEO одной карточки
# --------------------------------------------------------------------------- #

async def _run_seo(message: Message, product_id: int) -> None:
    """Улучшить название и описание одной карточки."""
    await message.answer(
        f"⏳ Беру карточку <code>{product_id}</code>…",
        parse_mode=ParseMode.HTML,
    )

    try:
        api = OzonAPI()
        attrs_data = await api.get_product_attributes([product_id])
    except OzonAPIError as e:
        await message.answer(
            f"❌ OZON [{e.status}]: {e.endpoint}\n<code>{e.message[:300]}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    items = attrs_data.get("result", []) or []
    if not items:
        await message.answer("❌ Товар не найден.")
        return
    item = items[0]
    offer_id = item.get("offer_id", "")
    name = item.get("name", "")
    description = ""
    for attr in item.get("attributes", []) or []:
        if attr.get("attribute_id") == ATTR_DESCRIPTION:
            values = attr.get("values", []) or []
            if values:
                description = values[0].get("value", "")
                break

    if not name:
        await message.answer("❌ У товара пустое название — не с чем работать.")
        return

    await message.answer("🤖 Готовлю улучшения через Claude…")
    try:
        content = ContentService()
        result = await content.improve_product_card(
            current_name=name,
            current_description=description,
            offer_id=offer_id,
        )
    except ClaudeError as e:
        await message.answer(f"❌ Claude недоступен: {e}")
        return

    new_name = result.get("name", name).strip()
    new_desc = result.get("description", description).strip()
    rationale = result.get("rationale", "").strip()

    await _send_seo_preview(
        message, product_id, offer_id, name, description, new_name, new_desc, rationale
    )


async def _send_seo_preview(
    message: Message,
    product_id: int,
    offer_id: str,
    old_name: str,
    old_desc: str,
    new_name: str,
    new_desc: str,
    rationale: str,
) -> None:
    """Показать «было/стало» с кнопками применения."""
    token = _make_token()
    _pending[token] = {
        "offer_id": offer_id,
        "product_id": product_id,
        "name": new_name,
        "description": new_desc,
    }

    text = (
        f"<b>SEO-улучшение</b> <code>{product_id}</code>\n"
        f"Артикул: <code>{offer_id}</code>\n\n"
        f"<b>Название было:</b>\n{_html_escape(old_name)}\n\n"
        f"<b>Стало:</b>\n{_html_escape(new_name)}\n\n"
        f"<b>Описание было</b> ({len(old_desc)} симв.):\n{_html_escape(old_desc[:300])}"
        f"{'…' if len(old_desc) > 300 else ''}\n\n"
        f"<b>Стало</b> ({len(new_desc)} симв.):\n{_html_escape(new_desc[:300])}"
        f"{'…' if len(new_desc) > 300 else ''}"
    )
    if rationale:
        text += f"\n\n<i>{_html_escape(rationale)}</i>"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Применить", callback_data=f"seo:apply:{token}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"seo:cancel:{token}"),
            ]
        ]
    )
    # Telegram режет сообщения после 4096 символов — обрезаем безопасно
    if len(text) > 4000:
        text = text[:3990] + "…"
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# --------------------------------------------------------------------------- #
# Пакетный SEO по всем товарам
# --------------------------------------------------------------------------- #

# Пауза между товарами, чтобы не флудить чат и не упереться в rate-limits
_SEO_ALL_DELAY_SEC = 2.0


async def _run_seo_all(message: Message, bot: Bot) -> None:
    """Пройти по всем товарам, для каждого предложить SEO-улучшение."""
    global _seo_all_active, _seo_all_stop
    _seo_all_active = True
    _seo_all_stop = False

    try:
        await message.answer(
            "⏳ Беру все товары магазина…\n"
            "Для каждого подготовлю превью «было/стало» с кнопками. "
            "Прервать в любой момент: /ozon_seo_stop"
        )

        # 1. Собираем полный список товаров с пагинацией
        api = OzonAPI()
        all_products: list[dict] = []
        last_id = ""
        try:
            while True:
                page = await api.get_products_list(limit=200, last_id=last_id)
                items = page.get("result", {}).get("items", []) or []
                all_products.extend(items)
                last_id = page.get("result", {}).get("last_id", "") or ""
                if not last_id or not items:
                    break
        except OzonAPIError as e:
            await message.answer(
                f"❌ OZON [{e.status}]: {e.endpoint}\n<code>{e.message[:300]}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        if not all_products:
            await message.answer("📭 Товаров не нашлось.")
            return

        await message.answer(f"📦 Товаров в магазине: <b>{len(all_products)}</b>", parse_mode=ParseMode.HTML)

        # 2. По одному товару: тянем атрибуты, шлём в Claude, показываем превью
        content = ContentService()
        processed = 0
        skipped = 0
        errors = 0

        for i, prod in enumerate(all_products, 1):
            if _seo_all_stop:
                await message.answer(f"⏸ Остановлено. Обработано: {processed}/{len(all_products)}")
                return

            product_id = prod.get("product_id")
            if not product_id:
                skipped += 1
                continue

            try:
                attrs_data = await api.get_product_attributes([int(product_id)])
                items = attrs_data.get("result", []) or []
                if not items:
                    skipped += 1
                    continue
                item = items[0]
                offer_id = item.get("offer_id", "")
                name = item.get("name", "")
                description = ""
                for attr in item.get("attributes", []) or []:
                    if attr.get("attribute_id") == ATTR_DESCRIPTION:
                        values = attr.get("values", []) or []
                        if values:
                            description = values[0].get("value", "")
                            break

                if not name:
                    skipped += 1
                    continue

                # Прогресс-индикатор каждые 5 товаров
                if i % 5 == 1:
                    await message.answer(
                        f"⚙️ Обрабатываю {i}/{len(all_products)} (ок: {processed}, пропуск: {skipped}, ошибок: {errors})"
                    )

                result = await content.improve_product_card(
                    current_name=name,
                    current_description=description,
                    offer_id=offer_id,
                )

                new_name = result.get("name", name).strip()
                new_desc = result.get("description", description).strip()
                rationale = result.get("rationale", "").strip()

                await _send_seo_preview(
                    message,
                    int(product_id),
                    offer_id,
                    name,
                    description,
                    new_name,
                    new_desc,
                    rationale,
                )
                processed += 1

            except OzonAPIError as e:
                errors += 1
                log.warning(f"OZON error for product {product_id}: {e}")
                await message.answer(
                    f"⚠️ Пропустил <code>{product_id}</code>: OZON [{e.status}] {e.message[:200]}",
                    parse_mode=ParseMode.HTML,
                )
            except ClaudeError as e:
                errors += 1
                log.warning(f"Claude error for product {product_id}: {e}")
                await message.answer(f"⚠️ Пропустил <code>{product_id}</code>: AI {e}", parse_mode=ParseMode.HTML)
            except Exception as e:
                errors += 1
                log.exception(f"Unexpected error for product {product_id}")
                await message.answer(f"⚠️ Пропустил <code>{product_id}</code>: {e}", parse_mode=ParseMode.HTML)

            await asyncio.sleep(_SEO_ALL_DELAY_SEC)

        await message.answer(
            f"✅ <b>Пакетный SEO завершён</b>\n"
            f"Обработано: {processed}\n"
            f"Пропущено: {skipped}\n"
            f"Ошибок: {errors}\n\n"
            f"Просмотри превью выше и применяй нужные кнопкой ✅.",
            parse_mode=ParseMode.HTML,
        )
    finally:
        _seo_all_active = False
        _seo_all_stop = False


# --------------------------------------------------------------------------- #
# Отзывы
# --------------------------------------------------------------------------- #

async def _run_reviews(message: Message) -> None:
    """Необработанные отзывы + AI-предложения ответов."""
    await message.answer("⏳ Беру необработанные отзывы…")
    try:
        api = OzonAPI()
        data = await api.get_reviews(status="UNPROCESSED", limit=20)
    except OzonAPIError as e:
        if e.status in (402, 403):
            await message.answer(
                "⚠️ Отзывы доступны только при подписке OZON Premium.\n"
                f"Ответ API: <code>{e.message[:200]}</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        await message.answer(
            f"❌ OZON [{e.status}]: {e.endpoint}\n<code>{e.message[:300]}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    reviews = data.get("reviews", []) or data.get("result", {}).get("reviews", []) or []
    if not reviews:
        await message.answer("📭 Необработанных отзывов нет.")
        return

    content = ContentService()

    for r in reviews[:5]:
        review_id = r.get("id") or r.get("review_id") or ""
        rating = r.get("rating", 5) or 5
        text = r.get("text", "") or ""
        product_name = r.get("product_name", "") or ""

        try:
            suggested = await content.reply_to_review(
                review_text=text, rating=rating, product_name=product_name
            )
        except ClaudeError as e:
            suggested = f"(AI недоступен: {e})"

        token = _make_token()
        _pending[token] = {"review_id": review_id, "text": suggested}

        stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
        body = (
            f"💬 <b>Отзыв</b> {stars}\n"
            f"Товар: {_html_escape(product_name) or '—'}\n"
            f"id: <code>{review_id}</code>\n\n"
            f"<b>Покупатель:</b>\n{_html_escape(text[:600])}"
            f"{'…' if len(text) > 600 else ''}\n\n"
            f"<b>Предлагаемый ответ:</b>\n{_html_escape(suggested)}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"review:apply:{token}"),
                    InlineKeyboardButton(text="❌ Пропустить", callback_data=f"review:cancel:{token}"),
                ]
            ]
        )
        await message.answer(body, reply_markup=kb, parse_mode=ParseMode.HTML)

    if len(reviews) > 5:
        await message.answer(
            f"…и ещё {len(reviews) - 5} отзывов. Обработай эти и запусти /ozon_reviews снова."
        )


# --------------------------------------------------------------------------- #
# Сводка за вчера
# --------------------------------------------------------------------------- #

async def _run_report(message: Message) -> None:
    await message.answer("⏳ Собираю данные за вчера и готовлю сводку…")

    msk = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk)
    yesterday_start_msk = (now_msk - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    yesterday_end_msk = yesterday_start_msk + timedelta(days=1)
    since = yesterday_start_msk.astimezone(timezone.utc)
    to = yesterday_end_msk.astimezone(timezone.utc)

    try:
        api = OzonAPI()
        orders_data = await api.get_fbs_orders(since=since, to=to, limit=200)
        stocks_data = await api.get_stock_on_warehouses(limit=200)
    except OzonAPIError as e:
        await message.answer(
            f"❌ Не получилось забрать данные из OZON [{e.status}]:\n"
            f"<code>{e.endpoint}</code>\n\n{e.message[:300]}",
            parse_mode=ParseMode.HTML,
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    postings = _extract_postings(orders_data)
    stocks = stocks_data.get("result", {}).get("rows", []) or []

    total_orders = len(postings)
    cancelled = sum(1 for p in postings if p.get("status") == "cancelled")
    revenue = 0.0
    units_sold = 0
    sku_counter: dict[str, int] = {}
    for p in postings:
        for prod in p.get("products", []) or []:
            qty = prod.get("quantity", 0) or 0
            price = float(prod.get("price", 0) or 0)
            revenue += price * qty
            units_sold += qty
            offer = prod.get("offer_id", "?")
            sku_counter[offer] = sku_counter.get(offer, 0) + qty

    top_sku = sorted(sku_counter.items(), key=lambda x: -x[1])[:5]
    low_stock = [r for r in stocks if (r.get("free_to_sell_amount") or 0) < 5]

    summary_data = {
        "date": yesterday_start_msk.strftime("%d.%m.%Y"),
        "orders_total": total_orders,
        "orders_cancelled": cancelled,
        "revenue": round(revenue, 2),
        "units_sold": units_sold,
        "top_sku": top_sku,
        "low_stock_count": len(low_stock),
        "low_stock_examples": [
            f"{r.get('item_code', '?')} @ {r.get('warehouse_name', '?')}: {r.get('free_to_sell_amount', 0)}"
            for r in low_stock[:5]
        ],
    }

    try:
        content = ContentService()
        analysis = await content.make_daily_summary(summary_data)
    except ClaudeError as e:
        await message.answer(
            f"⚠️ Claude недоступен ({e}), вот сырые данные:\n\n"
            f"<pre>{json.dumps(summary_data, ensure_ascii=False, indent=2)}</pre>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await message.answer(analysis, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await message.answer(analysis)


# --------------------------------------------------------------------------- #
# Утренняя сводка по расписанию
# --------------------------------------------------------------------------- #

async def send_daily_report(bot: Bot, chat_id: int | str) -> None:
    """Отправить утреннюю сводку. Вызывается планировщиком."""

    class _Adapter:
        def __init__(self, bot: Bot, chat_id):
            self._bot = bot
            self._chat_id = chat_id

        async def answer(self, text: str, **kwargs):
            await self._bot.send_message(self._chat_id, text, **kwargs)

    await _run_report(_Adapter(bot, chat_id))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Хелперы
# --------------------------------------------------------------------------- #

def _extract_postings(data: dict) -> list[dict]:
    """Достаёт список заказов из ответа OZON независимо от формы result."""
    result = data.get("result", [])
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("postings", []) or []
    return []


def _format_orders(postings: list[dict], header: str) -> str:
    lines = [header, ""]
    for p in postings[:10]:
        num = p.get("posting_number", "?")
        status = p.get("status", "?")
        products = p.get("products", []) or []
        items = ", ".join(
            f"{pr.get('offer_id', '?')}×{pr.get('quantity', 0)}" for pr in products[:3]
        )
        if len(products) > 3:
            items += f" +{len(products) - 3}"
        lines.append(f"• <code>{num}</code> [{status}] {items}")
    if len(postings) > 10:
        lines.append(f"\n…и ещё {len(postings) - 10} заказов")
    return "\n".join(lines)


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _make_token() -> str:
    """Короткий уникальный токен для callback_data (Telegram лимит — 64 байта)."""
    return secrets.token_urlsafe(8)
