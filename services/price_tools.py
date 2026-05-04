"""Прайс-тулы для Claude tool-use. Обёртка над Roastberry price_manager.

Импортирует price_manager как модуль (без subprocess) — нужны openpyxl и reportlab
в venv Bishop'а.
"""
import json
import sys
from datetime import date
from pathlib import Path

PRICES_DIR = Path("/root/projects/ai-agents-rb/Прайсы")
if str(PRICES_DIR) not in sys.path:
    sys.path.insert(0, str(PRICES_DIR))

import price_manager as pm  # noqa: E402


# ─── Tool definitions для Anthropic API ─────────────────────────────────────

_POS_INPUT = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Название позиции БЕЗ суффикса обжарки. Способ обжарки передавай в roast, НЕ в имени.",
        },
        "type": {
            "type": "string",
            "enum": ["моносорт", "микролот", "blend Es", "blend F"],
            "description": "Тип позиции. Микролот считается по другим формулам (CEH=250, наценка через множитель 0.5)",
        },
        "roast": {
            "type": "array",
            "description": "Способ обжарки как ТЭГ позиции. F=фильтр, E=эспрессо. Можно оба ['F','E']. Это атрибут одной позиции, НЕ повод создавать вторую.",
            "items": {"type": "string", "enum": ["F", "E"]},
        },
        "green_usd": {
            "type": "number",
            "description": "Цена зелёного кофе $/кг. Для моносорта/микролота обязательно. Для бленда — оставь пустым и передай components.",
        },
        "components": {
            "type": "array",
            "description": "Только для бленда. Состав: santos / robusta / ethiopia с долями (pct) и ценами (usd).",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["santos", "robusta", "ethiopia"]},
                    "pct": {"type": "number", "description": "Доля компонента, например 70"},
                    "usd": {"type": "number", "description": "Цена компонента $/кг"},
                },
                "required": ["name", "pct", "usd"],
            },
        },
    },
    "required": ["name", "type"],
}


_TOOL_SHOW = {
    "name": "price_show",
    "description": "Показать текущие позиции прайса с ценой 1кг и оптовыми. Используй для «покажи прайс», «какие позиции», «сколько стоит X», «есть ли в наличии Y».",
    "input_schema": {"type": "object", "properties": {}},
}
_TOOL_CALC = {
    "name": "price_calculate",
    "description": "Рассчитать цены для новой позиции БЕЗ записи в реестр. Возвращает: сырьё, СТМ 1кг, Базовый 1кг, от 10кг, от 25кг, Базовый 200г, СТМ 200г. Используй для «посчитай», «прикинь», «сколько будет стоить».",
    "input_schema": _POS_INPUT,
}
_TOOL_ADD = {
    "name": "price_add",
    "description": "Добавить позицию в реестр positions.json и пересобрать чистовики (Excel + PDF). ВАЖНО: используй только после явного подтверждения от пользователя. Если пользователь сразу пишет «добавь» — сначала покажи расчёт через price_calculate и спроси «добавлять?». Зови этот тул только после «да/добавляй/ок/верно».",
    "input_schema": _POS_INPUT,
}
_TOOL_REMOVE = {
    "name": "price_remove",
    "description": "Удалить позицию из positions.json (только из JSON-реестра, черновик Дмитрия не модифицируется). Имя должно ТОЧНО совпадать с тем что в реестре. Если неуверен — сначала вызови price_show.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Точное имя позиции из реестра"},
        },
        "required": ["name"],
    },
}

_TOOL_SEND_FILE_PUBLIC = {
    "name": "price_send_file",
    "description": "Прислать файл прайса, каталога или КП по аренде в Telegram-чат. Используй когда просят «пришли/скинь/вышли прайс/каталог/коммерческое предложение по аренде». kind=price — простой прайс с ценами; kind=catalog — каталог сортов с описаниями; kind=rental — коммерческое предложение по аренде кофейного оборудования (NIMBUS V.4 + WPM ZD-18). По умолчанию pdf.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["price", "catalog", "rental"],
                "description": "price = прайс-лист с ценами; catalog = каталог с описанием сортов; rental = КП по аренде кофейного оборудования",
            },
            "format": {
                "type": "string",
                "enum": ["pdf", "xlsx"],
                "description": "Формат. Каталог и rental только в pdf. По умолчанию pdf.",
            },
        },
        "required": ["kind"],
    },
}

