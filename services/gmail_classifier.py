"""
Классификатор Gmail-писем через Claude.

Категории:
  🏦 bank        — банки, платёжные системы, кошельки
  💰 finance     — счета/инвойсы, бухгалтерия, налоги
  💼 work        — рабочее по Roastberry: поставщики, клиенты, команда
  👨 personal    — друзья, семья, личные сервисы (госуслуги тоже сюда)
  🔔 service     — IT-уведомления: GitHub, Railway, Render, Google, статусы
  📢 promo       — реклама, акции, рассылки
  🚫 spam        — фишинг, мошенничество, мусор

Если отправитель в whitelist — категория ставится по подсказке whitelist.categories
без вызова Claude. Дешевле и предсказуемее.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Iterable

from anthropic import AsyncAnthropic

from config import settings
from services.gmail_tools import GmailMessage, GmailWhitelist, _domain

log = logging.getLogger(__name__)

CATEGORIES = {
    "bank":     ("🏦", "Банк"),
    "finance":  ("💰", "Финансы"),
    "work":     ("💼", "Работа"),
    "personal": ("👨", "Личное"),
    "service":  ("🔔", "Уведомления"),
    "promo":    ("📢", "Промо"),
    "spam":     ("🚫", "Спам"),
}

# Маппинг whitelist-категорий → наши категории
WHITELIST_CATEGORY_MAP = {
    "банки":     "bank",
    "госуслуги": "personal",  # «Личное», т.к. это госсервисы для физлица
    "связь":     "service",
}


_SYSTEM = """Ты классифицируешь email-письма для владельца кофейного бренда Roastberry (Дмитрий).

Категории (отвечай ТОЛЬКО ключом):
- bank — банковские письма, операции, выписки, оповещения о платежах от банков и платёжных систем (Сбер, Тинькофф, Альфа, МТС-Банк, ВТБ, ЮMoney, QIWI и т.д.)
- finance — счета на оплату, инвойсы, акты, налоговая, бухгалтерия, финансовые отчёты не от банков
- work — деловая переписка по Roastberry: поставщики (зерно, оборудование), клиенты, партнёры, команда, договоры, заказы
- personal — личные сервисы и контакты: госуслуги, налог.ру, друзья, семья, медицина, личные подписки (стриминги, образование), путешествия
- service — уведомления IT-сервисов: Google, GitHub, Railway, Render, Vercel, OpenAI, Anthropic, статусы деплоев, безопасность аккаунтов, Telegram-сервисы, всё что «no-reply» от технических платформ
- promo — реклама, акции, рассылки, маркетплейсы (Ozon, WB, Яндекс.Маркет промо), скидки
- spam — фишинг, мошенничество, нигерийские письма, явный мусор

Получишь JSON-массив писем. Верни ТОЛЬКО JSON-массив той же длины:
[{"category": "bank|finance|work|personal|service|promo|spam", "confidence": 0.0-1.0}]

