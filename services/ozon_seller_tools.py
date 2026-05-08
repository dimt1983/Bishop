"""
Ozon Селлер: ежемесячные отчёты о реализации.

Файлы лежат на Я.Диске в `Roastberry/Озон отчет/`:
  • Отчет о реализации товара_YYYYMMDD.xlsx
  • Позаказный отчет о реализации_YYYYMMDD.xlsx

Бишеп умеет:
  • ozon_monthly_report(month) — сделать готовый Excel-отчёт-сводку и отправить файлом
  • ozon_quick_summary(month) — текстовая сводка без файла

Берёт «Позаказный отчёт» (он содержит и итоги, и детализацию заказов).

Workflow:
  1. yadisk-rclone listf → найти файл за нужный месяц
  2. yadisk-rclone copy → скачать в workdir
  3. openpyxl → читать
  4. сводка по SKU → openpyxl → новый xlsx
  5. вернуть path для отправки в Telegram
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

WORKDIR = Path("/root/projects/ai-agents-rb/bishoprb-agent/workdir/ozon")
WORKDIR.mkdir(parents=True, exist_ok=True)

YADISK_FOLDER = "yadisk:Roastberry/Озон отчет"


# ─── Tool-use схемы ─────────────────────────────────────────────────────────

_TOOL_REPORT = {
    "name": "ozon_monthly_report",
    "description": (
        "Базовый отчёт по Ozon: сводка продаж по SKU за месяц (только из 'Позаказный отчёт о реализации'). "
        "Приготовит Excel-файл и отправит в Telegram. Используй когда нужна быстрая сводка по товарам."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "month": {"type": "string", "description": "'YYYY-MM' либо 'last' / 'current'."},
        },
        "required": ["month"],
    },
}

_TOOL_FULL_REPORT = {
    "name": "ozon_full_monthly_report",
    "description": (
        "ПОЛНЫЙ месячный отчёт Ozon — взаиморасчёты, услуги, штрафы, лояльность, "
        "страховка, B2B-продажи. Объединяет ВСЕ документы Ozon за месяц в один Excel "
        "с финальным сальдо (что пришло на счёт). Используй когда спрашивают "
        "«полный отчёт», «итоги по Озону», «сколько заработали в Озоне», «сколько Озон забрал», "
        "«взаиморасчёты», «сальдо». Файл прикрепится автоматически. Источник — Я.Диск "
        "папка 'Roastberry/Озон отчет' (Ozon выкладывает все документы в начале месяца за прошлый)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "month": {"type": "string", "description": "'YYYY-MM' либо 'last'."},
        },
        "required": ["month"],
    },
}

_TOOL_SUMMARY = {
    "name": "ozon_quick_summary",
    "description": (
        "Быстрая текстовая сводка по продажам на Ozon за указанный месяц. "
        "Без файла — только цифры. Удобно когда нужно ответить кратко."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "month": {"type": "string", "description": "'YYYY-MM' либо 'last'."},
        },
        "required": ["month"],
    },
}

_TOOL_API_CHECK = {
    "name": "ozon_api_check",
    "description": (
        "Проверить подключение Бишепа к Ozon Seller API. "
        "Используй когда спрашивают «работает ли Озон API», «подключен ли к Озону», "
        "«статус Озон». Без аргументов. Возвращает либо имя магазина если всё ок, "
        "либо точный код ошибки Ozon с подсказкой."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TOOLS_OWNER: list[dict] = [_TOOL_REPORT, _TOOL_FULL_REPORT, _TOOL_SUMMARY, _TOOL_API_CHECK]


# ─── Helpers ────────────────────────────────────────────────────────────────


def _resolve_month(month_arg: str) -> str:
    """'last'/'current'/'YYYY-MM' → 'YYYY-MM'."""
    s = (month_arg or "").strip().lower()
    today = date.today()
    if s in ("last", "previous", "prev", "прошлый"):
        first = today.replace(day=1)
        last = first - timedelta(days=1)
        return last.strftime("%Y-%m")
    if s in ("current", "this", "сейчас", "текущий"):
        return today.strftime("%Y-%m")
    if re.match(r"^\d{4}-\d{2}$", s):
        return s
    # ru-варианты "апрель 2026"
    months_ru = {
        "январ": "01", "феврал": "02", "март": "03", "апрел": "04",
        "май": "05", "мая": "05", "июн": "06", "июл": "07",
        "август": "08", "сентябр": "09", "октябр": "10",
        "ноябр": "11", "декабр": "12",
    }
    for ru, mm in months_ru.items():
        if ru in s:
            year = re.search(r"20\d{2}", s)
            yr = year.group() if year else str(today.year)
            return f"{yr}-{mm}"
    raise ValueError(f"Не понял месяц: {month_arg!r}. Используй 'YYYY-MM' или 'last'.")


def _yadisk_list() -> list[str]:
    """Список файлов в папке Озон отчет."""
    res = subprocess.run(
        ["rclone", "lsf", YADISK_FOLDER],
        capture_output=True, text=True, timeout=30,
    )
    if res.returncode != 0:
        raise RuntimeError(f"rclone lsf failed: {res.stderr[:300]}")
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _find_file_for_month(month: str, kind: str = "позаказный") -> Optional[str]:
    """Найти файл вида 'Позаказный отчет о реализации_YYYYMMDD.xlsx' за месяц."""
    files = _yadisk_list()
    yyyy, mm = month.split("-")
    pattern = re.compile(rf"_{yyyy}{mm}\d{{2}}\.xlsx$", re.IGNORECASE)
    candidates = [f for f in files if pattern.search(f)]
    if not candidates:
        return None
    # Предпочтём «Позаказный» если есть, иначе «Отчет о реализации товара»
    if kind == "позаказный":
        for f in candidates:
            if "позаказ" in f.lower():
                return f
    for f in candidates:
        if "отчет о реализации товара" in f.lower():
            return f
    return candidates[0]


def _yadisk_fetch(remote_name: str) -> Path:
    """Скачать файл в workdir/ozon. Если уже скачан — не качаем повторно."""
    local = WORKDIR / remote_name
    if local.exists() and local.stat().st_size > 1000:
        return local
    res = subprocess.run(
        ["rclone", "copy", f"{YADISK_FOLDER}/{remote_name}", str(WORKDIR)],
        capture_output=True, text=True, timeout=60,
    )
    if res.returncode != 0:
        raise RuntimeError(f"rclone copy failed: {res.stderr[:300]}")
    if not local.exists():
        raise FileNotFoundError(f"Скачали но локально нет: {local}")
    return local


def _find_files_for_month(month: str) -> dict[str, str]:
    """Найти ВСЕ файлы Ozon за месяц по типам.

    Возвращает {kind: filename}, kind ∈
      'pozakaznyy', 'realization_goods', 'billing', 'settlement',
      'pereyvystavlenie', 'pereyvystavlenie_pvz', 'pereyvystavlenie_acquiring',
      'fines', 'loyalty', 'b2b_sales', 'insurance', 'predoplata', 'predoplata_b2b',
      'service_act', 'job_act', 'sverka'
    """
    files = _yadisk_list()
    yyyy, mm = month.split("-")
    date_re = re.compile(rf"_{yyyy}{mm}\d{{2}}", re.IGNORECASE)

    out: dict[str, str] = {}
    for f in files:
        fl = f.lower()
        # 1. Реализация
        if "позаказный отчет о реализации" in fl and date_re.search(f):
            out["pozakaznyy"] = f
        elif "отчет о реализации товара" in fl and date_re.search(f):
            out["realization_goods"] = f
        # 2. Биллинг (суммы услуг)
        elif "отчет о суммах услуг" in fl:
            out["billing"] = f
        # 3. Взаиморасчёты
        elif "documentrealizationreportcommissionmutualsettlement" in fl and date_re.search(f):
            out["settlement"] = f
        # 4. Перевыставление услуг
        elif fl.startswith("отчет о перевыставлении услуг") and date_re.search(f):
            out["pereyvystavlenie"] = f
        elif "детальный отчет о перевыставлении" in fl:
            if "пвз" in fl or "курьер" in fl:
                out["pereyvystavlenie_pvz"] = f
            elif "эквайр" in fl:
                out["pereyvystavlenie_acquiring"] = f
        # 5. Штрафы
        elif "отчет по штрафам" in fl and date_re.search(f):
            out["fines"] = f
        # 6. Лояльность
        elif "лояльности" in fl or "лоялност" in fl:
            out["loyalty"] = f
        # 7. B2B продажи
        elif "documentb2bsales" in fl:
            out["b2b_sales"] = f
        # 8. Страхование
        elif "акт о страховой премии" in fl and date_re.search(f) and "(1)" not in f:
            out["insurance"] = f
        # 9. Предоплаты
        elif "отчет по предоплатам за товары (b2b)" in fl:
            out["predoplata_b2b"] = f
        elif "отчет по предоплатам за товары" in fl:
            out["predoplata"] = f
        # 10. Акт об оказанных услугах (Звёздные товары)
        elif "акт об оказанных услугах" in fl:
            out["service_act"] = f
        # 11. Акт выполненных работ (PDF)
        elif "marketplacedocumentexecutionjobact" in fl:
            out["job_act"] = f
        # 12. Акт сверки
        elif "акт сверки" in fl:
            out["sverka"] = f
    return out


def _parse_settlement(path: Path) -> dict:
    """«Отчёт о взаиморасчётах» — финальное сальдо за период."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active
    ops: list[dict] = []
    initial = {"debit": 0.0, "credit": 0.0}
    final = {"debit": 0.0, "credit": 0.0}
    in_table = False
    for row in ws.iter_rows(values_only=True):
        if row[0] and "Наименование" in str(row[0]):
            in_table = True
            continue
        if not in_table or not row[0]:
            continue
        name = str(row[0]).strip()
        # Колонки: name | doc | date | debit (Ozon должен) | credit (Ozon забирает)
        doc = row[1] or ""
        dt = row[2]
        debit = float(row[3] or 0)
        credit = float(row[4] or 0)
        if name.lower().startswith("начальное сальдо"):
            initial = {"debit": debit, "credit": credit}
        elif name.lower().startswith("конечное сальдо"):
            final = {"debit": debit, "credit": credit}
            break
        else:
            ops.append({
                "name": name, "doc": str(doc),
                "date": str(dt)[:10] if dt else "",
                "debit": debit, "credit": credit,
            })
    # Группировка по типу операции
    by_type: dict[str, dict] = defaultdict(lambda: {"n": 0, "debit": 0.0, "credit": 0.0})
    for op in ops:
        b = by_type[op["name"]]
        b["n"] += 1
        b["debit"] += op["debit"]
        b["credit"] += op["credit"]
    return {
        "ops": ops, "by_type": dict(by_type),
        "initial": initial, "final": final,
    }


