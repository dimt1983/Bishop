"""Рендер пакетных карточек Roastberry — наложение этикетки на красный
(эспрессо) и зелёный (фильтр) шаблоны.

Шаблоны лежат в BOT_TG/photos/Эспрессо, Фильтр, 200 г/.
Координаты этикетки выверены вручную Дмитрием.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont


TEMPLATE_DIR = Path("/root/projects/ai-agents-rb/BOT_TG/photos/Эспрессо, Фильтр, 200 г")

TEMPLATES = {
    "filter": {
        "path": TEMPLATE_DIR / "FILTER1.png",
        "bbox": (571, 1359, 1161, 1777),  # x1, y1, x2, y2
    },
    "espresso": {
        "path": TEMPLATE_DIR / "ESPRESSO1.png",
        "bbox": (576, 1342, 1140, 1749),
    },
}

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Поля которые отображаются на этикетке (имя в data-словаре)
LABEL_FIELDS = (
    "name", "type", "roast_descr",
    "aroma", "taste",
    "region", "altitude", "variety",
    "process", "roast_date", "batch",
)

# Поля которые ОБЯЗАТЕЛЬНО должен заполнить пользователь.
# type/roast_date/batch выводятся автоматически — не считаются обязательными.
REQUIRED_FROM_USER = (
    "name", "roast_descr",
    "aroma", "taste",
    "region", "altitude", "variety",
    "process",
)


def kind_from_subcategory(subcategory: str) -> str | None:
    """Возвращает 'espresso' / 'filter' или None если фасовка не подходит."""
    if not subcategory:
        return None
    if subcategory.startswith("coffee_espresso"):
        return "espresso"
    if subcategory.startswith("coffee_filter"):
        return "filter"
    return None  # coffee_black / coffee_borshch / coffee_drip_capsules — нет шаблона


def type_from_subcategory(subcategory: str) -> str:
    """Микролот / Моносорт / Смесь / пусто."""
    if not subcategory:
        return ""
    if subcategory.endswith("_microlot"):
        return "микролот"
    if subcategory.endswith("_mono"):
        return "моносорт"
    if subcategory.endswith("_blend"):
        return "смесь"
    return ""


def find_missing(card: dict) -> list[str]:
    """Возвращает список обязательных полей которых нет в карточке."""
    missing = []
    for k in REQUIRED_FROM_USER:
        v = card.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            missing.append(k)
    return missing


def render(kind: str, data: dict, out_path: Path) -> None:
    """Рендерит этикетку на шаблоне kind (espresso/filter) и сохраняет в out_path."""
    cfg = TEMPLATES[kind]
    LX1, LY1, LX2, LY2 = cfg["bbox"]

    im = Image.open(cfg["path"]).convert("RGBA")
    d = ImageDraw.Draw(im)

    # Стираем оригинальный текст этикетки
    PAD = 4
    d.rectangle([LX1+PAD, LY1+PAD, LX2-PAD, LY2-PAD], fill=(255, 255, 255, 255))

    INX1 = LX1 + 22
    INX2 = LX2 - 22
    INY1 = LY1 + 22

    NAME_FONT_SIZE = 32
    BADGE_FONT_SIZE = 15
    BADGE_W = 135

    f_badge = ImageFont.truetype(FONT_REG, BADGE_FONT_SIZE)
    badge_y = INY1 + 4
    for ln in [data.get("type", ""), data.get("roast_descr", "")]:
        if not ln:
            continue
        bbox = d.textbbox((0, 0), ln, font=f_badge)
        w = bbox[2] - bbox[0]
        d.text((INX2 - w, badge_y), ln, fill=(110, 110, 110), font=f_badge)
        badge_y += BADGE_FONT_SIZE + 4

    # Имя — авто-уменьшение если не влезает
    name = data.get("name", "")
    nfs = NAME_FONT_SIZE
    while nfs > 22:
        f_name = ImageFont.truetype(FONT_BOLD, nfs)
        bbox = d.textbbox((0, 0), name, font=f_name)
        if bbox[2] - bbox[0] <= (INX2 - INX1) - BADGE_W - 8:
            break
        nfs -= 2
    f_name = ImageFont.truetype(FONT_BOLD, nfs)
    d.text((INX1, INY1), name, fill=(40, 40, 40), font=f_name)

    sep_y = INY1 + nfs + 12
    d.line([(INX1, sep_y), (INX2, sep_y)], fill=(220, 220, 220), width=1)

    LBL_SIZE = TXT_SIZE = 15
    f_lbl = ImageFont.truetype(FONT_BOLD, LBL_SIZE)
    f_txt = ImageFont.truetype(FONT_REG, TXT_SIZE)

    y = sep_y + 14
    txt_x = INX1 + 78
    for label, key, width in [("Аромат:", "aroma", 38), ("Вкус:", "taste", 38)]:
        d.text((INX1, y), label, fill=(60, 60, 60), font=f_lbl)
        lines = textwrap.wrap(data.get(key, "") or "—", width=width)
        for i, ln in enumerate(lines):
            d.text((txt_x, y + i*(TXT_SIZE+4)), ln, fill=(60, 60, 60), font=f_txt)
        y += max(LBL_SIZE, len(lines)*(TXT_SIZE+4)) + 10

    d.line([(INX1, y), (INX2, y)], fill=(220, 220, 220), width=1)
    y += 12

    META_LBL_SIZE = 11
    META_VAL_SIZE = 14
    f_meta_lbl = ImageFont.truetype(FONT_REG, META_LBL_SIZE)
    f_meta_val = ImageFont.truetype(FONT_BOLD, META_VAL_SIZE)

    col1_x = INX1
    col2_x = INX1 + (INX2 - INX1)//2 + 6
    row_h = max(34, (LY2 - 18 - y) // 3)

    def draw_meta(x, yy, label, value):
        d.text((x, yy), label, fill=(140, 140, 140), font=f_meta_lbl)
        d.text((x, yy + META_LBL_SIZE + 2), str(value or "—"),
               fill=(40, 40, 40), font=f_meta_val)

    draw_meta(col1_x, y + row_h*0, "Регион:",     data.get("region"))
    draw_meta(col1_x, y + row_h*1, "Высота:",     data.get("altitude"))
    draw_meta(col1_x, y + row_h*2, "Сорт:",       data.get("variety"))
    draw_meta(col2_x, y + row_h*0, "Обработка:",  data.get("process"))
    draw_meta(col2_x, y + row_h*1, "Обжарка:",    data.get("roast_date"))
    draw_meta(col2_x, y + row_h*2, "Партия:",     data.get("batch"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out_path, "JPEG", quality=92)


def build_label_data(card: dict) -> dict:
    """Собирает словарь для этикетки из карточки products.json.

    Дополняет автополями (тип из подкатегории, дата обжарки сегодня если
    нет, партия по умолчанию '1')."""
    data = {
        "name": card.get("name", ""),
        "type": type_from_subcategory(card.get("subcategory", "")),
        "roast_descr": card.get("roast_descr", ""),
        "aroma": card.get("aroma", ""),
        "taste": card.get("taste", ""),
        "region": card.get("region", ""),
        "altitude": card.get("altitude", ""),
        "variety": card.get("variety", ""),
        "process": card.get("process", ""),
        "roast_date": card.get("roast_date") or date.today().strftime("%d.%m.%Y"),
        "batch": str(card.get("batch") or "1"),
    }
    return data
