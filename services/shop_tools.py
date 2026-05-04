"""Тулы для Claude tool-use по управлению Mini App-магазином (TMA).

Bishop редактирует products.json и фото в `/root/projects/ai-agents-rb/BOT_TG/tma_static/`,
коммитит изменения в репо `dimt1983/TG-BOT` (через клонированную копию в /tmp/TG-BOT)
и пушит — Railway автоматически передеплоит TMA через 1-2 минуты.

Авторизация: основные tools (запись) разрешены только owner_telegram_id
(передаётся в context — см. claude_service.shop_chat).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from utils import log


# ── Пути ──
TMA_STATIC = Path("/root/projects/ai-agents-rb/BOT_TG/tma_static")
PRODUCTS_JSON = TMA_STATIC / "products.json"
PHOTOS_DIR = TMA_STATIC / "photos" / "products"
GIT_REPO = Path("/tmp/TG-BOT")


# ─── Tool definitions ───────────────────────────────────────────────────────

_TOOL_SEARCH = {
    "name": "shop_search",
    "description": "Найти товары в магазине по части названия / категории / подкатегории. "
                   "Возвращает список матчей. Используй ВСЕГДА перед другими тулами, "
                   "если не уверен в точном tma_id товара.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Часть названия или категории. Пусто = все"},
            "category": {"type": "string", "enum": ["coffee","tea","syrup","milk",""], "description": "Опц. фильтр по категории"},
            "limit": {"type": "integer", "description": "Макс. результатов", "default": 15},
        },
    },
}

_TOOL_GET = {
    "name": "shop_get_product",
    "description": "Полная карточка одного товара: имя, фасовки/цены, описание, остаток, фото.",
    "input_schema": {
        "type": "object",
        "properties": {"tma_id": {"type": "string"}},
        "required": ["tma_id"],
    },
}

_TOOL_UPDATE_FIELD = {
    "name": "shop_update_field",
    "description": "Обновить поле товара: price/description/stock/tags/name/country/roast/process. "
                   "Для price указывай fasovka_size (\"200 г\"/\"1 кг\"/...) и new_price. "
                   "Для description/name/country/roast/process — value (string). "
                   "Для tags — список (заменяет полностью). "
                   "Для stock — целое число.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tma_id": {"type": "string"},
            "field": {"type": "string", "enum": ["price","description","stock","tags","name","country","roast","process"]},
            "value": {"description": "Новое значение (тип зависит от поля)"},
            "fasovka_size": {"type": "string", "description": "Только для field=price (например '1 кг')"},
            "new_price": {"type": "number", "description": "Только для field=price"},
        },
        "required": ["tma_id","field"],
    },
}

_TOOL_SET_PHOTO_URL = {
    "name": "shop_set_photo_from_url",
    "description": "Скачать фото по URL и привязать к товару.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tma_id": {"type": "string"},
            "url": {"type": "string", "description": "Прямой URL картинки (https://...jpg/png)"},
        },
        "required": ["tma_id","url"],
    },
}

_TOOL_SET_PHOTO_TG = {
    "name": "shop_set_photo_from_telegram",
    "description": "Привязать фото которое пользователь только что прислал в чат. "
                   "Используй когда видишь сообщение про 'добавь фото' / 'это фото товара' "
                   "и в контексте упомянуто что фото уже отправлено.",
    "input_schema": {
        "type": "object",
        "properties": {"tma_id": {"type": "string"}},
        "required": ["tma_id"],
    },
}

_TOOL_ADD = {
    "name": "shop_add_product",
    "description": "Добавить новый товар в магазин. Минимум: name, category, subcategory, fasovka [(size, price)].",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "category": {"type": "string", "enum": ["coffee","tea","syrup","milk"]},
            "subcategory": {"type": "string", "description": "ID подкатегории (например 'tea_althaus_loose')"},
            "fasovka": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"size": {"type":"string"}, "price": {"type":"number"}},
                    "required": ["size","price"],
                },
            },
            "description": {"type": "string"},
            "country": {"type": "string"},
            "roast": {"type": "string"},
            "process": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "stock": {"type": "integer"},
        },
        "required": ["name","category","subcategory","fasovka"],
    },
}

_TOOL_REMOVE = {
    "name": "shop_remove_product",
    "description": "Удалить товар из магазина (полностью).",
    "input_schema": {
        "type": "object",
        "properties": {"tma_id": {"type": "string"}},
        "required": ["tma_id"],
    },
}

_TOOL_LIST_SUBCATS = {
    "name": "shop_list_subcategories",
    "description": "Список подкатегорий с id и названием. Используй чтобы выбрать subcategory при добавлении товара.",
    "input_schema": {
        "type": "object",
        "properties": {"category": {"type": "string", "description": "Опц. фильтр (coffee/tea/syrup/milk)"}},
    },
}

_TOOL_SEND_PHOTO = {
    "name": "shop_send_photo",
    "description": "Отправить фото товара пользователю в чат. Используй когда просят "
                   "«скинь/покажи/пришли фото товара». Может также использоваться для проверки "
                   "что фото действительно привязано после правки.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tma_id": {"type": "string"},
            "caption": {"type": "string", "description": "Подпись к фото (опц.)"},
        },
        "required": ["tma_id"],
    },
}

_TOOL_PUBLISH = {
    "name": "shop_publish",
    "description": "Закоммитить накопленные изменения в Git и запушить на GitHub. "
                   "Railway передеплоит магазин через 1-2 минуты. "
                   "Используй ОДИН РАЗ в конце сессии после всех правок (не после каждой).",
    "input_schema": {
        "type": "object",
        "properties": {
            "comment": {"type": "string", "description": "Что изменилось (для git commit message)"},
        },
        "required": ["comment"],
    },
}


TOOLS_OWNER = [_TOOL_SEARCH, _TOOL_GET, _TOOL_LIST_SUBCATS, _TOOL_UPDATE_FIELD,
               _TOOL_SET_PHOTO_URL, _TOOL_SET_PHOTO_TG, _TOOL_ADD, _TOOL_REMOVE,
               _TOOL_SEND_PHOTO, _TOOL_PUBLISH]
TOOLS_READONLY = [_TOOL_SEARCH, _TOOL_GET, _TOOL_LIST_SUBCATS, _TOOL_SEND_PHOTO]


# ─── Реализация ─────────────────────────────────────────────────────────────

def _load() -> dict:
    return json.loads(PRODUCTS_JSON.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    PRODUCTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE)
    return s[:50]


def _to_dict_resp(success: bool, **kw) -> str:
    payload = {"ok": success, **kw}
    return json.dumps(payload, ensure_ascii=False)


# ── tools ──

def shop_search(query: str = "", category: str = "", limit: int = 15) -> str:
    data = _load()
    q = (query or "").strip().lower()
    items = data["products"]
    if category:
        items = [p for p in items if p.get("category") == category]
    if q:
        items = [p for p in items if q in p.get("name", "").lower()
                 or q in (p.get("country") or "").lower()
                 or q in p.get("subcategory", "").lower()]
    items = items[:limit]
    return _to_dict_resp(True, count=len(items), items=[
        {"tma_id": p["id"], "name": p["name"], "category": p["category"],
         "subcategory": p["subcategory"], "min_price": min(f["price"] for f in p["fasovka"]),
         "has_photo": bool(p.get("photo")), "stock": p.get("stock", 0)}
        for p in items
    ])


def shop_get_product(tma_id: str) -> str:
    data = _load()
    p = next((x for x in data["products"] if x["id"] == tma_id), None)
    if not p:
        return _to_dict_resp(False, error=f"Товар не найден: {tma_id}")
    return _to_dict_resp(True, product=p)


def shop_list_subcategories(category: str = "") -> str:
    data = _load()
    subs = data["subcategories"]
    if category:
        subs = [s for s in subs if s["parent"] == category]
    return _to_dict_resp(True, count=len(subs), subcategories=subs)


def shop_update_field(tma_id: str, field: str, value=None,
                      fasovka_size: str = "", new_price: float = None) -> str:
    data = _load()
    p = next((x for x in data["products"] if x["id"] == tma_id), None)
    if not p:
        return _to_dict_resp(False, error=f"Товар не найден: {tma_id}")
    if field == "price":
        if not fasovka_size or new_price is None:
            return _to_dict_resp(False, error="Для price нужны fasovka_size и new_price")
        # ищем фасовку
        fa = next((f for f in p.get("fasovka", []) if f["size"] == fasovka_size), None)
        if not fa:
            return _to_dict_resp(False, error=f"Фасовка не найдена: {fasovka_size}",
                                 available=[f["size"] for f in p.get("fasovka", [])])
        old = fa["price"]
        fa["price"] = float(new_price)
        _save(data)
        return _to_dict_resp(True, msg=f"Цена {fasovka_size} обновлена: {old} → {new_price}")
    if field == "stock":
        try:
            v = int(value)
        except Exception:
            return _to_dict_resp(False, error="stock должен быть целым числом")
        p["stock"] = v
        _save(data)
        return _to_dict_resp(True, msg=f"Остаток обновлён: {v}")
    if field == "tags":
        if not isinstance(value, list):
            return _to_dict_resp(False, error="tags должен быть массивом строк")
        p["tags"] = [str(t) for t in value]
        _save(data)
        return _to_dict_resp(True, msg=f"Теги: {p['tags']}")
    # текстовые поля
    if field in ("name", "description", "country", "roast", "process"):
        p[field] = str(value or "")
        _save(data)
        return _to_dict_resp(True, msg=f"Поле {field} обновлено")
    return _to_dict_resp(False, error=f"Неизвестное поле: {field}")


def _download(url: str, dest: Path) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if len(data) < 500:
            return False, "слишком маленький файл"
        dest.write_bytes(data)
        return True, "ok"
    except Exception as e:
        return False, str(e)


def shop_set_photo_from_url(tma_id: str, url: str) -> str:
    data = _load()
    p = next((x for x in data["products"] if x["id"] == tma_id), None)
    if not p:
        return _to_dict_resp(False, error=f"Товар не найден: {tma_id}")
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = PHOTOS_DIR / f"{tma_id}.jpg"
    ok, msg = _download(url, dest)
    if not ok:
        return _to_dict_resp(False, error=f"Не удалось скачать: {msg}")
    p["photo"] = f"photos/products/{tma_id}.jpg"
    _save(data)
    return _to_dict_resp(True, msg=f"Фото привязано: {dest.name}")


# Контекст: pending photo bytes (передаются в shop_chat при наличии attached photo)
_PENDING_PHOTO: dict[int, bytes] = {}


def set_pending_photo(user_id: int, image_bytes: bytes) -> None:
    _PENDING_PHOTO[user_id] = image_bytes


def clear_pending_photo(user_id: int) -> None:
    _PENDING_PHOTO.pop(user_id, None)


def shop_set_photo_from_telegram(tma_id: str, _user_id: int = 0) -> str:
    if _user_id not in _PENDING_PHOTO:
        return _to_dict_resp(False, error="Нет приложенного фото. Попроси пользователя прислать фото в этом же сообщении.")
    img = _PENDING_PHOTO[_user_id]
    data = _load()
    p = next((x for x in data["products"] if x["id"] == tma_id), None)
    if not p:
        return _to_dict_resp(False, error=f"Товар не найден: {tma_id}")
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = PHOTOS_DIR / f"{tma_id}.jpg"
    dest.write_bytes(img)
    p["photo"] = f"photos/products/{tma_id}.jpg"
    _save(data)
    clear_pending_photo(_user_id)
    return _to_dict_resp(True, msg=f"Фото из чата привязано к {tma_id}")


def shop_add_product(name: str, category: str, subcategory: str,
                     fasovka: list, description: str = "",
                     country: str = "", roast: str = "", process: str = "",
                     tags: Optional[list] = None, stock: int = 10) -> str:
    data = _load()
    # Проверим что подкатегория существует
    if not any(s["id"] == subcategory for s in data["subcategories"]):
        return _to_dict_resp(False, error=f"Подкатегория '{subcategory}' не существует. Используй shop_list_subcategories.")
    # Уникальный id
    base = f"{category[0]}-{_slug(name)}"
    tma_id = base
    i = 2
    while any(p["id"] == tma_id for p in data["products"]):
        tma_id = f"{base}_{i}"
        i += 1
    item = {
        "id": tma_id, "category": category, "subcategory": subcategory,
        "name": name, "country": country, "roast": roast, "process": process,
        "description": description,
        "recipe_e": "", "recipe_f": "",
        "fasovka": fasovka, "stock": int(stock),
        "tags": tags or [], "photo": None,
    }
    data["products"].append(item)
    _save(data)
    return _to_dict_resp(True, msg=f"Добавлен товар: {tma_id}", tma_id=tma_id)


def shop_remove_product(tma_id: str) -> str:
    data = _load()
    before = len(data["products"])
    data["products"] = [p for p in data["products"] if p["id"] != tma_id]
    if len(data["products"]) == before:
        return _to_dict_resp(False, error=f"Товар не найден: {tma_id}")
    _save(data)
    # удалим фото
    photo_path = PHOTOS_DIR / f"{tma_id}.jpg"
    if photo_path.exists():
        photo_path.unlink()
    return _to_dict_resp(True, msg=f"Товар {tma_id} удалён")


def shop_send_photo(tma_id: str, caption: str = "") -> str:
    """Возвращает marker для loop'а — он подхватит и отправит фото в Telegram.
    Сам файл должен лежать в PHOTOS_DIR/{tma_id}.jpg."""
    data = _load()
    p = next((x for x in data["products"] if x["id"] == tma_id), None)
    if not p:
        return _to_dict_resp(False, error=f"Товар не найден: {tma_id}")
    photo_path = PHOTOS_DIR / f"{tma_id}.jpg"
    if not photo_path.exists():
        return _to_dict_resp(False, error=f"У товара '{p['name']}' нет фото в каталоге")
    return _to_dict_resp(
        True,
        status="ready",
        path=str(photo_path),
        caption=caption or p["name"],
        filename=f"{tma_id}.jpg",
        msg=f"Фото отправлено: {p['name']}",
    )


def shop_publish(comment: str = "Bishop: shop update") -> str:
    """Копирует TMA-файлы в /tmp/TG-BOT и пушит в GitHub.
    Перед коммитом подтягивает свежий main с remote (fetch + rebase),
    чтобы не упасть с 'Updates were rejected (fetch first)'."""
    if not GIT_REPO.exists():
        return _to_dict_resp(False, error=f"Git repo не клонирован: {GIT_REPO}")
    env = {**os.environ}
    git = ["git", "-C", str(GIT_REPO)]

    try:
        # 0. Синк с remote — на случай если кто-то ещё пушил
        subprocess.run(git + ["fetch", "origin", "main"], check=True, env=env,
                       capture_output=True, text=True)
        # Если в локальной копии есть unstaged изменения — git rebase упадёт.
        # Делаем rebase ТОЛЬКО когда нет грязных рабочих файлов; иначе сначала
        # быстрый stash. После — pop. Если конфликт — сразу abort и сообщаем.
        dirty = subprocess.run(git + ["status", "--porcelain"], check=True, env=env,
                               capture_output=True, text=True).stdout.strip()
        stashed = False
        if dirty:
            r = subprocess.run(git + ["stash", "push", "-u", "-m", "bishop-pre-rebase"],
                               env=env, capture_output=True, text=True)
            stashed = r.returncode == 0
        rb = subprocess.run(git + ["rebase", "origin/main"], env=env,
                            capture_output=True, text=True)
        if rb.returncode != 0:
            subprocess.run(git + ["rebase", "--abort"], env=env, capture_output=True)
            if stashed:
                subprocess.run(git + ["stash", "pop"], env=env, capture_output=True)
            return _to_dict_resp(False, error=f"Не получилось rebase: {rb.stderr.strip()[:300]}")
        if stashed:
            subprocess.run(git + ["stash", "pop"], env=env, capture_output=True)

        # 1. Копируем актуальные файлы магазина
        subprocess.run(["cp", str(PRODUCTS_JSON),
                        str(GIT_REPO / "tma_static" / "products.json")], check=True)
        subprocess.run(
            "cp -r " + str(PHOTOS_DIR) + "/. " +
            str(GIT_REPO / "tma_static" / "photos" / "products" / ""),
            shell=True, check=False,
        )

        # 2. add + commit + push
        subprocess.run(git + ["add", "tma_static/products.json",
                              "tma_static/photos/products/"], check=True, env=env)
        result = subprocess.run(git + ["status", "--short"],
                                check=True, capture_output=True, text=True, env=env)
        if not result.stdout.strip():
            return _to_dict_resp(True, msg="Изменений нет, push не нужен")

        subprocess.run(git + ["config", "user.email", "bishop@roastberry.local"],
                       check=True, env=env)
        subprocess.run(git + ["config", "user.name", "Bishop"], check=True, env=env)
        subprocess.run(git + ["commit", "-m", f"Bishop: {comment}"], check=True, env=env)

        push = subprocess.run(git + ["push", "origin", "main"], env=env,
                              capture_output=True, text=True)
        if push.returncode != 0:
            # Один retry: ещё раз fetch + rebase + push (вдруг прилетело прямо сейчас)
            subprocess.run(git + ["fetch", "origin", "main"], env=env, capture_output=True)
            subprocess.run(git + ["rebase", "origin/main"], env=env, capture_output=True)
            push = subprocess.run(git + ["push", "origin", "main"], env=env,
                                  capture_output=True, text=True)
            if push.returncode != 0:
                return _to_dict_resp(False,
                                     error=f"Push отвергнут: {push.stderr.strip()[:300]}")

        return _to_dict_resp(True,
                             msg="Закоммичено и запушено. Railway передеплоит TMA через ~2 минуты.")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace") if hasattr(e.stderr, "decode") else (e.stderr or "")
        return _to_dict_resp(False, error=f"Git ошибка: {e} {stderr[:300]}")


# ── Диспетчер ──

def execute_tool(name: str, input_data: dict, user_id: int = 0) -> str:
    """Выполняет тул по имени. Возвращает JSON-строку результата.
    user_id передаётся для shop_set_photo_from_telegram (для pending_photo)."""
    try:
        if name == "shop_search":
            return shop_search(**input_data)
        if name == "shop_get_product":
            return shop_get_product(**input_data)
        if name == "shop_list_subcategories":
            return shop_list_subcategories(**input_data)
        if name == "shop_update_field":
            return shop_update_field(**input_data)
        if name == "shop_set_photo_from_url":
            return shop_set_photo_from_url(**input_data)
        if name == "shop_set_photo_from_telegram":
            return shop_set_photo_from_telegram(_user_id=user_id, **input_data)
        if name == "shop_add_product":
            return shop_add_product(**input_data)
        if name == "shop_remove_product":
            return shop_remove_product(**input_data)
        if name == "shop_send_photo":
            return shop_send_photo(**input_data)
        if name == "shop_publish":
            return shop_publish(**input_data)
        return _to_dict_resp(False, error=f"Неизвестный тул: {name}")
    except TypeError as e:
        return _to_dict_resp(False, error=f"Неверные аргументы для {name}: {e}")
    except Exception as e:
        log.exception(f"shop_tools.execute_tool failed for {name}")
        return _to_dict_resp(False, error=str(e))
