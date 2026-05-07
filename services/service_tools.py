"""Bishop-тулы для управления сервисной службой Roastberry.

Все запросы идут через HTTP к David'у (wahelp-agent на Railway):
https://wahelp-agent-production.up.railway.app/admin/service/*

Авторизация — через ADMIN_API_TOKEN (env Bishop'а, тот же что у David'а).
"""
from __future__ import annotations

import os
import logging

import httpx

log = logging.getLogger(__name__)

DAVID_BASE_URL = os.environ.get(
    "DAVID_SERVICE_BASE_URL",
    "https://wahelp-agent-production.up.railway.app",
)
ADMIN_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")


# ─── Tools schema (Claude tool-use) ───────────────────────────────────────

_TOOL_ISSUE_CODE = {
    "name": "service_issue_invite_code",
    "description": (
        "Сгенерировать одноразовый регистрационный код для нового техника или "
        "менеджера сервисной службы Roastberry. Код действует 30 дней или до "
        "первой активации. Возвращает код, deep-link и описание.\n\n"
        "Используй когда Дмитрий просит:\n"
        "  – «выдай код для нового техника»\n"
        "  – «сгенерируй код менеджеру»\n"
        "  – «сделай приглашение на сервис»"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "enum": ["technician", "manager"],
                "description": "technician — мастер. manager — менеджер.",
            },
            "expires_days": {
                "type": "integer",
                "description": "Срок жизни кода в днях (default 30)",
            },
        },
        "required": ["role"],
    },
}


_TOOL_SEND_APP_LINK = {
    "name": "service_send_app_link",
    "description": (
        "Отправить кому-либо в личку Telegram ссылку на приложение сервисной "
        "службы Roastberry (https://t.me/rbr_service_bot/service).\n\n"
        "Используй когда Дмитрий говорит:\n"
        "  – «отправь Денису ссылку на приложение сервис»\n"
        "  – «скинь @username приложение»\n"
        "  – «дай клиенту ссылку чтобы он подал заявку»\n\n"
        "Адресат указывается как telegram_id (число) ИЛИ username (с @ или без). "
        "Если указан username — резолвится через Bot API. Если адресат не "
        "стартовал ни одного бота — Telegram отвергнет, верни fallback с "
        "сырой ссылкой чтобы Дмитрий сам переслал."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer"},
            "username": {"type": "string", "description": "С @ или без"},
            "role_hint": {
                "type": "string",
                "enum": ["client", "technician", "manager"],
                "description": "Под какую роль скинуть приветствие — добавит deep-link payload и текст сопроводительного сообщения. По умолчанию client.",
            },
            "comment": {
                "type": "string",
                "description": "Опциональный текст-сопроводитель для адресата (например 'привет, твой сервисный бот')",
            },
        },
    },
}


_TOOL_USERS_STATS = {
    "name": "service_users_stats",
    "description": (
        "Вернуть сводку по всем зарегистрированным в сервисной службе "
        "(техники, менеджеры, координаторы) и активным клиентам, подававшим "
        "заявки. По каждому участнику команды — кол-во поданных / принятых / "
        "закрытых заявок. Также: счётчики invite-кодов и pending-запросов "
        "роли.\n\n"
        "Используй когда Дмитрий говорит:\n"
        "  – «покажи команду сервиса / зарегистрированных»\n"
        "  – «статистика по сервисникам»\n"
        "  – «кто работает в сервисе и сколько заявок закрыл»\n"
        "  – «сколько кодов выдано»"
    ),
    "input_schema": {"type": "object", "properties": {}},
}


TOOLS_OWNER = [_TOOL_ISSUE_CODE, _TOOL_SEND_APP_LINK, _TOOL_USERS_STATS]
TOOLS_READONLY = []


# ─── Implementations ──────────────────────────────────────────────────────