_TOOL_SEND_FILE_OWNER = {
    "name": "price_send_file",
    "description": "Прислать файл в Telegram-чат. Доступные: price (клиентский прайс), catalog (каталог с описаниями), rental (КП по аренде кофейного оборудования), stm (внутренний СТМ-прайс с себестоимостью), dashboard (внутренний дашборд). Format — pdf или xlsx (для catalog/rental/dashboard только pdf).",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["price", "catalog", "rental", "stm", "dashboard"],
            },
            "format": {"type": "string", "enum": ["pdf", "xlsx"]},
        },
        "required": ["kind"],
    },
}

TOOLS_OWNER = [_TOOL_SHOW, _TOOL_CALC, _TOOL_ADD, _TOOL_REMOVE, _TOOL_SEND_FILE_OWNER]
TOOLS_READONLY = [_TOOL_SHOW, _TOOL_SEND_FILE_PUBLIC]
TOOLS = TOOLS_OWNER  # обратная совместимость

# Карта файлов чистовиков → формат → имя файла. Базовая директория — pm.OUTPUT_DIR.
_FILES = {
    "price":     {"pdf": "Roastberry_Прайс_2026.pdf",   "xlsx": "Roastberry_Прайс_2026.xlsx"},
    "catalog":   {"pdf": "Roastberry_Каталог_2026.pdf"},
    "rental":    {"pdf": "Roastberry_КП_Аренда.pdf"},
    "stm":       {"pdf": "Roastberry_СТМ_2026.pdf",     "xlsx": "Roastberry_СТМ_2026.xlsx"},
    "dashboard": {"pdf": "Roastberry_Дашборд_2026.pdf"},
}
_FILE_CAPTIONS = {
    "price":     "Прайс Roastberry",
    "catalog":   "Каталог Roastberry",
    "rental":    "Коммерческое предложение Roastberry — аренда кофейного оборудования",
    "stm":       "СТМ-прайс Roastberry (внутренний)",
    "dashboard": "Дашборд Roastberry (внутренний)",
}


# ─── Executors ───────────────────────────────────────────────────────────────

def _resolve_green_usd(inp: dict) -> tuple[float, list | None]:
    components = inp.get("components")
    if components:
        green_usd = sum(c["pct"] / 100.0 * c["usd"] for c in components)
        return green_usd, components
    green_usd = inp.get("green_usd")
    if green_usd is None:
        raise ValueError("Не указано ни green_usd, ни components")
    return float(green_usd), None


def _calc_payload(name: str, ptype: str, green_usd: float, p: dict) -> dict:
    return {
        "name": name,
        "type": ptype,
        "green_usd": round(green_usd, 4),
        "syrye": p["syrye"],
        "stm_1kg": p["stm_1kg"],
        "bazoviy_1kg": p["bazoviy_1kg"],
        "p10": p["p10"],
        "p25": p["p25"],
        "bazoviy_200g": p["bazoviy_200g"],
        "stm_200g": p["stm_200g"],
    }


def _tool_show() -> str:
    main = pm.collect_main()
    lines = [f"Всего позиций: {len(main)}\n"]
    for r in main:
        tag = "🆕 " if r["is_new"] else ""
        lines.append(
            f"{tag}{(r['type'] or '')[:12]:12} | {str(r['name'])[:48]:48} | "
            f"баз {r['bazoviy_1kg']:>7} | 10кг {r['p10']:>6} | 25кг {r['p25']:>6}"
        )
    return "\n".join(lines)


