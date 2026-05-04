"""
Gmail tool-use для Бишепа — даёт Claude возможность отвечать на свободные
вопросы про почту в обычном чате.

Примеры запросов которые теперь работают:
  «бишоп, что у меня в почте от тинькофф?»
  «дай сводку за сегодня»
  «есть ли что-то от поставщиков сегодня?»
  «сколько спама за неделю?»
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Iterable

from config import settings
from services.gmail_classifier import (
    CATEGORIES,
    Classification,
    classify_messages,
)
from services.gmail_tools import GmailMessage, GmailService, _domain

log = logging.getLogger(__name__)


# ─── Tool schemas для Claude ────────────────────────────────────────────────

_TOOL_LIST = {
    "name": "gmail_list",
    "description": (
        "Получить последние письма Дмитрия из Gmail с категориями. "
        "Используй когда нужен общий обзор почты за период или быстрый "
        "ответ на «что в почте?», «есть что-то новое?». "
        "Возвращает список писем с from/subject/date/category. "
        "Тела писем НЕ возвращаются — только метаданные."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit":      {"type": "integer", "description": "Сколько писем (1..50, по умолчанию 20)"},
            "since_days": {"type": "integer", "description": "За сколько дней (1..14, по умолчанию 3)"},
        },
        "required": [],
    },
}

_TOOL_SEARCH = {
    "name": "gmail_search",
    "description": (
        "Найти письма по запросу. Используй когда пользователь спрашивает "
        "конкретно: «от тинькофф», «про доставку», «от Лены», «с темой счёт». "
        "Поиск идёт по полям from, subject, snippet."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query":      {"type": "string", "description": "Поисковая строка (имя отправителя, домен, слово в теме)"},
            "since_days": {"type": "integer", "description": "За сколько дней искать (1..30, по умолчанию 7)"},
            "max_results": {"type": "integer", "description": "Макс. писем в ответе (1..30, по умолчанию 10)"},
        },
        "required": ["query"],
    },
}

_TOOL_DIGEST = {
    "name": "gmail_digest",
    "description": (
        "Сводка по почте за период с группировкой по категориям "
        "(банки/финансы/работа/личное/уведомления/промо/спам). "
        "Используй когда пользователь просит сводку, дайджест, общую картину почты."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "since_days": {"type": "integer", "description": "За сколько дней (1..14, по умолчанию 1)"},
        },
        "required": [],
    },
}

_TOOL_COUNT = {
    "name": "gmail_count_by_category",
    "description": (
        "Просто количество писем по категориям за период. Используй когда "
        "нужны только числа (без перечисления писем). Например: «сколько спама за неделю?», "
        "«сколько уведомлений от ГитХаба за месяц?»."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "since_days": {"type": "integer", "description": "За сколько дней (1..30, по умолчанию 7)"},
        },
        "required": [],
    },
}

TOOLS_OWNER: list[dict] = [_TOOL_LIST, _TOOL_SEARCH, _TOOL_DIGEST, _TOOL_COUNT]
TOOLS_READONLY: list[dict] = []   # Не-владельцу почту вообще не показываем


# ─── Helpers ────────────────────────────────────────────────────────────────


def _gm() -> GmailService | None:
    if not settings.gmail_user or not settings.gmail_app_password:
        return None
    return GmailService(settings.gmail_user, settings.gmail_app_password)


def _msg_to_dict(m: GmailMessage, c: Classification | None = None) -> dict:
    d = {
        "from_name": m.from_name,
        "from_email": m.from_email,
        "subject": m.subject,
        "date": m.date.isoformat(timespec="minutes"),
        "snippet": m.snippet[:160],
        "is_unread": m.is_unread,
        "is_whitelisted": m.is_whitelisted,
    }
    if c:
        d["category"] = c.category
        d["category_label"] = c.label
        d["category_emoji"] = c.emoji
    return d


# ─── Tool implementations ───────────────────────────────────────────────────


async def _tool_list(inp: dict) -> str:
    gm = _gm()
    if not gm:
        return json.dumps({"status": "error", "error": "gmail_not_configured"}, ensure_ascii=False)
    limit = max(1, min(int(inp.get("limit", 20)), 50))
    since_days = max(1, min(int(inp.get("since_days", 3)), 14))
    msgs = await gm.list_recent(limit=limit, since_days=since_days)
    classes = await classify_messages(msgs) if msgs else []
    return json.dumps({
        "status": "ok",
        "count": len(msgs),
        "since_days": since_days,
        "messages": [_msg_to_dict(m, c) for m, c in zip(msgs, classes)],
    }, ensure_ascii=False)


async def _tool_search(inp: dict) -> str:
    gm = _gm()
    if not gm:
        return json.dumps({"status": "error", "error": "gmail_not_configured"}, ensure_ascii=False)
    query = (inp.get("query") or "").strip().lower()
    if not query:
        return json.dumps({"status": "error", "error": "empty_query"}, ensure_ascii=False)
    since_days = max(1, min(int(inp.get("since_days", 7)), 30))
    max_results = max(1, min(int(inp.get("max_results", 10)), 30))

    # Берём пошире пул, фильтруем локально (IMAP не ищет в snippet)
    pool = await gm.list_recent(limit=200, since_days=since_days)
    matched: list[GmailMessage] = []
    for m in pool:
        haystack = " ".join([
            (m.from_name or ""),
            (m.from_email or ""),
            (m.subject or ""),
            (m.snippet or ""),
        ]).lower()
        if query in haystack:
            matched.append(m)
            if len(matched) >= max_results:
                break

    classes = await classify_messages(matched) if matched else []
    return json.dumps({
        "status": "ok",
        "query": query,
        "since_days": since_days,
        "count": len(matched),
        "scanned": len(pool),
        "messages": [_msg_to_dict(m, c) for m, c in zip(matched, classes)],
    }, ensure_ascii=False)


async def _tool_digest(inp: dict) -> str:
    gm = _gm()
    if not gm:
        return json.dumps({"status": "error", "error": "gmail_not_configured"}, ensure_ascii=False)
    since_days = max(1, min(int(inp.get("since_days", 1)), 14))
    msgs = await gm.list_recent(limit=200, since_days=since_days)
    if not msgs:
        return json.dumps({"status": "ok", "since_days": since_days, "total": 0, "by_category": {}}, ensure_ascii=False)

    classes = await classify_messages(msgs)
    by_cat: dict[str, list[dict]] = {}
    for m, c in zip(msgs, classes):
        by_cat.setdefault(c.category, []).append(_msg_to_dict(m, c))
    summary = {cat: {"count": len(items), "label": CATEGORIES[cat][1], "emoji": CATEGORIES[cat][0]}
               for cat, items in by_cat.items()}
    return json.dumps({
        "status": "ok",
        "since_days": since_days,
        "total": len(msgs),
        "summary": summary,
        "details": {cat: items[:8] for cat, items in by_cat.items()},  # макс 8 на категорию
    }, ensure_ascii=False)


async def _tool_count(inp: dict) -> str:
    gm = _gm()
    if not gm:
        return json.dumps({"status": "error", "error": "gmail_not_configured"}, ensure_ascii=False)
    since_days = max(1, min(int(inp.get("since_days", 7)), 30))
    msgs = await gm.list_recent(limit=300, since_days=since_days)
    if not msgs:
        return json.dumps({"status": "ok", "since_days": since_days, "total": 0, "by_category": {}}, ensure_ascii=False)
    classes = await classify_messages(msgs)
    counts: dict[str, int] = {}
    for c in classes:
        counts[c.category] = counts.get(c.category, 0) + 1
    return json.dumps({
        "status": "ok",
        "since_days": since_days,
        "total": len(msgs),
        "by_category": {
            cat: {"count": n, "label": CATEGORIES[cat][1], "emoji": CATEGORIES[cat][0]}
            for cat, n in counts.items()
        },
    }, ensure_ascii=False)


_DISPATCH = {
    "gmail_list": _tool_list,
    "gmail_search": _tool_search,
    "gmail_digest": _tool_digest,
    "gmail_count_by_category": _tool_count,
}


async def execute_tool_async(name: str, inp: dict) -> str:
    handler = _DISPATCH.get(name)
    if handler is None:
        return json.dumps({"status": "error", "error": f"unknown gmail tool: {name}"}, ensure_ascii=False)
    try:
        return await handler(inp)
    except Exception as e:
        log.exception("gmail tool %s failed: %s", name, e)
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)


def execute_tool(name: str, inp: dict) -> str:
    """Синхронная обёртка для совместимости с диспетчерами claude_service."""
    return asyncio.get_event_loop().run_until_complete(execute_tool_async(name, inp))
