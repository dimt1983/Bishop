"""
Бизнес-мониторинг: проверяет СМЫСЛ данных, а не только HTTP-код.

В отличие от uptime_service (200 OK = жив), этот проверяет что:
- Каталог TG-бота возвращает реальные товары (products > 0)
- Девид имеет каталог в памяти (debug/catalog total > 0)
- (опционально) Можно добавить ещё чеки

Шлёт алерт владельцу при первом обнаружении проблемы и при восстановлении.
Состояние хранится в памяти процесса (теряется при рестарте — это OK).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from aiogram import Bot

from config import settings

log = logging.getLogger(__name__)

# Конфигурация чеков. Расширять по мере необходимости.
TG_BOT_PUBLIC_URL = "https://tg-bot-production-ae5c.up.railway.app"
DAVID_URL = "https://wahelp-agent-production.up.railway.app"

# In-memory состояние: {check_name: bool}
_LAST_OK: dict[str, Optional[bool]] = {}


async def _check_tg_bot_catalog(orders_token: str) -> tuple[bool, str]:
    """TG-бот /sync должен вернуть products с длиной > 0."""
    url = f"{TG_BOT_PUBLIC_URL}/sync"
    headers = {"Authorization": f"Bearer {orders_token}"} if orders_token else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(url, headers=headers)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        data = r.json()
        products = data.get("products", [])
        if not products:
            return False, "products пустой"
        in_stock = sum(1 for p in products if (p.get("stock") or 0) > 0)
        return True, f"{len(products)} товаров, {in_stock} в наличии"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"


async def _check_david_catalog() -> tuple[bool, str]:
    """Девид /debug/catalog должен показывать total > 0."""
    url = f"{DAVID_URL}/debug/catalog"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(url)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        stats = r.json().get("stats", {})
        total = stats.get("total", 0)
        if total == 0:
            return False, "catalog total=0 (Девид не подгрузил товары)"
        return True, f"total={total}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"


async def _check_david_mode() -> tuple[bool, str]:
    """Девид /health должен быть в comment_v2 (текущий боевой режим)."""
    url = f"{DAVID_URL}/health"
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(url)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        d = r.json()
        mode = d.get("mode", "?")
        if mode != "comment_v2":
            return False, f"mode={mode} (ожидается comment_v2)"
        return True, f"mode={mode}, whitelist={d.get('whitelist_count', '?')}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"


CHECKS = {
    "tg_bot_catalog": ("📦 TG-бот: каталог", _check_tg_bot_catalog),
    "david_catalog": ("🤖 Девид: каталог", _check_david_catalog),
    "david_mode": ("⚙️  Девид: режим", _check_david_mode),
}


def _orders_token() -> str:
    # Девидовский токен — он же для /sync TG-бота
    import os
    return os.environ.get("API_ORDERS_TOKEN", "")


async def run_health_checks(bot: Bot) -> None:
    """Один цикл проверок с алертами при смене состояния. Запускать по таймеру."""
    if not settings.owner_telegram_id:
        return

    token = _orders_token()
    for key, (name, fn) in CHECKS.items():
        try:
            if fn is _check_tg_bot_catalog:
                ok, msg = await fn(token)
            else:
                ok, msg = await fn()
        except Exception as e:
            log.exception("business_health check %s crashed: %s", key, e)
            continue

        prev = _LAST_OK.get(key)
        _LAST_OK[key] = ok

        # Алерт только при смене или при первой DOWN
        if prev is None and ok:
            continue  # baseline: тихо принимаем UP
        if prev is None and not ok:
            await _send(bot, f"🔴 <b>{name}</b> — DOWN\n{msg}")
            continue
        if prev != ok:
            if ok:
                await _send(bot, f"🟢 <b>{name}</b> — снова OK\n{msg}")
            else:
                await _send(bot, f"🔴 <b>{name}</b> — DOWN\n{msg}")


async def _send(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(
            settings.owner_telegram_id, text,
            parse_mode="HTML", disable_web_page_preview=True,
        )
    except Exception as e:
        log.exception("business_health send failed: %s", e)


async def get_status_snapshot() -> str:
    """Текущий снимок всех чеков (для команды /health)."""
    token = _orders_token()
    lines = ["💼 <b>Бизнес-чеки</b>", ""]
    for key, (name, fn) in CHECKS.items():
        try:
            if fn is _check_tg_bot_catalog:
                ok, msg = await fn(token)
            else:
                ok, msg = await fn()
            mark = "🟢" if ok else "🔴"
            lines.append(f"{mark} {name}")
            lines.append(f"     <code>{msg}</code>")
        except Exception as e:
            lines.append(f"❓ {name}: <code>{type(e).__name__}</code>")
        lines.append("")
    return "\n".join(lines)