def _tool_calculate(inp: dict) -> str:
    green_usd, components = _resolve_green_usd(inp)
    p = pm.calculate(green_usd, ptype=inp["type"])
    payload = _calc_payload(inp["name"], inp["type"], green_usd, p)
    if components:
        payload["components"] = components
    return json.dumps(payload, ensure_ascii=False)


def _tool_add(inp: dict) -> str:
    green_usd, components = _resolve_green_usd(inp)
    p = pm.calculate(green_usd, ptype=inp["type"])

    positions = pm.load_positions()
    positions = [pp for pp in positions if pp["name"] != inp["name"]]
    positions.append({
        "name": inp["name"],
        "type": inp["type"],
        "green_usd": round(green_usd, 4),
        "components": components,
        "added": date.today().isoformat(),
    })
    pm.save_positions(positions)

    # roast → tags в metadata.json. Бленды получают префикс B (BF/BE).
    roast = inp.get("roast") or []
    if roast:
        ptype = inp["type"]
        prefix = "B" if ptype.startswith("blend") else ""
        tags = [f"{prefix}{r}" for r in roast]
        meta = pm.load_metadata()
        existing = meta.get(inp["name"], {})
        meta[inp["name"]] = {
            "name": inp["name"],
            "display_name": existing.get("display_name") or inp["name"],
            "tags": tags,
            "edition": existing.get("edition"),
            "description": existing.get("description", ""),
            "q_score": existing.get("q_score"),
        }
        pm.save_metadata(meta)

    pm.cmd_export(None)

    payload = _calc_payload(inp["name"], inp["type"], green_usd, p)
    payload["status"] = "added"
    payload["registry"] = str(pm.POSITIONS_FILE)
    if roast:
        payload["roast"] = roast
    return json.dumps(payload, ensure_ascii=False)


def _tool_remove(inp: dict) -> str:
    positions = pm.load_positions()
    before = len(positions)
    positions = [pp for pp in positions if pp["name"] != inp["name"]]
    if len(positions) == before:
        return json.dumps(
            {"status": "not_found", "name": inp["name"]},
            ensure_ascii=False,
        )
    pm.save_positions(positions)
    pm.cmd_export(None)
    return json.dumps(
        {"status": "removed", "name": inp["name"]},
        ensure_ascii=False,
    )


def _tool_send_file(inp: dict) -> str:
    """Подготавливает файл для отправки. Возвращает JSON с path/caption.

    Сама отправка происходит в хэндлере (Bishop'е через aiogram).
    """
    kind = inp.get("kind")
    fmt = inp.get("format") or "pdf"
    files_for_kind = _FILES.get(kind)
    if not files_for_kind:
        return json.dumps(
            {"status": "error", "error": f"unknown kind: {kind}"},
            ensure_ascii=False,
        )
    filename = files_for_kind.get(fmt) or files_for_kind.get("pdf")
    if not filename:
        return json.dumps(
            {"status": "error", "error": f"format {fmt} недоступен для {kind}"},
            ensure_ascii=False,
        )
    path = pm.OUTPUT_DIR / filename
    if not path.exists():
        return json.dumps(
            {"status": "error", "error": f"файл не найден: {filename}"},
            ensure_ascii=False,
        )
    caption = _FILE_CAPTIONS.get(kind, "")
    return json.dumps(
        {"status": "ready", "path": str(path), "caption": caption, "filename": filename},
        ensure_ascii=False,
    )


_DISPATCH = {
    "price_show": lambda inp: _tool_show(),
    "price_calculate": _tool_calculate,
    "price_add": _tool_add,
    "price_remove": _tool_remove,
    "price_send_file": _tool_send_file,
}


def execute_tool(name: str, inp: dict) -> str:
    """Синхронный диспетчер. Из async-кода вызывай через asyncio.to_thread."""
    handler = _DISPATCH.get(name)
    if handler is None:
        return json.dumps(
            {"status": "error", "error": f"unknown tool: {name}"},
            ensure_ascii=False,
        )
    try:
        return handler(inp)
    except Exception as e:
        return json.dumps(
            {"status": "error", "error": str(e)},
            ensure_ascii=False,
        )