def _parse_billing_services(path: Path) -> list[dict]:
    """«Отчёт о суммах услуг» — список услуг с количеством и суммой."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active
    services = []
    in_services = False
    for row in ws.iter_rows(values_only=True):
        first = row[0] if row else None
        if first and "Наименование услуги" in str(first):
            in_services = True
            continue
        if not in_services:
            continue
        if not first:
            continue
        if str(first).strip().lower() == "итого":
            break
        # name | count | sum_with_nds
        try:
            qty = int(row[1] or 0) if row[1] is not None else 0
            sum_v = float(row[2] or 0) if row[2] is not None else 0
            services.append({"name": str(first).strip(), "qty": qty, "sum": sum_v})
        except (ValueError, TypeError):
            continue
    return services


def _parse_fines(path: Path) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active
    fines = []
    header_row = None
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if row and any(("Наименование" in str(c)) for c in row if c):
            header_row = i
            continue
        if header_row is None or i <= header_row:
            continue
        non_empty = [c for c in row if c is not None]
        if not non_empty:
            continue
        # Ищем числовое значение суммы
        amount = 0
        name = ""
        for c in row:
            if isinstance(c, (int, float)) and c > 0:
                amount = float(c)
            elif c and not name:
                name = str(c)[:80]
        if amount and name:
            fines.append({"name": name, "amount": amount})
    return fines


def _parse_loyalty(path: Path) -> dict:
    """Программы лояльности — компенсации Ozon продавцу."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active
    rows = []
    total = 0.0
    in_table = False
    for row in ws.iter_rows(values_only=True):
        first = row[0]
        if first and "№ п/п" in str(first):
            in_table = True
            continue
        if not in_table:
            continue
        if not first:
            continue
        # # | программа | договор | ИНН | сумма
        try:
            program = str(row[1] or "")[:60]
            amount = float(row[4] or 0)
            if amount:
                rows.append({"program": program, "amount": amount})
                total += amount
        except (ValueError, TypeError):
            continue
    return {"rows": rows, "total": total}


