"""Assortment-тулы для Claude tool-use. Обёртка над Прайсы/assortment_manager.py.

Реестр всего ассортимента Roastberry: молоко, сиропы, чай, наборы.
Каждая позиция уже имеет «Цена Поступления» (без НДС) и «Базовый прайс» (с НДС)
из Excel-файла «прас для расчетов.xlsx». Bishop умеет показывать прайс,
искать позиции и прикидывать цену для новой позиции по медианному коэффициенту
наценки бренда.
"""
import json
import sys
from pathlib import Path

PRICES_DIR = Path("/root/projects/ai-agents-rb/Прайсы")
if str(PRICES_DIR) not in sys.path:
    sys.path.insert(0, str(PRICES_DIR))

import assortment_manager as am  # noqa: E402


# ─── Tool-определения для Anthropic API ────────────────────────────────────

_TOOL_SHOW = {
    "name": "assortment_show",
    "description": "Показать позиции ассортимента (молоко, сиропы, чай, наборы и т.п.) из реестра «прас для расчетов.xlsx». Можно отфильтровать по бренду или категории. Используй когда просят «покажи прайс на сиропы», «какие у нас есть молоко», «прайс на Botanika».",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand": {"type": "string", "description": "Бренд: BARLINE / BOTANIKA / Herbarista / SweetShot / NIKTEA листовой / Чай листовой и т.п."},
            "category": {"type": "string", "description": "Категория верхнего уровня: МОЛОКО / СИРОПЫ / ЧАЙ / RBR TEA / RESTORANICA / Китайский"},
            "limit": {"type": "integer", "description": "Максимум строк, по умолчанию 50"},
        },
    },
}

_TOOL_SEARCH = {
    "name": "assortment_search",
    "description": "Найти позицию в ассортименте по части названия. Используй для «сколько стоит сироп карамель», «есть ли у нас молочный улун», «найди позиции с лимоном».",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Часть названия позиции"},
        },
        "required": ["query"],
    },
}

_TOOL_CALC = {
    "name": "assortment_calculate",
    "description": "Прикинуть базовую цену для НОВОЙ позиции по медианному коэффициенту наценки её бренда. Используй когда просят «посчитай новый сироп BARLINE при поступлении 380», «прикинь цену для Botanika $2.5». Ничего не записывает.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand": {"type": "string", "description": "Точное название бренда из реестра (см. assortment_show или assortment_coeffs)"},
            "supply_rub": {"type": "number", "description": "Цена поступления в рублях (без НДС)"},
        },
        "required": ["brand", "supply_rub"],
    },
}

_TOOL_COEFFS = {
    "name": "assortment_coeffs",
    "description": "Показать таблицу медианных коэффициентов наценки по всем брендам в реестре. Используй когда просят «какая у нас наценка», «коэф для BARLINE», «по сколько разница между поступлением и базовой».",
    "input_schema": {"type": "object", "properties": {}},
}

_TOOL_SEND_CATALOG = {
    "name": "assortment_send_catalog",
    "description": "Прислать каталог чая (PDF с картинками и описаниями) в Telegram. kind=tea_all — сводный по всем брендам; kind=althaus / niktea — отдельный по бренду. Используй когда просят «пришли каталог чая», «скинь каталог Althaus», «пришли каталог Niktea». Для каталога кофе используй price_send_file (kind=catalog).",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["tea_all", "althaus", "niktea"],
                "description": "tea_all — все бренды чая в одном файле; althaus — только Althaus; niktea — только Niktea",
            },
        },
        "required": ["kind"],
    },
}

_TOOL_SEND_PRICELIST = {
    "name": "assortment_send_pricelist",
    "description": "Прислать клиентский прайс-лист (только базовые цены, без себестоимости) по категории. Используй когда просят «пришли прайс на чай / сиропы / молоко / прочее». Для прайса на кофе — price_send_file (kind=price).",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["tea", "syrups", "other"],
                "description": "tea = чай (Althaus, Niktea, RBR TEA, китайский); syrups = сиропы и топпинги; other = молоко, наборы, остальное",
            },
            "format": {
                "type": "string",
                "enum": ["pdf", "xlsx"],
                "description": "По умолчанию pdf",
            },
        },
        "required": ["category"],
    },
}

