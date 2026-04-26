"""
OZON-хендлер для Bishop.

Команды:
    /ozon          — главное меню с кнопками
    /ozon_help     — список команд
    /ozon_report   — сводка за вчера (заказы + остатки + AI-анализ)
    /ozon_orders   — заказы за сегодня
    /ozon_products — список товаров
    /ozon_stocks   — остатки на складах
    /ozon_check    — проверка соединений (API OZON, ProxyAPI)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from services.ozon_api import OzonAPI, OzonAPIError
from services.claude_service import ClaudeService, ClaudeError


log = logging.getLogger(__name__)
router = Router(name="ozon")


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
                InlineKeyboardButton(text="🔧 Проверка API", callback_data="ozon:check"),
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
        parse_mode="HTML",
    )


@router.message(Command("ozon_help"))
async def cmd_help(message: Message) -> None:
    text = (
        "<b>Команды OZON-агента:</b>\n\n"
        "/ozon — главное меню\n"
        "/ozon_report — сводка за вчера\n"
        "/ozon_orders — заказы за сегодня\n"
        "/ozon_products — список товаров\n"
        "/ozon_stocks — остатки на складах\n"
        "/ozon_check — проверить подключения\n"
    )
    await message.answer(text, parse_mode="HTML")


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


# --------------------------------------------------------------------------- #
# Callback от инлайн-кнопок
# --------------------------------------------------------------------------- #

@router.callback_query(F.data.startswith("ozon:"))
async def on_callback(call: CallbackQuery) -> None:
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
    elif action == "check":
        await _run_check(call.message)


# --------------------------------------------------------------------------- #
# Реализация команд
# --------------------------------------------------------------------------- #

async def _run_check(message: Message) -> None:
    """Проверка всех подключений: OZON, ProxyAPI."""
    lines = ["🔧 <b>Проверка подключений</b>\n"]

    # OZON
    try:
        api = OzonAPI()
        result = await api.get_products_list(limit=1)
        count = len(result.get("result", {}).get("items", []))
        total = result.get("result", {}).get("total", "?")
        lines.append(f"✅ OZON API: товаров в магазине ~{total} (получен {count})")
    except OzonAPIError as e:
        lines.append(f"❌ OZON API [{e.status}]: {e.endpoint}")
    except Exception as e:
        lines.append(f"❌ OZON API: {e}")

    # ProxyAPI / Claude
    try:
        claude = ClaudeService()
        answer = await claude.ask("Скажи одним словом: ок?", max_tokens=20)
        lines.append(f"✅ Claude (ProxyAPI): {answer.strip()[:50]}")
    except ClaudeError as e:
        lines.append(f"❌ Claude: {e}")
    except Exception as e:
        lines.append(f"❌ Claude: {e}")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def _run_orders_today(message: Message) -> None:
    """Заказы FBS за сегодня."""
    await message.answer("⏳ Загружаю заказы за сегодня…")
    try:
        api = OzonAPI()
        # «Сегодня» в МСК
        msk = timezone(timedelta(hours=3))
        now_msk = datetime.now(msk)
        since = now_msk.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        to = datetime.now(timezone.utc)
        data = await api.get_fbs_orders(since=since, to=to, limit=100)
    except OzonAPIError as e:
        await message.answer(f"❌ Ошибка OZON [{e.status}]:\n<code>{e.endpoint}</code>", parse_mode="HTML")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    postings = _extract_postings(data)
    if not postings:
        await message.answer("📭 Сегодня заказов FBS пока нет.")
        return

    text = _format_orders(postings, header=f"🛒 <b>Заказы FBS за сегодня</b> ({len(postings)} шт.)")
    await message.answer(text, parse_mode="HTML")


async def _run_products(message: Message) -> None:
    """Краткий список товаров."""
    await message.answer("⏳ Загружаю товары…")
    try:
        api = OzonAPI()
        data = await api.get_products_list(limit=20)
    except OzonAPIError as e:
        await message.answer(f"❌ Ошибка OZON [{e.status}]:\n<code>{e.endpoint}</code>", parse_mode="HTML")
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
    await message.answer("\n".join(lines), parse_mode="HTML")


async def _run_stocks(message: Message) -> None:
    """Остатки на складах."""
    await message.answer("⏳ Загружаю остатки…")
    try:
        api = OzonAPI()
        data = await api.get_stock_on_warehouses(limit=100)
    except OzonAPIError as e:
        await message.answer(f"❌ Ошибка OZON [{e.status}]:\n<code>{e.endpoint}</code>", parse_mode="HTML")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    rows = data.get("result", {}).get("rows", []) or []
    if not rows:
        await message.answer("📭 Остатков на складах нет (возможно, товары не отгружены на FBO).")
        return

    lines = [f"📍 <b>Остатки на складах</b> ({len(rows)} позиций):\n"]
    # сортируем по убыванию present
    rows_sorted = sorted(rows, key=lambda r: -(r.get("free_to_sell_amount") or 0))
    for r in rows_sorted[:20]:
        sku = r.get("item_code") or r.get("offer_id") or "?"
        wh = r.get("warehouse_name", "?")
        free = r.get("free_to_sell_amount", 0)
        lines.append(f"• <code>{sku}</code> @ {wh}: <b>{free}</b> шт.")
    if len(rows_sorted) > 20:
        lines.append(f"\n…и ещё {len(rows_sorted) - 20} позиций")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def _run_report(message: Message) -> None:
    """Сводка за вчера: данные → Claude → красивый текст."""
    await message.answer("⏳ Собираю данные за вчера и готовлю сводку…")

    # 1. Собираем данные
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
            parse_mode="HTML",
        )
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    postings = _extract_postings(orders_data)
    stocks = stocks_data.get("result", {}).get("rows", []) or []

    # 2. Агрегация
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

    # 3. Просим Claude причесать
    system = (
        "Ты — аналитик магазина на маркетплейсе OZON. "
        "На вход получаешь JSON с показателями за день. "
        "Сделай короткую сводку: ключевые цифры, что важно, 2–3 рекомендации. "
        "Без лишней воды, по-русски, эмодзи в меру. Не больше 1500 символов."
    )
    user_msg = (
        f"Данные за {summary_data['date']}:\n"
        f"```json\n{json.dumps(summary_data, ensure_ascii=False, indent=2)}\n```"
    )

    try:
        claude = ClaudeService()
        analysis = await claude.ask(user_msg, system=system, max_tokens=1500)
    except ClaudeError as e:
        # Если Claude недоступен — отдаём хотя бы сырую сводку
        await message.answer(
            f"⚠️ Claude недоступен ({e}), вот сырые данные:\n\n"
            f"<pre>{json.dumps(summary_data, ensure_ascii=False, indent=2)}</pre>",
            parse_mode="HTML",
        )
        return

    await message.answer(analysis)


# --------------------------------------------------------------------------- #
# Утренняя сводка по расписанию (вызывается из main.py)
# --------------------------------------------------------------------------- #

async def send_daily_report(bot, chat_id: int | str) -> None:
    """Отправить утреннюю сводку в указанный чат. Вызывается планировщиком."""

    class _Adapter:
        """Минимальный адаптер, чтобы переиспользовать _run_report."""

        def __init__(self, bot, chat_id):
            self._bot = bot
            self._chat_id = chat_id

        async def answer(self, text: str, **kwargs):
            await self._bot.send_message(self._chat_id, text, **kwargs)

    await _run_report(_Adapter(bot, chat_id))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Вспомогательное
# --------------------------------------------------------------------------- #

def _extract_postings(data: dict) -> list[dict]:
    """
    Достаёт список заказов из ответа OZON.

    Формат /v3/posting/fbs/list: {"result": {"postings": [...], "has_next": bool}}
    Но на всякий случай поддерживаем и старый формат, где result — это сразу список.
    """
    result = data.get("result", [])
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("postings", []) or []
    return []


def _format_orders(postings: list[dict], header: str) -> str:
    """Короткое представление списка заказов."""
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
