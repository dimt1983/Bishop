"""Tools для управления учениками Roastberry Academy через Bishop.

База — SQLite portal_academy.db (создаётся portal/server.py).

Доступные тулы:
- students_invite           — создать magic-link, отправить ученику в TG
- students_list             — все ученики и их доступ
- students_progress         — прогресс конкретного ученика (или сводка по курсам)
- students_grant_course     — открыть доступ к курсу
- students_revoke           — отозвать доступ полностью или к курсу
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional

import requests

DB_PATH = Path("/root/projects/ai-agents-rb/Курс/portal_academy.db")
PORTAL_URL = os.environ.get("PORTAL_URL", "http://64.188.57.142:8765")
INVITE_TTL = 7 * 24 * 3600  # 7 дней

COURSE_NAMES = {
    1: "Любитель кофе",
    2: "Бариста",
    3: "Профи",
    4: "Владелец кофейни",
    5: "Чай и авторские напитки",
}


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> int:
    return int(time.time())


def _bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _md_to_html(text: str) -> str:
    """Конвертирует «лёгкий Markdown» (как в коде) в HTML для Telegram parse_mode=HTML.

    Обрабатывает: **bold** → <b>, *italic* → <i>, `code` → <code>.
    Главное — экранирует <, >, & и НЕ ломается на _ внутри URL-токенов.
    """
    # 1) Сохраняем backticks-блоки, чтобы внутри них ничего не подменилось
    placeholders: list[str] = []

    def _save(m: "re.Match[str]") -> str:
        placeholders.append(m.group(1))
        return f"\x00CODE{len(placeholders)-1}\x00"

    text = re.sub(r"`([^`\n]+)`", _save, text)

    # 2) Экранируем HTML-special chars в остатке
    text = html.escape(text)

    # 3) **bold** → <b>bold</b>
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    # 4) *italic* → <i>italic</i>
    text = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", text)

    # 5) Возвращаем код-блоки как <code>…</code>
    for i, code in enumerate(placeholders):
        text = text.replace(f"\x00CODE{i}\x00", f"<code>{html.escape(code)}</code>")

    return text


def _send_tg(chat_id: int, text: str) -> dict:
    token = _bot_token()
    if not token:
        return {"ok": False, "error": "no TELEGRAM_BOT_TOKEN"}
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": _md_to_html(text), "parse_mode": "HTML",
                  "disable_web_page_preview": False},
            timeout=15,
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


BISHOP_DB = Path("/root/projects/ai-agents-rb/bishoprb-agent/bishop.db")


def _resolve_username(username: str) -> tuple[int | None, str]:
    """Резолвит username в telegram_id.

    Сначала ищем в локальной базе Бишопа (там все, кто когда-либо писал боту).
    Если не нашли — пробуем Telegram getChat (работает не для всех).
    Возвращает (tg_id, error_or_first_name).
    """
    handle = username.lstrip("@").strip()
    if not handle:
        return None, "empty username"

    # 1. Локальная база Бишопа
    try:
        if BISHOP_DB.exists():
            with sqlite3.connect(BISHOP_DB) as c:
                row = c.execute(
                    "SELECT telegram_id, first_name FROM users WHERE LOWER(username) = LOWER(?)",
                    (handle,),
                ).fetchone()
                if row:
                    return int(row[0]), row[1] or ""
    except Exception:
        pass

    # 2. Telegram Bot API getChat
    token = _bot_token()
    if not token:
        return None, "no TELEGRAM_BOT_TOKEN"
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": "@" + handle},
            timeout=15,
        )
        data = r.json()
        if not data.get("ok"):
            return None, data.get("description", "unknown error")
        chat = data.get("result") or {}
        return chat.get("id"), chat.get("first_name") or ""
    except Exception as e:
        return None, str(e)


# ─── Tool schemas ────────────────────────────────────────────────────────────

_TOOL_INVITE = {
    "name": "students_invite",
    "description": (
        "Создать magic-link для ученика и отправить ему в Telegram. "
        "Один токен = одна активация (после клика — мёртв).\n\n"
        "ID: можно указать telegram_id (число) ИЛИ username (например, '@alenka_belokopytova' или 'alenka_belokopytova'). "
        "Если username — бот сам резолвит его через Telegram API. Username будет работать только если "
        "пользователь публичный.\n\n"
        "Параметр mode:\n"
        "• 'direct' (по умолчанию) — выдаёт сразу все курсы из courses.\n"
        "• 'progressive' — даёт доступ ТОЛЬКО к Курсу 1. Курс 2 откроется автоматически "
        "после того, как ученик пройдёт ВСЕ уроки Курса 1 на 90%+. И так далее по цепочке. "
        "Используй для аттестации сотрудников.\n\n"
        "В progressive режиме параметр courses игнорируется.\n\n"
        "Параметр valid_days — срок действия доступа в днях. По умолчанию бессрочно. "
        "Используй для временных доступов (испытательный срок, пробный период)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer", "description": "Telegram ID ученика (число)"},
            "username": {"type": "string", "description": "Username ученика, например 'alenka_belokopytova' или '@alenka_belokopytova'. Если указан — резолвится в telegram_id через Bot API."},
            "first_name": {"type": "string", "description": "Имя ученика (для приветствия)"},
            "courses": {"type": "string", "description": "Курсы: '1,2' или 'all' (для mode=direct)"},
            "mode": {
                "type": "string",
                "enum": ["direct", "progressive"],
                "description": "direct = сразу все, progressive = по цепочке после успешной аттестации",
            },
            "valid_days": {
                "type": "integer",
                "description": "Срок действия доступа в днях. По умолчанию бессрочно (NULL).",
            },
            "send_to_owner_for_forwarding": {
                "type": "boolean",
                "description": "Если true — шлёт ссылку владельцу для пересылки (когда бот не может писать ученику первым)",
            },
        },
    },
}

_TOOL_SET_EXPIRY = {
    "name": "students_set_expiry",
    "description": (
        "Установить или снять срок действия доступа существующего ученика. "
        "valid_days — срок в днях от текущего момента, либо 0 для снятия ограничения (бессрочно)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer"},
            "course_id": {"type": "integer", "description": "ID курса; если не указан — для всех курсов ученика"},
            "valid_days": {"type": "integer", "description": "Дней от сейчас. 0 = снять ограничение"},
        },
        "required": ["telegram_id", "valid_days"],
    },
}

_TOOL_LIST = {
    "name": "students_list",
    "description": "Список всех учеников Академии: TG ID, имя, роль, доступные курсы, последняя активность.",
    "input_schema": {"type": "object", "properties": {}},
}

_TOOL_PROGRESS = {
    "name": "students_progress",
    "description": (
        "Прогресс ученика. Если telegram_id указан — детальный по курсам/урокам. "
        "Иначе — сводка по всем активным ученикам."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer"},
        },
    },
}

_TOOL_GRANT = {
    "name": "students_grant_course",
    "description": "Открыть ученику доступ к курсу без выдачи нового токена (если он уже зарегистрирован).",
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer"},
            "course_id": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        },
        "required": ["telegram_id", "course_id"],
    },
}

_TOOL_REVOKE = {
    "name": "students_revoke",
    "description": (
        "Отозвать доступ. Если course_id указан — только к одному курсу. "
        "Иначе — полный бан (удаляются все доступы и сессии)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer"},
            "course_id": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        },
        "required": ["telegram_id"],
    },
}

TOOLS_OWNER = [_TOOL_INVITE, _TOOL_LIST, _TOOL_PROGRESS, _TOOL_GRANT, _TOOL_REVOKE, _TOOL_SET_EXPIRY]
TOOLS_READONLY: list[dict] = []


# ─── Executors ───────────────────────────────────────────────────────────────

def _tool_invite(inp: dict) -> str:
    # Резолвим адресата: либо telegram_id, либо username
    tg_id_raw = inp.get("telegram_id")
    username = inp.get("username") or ""
    first_name = inp.get("first_name") or ""

    if tg_id_raw:
        tg_id = int(tg_id_raw)
    elif username:
        tg_id, resolved_name = _resolve_username(username)
        if tg_id is None:
            handle = username.lstrip("@")
            return json.dumps({
                "error": f"не нашёл @{handle} ни в локальной базе, ни через Telegram API",
                "tg_api_response": resolved_name,
                "explanation": (
                    "Это не баг — это ограничение Telegram Bot API: "
                    "боты не умеют искать private-пользователей по @username. "
                    "Резолв работает только если пользователь раньше писал боту (тогда он в локальной базе) "
                    "или это публичный канал/группа."
                ),
                "what_to_tell_owner": (
                    f"Пользователь @{handle} не писал мне раньше — поэтому я не знаю его telegram_id. "
                    f"Есть два пути:\n"
                    f"1) Попроси @{handle} написать мне в личку команду /id — я покажу ему его ID, "
                    f"он перешлёт тебе, и ты пришлёшь мне число.\n"
                    f"2) Или попроси @{handle} просто написать мне /start — я запомню его в базе, "
                    f"и тогда смогу резолвить его @username сам."
                ),
            }, ensure_ascii=False)
        if not first_name and resolved_name:
            first_name = resolved_name
    else:
        return json.dumps({"error": "нужен telegram_id или username"}, ensure_ascii=False)

    mode = (inp.get("mode") or "direct").strip()
    valid_days = inp.get("valid_days")
    expires_at = (_now() + int(valid_days) * 86400) if valid_days else None
    if mode not in ("direct", "progressive"):
        return json.dumps({"error": "mode must be 'direct' or 'progressive'"}, ensure_ascii=False)
    forward_to_owner = bool(inp.get("send_to_owner_for_forwarding", False))

    if mode == "progressive":
        # Прогрессивный режим: доступ начинается с Курса 1.
        courses_csv = "1"
        courses_label = (
            "к школе по программе аттестации. "
            "Сейчас открыт «Курс 1: Любитель». Следующий курс откроется автоматически, "
            "когда сдашь тесты текущего курса на 90%+"
        )
    else:
        courses_csv = str(inp.get("courses") or "").strip()
        if not courses_csv:
            return json.dumps({"error": "courses required when mode=direct"}, ensure_ascii=False)
        if courses_csv != "all":
            parts = [p.strip() for p in courses_csv.split(",") if p.strip()]
            if not all(p.isdigit() and int(p) in COURSE_NAMES for p in parts):
                return json.dumps({"error": "courses must be 'all' or csv of 1..5"}, ensure_ascii=False)
        courses_label = (
            "ко всем курсам"
            if courses_csv == "all"
            else "к курсам: " + ", ".join(f"«{COURSE_NAMES[int(p)]}»" for p in courses_csv.split(","))
        )

    token = secrets.token_urlsafe(24)
    now = _now()

    with _db() as c:
        c.execute("""
            INSERT OR IGNORE INTO students (telegram_id, first_name, role, created_at, access_mode)
            VALUES (?, ?, 'student', ?, ?)
        """, (tg_id, first_name, now, mode))
        if first_name:
            c.execute("UPDATE students SET first_name = ? WHERE telegram_id = ? AND (first_name IS NULL OR first_name = '')",
                      (first_name, tg_id))
        # Обновляем mode (на случай если ученик уже был с другим режимом)
        c.execute("UPDATE students SET access_mode = ? WHERE telegram_id = ?", (mode, tg_id))
        c.execute("""
            INSERT INTO invites (token, telegram_id, courses_csv, created_at, expires_at, access_expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (token, tg_id, courses_csv, now, now + INVITE_TTL, expires_at))
        c.commit()

    link = f"{PORTAL_URL}/?t={token}"
    if mode == "progressive":
        invite_text = (
            f"Привет{', ' + first_name if first_name else ''}! 👋\n\n"
            f"Тебе открыт доступ к *аттестационной программе Roastberry Academy*.\n\n"
            f"🔗 Открыть: {link}\n\n"
            f"Сейчас доступен *Курс 1 «Любитель кофе»* (25 уроков). "
            f"Когда сдашь все тесты на *90%+* — *Курс 2 «Бариста»* откроется автоматически. "
            f"Дальше — Курсы 3, 4 и 5 по той же логике.\n\n"
            f"⏰ Ссылка работает только у тебя и только один раз. "
            f"После клика портал запоминает твой Telegram, прогресс сохраняется.\n\n"
            f"Удачи!"
        )
    else:
        invite_text = (
            f"Привет{', ' + first_name if first_name else ''}! 👋\n\n"
            f"Ты получил доступ к Roastberry Academy {courses_label}.\n\n"
            f"🔗 Открыть курс: {link}\n\n"
            f"Ссылка работает только у тебя и только один раз — после клика она «сгорает», "
            f"и портал запоминает твой Telegram. Прогресс по урокам и тестам сохраняется.\n\n"
            f"Каждый урок завершается тестом. Урок засчитан, только если набрал 90%+. "
            f"Удачи!"
        )

    if forward_to_owner:
        owner_id = 466755177
        forward_text = (
            f"📨 Magic-link для пересылки\n\n"
            f"Адресат: {first_name or 'без имени'} (TG ID {tg_id})\n"
            f"Доступ: {courses_label}\n\n"
            f"Перешли ему сообщение ниже:\n\n"
            f"——\n{invite_text}"
        )
        r = _send_tg(owner_id, forward_text)
        return json.dumps({
            "status": "sent_to_owner_for_forwarding" if r.get("ok") else "failed",
            "telegram_id": tg_id, "link": link, "details": r,
        }, ensure_ascii=False)

    r = _send_tg(tg_id, invite_text)
    if not r.get("ok"):
        # Бот не может писать первым — шлём владельцу для пересылки
        owner_id = 466755177
        forward_text = (
            f"⚠️ Не удалось отправить magic-link напрямую {first_name or tg_id} ({tg_id}). "
            f"Telegram запретил («bot can't initiate conversation»). "
            f"Перешли ему ссылку вручную:\n\n"
            f"——\n{invite_text}"
        )
        r2 = _send_tg(owner_id, forward_text)
        return json.dumps({
            "status": "fallback_owner_forward",
            "telegram_id": tg_id, "link": link,
            "owner_notified": r2.get("ok"),
            "tg_error": r.get("description"),
        }, ensure_ascii=False)

    return json.dumps({
        "status": "sent", "telegram_id": tg_id, "link": link,
        "courses": courses_csv, "mode": mode,
        "valid_days": valid_days,
        "expires_at": expires_at,
    }, ensure_ascii=False)