TOOLS_OWNER = [_TOOL_SHOW, _TOOL_SEARCH, _TOOL_CALC, _TOOL_COEFFS,
               _TOOL_SEND_CATALOG, _TOOL_SEND_PRICELIST]
# Public видит прайс, но не себестоимость и не коэф наценки
_TOOL_SHOW_PUBLIC = {
    "name": "assortment_show",
    "description": "Показать позиции ассортимента Roastberry (молоко, сиропы, чай, наборы). Только базовая цена. Себестоимость не показывается.",
    "input_schema": _TOOL_SHOW["input_schema"],
}
_TOOL_SEARCH_PUBLIC = {
    "name": "assortment_search",
    "description": "Найти позицию в ассортименте Roastberry по части названия. Возвращается только базовая цена.",
    "input_schema": _TOOL_SEARCH["input_schema"],
}
TOOLS_READONLY = [_TOOL_SHOW_PUBLIC, _TOOL_SEARCH_PUBLIC,
                  _TOOL_SEND_CATALOG, _TOOL_SEND_PRICELIST]


# ─── Каталог-файлы ─────────────────────────────────────────────────────────

_TEA_DIR = Path("/root/projects/ai-agents-rb/Чай/чистовики")
_PRICELIST_DIR = Path("/root/projects/ai-agents-rb/Прайсы/чистовики")

_CATALOG_FILES = {
    "tea_all": {
        "path": _TEA_DIR / "Roastberry_Каталог_Чай.pdf",
        "caption": "Каталог чая Roastberry — все бренды",
    },
    "althaus": {
        "path": _TEA_DIR / "Roastberry_Каталог_Althaus.pdf",
        "caption": "Каталог Althaus",
    },
    "niktea": {
        "path": _TEA_DIR / "Roastberry_Каталог_Niktea.pdf",
        "caption": "Каталог Niktea",
    },
}

_PRICELIST_FILES = {
    "tea":    {"pdf": "Roastberry_Прайс_Чай.pdf",     "xlsx": "Roastberry_Прайс_Чай.xlsx",
               "caption": "Прайс Roastberry — Чай"},
    "syrups": {"pdf": "Roastberry_Прайс_Сиропы.pdf",  "xlsx": "Roastberry_Прайс_Сиропы.xlsx",
               "caption": "Прайс Roastberry — Сиропы"},
    "other":  {"pdf": "Roastberry_Прайс_Прочее.pdf",  "xlsx": "Roastberry_Прайс_Прочее.xlsx",
               "caption": "Прайс Roastberry — Прочее (молоко, наборы)"},
}


def _tool_send_catalog(inp: dict) -> str:
    kind = inp.get("kind")
    info = _CATALOG_FILES.get(kind)
    if not info:
        return json.dumps({"status": "error", "error": f"unknown kind: {kind}"}, ensure_ascii=False)
    path: Path = info["path"]
    if not path.exists():
        return json.dumps(
            {"status": "error", "error": f"файл не найден: {path.name}. Сначала запусти tea_catalog.py"},
            ensure_ascii=False,
        )
    return json.dumps({
        "status": "ready",
        "path": str(path),
        "caption": info["caption"],
        "filename": path.name,
    }, ensure_ascii=False)


def _tool_send_pricelist(inp: dict) -> str:
    cat = inp.get("category")
    fmt = inp.get("format") or "pdf"
    info = _PRICELIST_FILES.get(cat)
    if not info:
        return json.dumps({"status": "error", "error": f"unknown category: {cat}"}, ensure_ascii=False)
    fname = info.get(fmt)
    if not fname:
        return json.dumps({"status": "error", "error": f"format {fmt} недоступен для {cat}"}, ensure_ascii=False)
    path = _PRICELIST_DIR / fname
    if not path.exists():
        return json.dumps(
            {"status": "error",
             "error": f"файл не найден: {fname}. Запусти assortment_manager.py export"},
            ensure_ascii=False,
        )
    return json.dumps({
        "status": "ready",
        "path": str(path),
        "caption": info["caption"],
        "filename": path.name,
    }, ensure_ascii=False)