def _parse_insurance(path: Path) -> dict:
    """Страховая премия — итого комиссия за страховку."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active
    total = 0.0
    for row in ws.iter_rows(values_only=True):
        for c in row:
            if c is None: continue
            sc = str(c)
            # Ищем «Итого» рядом с числом
            if sc.lower().strip().startswith("итого"):
                # числа в той же строке
                for cc in row:
                    if isinstance(cc, (int, float)) and cc > 0:
                        total = max(total, float(cc))
    return {"total": total}


def _parse_pozakaznyy(path: Path) -> dict:
    """Парсит «Позаказный отчёт о реализации». Возвращает агрегаты + итоги."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active

    # По наблюдению структура у Ozon стабильна:
    # row 13-14 — заголовки колонок (двухуровневые)
    # row 15 — нумерация колонок
    # row 16+ — данные
    by_sku: dict[str, dict] = defaultdict(lambda: {
        "name": "", "sku": "", "article": "", "qty": 0, "revenue": 0.0,
        "loyalty": 0.0, "baly": 0.0, "ozon_fee": 0.0, "to_seller": 0.0,
        "ret_qty": 0, "ret_sum": 0.0,
    })

    total_revenue = 0.0
    total_loyalty = 0.0
    total_baly = 0.0
    total_qty = 0
    total_ozon_fee = 0.0
    total_to_seller = 0.0
    total_ret_qty = 0
    total_ret_sum = 0.0
    period_min = None
    period_max = None

    for row in ws.iter_rows(min_row=16, values_only=True):
        if row[0] is None or not isinstance(row[0], (int, float)):
            continue
        name = (row[1] or "")[:120]
        article = row[2] or ""
        sku = str(row[3] or "")
        sold = float(row[5] or 0)
        loyalty = float(row[6] or 0)
        baly = float(row[7] or 0)
        qty = int(row[8] or 0)
        ozon_fee = float(row[12] or 0)
        to_seller = float(row[13] or 0)
        ret_qty = int(row[17] or 0)
        ret_sum = float(row[14] or 0)

        # Агрегат по SKU
        b = by_sku[sku] if sku else by_sku[name]
        b["sku"] = sku
        b["article"] = article
        b["name"] = name
        b["qty"] += qty
        b["revenue"] += sold
        b["loyalty"] += loyalty
        b["baly"] += baly
        b["ozon_fee"] += ozon_fee
        b["to_seller"] += to_seller
        b["ret_qty"] += ret_qty
        b["ret_sum"] += ret_sum

        # Итоги
        total_revenue += sold
        total_loyalty += loyalty
        total_baly += baly
        total_qty += qty
        total_ozon_fee += ozon_fee
        total_to_seller += to_seller
        total_ret_qty += ret_qty
        total_ret_sum += ret_sum

        # Период по датам заказов
        order_date = row[22]
        if order_date:
            try:
                ds = str(order_date)[:10]
                if period_min is None or ds < period_min: period_min = ds
                if period_max is None or ds > period_max: period_max = ds
            except Exception:
                pass

    # Сортируем SKU по выручке
    skus = sorted(by_sku.values(), key=lambda x: -x["revenue"])

    return {
        "skus": skus,
        "totals": {
            "qty": total_qty,
            "revenue": total_revenue,
            "loyalty": total_loyalty,
            "baly": total_baly,
            "ozon_fee": total_ozon_fee,
            "to_seller": total_to_seller,
            "returns_qty": total_ret_qty,
            "returns_sum": total_ret_sum,
        },
        "period": {"from": period_min, "to": period_max},
    }