def _tool_set_expiry(inp: dict) -> str:
    tg_id = int(inp["telegram_id"])
    valid_days = int(inp["valid_days"])
    course_id = inp.get("course_id")
    new_expires = (_now() + valid_days * 86400) if valid_days > 0 else None

    with _db() as c:
        if course_id:
            c.execute(
                "UPDATE access SET expires_at = ? WHERE telegram_id = ? AND course_id = ?",
                (new_expires, tg_id, int(course_id)),
            )
            scope = f"course_{course_id}"
        else:
            c.execute(
                "UPDATE access SET expires_at = ? WHERE telegram_id = ?",
                (new_expires, tg_id),
            )
            scope = "all"
        c.commit()
    return json.dumps({
        "status": "updated", "telegram_id": tg_id,
        "scope": scope, "expires_at": new_expires,
        "valid_days": valid_days if valid_days > 0 else "unlimited",
    }, ensure_ascii=False)


def _tool_list(inp: dict) -> str:
    with _db() as c:
        students = c.execute("""
            SELECT s.telegram_id, s.first_name, s.username, s.role, s.access_mode,
                   s.created_at, s.last_seen_at
            FROM students s
            ORDER BY s.last_seen_at DESC NULLS LAST, s.created_at DESC
        """).fetchall()
        result = []
        for s in students:
            access = [r["course_id"] for r in c.execute(
                "SELECT course_id FROM access WHERE telegram_id = ? ORDER BY course_id",
                (s["telegram_id"],),
            ).fetchall()]
            done_count = c.execute(
                "SELECT COUNT(*) AS n FROM progress WHERE telegram_id = ? AND best_percent >= 90",
                (s["telegram_id"],),
            ).fetchone()["n"]
            result.append({
                "telegram_id": s["telegram_id"],
                "first_name": s["first_name"] or "",
                "username": s["username"] or "",
                "role": s["role"],
                "access_mode": s["access_mode"] or "direct",
                "courses_access": access,
                "lessons_passed": done_count,
                "last_seen_at": s["last_seen_at"],
            })
    return json.dumps({"count": len(result), "students": result}, ensure_ascii=False)