async def _tool_issue_code(inp: dict, owner_tg_id: int = 0) -> str:
    role = inp.get("role")
    expires_days = int(inp.get("expires_days") or 30)
    if role not in ("technician", "manager"):
        return f"❌ role должен быть technician или manager (получено: {role!r})"
    if not ADMIN_TOKEN:
        return "❌ ADMIN_API_TOKEN не задан в env Bishop'а"
    payload = {
        "role": role,
        "issued_by": owner_tg_id or 0,
        "expires_days": expires_days,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{DAVID_BASE_URL.rstrip('/')}/admin/service/issue_invite_code",
                headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
                json=payload,
            )
            data = r.json()
    except Exception as e:
        log.exception("issue_code request failed: %s", e)
        return f"❌ Не получилось обратиться к David'у: {e}"
    if not data.get("ok"):
        return f"❌ Ошибка: {data}"
    code = data["code"]
    deep_link = data.get("deep_link", "")
    role_label = "техник" if role == "technician" else "менеджер"
    return (
        f"✅ Код регистрации для {role_label}а:\n\n"
        f"🔑 <code>{code}</code>\n\n"
        f"📲 Прямая ссылка (можно скинуть человеку):\n"
        f"{deep_link}\n\n"
        f"⏰ Действует до: {data.get('expires_at', '?')[:10]}\n"
        f"🚫 Активируется один раз и сгорает.\n\n"
        f"Передай код или ссылку человеку — он введёт код в "
        f"@rbr_service_bot → 🛠 Сервис → «Войти как сотрудник»."
    )


async def _tool_send_app_link(inp: dict) -> str:
    """Отправить ссылку на сервис-бот в личку TG."""
    import os as _os
    bishop_token = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
    # Bishop читает из своего .env / settings — берём через config
    if not bishop_token:
        try:
            from config import settings as _settings
            bishop_token = _settings.telegram_bot_token
        except Exception:
            pass
    if not bishop_token:
        return "❌ TELEGRAM_BOT_TOKEN не задан — Bishop не может отправить сообщение"

    role_hint = (inp.get("role_hint") or "client").lower()
    payload_map = {"client": "client", "technician": "technician", "manager": "manager"}
    payload = payload_map.get(role_hint, "client")

    role_text = {
        "client": "клиент / подача заявки",
        "technician": "техник",
        "manager": "менеджер",
    }.get(role_hint, "клиент")

    # Резолвим адресата
    target_id = inp.get("telegram_id")
    username = (inp.get("username") or "").lstrip("@").strip()
    if not target_id and username:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{bishop_token}/getChat",
                    params={"chat_id": "@" + username},
                )
                d = r.json()
                if d.get("ok"):
                    target_id = d["result"]["id"]
        except Exception as e:
            log.warning("getChat for @%s failed: %s", username, e)

    base_link = "https://t.me/rbr_service_bot/service"
    deep_link = f"https://t.me/rbr_service_bot?start={payload}"
    fallback_text = (
        f"📲 Ссылка на сервис Roastberry ({role_text}):\n"
        f"• Приложение: {base_link}\n"
        f"• Бот с инструкцией: {deep_link}"
    )

    if not target_id:
        return (
            f"⚠️ Не нашёл @{username or '?'} — публичного profile нет или username неверный.\n\n"
            f"Скопируй и перешли вручную:\n"
            f"{fallback_text}"
        )

    # Шлём в личку
    comment = (inp.get("comment") or "").strip()
    msg_text = (
        f"👋 Привет!\n\n"
        f"{comment + chr(10) + chr(10) if comment else ''}"
        f"Открой приложение сервисной службы Roastberry — там можно подать "
        f"заявку и следить за её статусом:\n\n"
        f"🚀 {base_link}\n\n"
        f"Если откроешь по короткой ссылке выше — сразу попадёшь в Mini App. "
        f"Альтернатива — запустить бота через инструкцию: {deep_link}"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{bishop_token}/sendMessage",
                json={"chat_id": target_id, "text": msg_text, "disable_web_page_preview": False},
            )
            data = r.json()
    except Exception as e:
        return f"❌ Ошибка Telegram: {e}\n\n{fallback_text}"

    if not data.get("ok"):
        desc = data.get("description", "?")
        if "bot can't initiate" in desc.lower() or "chat not found" in desc.lower():
            return (
                f"⚠️ Не получилось отправить @{username or target_id} напрямую "
                f"({desc}).\n\nПричина: получатель не общался с Bishop'ом раньше — "
                f"Telegram блокирует первый исходящий контакт.\n\n"
                f"Перешли ему сам:\n{fallback_text}"
            )
        return f"❌ Telegram отклонил: {desc}\n\n{fallback_text}"

    return (
        f"✅ Отправил ссылку @{username or target_id} в личку — он получит "
        f"приветствие и кнопку на приложение."
    )