def _build_xlsx(month: str, parsed: dict) -> Path:
    """Сделать готовый Excel-отчёт. Возвращает путь."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    out = WORKDIR / f"Озон_сводка_{month}.xlsx"
    wb = openpyxl.Workbook()

    # ── Лист 1: Сводка по SKU ────────────────────────────────────────────
    ws = wb.active
    ws.title = "Сводка"

    bold = Font(bold=True, size=11)
    header_fill = PatternFill("solid", fgColor="1d1d1f")
    header_font = Font(bold=True, color="ffffff", size=10)
    total_fill = PatternFill("solid", fgColor="f5f5f7")
    money_fmt = '#,##0.00 ₽'
    int_fmt = '0'
    border = Border(
        left=Side(style='thin', color='e4e4e7'),
        right=Side(style='thin', color='e4e4e7'),
        top=Side(style='thin', color='e4e4e7'),
        bottom=Side(style='thin', color='e4e4e7'),
    )

    ws["A1"] = f"📦 Ozon · продажи · {month}"
    ws["A1"].font = Font(bold=True, size=14)
    period = parsed.get("period") or {}
    ws["A2"] = f"Период заказов: {period.get('from','—')} → {period.get('to','—')}"
    ws["A2"].font = Font(italic=True, color="86868b")

    headers = ["№", "Товар", "Артикул", "SKU", "Кол-во", "Сумма ₽",
               "Средняя цена ₽", "Возвраты"]
    row = 4
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = border

    for i, sku in enumerate(parsed["skus"], 1):
        row += 1
        avg_price = sku["revenue"] / sku["qty"] if sku["qty"] else 0
        values = [
            i,
            sku["name"],
            sku["article"],
            sku["sku"],
            sku["qty"],
            sku["revenue"],
            avg_price,
            sku["ret_qty"] if sku["ret_qty"] else None,
        ]
        for col, v in enumerate(values, 1):
            c = ws.cell(row=row, column=col, value=v)
            c.border = border
            if col in (5, 8):
                c.number_format = int_fmt
                c.alignment = Alignment(horizontal="center")
            elif col in (6, 7):
                c.number_format = money_fmt
                c.alignment = Alignment(horizontal="right")

    # Итоговая строка
    row += 1
    t = parsed["totals"]
    ws.cell(row=row, column=1, value="ИТОГО").font = bold
    ws.cell(row=row, column=2, value=f"{len(parsed['skus'])} SKU").font = bold
    ws.cell(row=row, column=5, value=t["qty"])
    ws.cell(row=row, column=5).number_format = int_fmt
    ws.cell(row=row, column=6, value=t["revenue"])
    ws.cell(row=row, column=6).number_format = money_fmt
    avg = t["revenue"] / t["qty"] if t["qty"] else 0
    ws.cell(row=row, column=7, value=avg)
    ws.cell(row=row, column=7).number_format = money_fmt
    ws.cell(row=row, column=8, value=t["returns_qty"])
    for col in range(1, 9):
        c = ws.cell(row=row, column=col)
        c.fill = total_fill
        c.font = Font(bold=True)
        c.border = border

    # Ширина колонок
    widths = [5, 50, 28, 14, 9, 14, 14, 11]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + col)].width = w
    ws.row_dimensions[1].height = 22

    # ── Лист 2: Финансы ───────────────────────────────────────────────────
    ws2 = wb.create_sheet("Финансы")
    ws2["A1"] = f"💰 Финансы · {month}"
    ws2["A1"].font = Font(bold=True, size=14)
    fin_rows = [
        ("Выручка валом", t["revenue"], "цена реализации × кол-во"),
        ("Выплаты по лояльности", t["loyalty"], "Ozon компенсирует продавцу"),
        ("Баллы за скидки", t["baly"], "Ozon компенсирует продавцу"),
        ("Комиссия Ozon", -t["ozon_fee"], "удерживает с продавца"),
        ("К начислению продавцу", t["to_seller"], "итог за период"),
        ("Возвратов (шт)", t["returns_qty"], ""),
        ("Возвратов (₽)", -t["returns_sum"], ""),
    ]
    for i, (label, val, hint) in enumerate(fin_rows, 3):
        ws2.cell(row=i, column=1, value=label).font = Font(bold=True if "К начислению" in label else False)
        c = ws2.cell(row=i, column=2, value=val)
        c.number_format = money_fmt if isinstance(val, float) else int_fmt
        c.alignment = Alignment(horizontal="right")
        if "К начислению" in label:
            c.font = Font(bold=True, size=12, color="0071e3")
        ws2.cell(row=i, column=3, value=hint).font = Font(italic=True, color="86868b", size=9)

    ws2.column_dimensions["A"].width = 28
    ws2.column_dimensions["B"].width = 16
    ws2.column_dimensions["C"].width = 38

    wb.save(str(out))
    return out


# ─── Tool implementations ───────────────────────────────────────────────────


def _tool_monthly_report(inp: dict) -> str:
    try:
        month = _resolve_month(inp.get("month", "last"))
        remote = _find_file_for_month(month)
        if not remote:
            return json.dumps({
                "status": "not_found",
                "month": month,
                "error": f"В папке 'Озон отчет' на Я.Диске нет файла за {month}. "
                         f"Проверь что Ozon выгрузил отчёт.",
            }, ensure_ascii=False)
        local = _yadisk_fetch(remote)
        parsed = _parse_pozakaznyy(local)
        out = _build_xlsx(month, parsed)
        t = parsed["totals"]
        return json.dumps({
            "status": "ready",
            "month": month,
            "file_path": str(out),
            "filename": out.name,
            "caption": (
                f"📦 Ozon сводка · {month}\n\n"
                f"• Заказов: {t['qty']}\n"
                f"• Выручка: {t['revenue']:,.0f} ₽\n"
                f"• Комиссия Ozon: {t['ozon_fee']:,.0f} ₽\n"
                f"• К начислению: {t['to_seller']:,.0f} ₽\n"
                f"• Возвратов: {t['returns_qty']} шт\n"
                f"• SKU: {len(parsed['skus'])}"
            ),
            "totals": t,
            "skus_count": len(parsed["skus"]),
            "source_file": remote,
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("ozon_monthly_report failed")
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def _tool_quick_summary(inp: dict) -> str:
    try:
        month = _resolve_month(inp.get("month", "last"))
        remote = _find_file_for_month(month)
        if not remote:
            return json.dumps({
                "status": "not_found",
                "month": month,
                "error": f"Нет файла за {month}.",
            }, ensure_ascii=False)
        local = _yadisk_fetch(remote)
        parsed = _parse_pozakaznyy(local)
        t = parsed["totals"]
        top5 = parsed["skus"][:5]
        return json.dumps({
            "status": "ok",
            "month": month,
            "totals": t,
            "skus_count": len(parsed["skus"]),
            "top5": [
                {"name": s["name"], "qty": s["qty"], "revenue": s["revenue"]}
                for s in top5
            ],
            "period": parsed.get("period"),
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("ozon_quick_summary failed")
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def _tool_full_monthly_report(inp: dict) -> str:
    """Полный месячный отчёт Ozon: все документы → один Excel."""
    try:
        month = _resolve_month(inp.get("month", "last"))
        files = _find_files_for_month(month)
        if not files:
            return json.dumps({
                "status": "not_found", "month": month,
                "error": f"Документы за {month} не найдены на Я.Диске.",
            }, ensure_ascii=False)

        # Скачиваем все
        local_files: dict[str, Path] = {}
        for kind, name in files.items():
            try:
                local_files[kind] = _yadisk_fetch(name)
            except Exception as e:
                log.warning(f"fetch {kind} failed: {e}")

        # Парсим
        sections: dict[str, object] = {}
        # 1. Реализация (ключевая)
        if "pozakaznyy" in local_files:
            sections["realization"] = _parse_pozakaznyy(local_files["pozakaznyy"])
        # 2. Взаиморасчёты (главный финансовый итог)
        if "settlement" in local_files:
            sections["settlement"] = _parse_settlement(local_files["settlement"])
        # 3. Услуги
        if "billing" in local_files:
            sections["billing"] = _parse_billing_services(local_files["billing"])
        # 4. Штрафы
        if "fines" in local_files:
            sections["fines"] = _parse_fines(local_files["fines"])
        # 5. Лояльность
        if "loyalty" in local_files:
            sections["loyalty"] = _parse_loyalty(local_files["loyalty"])
        # 6. Страхование
        if "insurance" in local_files:
            sections["insurance"] = _parse_insurance(local_files["insurance"])

        # Строим Excel
        out = _build_full_xlsx(month, sections, list(files.keys()))

        # Делаем краткое резюме
        sttl = sections.get("settlement", {})
        final_sal = (sttl.get("final") or {}).get("credit", 0) - (sttl.get("final") or {}).get("debit", 0)
        real = sections.get("realization", {})
        real_total = (real.get("totals") or {}).get("revenue", 0)
        billing_total = sum(s["sum"] for s in sections.get("billing", []))
        fines_total = sum(f["amount"] for f in sections.get("fines", []))
        loyalty_total = (sections.get("loyalty") or {}).get("total", 0)
        insurance_total = (sections.get("insurance") or {}).get("total", 0)

        return json.dumps({
            "status": "ready",
            "month": month,
            "file_path": str(out),
            "filename": out.name,
            "caption": (
                f"📊 Озон · полный отчёт · {month}\n\n"
                f"📦 Реализация:    {real_total:>12,.0f} ₽\n"
                f"💸 Услуги Ozon:   {billing_total:>12,.0f} ₽\n"
                f"🎁 Лояльность:    {loyalty_total:>12,.0f} ₽\n"
                f"⚠️ Штрафы:         {fines_total:>12,.0f} ₽\n"
                f"🛡 Страховка:      {insurance_total:>12,.0f} ₽\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Сальдо к получению: <b>{final_sal:,.0f} ₽</b>\n\n"
                f"Источников: {len(files)} файлов"
            ),
            "sources": list(files.keys()),
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("ozon_full_monthly_report failed")
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def _build_full_xlsx(month: str, sections: dict, sources: list) -> Path:
    """Полный Excel-отчёт из всех документов Озона за месяц."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    out = WORKDIR / f"Озон_ПОЛНЫЙ_{month}.xlsx"
    wb = openpyxl.Workbook()

    title_font = Font(bold=True, size=14, color="1d1d1f")
    h_font = Font(bold=True, color="ffffff", size=10)
    h_fill = PatternFill("solid", fgColor="1d1d1f")
    bold = Font(bold=True)
    money = '#,##0.00 ₽'
    int_fmt = '0'
    border = Border(*(Side(style='thin', color='e4e4e7') for _ in range(4)))
    accent_fill = PatternFill("solid", fgColor="f5f5f7")

    # ── Лист 1: ИТОГО ────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Итого"
    ws["A1"] = f"📊 Озон · ПОЛНЫЙ ОТЧЁТ · {month}"
    ws["A1"].font = title_font

    sttl = sections.get("settlement", {})
    final = sttl.get("final") or {"debit": 0, "credit": 0}
    initial = sttl.get("initial") or {"debit": 0, "credit": 0}
    real = sections.get("realization", {})
    real_t = real.get("totals") or {}

    rows = [
        ("Источников документов", len(sources), ""),
        ("Источники", ", ".join(sources), ""),
        ("", "", ""),
        ("📦 Заказов", real_t.get("qty", 0), "штук"),
        ("📦 Реализация (выручка)", real_t.get("revenue", 0), "цена × кол-во"),
        ("➕ Выплаты лояльности от Ozon", real_t.get("loyalty", 0), "из реализации"),
        ("➕ Баллы за скидки от Ozon", real_t.get("baly", 0), "Ozon компенсирует"),
        ("➖ Комиссия Ozon в реализации", real_t.get("ozon_fee", 0), "из реализации"),
        ("💵 К начислению из реализации", real_t.get("to_seller", 0), ""),
        ("", "", ""),
        ("⚠️ Штрафы", sum(f["amount"] for f in sections.get("fines", [])), "от Ozon"),
        ("🎁 Лояльность партнёров", (sections.get("loyalty") or {}).get("total", 0), "компенсации"),
        ("🛡 Страховые премии", (sections.get("insurance") or {}).get("total", 0), "Ozon страхует товары"),
        ("💸 Услуги Ozon (биллинг)", sum(s["sum"] for s in sections.get("billing", [])), "доставка, обработка"),
        ("", "", ""),
        ("Начальное сальдо", initial.get("credit", 0) - initial.get("debit", 0), "+ Ozon должен / − должен Ozon"),
        ("Конечное сальдо", final.get("credit", 0) - final.get("debit", 0), "на конец периода"),
    ]
    for i, (label, val, hint) in enumerate(rows, 3):
        ws.cell(row=i, column=1, value=label).font = bold if label.startswith(("📦", "💵", "Начальное", "Конечное")) else Font()
        c = ws.cell(row=i, column=2, value=val)
        if isinstance(val, (int, float)):
            c.number_format = money if abs(val) > 100 else int_fmt
            c.alignment = Alignment(horizontal="right")
        if "Конечное сальдо" in label:
            c.font = Font(bold=True, size=12, color="0071e3")
            c.fill = accent_fill
        ws.cell(row=i, column=3, value=hint).font = Font(italic=True, color="86868b", size=9)

    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 38

    # ── Лист 2: Услуги Ozon (детально) ───────────────────────────────────
    if sections.get("billing"):
        ws2 = wb.create_sheet("Услуги")
        ws2["A1"] = f"💸 Услуги Ozon · {month}"
        ws2["A1"].font = title_font
        headers = ["Наименование", "Кол-во", "Сумма с НДС, ₽"]
        for j, h in enumerate(headers, 1):
            c = ws2.cell(row=3, column=j, value=h)
            c.font = h_font; c.fill = h_fill
            c.alignment = Alignment(horizontal="center")
        total = 0
        for i, s in enumerate(sections["billing"], 4):
            ws2.cell(row=i, column=1, value=s["name"])
            ws2.cell(row=i, column=2, value=s["qty"]).alignment = Alignment(horizontal="center")
            c = ws2.cell(row=i, column=3, value=s["sum"])
            c.number_format = money; c.alignment = Alignment(horizontal="right")
            total += s["sum"]
        last = i + 1
        ws2.cell(row=last, column=1, value="ИТОГО").font = bold
        c = ws2.cell(row=last, column=3, value=total)
        c.number_format = money; c.font = bold; c.fill = accent_fill
        ws2.column_dimensions["A"].width = 50
        ws2.column_dimensions["B"].width = 12
        ws2.column_dimensions["C"].width = 18

    # ── Лист 3: Взаиморасчёты ────────────────────────────────────────────
    if sections.get("settlement"):
        ws3 = wb.create_sheet("Взаиморасчёты")
        ws3["A1"] = f"💰 Взаиморасчёты с Ozon · {month}"
        ws3["A1"].font = title_font
        ws3.cell(row=2, column=1, value=f"Начальное сальдо: {initial.get('credit',0)-initial.get('debit',0):,.2f} ₽").font = Font(italic=True)
        headers = ["Операция", "Документ", "Дата", "Дебет (Ozon должен)", "Кредит (Ozon забирает)"]
        for j, h in enumerate(headers, 1):
            c = ws3.cell(row=4, column=j, value=h)
            c.font = h_font; c.fill = h_fill
            c.alignment = Alignment(horizontal="center")
        # Группа по типу
        for i, (typ, b) in enumerate(sorted(sttl["by_type"].items(), key=lambda x: -(x[1]["debit"]+x[1]["credit"])), 5):
            ws3.cell(row=i, column=1, value=typ).font = bold
            ws3.cell(row=i, column=2, value=f"({b['n']} оп.)")
            c = ws3.cell(row=i, column=4, value=b["debit"])
            c.number_format = money; c.alignment = Alignment(horizontal="right")
            c = ws3.cell(row=i, column=5, value=b["credit"])
            c.number_format = money; c.alignment = Alignment(horizontal="right")
        last = i + 1
        ws3.cell(row=last, column=1, value=f"Конечное сальдо: {final.get('credit',0)-final.get('debit',0):,.2f} ₽").font = Font(bold=True, color="0071e3")
        ws3.column_dimensions["A"].width = 40
        ws3.column_dimensions["B"].width = 18
        ws3.column_dimensions["C"].width = 14
        ws3.column_dimensions["D"].width = 22
        ws3.column_dimensions["E"].width = 22

    # ── Лист 4: Реализация (топ SKU) ─────────────────────────────────────
    if real.get("skus"):
        ws4 = wb.create_sheet("Топ SKU")
        ws4["A1"] = f"🏆 Топ товаров · {month}"
        ws4["A1"].font = title_font
        headers = ["№", "Товар", "Артикул", "Кол-во", "Выручка ₽", "Средняя цена"]
        for j, h in enumerate(headers, 1):
            c = ws4.cell(row=3, column=j, value=h)
            c.font = h_font; c.fill = h_fill
            c.alignment = Alignment(horizontal="center")
        for i, s in enumerate(real["skus"][:50], 4):
            ws4.cell(row=i, column=1, value=i-3).alignment = Alignment(horizontal="center")
            ws4.cell(row=i, column=2, value=s["name"][:80])
            ws4.cell(row=i, column=3, value=s["article"])
            ws4.cell(row=i, column=4, value=s["qty"]).alignment = Alignment(horizontal="center")
            c = ws4.cell(row=i, column=5, value=s["revenue"]); c.number_format = money
            avg = s["revenue"] / s["qty"] if s["qty"] else 0
            c = ws4.cell(row=i, column=6, value=avg); c.number_format = money
        for col, w in enumerate([5, 50, 28, 10, 16, 14], 1):
            ws4.column_dimensions[chr(64+col)].width = w

    wb.save(str(out))
    return out


def _tool_api_check(inp: dict) -> str:
    """Проверка подключения Ozon API."""
    import asyncio
    from services.ozon_api_client import OzonClient
    try:
        client = OzonClient()
        result = asyncio.run(client.check_connection())
        if result.get("ok"):
            return json.dumps({
                "status": "ok",
                "message": "✅ Ozon API подключен",
                "seller": result.get("seller"),
            }, ensure_ascii=False)
        return json.dumps({
            "status": "error",
            "message": "❌ Ozon API не подключен",
            **result,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Crash: {type(e).__name__}: {e}",
        }, ensure_ascii=False)


_DISPATCH = {
    "ozon_monthly_report": _tool_monthly_report,
    "ozon_full_monthly_report": _tool_full_monthly_report,
    "ozon_quick_summary": _tool_quick_summary,
    "ozon_api_check": _tool_api_check,
}


def execute_tool(name: str, inp: dict) -> str:
    fn = _DISPATCH.get(name)
    if not fn:
        return json.dumps({"status": "error", "error": f"unknown tool: {name}"}, ensure_ascii=False)
    return fn(inp)