def _tool_progress(inp: dict) -> str:
    tg_id = inp.get("telegram_id")
    with _db() as c:
        if tg_id:
            tg_id = int(tg_id)
            student = c.execute("SELECT * FROM students WHERE telegram_id = ?", (tg_id,)).fetchone()
            if not student:
                return json.dumps({"error": "student not found"}, ensure_ascii=False)
            access = [r["course_id"] for r in c.execute(
                "SELECT course_id FROM access WHERE telegram_id = ?", (tg_id,)
            ).fetchall()]
            lessons = c.execute("""
                SELECT course_id, lesson_id, best_percent, attempts, completed_at
                FROM progress WHERE telegram_id = ?
                ORDER BY course_id, lesson_id
            """, (tg_id,)).fetchall()
            attempts = c.execute("""
                SELECT COUNT(*) AS n FROM quiz_attempts WHERE telegram_id = ?
            """, (tg_id,)).fetchone()["n"]
            return json.dumps({
                "telegram_id": tg_id,
                "first_name": student["first_name"] or "",
                "courses_access": access,
                "total_quiz_attempts": attempts,
                "lessons": [
                    {
                        "course_id": l["course_id"],
                        "lesson_id": l["lesson_id"],
                        "best_percent": l["best_percent"],
                        "attempts": l["attempts"],
                        "passed": l["best_percent"] >= 90,
                    }
                    for l in lessons
                ],
            }, ensure_ascii=False)
        else:
            # Сводка
            rows = c.execute("""
                SELECT s.telegram_id, s.first_name,
                       COUNT(DISTINCT p.course_id || ':' || p.lesson_id) FILTER (WHERE p.best_percent >= 90) AS passed,
                       COUNT(DISTINCT p.course_id || ':' || p.lesson_id) AS attempted
                FROM students s
                LEFT JOIN progress p ON p.telegram_id = s.telegram_id
                WHERE s.role != 'owner'
                GROUP BY s.telegram_id, s.first_name
                ORDER BY passed DESC, attempted DESC
            """).fetchall()
            return json.dumps({
                "summary": [
                    {
                        "telegram_id": r["telegram_id"],
                        "first_name": r["first_name"] or "",
                        "lessons_passed": r["passed"] or 0,
                        "lessons_attempted": r["attempted"] or 0,
                    }
                    for r in rows
                ],
            }, ensure_ascii=False)