async def _tool_users_stats(inp: dict) -> str:
    if not ADMIN_TOKEN:
        return "❌ ADMIN_API_TOKEN не задан в env Bishop'а"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{DAVID_BASE_URL.rstrip('/')}/admin/service/users_stats",
                headers={"X-Admin-Token": ADMIN_TOKEN},
            )
            data = r.json()
    except Exception as e:
        log.exception("users_stats request failed: %s", e)
        return f"❌ Не получилось обратиться к David'у: {e}"
    if isinstance(data, dict) and data.get("error"):
        return f"❌ {data['error']}"

    team = data.get("team") or []
    clients = data.get("clients") or []
    rr = data.get("role_requests") or {}
    ic = data.get("invite_codes") or {}

    # Группируем команду по role_label
    by_role: dict[str, list[dict]] = {}
    for m in team:
        by_role.setdefault(m.get("role_label") or m.get("role"), []).append(m)

    lines = ["<b>👥 Команда сервиса Roastberry</b>"]
    for role_label in sorted(by_role.keys()):
        members = by_role[role_label]
        lines.append(f"\n<b>{role_label}</b> ({len(members)})")
        for m in members:
            name = m.get("name") or "—"
            uname = f"@{m['username']}" if m.get("username") else ""
            inactive = "" if m.get("active", True) else " 🚫"
            stats_bits = []
            if m.get("created"): stats_bits.append(f"подал {m['created']}")
            if m.get("accepted"): stats_bits.append(f"принял {m['accepted']}")
            if m.get("closed"): stats_bits.append(f"закрыл {m['closed']}")
            stats_text = f" — {', '.join(stats_bits)}" if stats_bits else ""
            lines.append(f"• {name} {uname}{inactive}{stats_text}")

    if clients:
        lines.append(f"\n<b>👤 Клиенты с заявками</b> ({len(clients)})")
        for c in clients[:15]:
            lines.append(
                f"• tg <code>{c['user_id']}</code> — заявок {c['created']}"
            )
        if len(clients) > 15:
            lines.append(f"  …и ещё {len(clients) - 15}")

    lines.append(
        f"\n<b>🔑 Invite-коды</b>: всего {ic.get('total', 0)}, "
        f"активировано {ic.get('used', 0)}, "
        f"в обороте {ic.get('active', 0)}"
    )
    if rr.get("pending") or rr.get("approved") or rr.get("rejected"):
        lines.append(
            f"<b>📩 Запросы роли</b>: pending {rr.get('pending', 0)}, "
            f"approved {rr.get('approved', 0)}, rejected {rr.get('rejected', 0)}"
        )

    return "\n".join(lines)


async def execute(name: str, inp: dict, owner_tg_id: int = 0) -> str:
    """Точка входа из claude_service.py для tool-use."""
    if name == "service_issue_invite_code":
        return await _tool_issue_code(inp, owner_tg_id=owner_tg_id)
    if name == "service_send_app_link":
        return await _tool_send_app_link(inp)
    if name == "service_users_stats":
        return await _tool_users_stats(inp)
    return f"❌ Unknown service-tool: {name}"
