"""Сервис работы с Claude — парсинг задач, понимание ответов."""
import json
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic

from config import settings
from utils import log

client = AsyncAnthropic(api_key=settings.anthropic_api_key)
TZ = ZoneInfo(settings.timezone)


def _now() -> datetime:
    return datetime.now(TZ)


async def parse_task_creation(
    text: str,
    chat_members: list[dict],
) -> dict:
    """
    Парсит сообщение с постановкой задачи.

    Возвращает:
    {
        "success": bool,
        "error": str | None,
        "assignee_ids": list[int],         # telegram_id исполнителей
        "assignee_names": list[str],        # имена для сообщения
        "description": str,
        "deadline_iso": str,                # ISO формат
        "is_shared": bool | None,           # None если нужно переспросить
        "needs_clarification": bool,        # true если нужно уточнение
        "clarification_question": str | None,
    }

    chat_members — список {"telegram_id": int, "name": str, "username": str | None}
    """
    members_json = json.dumps(chat_members, ensure_ascii=False)
    now_iso = _now().strftime("%Y-%m-%d %H:%M:%S %z")

    system_prompt = f"""Ты помощник для парсинга задач из сообщений в рабочем чате.

Текущее время: {now_iso} (часовой пояс {settings.timezone})

Участники чата (выбирай исполнителей только из этого списка):
{members_json}

Твоя задача — извлечь из сообщения:
1. Кто исполнитель(и) — по имени или @username
2. Что нужно сделать (краткое описание)
3. Когда дедлайн (дата и время)
4. Если исполнителей несколько — определи тип:
   - "shared" (общая задача): "подготовьте презентацию вместе", "сделайте X"
   - "individual" (каждому своя): "пришлите каждый свой отчёт", "каждый сделает Y"
   - если неясно — пометь needs_clarification=true

Правила дедлайна:
- "завтра" = завтра 18:00
- "к пятнице" = пятница 18:00
- "сегодня" = сегодня к 18:00 если время не указано
- "утром" = 10:00, "вечером" = 18:00
- Если дедлайн в прошлом или не указан — установи завтра 18:00 и отметь в описании

Верни ТОЛЬКО JSON (без markdown, без пояснений):
{{
  "success": true или false,
  "error": null или "описание ошибки если не удалось",
  "assignee_ids": [telegram_id...],
  "assignee_names": ["имя1", "имя2"],
  "description": "короткое описание задачи",
  "deadline_iso": "2026-04-25T18:00:00+03:00",
  "is_shared": true/false/null,
  "needs_clarification": true/false,
  "clarification_question": null или "вопрос для постановщика"
}}

Если не нашёл исполнителя в списке участников — success=false, error объясняет.
"""

    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )
        raw = response.content[0].text.strip()
        # Убираем markdown fences если Claude их добавил
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result = json.loads(raw)
        log.info(f"Parsed task: {result}")
        return result
    except Exception as e:
        log.error(f"Failed to parse task: {e}")
        return {
            "success": False,
            "error": f"Не смог разобрать постановку: {e}",
            "needs_clarification": False,
        }


async def understand_completion_reply(
    text: str,
    pending_tasks: list[dict],
) -> dict:
    """
    Определяет относится ли сообщение в личке к закрытию задачи.

    pending_tasks: [{"id": int, "description": str, "deadline": str}, ...]

    Возвращает:
    {
        "action": "complete" | "postpone" | "question" | "unknown",
        "task_id": int | None,
        "new_deadline_iso": str | None,
        "clarification_needed": bool,
        "clarification_question": str | None,
    }
    """
    if not pending_tasks:
        return {"action": "unknown", "task_id": None}

    tasks_json = json.dumps(pending_tasks, ensure_ascii=False)
    now_iso = _now().strftime("%Y-%m-%d %H:%M:%S %z")

    system_prompt = f"""Ты помощник определяющий что хочет пользователь в личной переписке с ботом.

У пользователя есть открытые задачи:
{tasks_json}

Текущее время: {now_iso}

Сообщение пользователя относится к одной из задач. Определи что он хочет:

1. "complete" — подтверждает выполнение ("готово", "сделал", "закрыл", "отправил", "done")
2. "postpone" — просит перенести дедлайн ("перенеси на пн", "давай в пятницу", "не успеваю до завтра")
3. "question" — задаёт уточняющий вопрос
4. "unknown" — непонятно к чему относится

Если задач несколько и непонятно к какой относится — clarification_needed=true.

Верни ТОЛЬКО JSON:
{{
  "action": "complete" или "postpone" или "question" или "unknown",
  "task_id": id задачи или null,
  "new_deadline_iso": "ISO дата" или null (только для postpone),
  "clarification_needed": true/false,
  "clarification_question": null или "что переспросить"
}}
"""

    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"Failed to understand reply: {e}")
        return {"action": "unknown", "task_id": None}


async def search_chat_history(
    query: str,
    messages: list[dict],
) -> str:
    """
    Ищет ответ на вопрос по истории сообщений чата.

    messages: [{"sender": str, "text": str, "sent_at": str}, ...]
    """
    if not messages:
        return "В истории этого чата пока ничего нет."

    messages_text = "\n".join(
        f"[{m['sent_at']}] {m['sender']}: {m['text']}" for m in messages
    )

    system_prompt = """Ты помощник который ищет информацию в истории рабочего чата.

Правила:
- Отвечай кратко и по делу
- Цитируй конкретные сообщения с датой и автором если нашёл
- Если информации нет — честно скажи что не нашёл
- Не придумывай ничего чего нет в истории
"""

    user_prompt = f"""Вопрос: {query}

История чата:
{messages_text}"""

    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text
    except Exception as e:
        log.error(f"Search failed: {e}")
        return f"Не смог выполнить поиск: {e}"
