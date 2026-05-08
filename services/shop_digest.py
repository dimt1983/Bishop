"""Утренняя сводка заказов из TG-BOT для владельца.

Дёргает GET /sync на TG-BOT (Bearer-авторизация), фильтрует заказы за
последние сутки, группирует по статусу и шлёт владельцу Telegram-сообщение.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
from aiogram import Bot

from config import settings

log = logging.getLogger(__name__)


STATUS_LABELS = {
    "new":       "🆕 Новые",
    "confirmed": "✅ Подтверждённые",
    "paid":      "💳 Оплачены",
    "shipped":   "🚚 Отправлены",
    "done":      "📦 Выполнены",
    "delivered": "🎉 Доставлены",
    "cancelled": "❌ Отменены",
}


async def fetch_sync_snapshot() -> dict | None:
    """GET /sync — возвращает {orders, users, products} либо None."""
    if not settings.tg_bot_api_token or not settings.tg_bot_url:
        return None
    url = settings.tg_bot_url.rstrip("/") + "/sync"
    headers = {"Authorization": f"Bearer {settings.tg_bot_api_token}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("shop_digest: /sync failed: %s", e)
        return None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def build_digest_text(snapshot: dict, since_hours: int = 24) -> str:
    orders = snapshot.get("orders", []) or []
    users = {u["user_id"]: u for u in (snapshot.get("users") or [])}
    cutoff = datetime.now() - timedelta(hours=since_hours)

    recent = []
    for o in orders:
        dt = _parse_dt(o.get("created_at"))
        if dt and dt >= cutoff:
            recent.append((dt, o))
    recent.sort(key=lambda x: x[0], reverse=True)

    if not recent:
        return (
            f"☕ <b>Сводка по магазину</b>\n"
            f"<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>\n\n"
            f"За последние {since_hours} ч новых заказов нет."
        )

    by_status: dict[str, list] = {}
    total_sum = 0
    for _, o in recent:
        st = (o.get("status") or "new").lower()
        by_status.setdefault(st, []).append(o)
        total_sum += o.get("total") or 0

    lines = [
        f"☕ <b>Сводка по магазину</b>",
        f"<i>{datetime.now().strftime('%d.%m.%Y %H:%M')}</i>",
        f"\nЗа сутки: <b>{len(recent)} заказов · {total_sum:.0f} ₽</b>",
    ]
    # Сводка по статусам
    for st in ("new", "confirmed", "paid", "shipped", "done", "delivered", "cancelled"):
        lst = by_status.get(st)
        if not lst:
            continue
        s = sum((o.get("total") or 0) for o in lst)
        label = STATUS_LABELS.get(st, st)
        lines.append(f"  • {label}: {len(lst)} · {s:.0f} ₽")
    # Прочие статусы которых нет в STATUS_LABELS
    for st, lst in by_status.items():
        if st in STATUS_LABELS:
            continue
        s = sum((o.get("total") or 0) for o in lst)
        lines.append(f"  • {st}: {len(lst)} · {s:.0f} ₽")

    # Список новых (требуют действий) — детально
    new_orders = by_status.get("new", [])
    if new_orders:
        lines.append("\n🆕 <b>Требуют действия:</b>")
        for o in new_orders[:10]:
            uid = o.get("user_id")
            name = o.get("name") or (users.get(uid, {}) or {}).get("name") or "Клиент"
            phone = o.get("phone") or ""
            t = (o.get("created_at") or "")[11:16]
            lines.append(f"  · #{o['id']} · {t} · {name[:24]} · {(o.get('total') or 0):.0f} ₽" + (f" · {phone}" if phone else ""))
        if len(new_orders) > 10:
            lines.append(f"  ... и ещё {len(new_orders) - 10}")

    # Свежеподтверждённые / готовые — короткой строчкой
    if by_status.get("confirmed"):
        lines.append(f"\n✅ В работе: {len(by_status['confirmed'])} · "
                     + ", ".join(f"#{o['id']}" for o in by_status["confirmed"][:8]))
    if by_status.get("done") or by_status.get("delivered"):
        done = (by_status.get("done") or []) + (by_status.get("delivered") or [])
        lines.append(f"📦 Закрыто: {len(done)} · "
                     + ", ".join(f"#{o['id']}" for o in done[:8]))

    return "\n".join(lines)


async def send_morning_orders_digest(bot: Bot) -> None:
    """Утренний дайджест по заказам — шлётся OWNER_TELEGRAM_ID."""
    if not settings.owner_telegram_id:
        return
    snapshot = await fetch_sync_snapshot()
    if snapshot is None:
        try:
            await bot.send_message(
                settings.owner_telegram_id,
                "☕ Сводка по магазину\n\n⚠️ Не удалось получить данные TG-BOT (/sync). "
                "Проверь TG_BOT_URL и TG_BOT_API_TOKEN в env Bishop.",
            )
        except Exception:
            pass
        return
    text = build_digest_text(snapshot, since_hours=24)
    try:
        await bot.send_message(
            settings.owner_telegram_id,
            text[:4000],
            parse_mode="HTML",
        )
    except Exception as e:
        log.exception("morning orders digest send failed: %s", e)
