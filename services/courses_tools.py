"""Tools для редактирования курсов RB Academy через Bishop.

Структура курсов: /root/projects/ai-agents-rb/Курс/портал/data/course-{N}/
- manifest.json (генерится из программы, не трогаем)
- lessons/{module-id}-{lesson-id}.md (текст урока + блок ---illustrations--- JSON + ---quiz--- JSON)
- illustrations/{lesson-id}-{slot}.{png|svg} (картинки)

Используется тренером в Telegram через Bishop, чтобы быстро править контент уроков.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path

PORTAL = Path("/root/projects/ai-agents-rb/Курс/портал")
COURSE_NAMES = {
    1: "Любитель кофе",
    2: "Бариста",
    3: "Профи",
    4: "Владелец кофейни",
    5: "Чай и авторские напитки",
}


# ─── helpers ─────────────────────────────────────────────────────────────────

def _lesson_path(course_id: int, lesson_id: str) -> Path:
    return PORTAL / "data" / f"course-{course_id}" / "lessons" / f"{lesson_id.replace('.', '-')}.md"


def _read_lesson_md(course_id: int, lesson_id: str) -> tuple[str, list[dict], list[dict]]:
    """Возвращает (body_text_без_служебных_блоков, illustrations, quiz)."""
    p = _lesson_path(course_id, lesson_id)
    if not p.exists():
        raise FileNotFoundError(f"Урок не найден: course={course_id}, lesson={lesson_id}")
    full = p.read_text(encoding="utf-8")

    illustrations = []
    quiz = []
    m_il = re.search(r"---illustrations---\s*([\s\S]+?)(?=\n---|\Z)", full)
    if m_il:
        try:
            illustrations = json.loads(m_il.group(1).strip())
        except Exception:
            pass
    m_q = re.search(r"---quiz---\s*([\s\S]+?)(?=\n---|\Z)", full)
    if m_q:
        try:
            quiz = json.loads(m_q.group(1).strip())
        except Exception:
            pass
    body = re.sub(r"---illustrations---[\s\S]*?(?=\n---|\Z)", "", full)
    body = re.sub(r"---quiz---[\s\S]*?(?=\n---|\Z)", "", body)
    return body.strip(), illustrations, quiz


def _write_illustrations(course_id: int, lesson_id: str, items: list[dict]) -> None:
    p = _lesson_path(course_id, lesson_id)
    full = p.read_text(encoding="utf-8")
    new_block = "---illustrations---\n" + json.dumps(items, ensure_ascii=False, indent=2)
    if "---illustrations---" in full:
        full = re.sub(r"---illustrations---\s*[\s\S]+?(?=\n---|\Z)", new_block, full, count=1)
    else:
        full = full.rstrip() + "\n\n" + new_block + "\n"
    p.write_text(full, encoding="utf-8")


def _course_dir(course_id: int) -> Path:
    return PORTAL / "data" / f"course-{course_id}"


def _list_lesson_ids(course_id: int) -> list[str]:
    d = _course_dir(course_id) / "lessons"
    if not d.exists():
        return []
    return sorted(p.stem.replace("-", ".", 1) for p in d.glob("*.md"))


# ─── tool schemas ────────────────────────────────────────────────────────────

_TOOL_LIST_LESSONS = {
    "name": "courses_list_lessons",
    "description": (
        "Список всех уроков курса с их id и заголовком. "
        "course_id: 1=Любитель, 2=Бариста, 3=Профи, 4=Владелец кофейни, 5=Чай и авторские напитки. "
        "Используй когда тренер просит «покажи уроки», «что в курсе X», «список глав»."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        },
        "required": ["course_id"],
    },
}

_TOOL_READ_LESSON = {
    "name": "courses_read_lesson",
    "description": (
        "Прочитать урок целиком: текст, список иллюстраций (slot, caption, prompt, image, status), "
        "тест. Используй ПЕРЕД любой правкой, чтобы знать точный текст."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "lesson_id": {"type": "string", "description": "Например '1.1', '3.4', '4.6'"},
        },
        "required": ["course_id", "lesson_id"],
    },
}

_TOOL_REPLACE_TEXT = {
    "name": "courses_replace_text",
    "description": (
        "Заменить фрагмент текста в уроке. find_text должен ТОЧНО совпадать с куском в уроке "
        "(пробелы, переносы, кавычки). Если find_text встречается несколько раз — заменит все. "
        "Используй для исправления опечаток, переписи абзацев, изменения рецепта."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "lesson_id": {"type": "string"},
            "find_text": {"type": "string", "description": "Точный фрагмент для замены"},
            "replace_text": {"type": "string", "description": "Чем заменить"},
        },
        "required": ["course_id", "lesson_id", "find_text", "replace_text"],
    },
}

_TOOL_UPDATE_CAPTION = {
    "name": "courses_update_caption",
    "description": (
        "Обновить подпись (caption) или промпт (prompt) у конкретной иллюстрации в уроке. "
        "Используй когда тренер просит «поменяй подпись под картинкой» или «улучши промпт»."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "lesson_id": {"type": "string"},
            "slot": {"type": "string", "description": "Имя слота, напр. 'hero', 'cross_section'"},
            "caption": {"type": "string", "description": "Новый caption (опционально)"},
            "prompt": {"type": "string", "description": "Новый prompt для генерации (опционально)"},
        },
        "required": ["course_id", "lesson_id", "slot"],
    },
}

_TOOL_REGENERATE_IMAGE = {
    "name": "courses_regenerate_image",
    "description": (
        "Перегенерировать конкретную иллюстрацию через ProxyAPI/gpt-image-1. "
        "Используется ТОЛЬКО для category != 'C' (фотореалистичные). Стоит ~₽25 за фото. "
        "Используй когда тренер недоволен картинкой и просит «перерисуй» или «сгенерируй новую»."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "course_id": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
            "lesson_id": {"type": "string"},
            "slot": {"type": "string"},
        },
        "required": ["course_id", "lesson_id", "slot"],
    },
}

TOOLS_OWNER = [
    _TOOL_LIST_LESSONS,
    _TOOL_READ_LESSON,
    _TOOL_REPLACE_TEXT,
    _TOOL_UPDATE_CAPTION,
    _TOOL_REGENERATE_IMAGE,
]
TOOLS_READONLY = [_TOOL_LIST_LESSONS, _TOOL_READ_LESSON]


# ─── executors ───────────────────────────────────────────────────────────────

def _tool_list_lessons(inp: dict) -> str:
    course_id = int(inp["course_id"])
    course_name = COURSE_NAMES.get(course_id, f"Курс {course_id}")
    lessons = []
    for lid in _list_lesson_ids(course_id):
        try:
            body, _, _ = _read_lesson_md(course_id, lid)
            # title — первый «## » заголовок
            m = re.search(r"^## (.+)$", body, re.MULTILINE)
            title = m.group(1).strip() if m else "(без заголовка)"
            lessons.append({"id": lid, "title": title})
        except Exception as e:
            lessons.append({"id": lid, "title": f"(ошибка: {e})"})
    return json.dumps({"course_id": course_id, "course_name": course_name, "lessons": lessons}, ensure_ascii=False)


def _tool_read_lesson(inp: dict) -> str:
    course_id = int(inp["course_id"])
    lesson_id = inp["lesson_id"]
    try:
        body, illustrations, quiz = _read_lesson_md(course_id, lesson_id)
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    return json.dumps({
        "course_id": course_id,
        "lesson_id": lesson_id,
        "body": body,
        "illustrations": illustrations,
        "quiz": quiz,
    }, ensure_ascii=False)


def _tool_replace_text(inp: dict) -> str:
    course_id = int(inp["course_id"])
    lesson_id = inp["lesson_id"]
    find_text = inp["find_text"]
    replace_text = inp["replace_text"]
    p = _lesson_path(course_id, lesson_id)
    if not p.exists():
        return json.dumps({"error": "урок не найден"}, ensure_ascii=False)
    full = p.read_text(encoding="utf-8")
    if find_text not in full:
        return json.dumps({
            "status": "not_found",
            "hint": "find_text не найден дословно. Текст должен совпадать буквально, включая пробелы и переносы.",
        }, ensure_ascii=False)
    count = full.count(find_text)
    new_full = full.replace(find_text, replace_text)
    p.write_text(new_full, encoding="utf-8")
    return json.dumps({"status": "replaced", "count": count}, ensure_ascii=False)


def _tool_update_caption(inp: dict) -> str:
    course_id = int(inp["course_id"])
    lesson_id = inp["lesson_id"]
    slot = inp["slot"]
    try:
        _, items, _ = _read_lesson_md(course_id, lesson_id)
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    found = None
    for it in items:
        if it.get("slot") == slot:
            found = it
            break
    if found is None:
        return json.dumps({"error": f"slot '{slot}' не найден"}, ensure_ascii=False)
    if "caption" in inp and inp["caption"] is not None:
        found["caption"] = inp["caption"]
    if "prompt" in inp and inp["prompt"] is not None:
        found["prompt"] = inp["prompt"]
        found["status"] = "draft"  # промпт изменился — картинку надо перегенерить
    _write_illustrations(course_id, lesson_id, items)
    return json.dumps({"status": "updated", "slot": slot, "item": found}, ensure_ascii=False)


def _tool_regenerate_image(inp: dict) -> str:
    course_id = int(inp["course_id"])
    lesson_id = inp["lesson_id"]
    slot = inp["slot"]

    try:
        _, items, _ = _read_lesson_md(course_id, lesson_id)
    except FileNotFoundError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    item = next((it for it in items if it.get("slot") == slot), None)
    if item is None:
        return json.dumps({"error": f"slot '{slot}' не найден"}, ensure_ascii=False)
    if item.get("category") == "C":
        return json.dumps({
            "error": "category=C — это SVG-схема, а не фото. Регенерация не поддерживается через этот тул."
        }, ensure_ascii=False)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return json.dumps({"error": "ANTHROPIC_API_KEY не задан в окружении"}, ensure_ascii=False)

    SIZE_BY_RATIO = {
        "16/9": "1536x1024", "21/9": "1536x1024", "1/1": "1024x1024",
        "9/16": "1024x1536", "4/3": "1536x1024",
    }
    size = SIZE_BY_RATIO.get(item.get("ratio", "16/9"), "1536x1024")
    prompt = item.get("prompt", "")
    if not prompt:
        return json.dumps({"error": "пустой prompt"}, ensure_ascii=False)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.proxyapi.ru/openai/v1")
        resp = client.images.generate(
            model="gpt-image-1", prompt=prompt, size=size, quality="high", n=1,
        )
        b64 = resp.data[0].b64_json
        data = base64.b64decode(b64)
    except Exception as e:
        return json.dumps({"error": f"генерация упала: {e}"}, ensure_ascii=False)

    img_name = f"lesson-{lesson_id.replace('.', '-')}-{slot}.png"
    img_path = PORTAL / "data" / f"course-{course_id}" / "illustrations" / img_name
    img_path.parent.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(data)
    item["image"] = img_name
    item["status"] = "generated"
    _write_illustrations(course_id, lesson_id, items)
    return json.dumps({
        "status": "generated", "image": img_name, "size_bytes": len(data),
        "cost_usd": 0.250 if "1536" in size or "1024x1536" in size else 0.167,
    }, ensure_ascii=False)


_EXECUTORS = {
    "courses_list_lessons": _tool_list_lessons,
    "courses_read_lesson": _tool_read_lesson,
    "courses_replace_text": _tool_replace_text,
    "courses_update_caption": _tool_update_caption,
    "courses_regenerate_image": _tool_regenerate_image,
}


def execute(name: str, inp: dict) -> str:
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"}, ensure_ascii=False)
    try:
        return fn(inp)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
