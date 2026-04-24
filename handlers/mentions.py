"""Сервис работы с Claude — парсинг задач, понимание ответов."""
import json
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic

from config import settings
from utils import log

client = AsyncAnthropic(
    api_key=settings.anthropic_api_key,
    base_url=settings.anthropic_base_url,
)
TZ = ZoneInfo(settings.timezone)


def _now() -> datetime:
    return datetime.now(TZ)


async def parse_task_creation(
    text: str,
    chat_members: list[dict],
) -> dict:
    """
    Парсит сообщение с постановкой задачи.
    """
    members_json = json.dumps(chat_members, ensure_ascii=False, indent=2)
    now_iso = _now().strftime("%Y-%m-%d %H:%M:%S %z")

    system_prompt = f"""Ты помощник для парсинга задач из сообщений в рабочем чате.

Текущее время: {now_iso} (часовой пояс {settings.timezone})

Участники чата которые писали в нём хотя бы раз (ты можешь назначать задачи только им):
{members_json}

ОЧЕНЬ ВАЖНО: сопоставляй имена гибко, учитывая что люди в Telegram могут быть записаны по-разному:
- Имя в Telegram может быть фамилией, именем, прозвищем, или короткой формой
- Например, если в чате есть "Ра Sha" с username @b_ounc_e, а постановщик пишет "Паша" — это МОЖЕТ быть тот же человек (пользователь просто зовёт его по имени)
- Если в чате есть "Дмитрий" и пишут "Дима" или "Димон" — это он же
- Если упомянули @username точно совпадающий с username участника — это точно он
- Если написано имя которое явно близко по смыслу к одному из участников (включая транслитерацию, сокращение, или форму имени) — считай это совпадением
- Если точного совпадения нет, но есть один очевидный кандидат — выбери его и отметь это в описании задачи
- Если кандидатов несколько или совсем непонятно — success=false с объяснением "не могу однозначно определить исполнителя, уточните — в чате есть: <список>"
- Если упомянули @username которого НЕТ в списке — success=false, напиши что "@X ещё не писал в чат, попросите его написать любое сообщение сюда"

Правила дедлайна:
- "завтра" = завтра 18:00
- "к пятнице" = пятница 18:00
- "сегодня" = сегодня к 18:00 если время не указано
- "утром" = 10:00, "вечером" = 18:00
- Если конкретное время указано — используй его
- Если дедлайн явно в прошлом — завтра 18:00 + отметь в описании

Множественные исполнители:
- "shared" — общая задача ("подготовьте презентацию вместе", "сделайте X")
- "individual" — каждому своя ("пришлите каждый свой отчёт")
- Если неясно — needs_clarification=true

Отличай задачу от информационного сообщения:
- "напомни мне/ему X" = задача
- "сделай/проверь/пришли X" = задача
- "у нас появился бот", "читай историю", "привет" = НЕ задача, success=false с error="Не похоже на постановку задачи"

Верни ТОЛЬКО JSON (без markdown, без пояснений):
{{
  "success": true или false,
  "error": null или "человеко-читаемая причина",
  "assignee_ids": [telegram_id...],
  "assignee_names": ["как обращаться к исполнителю"],
  "description": "краткое описание задачи",
  "deadline_iso": "2026-04-25T18:00:00+03:00",
  "is_shared": true/false/null,
  "needs_clarification": true/false,
  "clarification_question": null или "вопрос"
}}
"""

    try:
        response = await client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )
        raw = response.content[0].text.strip()
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
    """Определяет относится ли сообщение в личке к закрытию задачи."""
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
    """Ищет ответ на вопрос по истории сообщений чата."""
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