Если сомнение между service и promo — выбирай service для no-reply от тех. платформ.
Если сомнение между work и promo — выбирай work (лучше показать письмо).
"""


@dataclass
class Classification:
    category: str          # ключ CATEGORIES
    confidence: float      # 0..1
    source: str            # 'whitelist' | 'claude' | 'fallback'

    @property
    def emoji(self) -> str:
        return CATEGORIES.get(self.category, ("❓", ""))[0]

    @property
    def label(self) -> str:
        return CATEGORIES.get(self.category, ("❓", "Неизв"))[1]


def _whitelist_category(addr: str, whitelist: GmailWhitelist) -> str | None:
    """Если адрес в whitelist под определённой категорией — вернуть наш ключ."""
    addr = (addr or "").lower()
    if not addr:
        return None
    d = _domain(addr)
    cats = whitelist._data.get("categories", {}) or {}
    for wl_cat, items in cats.items():
        for item in items:
            it = item.lower()
            if addr == it or d == it or d.endswith("." + it):
                return WHITELIST_CATEGORY_MAP.get(wl_cat)
    return None


async def classify_messages(
    messages: list[GmailMessage],
    whitelist: GmailWhitelist | None = None,
) -> list[Classification]:
    """Классифицирует пакет писем. Whitelisted идут без Claude.

    Возвращает список Classification той же длины что и messages.
    """
    whitelist = whitelist or GmailWhitelist()
    results: list[Classification | None] = [None] * len(messages)

    # Сперва: whitelist
    to_claude_idx: list[int] = []
    for i, m in enumerate(messages):
        wl_cat = _whitelist_category(m.from_email, whitelist)
        if wl_cat:
            results[i] = Classification(wl_cat, 1.0, "whitelist")
            continue
        to_claude_idx.append(i)

    if not to_claude_idx:
        return [r for r in results if r is not None]  # все по whitelist

    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )

    # Батчим по 25 — большие пакеты иногда теряют один элемент в выдаче.
    BATCH = 25
    for batch_start in range(0, len(to_claude_idx), BATCH):
        batch_idx = to_claude_idx[batch_start:batch_start + BATCH]
        payload = []
        for i in batch_idx:
            m = messages[i]
            payload.append({
                "from": f"{m.from_name} <{m.from_email}>" if m.from_name else m.from_email,
                "subject": (m.subject or "")[:100],
                "snippet": (m.snippet or "")[:120],
            })

        try:
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                system=_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": "Классифицируй эти письма:\n\n" + json.dumps(payload, ensure_ascii=False),
                }],
            )
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("not a list")
            # Длина может разъехаться на 1-2 — добиваем personal
            while len(parsed) < len(payload):
                parsed.append({"category": "personal", "confidence": 0.0})
            for j, item in enumerate(parsed[:len(payload)]):
                i = batch_idx[j]
                cat = item.get("category", "personal")
                if cat not in CATEGORIES:
                    cat = "personal"
                conf = float(item.get("confidence", 0.5))
                src = "claude" if conf > 0 else "fallback"
                results[i] = Classification(cat, conf, src)
        except Exception:
            log.exception("Gmail classifier batch %d failed, fallback for %d items",
                          batch_start // BATCH, len(batch_idx))
            for i in batch_idx:
                results[i] = Classification("personal", 0.0, "fallback")

    return [r for r in results if r is not None]


def format_inbox_with_categories(
    messages: list[GmailMessage],
    classifications: list[Classification],
    header: str = "📥 Inbox",
) -> str:
    """Inbox с эмодзи-категориями. Длина messages == classifications."""
    if not messages:
        return f"{header}\n\nПусто."

    lines = [f"<b>{header}</b>", f"<i>{len(messages)} писем</i>", ""]
    for m, c in zip(messages, classifications):
        sender = m.from_name or m.from_email
        time_str = m.date.astimezone().strftime("%d.%m %H:%M")
        unread = "● " if m.is_unread else "  "
        sender_e = sender.replace("<", "&lt;").replace(">", "&gt;")[:32]
        subject_e = (m.subject or "(без темы)").replace("<", "&lt;").replace(">", "&gt;")[:60]

        lines.append(f"{unread}{c.emoji} <b>{sender_e}</b>  <i>{time_str}</i>")
        lines.append(f"     {subject_e}")
    return "\n".join(lines)


def format_digest(
    messages: list[GmailMessage],
    classifications: list[Classification],
    period_label: str = "за последние 3 дня",
) -> str:
    """Сводка по категориям + важное."""
    if not messages:
        return f"📊 <b>Дайджест Gmail</b> ({period_label})\n\nПисем нет."

    # Группируем
    by_cat: dict[str, list[tuple[GmailMessage, Classification]]] = {}
    for m, c in zip(messages, classifications):
        by_cat.setdefault(c.category, []).append((m, c))

    # Порядок категорий по важности
    order = ["bank", "finance", "work", "personal", "service", "promo", "spam"]

    lines = [
        f"📊 <b>Дайджест Gmail</b> ({period_label})",
        f"<i>Всего: {len(messages)} писем</i>",
        "",
    ]

    # Краткая сводка вверху
    summary_parts = []
    for cat in order:
        items = by_cat.get(cat) or []
        if items:
            emo, label = CATEGORIES[cat]
            summary_parts.append(f"{emo} {label}: <b>{len(items)}</b>")
    lines.append("  ·  ".join(summary_parts))
    lines.append("")

    # Важные категории — детально (банк, финансы, работа, личное)
    for cat in ["bank", "finance", "work", "personal"]:
        items = by_cat.get(cat) or []
        if not items:
            continue
        emo, label = CATEGORIES[cat]
        lines.append(f"<b>{emo} {label}</b>")
        for m, c in items[:8]:  # топ-8 в категории
            sender = (m.from_name or m.from_email)[:28].replace("<", "&lt;").replace(">", "&gt;")
            subj = (m.subject or "(без темы)")[:60].replace("<", "&lt;").replace(">", "&gt;")
            t = m.date.astimezone().strftime("%d.%m %H:%M")
            lines.append(f"  • <b>{sender}</b> · <i>{t}</i>")
            lines.append(f"    {subj}")
        if len(items) > 8:
            lines.append(f"  <i>… ещё {len(items) - 8}</i>")
        lines.append("")

    # Шум — только числа
    noise = []
    for cat in ["service", "promo", "spam"]:
        items = by_cat.get(cat) or []
        if items:
            emo, label = CATEGORIES[cat]
            noise.append(f"{emo} {label}: {len(items)}")
    if noise:
        lines.append("<b>📦 Шум (можно почистить)</b>")
        lines.append("  ·  ".join(noise))

    return "\n".join(lines)