def _tool_grant(inp: dict) -> str:
    tg_id = int(inp["telegram_id"])
    cid = int(inp["course_id"])
    with _db() as c:
        student = c.execute("SELECT * FROM students WHERE telegram_id = ?", (tg_id,)).fetchone()
        if not student:
            return json.dumps({"error": "student not found — invite first"}, ensure_ascii=False)
        c.execute(
            "INSERT OR IGNORE INTO access (telegram_id, course_id, granted_at) VALUES (?, ?, ?)",
            (tg_id, cid, _now()),
        )
        c.commit()
    return json.dumps({
        "status": "granted", "telegram_id": tg_id, "course_id": cid,
        "course_name": COURSE_NAMES.get(cid, str(cid)),
    }, ensure_ascii=False)


def _tool_revoke(inp: dict) -> str:
    tg_id = int(inp["telegram_id"])
    cid = inp.get("course_id")
    with _db() as c:
        if cid:
            c.execute("DELETE FROM access WHERE telegram_id = ? AND course_id = ?",
                      (tg_id, int(cid)))
            scope = f"course_{cid}"
        else:
            c.execute("DELETE FROM access WHERE telegram_id = ?", (tg_id,))
            c.execute("DELETE FROM sessions WHERE telegram_id = ?", (tg_id,))
            c.execute("DELETE FROM invites WHERE telegram_id = ? AND used_at IS NULL", (tg_id,))
            scope = "all"
        c.commit()
    return json.dumps({"status": "revoked", "telegram_id": tg_id, "scope": scope}, ensure_ascii=False)


_EXECUTORS = {
    "students_invite": _tool_invite,
    "students_list": _tool_list,
    "students_progress": _tool_progress,
    "students_grant_course": _tool_grant,
    "students_revoke": _tool_revoke,
    "students_set_expiry": _tool_set_expiry,
}


def execute(name: str, inp: dict) -> str:
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"}, ensure_ascii=False)
    try:
        return fn(inp)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
