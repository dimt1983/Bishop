"""
Простой uptime-мониторинг сервисов.

Раз в N секунд пингует список URL-ов из таблицы uptime_monitors. При смене
состояния (UP→DOWN, DOWN→UP) шлёт сообщение в Telegram владельцу.

Низкие зависимости: только httpx + aiogram (через переданный bot).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from aiogram import Bot
from sqlalchemy import select

from database import UptimeMonitor, async_session_maker

log = logging.getLogger(__name__)

# Минимальный интервал — нагрузка на сервисы и не зашумить лог
MIN_INTERVAL = 60
DEFAULT_INTERVAL = 300


async def add_monitor(
    name: str,
    url: str,
    alert_chat_id: int,
    interval_seconds: int = DEFAULT_INTERVAL,
    expected_status: int = 200,
) -> UptimeMonitor:
    interval_seconds = max(MIN_INTERVAL, interval_seconds)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with async_session_maker() as s:
        m = UptimeMonitor(
            name=name[:120],
            url=url[:500],
            expected_status=expected_status,
            alert_chat_id=alert_chat_id,
            interval_seconds=interval_seconds,
            is_active=True,
        )
        s.add(m)
        await s.commit()
        await s.refresh(m)
        return m


async def list_monitors(active_only: bool = False) -> list[UptimeMonitor]:
    async with async_session_maker() as s:
        q = select(UptimeMonitor).order_by(UptimeMonitor.id)
        if active_only:
            q = q.where(UptimeMonitor.is_active == True)
        rs = await s.execute(q)
        return list(rs.scalars().all())


async def set_active(monitor_id: int, active: bool) -> bool:
    async with async_session_maker() as s:
        m = await s.get(UptimeMonitor, monitor_id)
        if not m:
            return False
        m.is_active = active
        await s.commit()
        return True


async def remove_monitor(monitor_id: int) -> bool:
    async with async_session_maker() as s:
        m = await s.get(UptimeMonitor, monitor_id)
        if not m:
            return False
        await s.delete(m)
        await s.commit()
        return True


async def _ping(url: str, expected_status: int, timeout: float = 10.0) -> tuple[bool, Optional[int], Optional[str]]:
    """Возвращает (is_up, http_status, error_text)."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Bishop-Uptime/1.0"})
        return (r.status_code == expected_status, r.status_code, None)
    except httpx.TimeoutException:
        return (False, None, "timeout")
    except httpx.HTTPError as e:
        return (False, None, f"{type(e).__name__}: {e}")
    except Exception as e:
        return (False, None, f"{type(e).__name__}: {e}")


async def _check_one(bot: Bot, m: UptimeMonitor) -> None:
    """Проверка одного монитора + алерт при смене состояния."""
    is_up, status, err = await _ping(m.url, m.expected_status)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    state_changed = (m.is_up is not None) and (m.is_up != is_up)

    async with async_session_maker() as s:
        m_db = await s.get(UptimeMonitor, m.id)
        if not m_db:
            return
        m_db.last_check_at = now
        m_db.last_status = status
        m_db.last_error = err
        prev_up = m_db.is_up
        m_db.is_up = is_up
        if not is_up and prev_up is not False:
            m_db.down_since = now
        elif is_up:
            m_db.down_since = None
        await s.commit()
        m_db_id = m_db.id
        m_name = m_db.name
        m_url = m_db.url
        m_chat = m_db.alert_chat_id
        m_down_since = m_db.down_since

    # Алерт при первой проверке (prev_up is None) только если DOWN.
    # При UP первой проверки тихо принимаем как baseline.
    if prev_up is None:
        if not is_up:
            await _send_alert(bot, m_chat, _down_msg(m_name, m_url, status, err, since=None))
        return

    if state_changed:
        if is_up:
            duration = ""
            if m_down_since is None and m.down_since:
                # Пересчёт длительности из старого значения
                pass
            await _send_alert(bot, m_chat, _up_msg(m_name, m_url, status))
        else:
            await _send_alert(bot, m_chat, _down_msg(m_name, m_url, status, err, since=now))


def _down_msg(name: str, url: str, status: Optional[int], err: Optional[str], since: Optional[datetime]) -> str:
    head = f"🔴 <b>{name}</b> — DOWN"
    body = []
    if status is not None:
        body.append(f"HTTP <code>{status}</code>")
    if err:
        body.append(f"Ошибка: <code>{err}</code>")
    body.append(f"<a href=\"{url}\">{url}</a>")
    return head + "\n" + "\n".join(body)


def _up_msg(name: str, url: str, status: Optional[int]) -> str:
    head = f"🟢 <b>{name}</b> — UP"
    return f"{head}\nHTTP <code>{status or 'OK'}</code>\n<a href=\"{url}\">{url}</a>"


async def _send_alert(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.exception("uptime: send_alert failed: %s", e)


async def uptime_worker(bot: Bot, tick_seconds: int = 60) -> None:
    """Главный цикл: каждые tick_seconds сек проверяет мониторы у которых
    подошёл интервал. Запускать как asyncio task в main."""
    log.info("Uptime worker started (tick=%ss)", tick_seconds)
    while True:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            mons = await list_monitors(active_only=True)
            due: list[UptimeMonitor] = []
            for m in mons:
                if m.last_check_at is None:
                    due.append(m)
                    continue
                elapsed = (now - m.last_check_at).total_seconds()
                if elapsed >= m.interval_seconds:
                    due.append(m)
            if due:
                # Параллельно, но небольшой fan-out чтобы не положить себя
                await asyncio.gather(*(_check_one(bot, m) for m in due))
        except Exception as e:
            log.exception("uptime_worker iteration failed: %s", e)
        await asyncio.sleep(tick_seconds)


def format_monitors_for_telegram(monitors: list[UptimeMonitor]) -> str:
    if not monitors:
        return "📡 Нет настроенных мониторов.\n\nДобавь: <code>/monitor add &lt;url&gt; &lt;имя&gt;</code>"
    lines = [f"📡 <b>Мониторы</b> ({len(monitors)})", ""]
    for m in monitors:
        if not m.is_active:
            mark = "⏸"
        elif m.is_up is None:
            mark = "❓"
        elif m.is_up:
            mark = "🟢"
        else:
            mark = "🔴"
        last = m.last_check_at.strftime("%d.%m %H:%M") if m.last_check_at else "—"
        status = f"HTTP {m.last_status}" if m.last_status else (m.last_error or "—")
        lines.append(f"{mark} <b>#{m.id}</b> {m.name}")
        lines.append(f"     <code>{m.url}</code>")
        lines.append(f"     {status} · проверка: {last} · каждые {m.interval_seconds}с")
        lines.append("")
    lines.append("Команды:")
    lines.append("• <code>/monitor add &lt;url&gt; [имя]</code>")
    lines.append("• <code>/monitor pause &lt;id&gt;</code> / <code>/monitor resume &lt;id&gt;</code>")
    lines.append("• <code>/monitor remove &lt;id&gt;</code>")
    return "\n".join(lines)
