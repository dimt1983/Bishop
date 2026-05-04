"""
Gmail-ассистент для Бишопа.

Уровень доступа: 🟢 БЕЗОПАСНЫЙ.
- Бишоп ЧИТАЕТ метаданные писем (from/subject/date/snippet) через IMAP.
- Сам не удаляет, не архивирует и не помечает спамом без явной команды.
- Whitelist: домены банков, госуслуг и доверенных отправителей не трогаются.

Подключение: IMAP imap.gmail.com:993, App Password (нужна 2FA в Gmail).
Документация App Password: https://support.google.com/accounts/answer/185833
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import json
import logging
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Файл с whitelist-доменами/адресами. Можно дополнять руками.
WHITELIST_PATH = Path(__file__).resolve().parents[1] / "data" / "gmail_whitelist.json"


@dataclass
class GmailMessage:
    """Метаданные одного письма (без тела — для безопасности)."""
    uid: str
    folder: str
    from_email: str
    from_name: str
    subject: str
    date: datetime
    snippet: str           # первые ~200 символов превью текста
    is_unread: bool
    has_attachments: bool
    is_whitelisted: bool   # отправитель в whitelist — не классифицируем как спам


def _decode_header_value(raw: str | None) -> str:
    """Декодирует заголовок типа =?UTF-8?B?...?= в читаемую строку."""
    if not raw:
        return ""
    decoded = decode_header(raw)
    out: list[str] = []
    for part, enc in decoded:
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out).strip()


_FROM_RE = re.compile(r"^\s*(?:\"?([^\"<]*)\"?\s*<)?([^>]+@[^>]+?)>?\s*$")


def _parse_from(raw: str) -> tuple[str, str]:
    """«Иван Петров <ivan@example.com>» → ('Иван Петров', 'ivan@example.com')."""
    raw = _decode_header_value(raw)
    m = _FROM_RE.match(raw)
    if not m:
        return "", raw.lower()
    name, addr = m.group(1) or "", m.group(2).strip().lower()
    return name.strip(), addr


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


# ─────────────────────────────────────────────────────────────────────────────


class GmailWhitelist:
    """
    Список доменов и адресов, которые Бишоп НИКОГДА не трогает
    (не помечает спамом / рекламой, не предлагает архивировать).

    Структура файла (JSON):
        {
          "domains": ["sberbank.ru", "tinkoff.ru", ...],
          "addresses": ["mama@gmail.com", "supplier@vendor.ru"],
          "categories": {
            "банки": ["sberbank.ru", "tinkoff.ru", "alfabank.ru", "mtsbank.ru"],
            "госуслуги": ["gosuslugi.ru", "nalog.ru"]
          }
        }
    """

    DEFAULT = {
        "domains": [
            # Банки РФ
            "sberbank.ru", "tinkoff.ru", "tbank.ru", "alfabank.ru",
            "mtsbank.ru", "vtb.ru", "raiffeisen.ru", "psbank.ru",
            "rshb.ru", "open.ru", "rosbank.ru",
            # Госуслуги, налоговая, пенсионный
            "gosuslugi.ru", "nalog.ru", "nalog.gov.ru", "pfr.gov.ru",
            "pochta.ru",
            # Мобильные операторы
            "mts.ru", "beeline.ru", "megafon.ru", "tele2.ru", "yota.ru",
            # Платёжные системы
            "yoomoney.ru", "qiwi.com",
            # Сервисы Google
            "accounts.google.com", "noreply@google.com",
        ],
        "addresses": [],
        "categories": {
            "банки": [
                "sberbank.ru", "tinkoff.ru", "tbank.ru", "alfabank.ru",
                "mtsbank.ru", "vtb.ru", "raiffeisen.ru", "psbank.ru",
            ],
            "госуслуги": ["gosuslugi.ru", "nalog.ru", "nalog.gov.ru"],
            "связь": ["mts.ru", "beeline.ru", "megafon.ru", "tele2.ru"],
        },
    }

    def __init__(self, path: Path = WHITELIST_PATH):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.DEFAULT, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return dict(self.DEFAULT)
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("gmail whitelist: failed to load %s", self.path)
            return dict(self.DEFAULT)

    @property
    def domains(self) -> set[str]:
        return {d.lower() for d in self._data.get("domains", [])}

    @property
    def addresses(self) -> set[str]:
        return {a.lower() for a in self._data.get("addresses", [])}

    def matches(self, addr: str) -> bool:
        """True если этот отправитель в whitelist."""
        addr = (addr or "").lower()
        if not addr:
            return False
        if addr in self.addresses:
            return True
        d = _domain(addr)
        if not d:
            return False
        if d in self.domains:
            return True
        # Поддержка субдоменов: noreply@push.sberbank.ru → sberbank.ru
        for whitelisted in self.domains:
            if d == whitelisted or d.endswith("." + whitelisted):
                return True
        return False


# ─────────────────────────────────────────────────────────────────────────────


class GmailService:
    """
    IMAP-клиент для Gmail. Только метаданные, не хранит тела писем.

    Использование:
        gm = GmailService(user="dimt1983@gmail.com", password="...")
        msgs = await gm.list_recent(limit=20, since_days=7)
    """

    def __init__(self, user: str, password: str, whitelist: Optional[GmailWhitelist] = None):
        self.user = user
        self.password = password
        self.whitelist = whitelist or GmailWhitelist()

    # IMAP блокирующий — оборачиваем в asyncio.to_thread

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        ctx = ssl.create_default_context()
        m = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
        m.login(self.user, self.password)
        return m

    def _list_recent_sync(self, limit: int, since_days: int, folder: str) -> list[GmailMessage]:
        m = self._imap_connect()
        try:
            m.select(folder, readonly=True)
            since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
            typ, data = m.search(None, f'(SINCE "{since_date}")')
            if typ != "OK" or not data or not data[0]:
                return []
            uids = data[0].split()
            uids = uids[-limit:][::-1]  # последние N, новейшие первыми

            results: list[GmailMessage] = []
            for uid in uids:
                # Тянем только заголовки + первые 1024 байта тела для snippet
                typ, mdata = m.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.1024> FLAGS)")
                if typ != "OK" or not mdata:
                    continue

                hdr_raw, body_raw, flags_raw = b"", b"", b""
                for part in mdata:
                    if isinstance(part, tuple) and len(part) >= 2:
                        meta, payload = part[0], part[1]
                        if b"HEADER" in (meta or b""):
                            hdr_raw = payload
                        elif b"TEXT" in (meta or b""):
                            body_raw = payload or b""
                    elif isinstance(part, bytes):
                        flags_raw += part

                msg = email.message_from_bytes(hdr_raw)
                from_name, from_addr = _parse_from(msg.get("From", ""))
                subject = _decode_header_value(msg.get("Subject", ""))
                try:
                    date = parsedate_to_datetime(msg.get("Date", "")) or datetime.now(timezone.utc)
                except Exception:
                    date = datetime.now(timezone.utc)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)

                snippet = body_raw.decode("utf-8", errors="replace")
                snippet = re.sub(r"\s+", " ", snippet).strip()[:200]

                flags_str = (flags_raw or b"").decode("ascii", errors="ignore")
                is_unread = r"\Seen" not in flags_str

                results.append(GmailMessage(
                    uid=uid.decode("ascii"),
                    folder=folder,
                    from_email=from_addr,
                    from_name=from_name,
                    subject=subject,
                    date=date,
                    snippet=snippet,
                    is_unread=is_unread,
                    has_attachments=False,  # пока не парсим, требует BODYSTRUCTURE
                    is_whitelisted=self.whitelist.matches(from_addr),
                ))
            return results
        finally:
            try:
                m.close()
            except Exception:
                pass
            try:
                m.logout()
            except Exception:
                pass

    async def list_recent(
        self, limit: int = 20, since_days: int = 7, folder: str = "INBOX"
    ) -> list[GmailMessage]:
        return await asyncio.to_thread(self._list_recent_sync, limit, since_days, folder)

    def _check_login_sync(self) -> tuple[bool, str]:
        try:
            m = self._imap_connect()
            try:
                m.select("INBOX", readonly=True)
                return True, "OK"
            finally:
                try: m.close()
                except Exception: pass
                try: m.logout()
                except Exception: pass
        except imaplib.IMAP4.error as e:
            return False, f"IMAP error: {e}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    async def check_login(self) -> tuple[bool, str]:
        """Quick credential check. Returns (ok, reason)."""
        return await asyncio.to_thread(self._check_login_sync)


# ─────────────────────────────────────────────────────────────────────────────


def format_inbox_telegram(messages: Iterable[GmailMessage], header: str = "📥 Inbox") -> str:
    """Форматирует список писем для отправки в Telegram (HTML)."""
    msgs = list(messages)
    if not msgs:
        return f"{header}\n\nПусто за этот период."

    lines = [f"<b>{header}</b>", f"<i>{len(msgs)} писем</i>", ""]
    for m in msgs:
        sender = m.from_name or m.from_email
        time_str = m.date.astimezone().strftime("%d.%m %H:%M")
        wl = " 🛡" if m.is_whitelisted else ""
        unread = "● " if m.is_unread else ""
        # Экранирование HTML
        sender_e = sender.replace("<", "&lt;").replace(">", "&gt;")[:40]
        subject_e = (m.subject or "(без темы)").replace("<", "&lt;").replace(">", "&gt;")[:60]
        lines.append(f"{unread}<b>{sender_e}</b>{wl}  <i>{time_str}</i>")
        lines.append(f"  {subject_e}")
        if m.snippet:
            snip_e = m.snippet.replace("<", "&lt;").replace(">", "&gt;")[:80]
            lines.append(f"  <code>{snip_e}…</code>")
        lines.append("")
    return "\n".join(lines)