# ─── Executors ──────────────────────────────────────────────────────────────

def _format_row_owner(p: dict) -> str:
    return (f"{p['brand'][:22]:<22} | {p['name'][:55]:<55} | "
            f"поступл {p['supply_rub']:>7.0f} → базовый {p['basic_rub']:>7.0f}  "
            f"k={p['markup']:.2f}")


def _format_row_public(p: dict) -> str:
    return f"{p['brand'][:22]:<22} | {p['name'][:60]:<60} | {p['basic_rub']:>7.0f} ₽"


def _tool_show(inp: dict, *, owner: bool) -> str:
    positions, _ = am.load_assortment()
    rows = positions
    if inp.get("brand"):
        b = inp["brand"].lower()
        rows = [p for p in rows if p["brand"].lower() == b]
    if inp.get("category"):
        c = inp["category"].lower()
        rows = [p for p in rows if p["category"].lower() == c]
    limit = int(inp.get("limit") or 50)
    rows_show = rows[:limit]
    fmt = _format_row_owner if owner else _format_row_public
    lines = [fmt(p) for p in rows_show]
    lines.append(f"\nПоказано {len(rows_show)} из {len(rows)} (всего в реестре {len(positions)})")
    return "\n".join(lines) if lines else "Ничего не нашлось."


def _tool_search(inp: dict, *, owner: bool) -> str:
    positions, _ = am.load_assortment()
    q = (inp.get("query") or "").lower().strip()
    if not q:
        return "Пустой запрос."
    rows = [p for p in positions if q in p["name"].lower()]
    fmt = _format_row_owner if owner else _format_row_public
    if not rows:
        return f"По запросу «{inp['query']}» ничего не найдено."
    lines = [fmt(p) for p in rows[:30]]
    if len(rows) > 30:
        lines.append(f"\n…и ещё {len(rows) - 30}. Уточни запрос.")
    return "\n".join(lines)


def _tool_calc(inp: dict) -> str:
    _, coeffs = am.load_assortment()
    res = am.calc_basic_price(float(inp["supply_rub"]), inp["brand"], coeffs)
    return json.dumps(res, ensure_ascii=False)


def _tool_coeffs() -> str:
    _, coeffs = am.load_assortment()
    lines = [f"{'Бренд':<32} {'n':>4} {'медиана':>8} {'мин':>6} {'макс':>6}"]
    lines.append("-" * 60)
    for brand, info in sorted(coeffs.items()):
        lines.append(f"{brand[:32]:<32} {info['n']:>4} "
                     f"{info['median']:>8.3f} {info['min']:>6.3f} {info['max']:>6.3f}")
    return "\n".join(lines)


_DISPATCH_OWNER = {
    "assortment_show": lambda inp: _tool_show(inp, owner=True),
    "assortment_search": lambda inp: _tool_search(inp, owner=True),
    "assortment_calculate": _tool_calc,
    "assortment_coeffs": lambda inp: _tool_coeffs(),
    "assortment_send_catalog": _tool_send_catalog,
    "assortment_send_pricelist": _tool_send_pricelist,
}
_DISPATCH_PUBLIC = {
    "assortment_show": lambda inp: _tool_show(inp, owner=False),
    "assortment_search": lambda inp: _tool_search(inp, owner=False),
    "assortment_send_catalog": _tool_send_catalog,
    "assortment_send_pricelist": _tool_send_pricelist,
}


def execute_tool(name: str, inp: dict, *, is_owner: bool = True) -> str:
    table = _DISPATCH_OWNER if is_owner else _DISPATCH_PUBLIC
    handler = table.get(name)
    if handler is None:
        return json.dumps({"status": "error", "error": f"unknown tool: {name}"}, ensure_ascii=False)
    try:
        return handler(inp)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
