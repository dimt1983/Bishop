"""
Бонус Monkey Grinder — ежемесячный расчёт премии для сети MG.

Источник — выгрузка 1С «Валовая прибыль предприятия» с фильтром
`Клиент.Сети = MONKEY GRINDER`. Каждый месяц 1-го числа этот xlsx
кладут в `yadisk:Roastberry/MG/`. Имя файла — произвольное (например
«отчет мг апрель.xlsx»), важна дата периода внутри файла.

Что делает Бишеп:
  • mg_bonus_calculate(month) — найти отчёт, посчитать премию по трём
    позициям с фиксированными ставками за единицу, собрать готовый
    Excel `Расчет премии <месяц> <гг>.xlsx` и отдать файлом в Telegram.
  • mg_bonus_summary(month)  — текстовая сводка без файла.
  • mg_bonus_check_pending() — проверить лежит ли уже отчёт за прошлый
    месяц; используется планировщиком 1-го числа.

Ставки премии за единицу (₽/шт или ₽/кг) хранятся здесь же — RATES.
Если 1С пришлёт новую номенклатуру с не-нулевым `E` (размер премии) —
её можно подхватить из самого отчёта; если ставки нет, позиция
помечается «нет ставки» и в ИТОГО не идёт.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

WORKDIR = Path("/root/projects/ai-agents-rb/bishoprb-agent/workdir/mg")
WORKDIR.mkdir(parents=True, exist_ok=True)

YADISK_FOLDER = "yadisk:Roastberry/MG"

# Фиксированные ставки бонуса (₽ за единицу). Согласованы с MG в марте 2026.
RATES: dict[str, float] = {
    'F "Roastberry" Бразилия Сертао упак. 200 г МОЛОТЫЙ': 51.23,
    'Бразилия Серрадо Дарк МАНКИ ГРИНДЕР - 1 кг': 154.43,
    'Бразилия Фазенда Сертао сухой МОЛОТЫЙ - 1 кг FILTER': 226.09,
}

RU_MONTHS = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}
RU_MONTHS_GEN = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


# ─── Tool схемы ────────────────────────────────────────────────────────────

_TOOL_CALCULATE = {
    "name": "mg_bonus_calculate",
    "description": (
        "Посчитать ежемесячный бонус Monkey Grinder по выгрузке 1С с Я.Диска. "
        "Скачивает отчёт за указанный месяц из папки 'Roastberry/MG', "
        "перемножает количества по торговым точкам на фиксированные ставки "
        "(51.23 ₽ за 200г, 154.43 ₽ за 1кг Дарк, 226.09 ₽ за 1кг Filter), "
        "формирует Excel с разбивкой по точкам и итогами и отправляет файлом. "
        "Используй когда Дмитрий говорит «посчитай бонус MG / MG за месяц / "
        "премия Манки Гриндер / премия за <месяц>»."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "month": {
                "type": "string",
                "description": "'YYYY-MM' либо 'last' (прошлый месяц) либо 'current'.",
            },
        },
        "required": ["month"],
    },
}

_TOOL_SUMMARY = {
    "name": "mg_bonus_summary",
    "description": (
        "Быстрая текстовая сводка по бонусу Monkey Grinder за указанный месяц "
        "без файла — только цифры по трём позициям и общая сумма."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "month": {"type": "string", "description": "'YYYY-MM' / 'last' / 'current'."},
        },
        "required": ["month"],
    },
}

_TOOL_CHECK_PENDING = {
    "name": "mg_bonus_check_pending",
    "description": (
        "Проверить лежит ли отчёт MG за прошлый месяц в Roastberry/MG. "
        "Возвращает status='ready' если файл найден или 'missing' если нет. "
        "Используется планировщиком 1-го числа месяца, чтобы либо посчитать, "
        "либо просигналить владельцу что отчёт не пришёл."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TOOLS_OWNER: list[dict] = [_TOOL_CALCULATE, _TOOL_SUMMARY, _TOOL_CHECK_PENDING]


# ─── Helpers ───────────────────────────────────────────────────────────────


def _resolve_month(month_arg: str) -> str:
    """'last'/'current'/'YYYY-MM'/'апрель'/'апрель 2026' → 'YYYY-MM'."""
    s = (month_arg or "").strip().lower()
    today = date.today()
    if s in ("last", "previous", "prev", "прошлый", "прошлый месяц"):
        first = today.replace(day=1)
        last = first - timedelta(days=1)
        return last.strftime("%Y-%m")
    if s in ("current", "this", "сейчас", "текущий"):
        return today.strftime("%Y-%m")
    if re.match(r"^\d{4}-\d{2}$", s):
        return s
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
    res = subprocess.run(
        ["rclone", "lsf", YADISK_FOLDER],
        capture_output=True, text=True, timeout=30,
    )
    if res.returncode != 0:
        raise RuntimeError(f"rclone lsf failed: {res.stderr[:300]}")
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _yadisk_fetch(remote_name: str) -> Path:
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


def _find_file_for_month(month: str) -> Optional[str]:
    """Найти xlsx в папке MG, у которого Период внутри листа покрывает месяц.

    На вход 'YYYY-MM'. Сначала пробуем по имени файла (русские месяцы /
    YYYY-MM / YYYYMM), и если не находим — заходим внутрь файлов и читаем C4.
    """
    files = [f for f in _yadisk_list() if f.lower().endswith(".xlsx")]
    if not files:
        return None

    yyyy, mm = month.split("-")
    mm_int = int(mm)
    ru = RU_MONTHS[mm_int]              # «апрель»
    ru_short = ru[:5]                   # «апрел»
    yyyy_short = yyyy[2:]               # «26»

    # Раунд 1 — по имени
    for f in files:
        fl = f.lower()
        if (
            f"{yyyy}-{mm}" in fl
            or f"{yyyy}{mm}" in fl
            or (ru_short in fl and (yyyy in fl or yyyy_short in fl or fl.count(yyyy_short) > 0))
            or (ru_short in fl and yyyy not in fl and yyyy_short not in fl)
        ):
            return f

    # Раунд 2 — заглядываем внутрь
    for f in files:
        try:
            local = _yadisk_fetch(f)
            import openpyxl
            wb = openpyxl.load_workbook(str(local), data_only=True, read_only=True)
            ws = wb.active
            for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
                for c in row:
                    if c is None: continue
                    sc = str(c)
                    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})", sc)
                    if m and m.group(2) == mm and m.group(3) == yyyy:
                        wb.close()
                        return f
            wb.close()
        except Exception as e:
            log.warning(f"peek into {f} failed: {e}")
            continue
    return None


# ─── Парсинг отчёта 1С ─────────────────────────────────────────────────────


def _parse_report(path: Path) -> dict:
    """Читает выгрузку 1С 'Валовая прибыль' для сети MG.

    Структура (стабильная):
      A2  — название отчёта
      C4  — период
      A10 'Номенклатура' / D10 'Количество' [/ E10 'Размер премии' …]
      A11 'Клиент'
      далее блоки: строка-номенклатура (A=имя, D=общее кол-во,
      опц E=ставка) → строки клиентов (A=имя, D=кол-во) → 'Итого'.
    """
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb.active

    period = None
    for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
        for c in row:
            if c and isinstance(c, str) and "Период:" in c:
                period = c.replace("Период:", "").strip()

    items: list[dict] = []
    current: Optional[dict] = None
    for row in ws.iter_rows(min_row=11, values_only=True):
        a = row[0]
        d = row[3] if len(row) > 3 else None
        e = row[4] if len(row) > 4 else None
        if a is None:
            continue
        a_str = str(a).strip()
        if a_str.lower() == "итого":
            break
        # Это позиция номенклатуры? Признак — есть ставка в RATES, либо
        # в столбце E отчёта самим 1С указан размер премии.
        is_nomenclature = (a_str in RATES) or (
            isinstance(e, (int, float)) and e and isinstance(d, (int, float)) and d
            and (current is None or isinstance(d, (int, float)))
        )
        # Уточнение: ориентируемся на жирные строки через RATES + наличие
        # количества без указанной ставки в E. Проще — фильтр по совпадению
        # имени с RATES, а fallback — по «Бразилия» / «Roastberry» в начале.
        if a_str in RATES:
            current = {
                "nom": a_str,
                "rate": RATES[a_str],
                "rate_source": "fixed",
                "total_qty_header": int(d or 0),
                "clients": [],
            }
            items.append(current)
        elif (
            isinstance(d, (int, float)) and d
            and (a_str.startswith(('F "Roastberry"', "Бразилия", "Roastberry"))
                 or "МАНКИ" in a_str.upper() or "МОЛОТЫЙ" in a_str.upper())
        ):
            # Новая номенклатура без фикс-ставки. Если 1С прислал E — берём.
            rate = float(e) if isinstance(e, (int, float)) and e else None
            current = {
                "nom": a_str,
                "rate": rate,
                "rate_source": "from_report" if rate else "missing",
                "total_qty_header": int(d or 0),
                "clients": [],
            }
            items.append(current)
        else:
            # Строка клиента
            if current is not None and isinstance(d, (int, float)):
                current["clients"].append({"name": a_str, "qty": int(d)})

    return {"period": period, "items": items}


# ─── Построение результирующего xlsx ──────────────────────────────────────


def _build_calc_xlsx(month: str, parsed: dict) -> Path:
    """Собирает xlsx 'Расчет премии <месяц> <гг>.xlsx' в строгом деловом
    стиле — для отправки клиенту."""
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    yyyy, mm = month.split("-")
    mm_int = int(mm)
    ru = RU_MONTHS[mm_int]
    yy = yyyy[2:]

    fname = f"Расчет премии {ru} {yy}.xlsx"
    out = WORKDIR / fname

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Расчёт премии"

    # ── Палитра (сдержанная, деловая) ───────────────────────────────────
    NAVY = "1F3864"        # тёмно-синий — шапка таблицы
    GRAY_DARK = "404040"   # для подзаголовков
    GRAY_MED = "BFBFBF"    # границы
    GRAY_LIGHT = "D9E1F2"  # выделение строки номенклатуры
    GRAY_BG = "F2F2F2"     # фон параметров
    SUBTOTAL_BG = "EDEDED" # ИТОГО по позиции
    TOTAL_BG = "1F3864"    # финальное ИТОГО
    WHITE = "FFFFFF"

    thin = Side(style="thin", color=GRAY_MED)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    bold = Font(bold=True)
    money_fmt = "#,##0.00"
    int_fmt = "#,##0"

    last_day = (date(int(yyyy), mm_int % 12 + 1, 1) - timedelta(days=1)).day if mm_int < 12 \
        else 31
    period_str = parsed.get("period") or f"01.{mm}.{yyyy} - {last_day:02d}.{mm}.{yyyy}"

    # ── Заголовок документа ─────────────────────────────────────────────
    ws.merge_cells("A1:G1")
    c = ws["A1"]
    c.value = f"РАСЧЁТ ПРЕМИИ MONKEY GRINDER · {ru.upper()} {yyyy}"
    c.font = Font(bold=True, size=14, color=WHITE)
    c.fill = PatternFill("solid", fgColor=NAVY)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # ── Блок параметров ─────────────────────────────────────────────────
    params = [
        ("Период:", period_str),
        ("Сеть:", "MONKEY GRINDER"),
        ("Данные продаж:", "В валюте упр. учёта с НДС"),
        ("Количество:", "В единицах хранения"),
    ]
    p_row = 3
    for label, val in params:
        ws.cell(row=p_row, column=1, value=label).font = Font(bold=True, color=GRAY_DARK)
        ws.cell(row=p_row, column=1).alignment = Alignment(horizontal="right")
        ws.merge_cells(start_row=p_row, start_column=2, end_row=p_row, end_column=7)
        cv = ws.cell(row=p_row, column=2, value=val)
        cv.font = Font(color=GRAY_DARK)
        p_row += 1

    # ── Шапка таблицы ───────────────────────────────────────────────────
    head_row = p_row + 1
    headers = ["Номенклатура / Торговая точка", "", "", "Кол-во",
               "Размер премии, ₽", "Сумма по тт, ₽", "Сумма по позиции, ₽"]
    # Объединяем A:C под "Номенклатура / Торговая точка"
    ws.merge_cells(start_row=head_row, start_column=1, end_row=head_row, end_column=3)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=head_row, column=col, value=h if h else None)
        cell.font = Font(bold=True, color=WHITE, size=10)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    ws.row_dimensions[head_row].height = 32

    # ── Тело таблицы ────────────────────────────────────────────────────
    row = head_row + 1
    total_qty_all = 0
    g_rows: list[int] = []
    NOM_FILL = PatternFill("solid", fgColor=GRAY_LIGHT)
    SUB_FILL = PatternFill("solid", fgColor=SUBTOTAL_BG)

    def _apply_borders(r: int):
        for col in range(1, 8):
            ws.cell(row=r, column=col).border = border

    for it in parsed["items"]:
        # Строка позиции (номенклатура)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        c = ws.cell(row=row, column=1, value=it["nom"])
        c.font = Font(bold=True, color=GRAY_DARK)
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.cell(row=row, column=4, value=it["total_qty_header"])
        ws.cell(row=row, column=4).font = bold
        ws.cell(row=row, column=4).number_format = int_fmt
        ws.cell(row=row, column=4).alignment = Alignment(horizontal="center")
        if it["rate"] is not None:
            rc = ws.cell(row=row, column=5, value=it["rate"])
            rc.font = bold
            rc.number_format = money_fmt
            rc.alignment = Alignment(horizontal="right")
        else:
            rc = ws.cell(row=row, column=5, value="нет ставки")
            rc.font = Font(bold=True, color="C00000")
            rc.alignment = Alignment(horizontal="center")
        # Заливка всей строки позиции
        for col in range(1, 8):
            ws.cell(row=row, column=col).fill = NOM_FILL
        _apply_borders(row)
        ws.row_dimensions[row].height = 30
        rate_row = row
        total_qty_all += it["total_qty_header"]
        row += 1

        # Строки клиентов
        first = row
        for cl in it["clients"]:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
            cn = ws.cell(row=row, column=1, value="    " + cl["name"])
            cn.alignment = Alignment(vertical="center")
            cn.font = Font(color=GRAY_DARK)
            qc = ws.cell(row=row, column=4, value=cl["qty"])
            qc.number_format = int_fmt
            qc.alignment = Alignment(horizontal="center")
            if it["rate"] is not None:
                fc = ws.cell(row=row, column=6, value=f"=D{row}*$E${rate_row}")
                fc.number_format = money_fmt
                fc.alignment = Alignment(horizontal="right")
            _apply_borders(row)
            row += 1
        last = row - 1

        # ИТОГО по позиции
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        c = ws.cell(row=row, column=1, value="Итого по позиции")
        c.font = Font(bold=True, color=GRAY_DARK)
        c.alignment = Alignment(horizontal="right", vertical="center")
        if it["rate"] is not None and last >= first:
            tc = ws.cell(row=row, column=7, value=f"=SUM(F{first}:F{last})")
            tc.number_format = money_fmt
            tc.font = bold
            tc.alignment = Alignment(horizontal="right")
            g_rows.append(row)
        for col in range(1, 8):
            ws.cell(row=row, column=col).fill = SUB_FILL
        _apply_borders(row)
        row += 1

    # ── Финальное ИТОГО ─────────────────────────────────────────────────
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    c = ws.cell(row=row, column=1, value="ИТОГО К ВЫПЛАТЕ")
    c.font = Font(bold=True, color=WHITE, size=12)
    c.alignment = Alignment(horizontal="right", vertical="center")
    qc = ws.cell(row=row, column=6, value=None)
    if g_rows:
        tc = ws.cell(row=row, column=7, value="=" + "+".join(f"G{r}" for r in g_rows))
        tc.number_format = money_fmt
        tc.font = Font(bold=True, color=WHITE, size=12)
        tc.alignment = Alignment(horizontal="right")
    for col in range(1, 8):
        cell = ws.cell(row=row, column=col)
        cell.fill = PatternFill("solid", fgColor=TOTAL_BG)
        cell.border = border
    ws.row_dimensions[row].height = 28

    # ── Ширины колонок ──────────────────────────────────────────────────
    widths = [42, 4, 4, 11, 17, 17, 19]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Чтобы при печати ничего не съезжало
    ws.print_options.horizontalCentered = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    # Закрепить шапку для удобной прокрутки
    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)

    wb.save(str(out))
    return out


def _compute_totals(parsed: dict) -> dict:
    """Считает итоги по каждой позиции и общую сумму (без xlsx)."""
    items_out = []
    grand = 0.0
    for it in parsed["items"]:
        qty_clients = sum(c["qty"] for c in it["clients"])
        rate = it["rate"]
        sum_premium = qty_clients * rate if rate is not None else None
        items_out.append({
            "nom": it["nom"],
            "rate": rate,
            "rate_source": it["rate_source"],
            "qty_header": it["total_qty_header"],
            "qty_clients_sum": qty_clients,
            "qty_match": qty_clients == it["total_qty_header"],
            "sum_premium": sum_premium,
            "clients_count": len(it["clients"]),
        })
        if sum_premium:
            grand += sum_premium
    return {"items": items_out, "grand_total": grand}


# ─── Tool implementations ─────────────────────────────────────────────────


def _tool_calculate(inp: dict) -> str:
    try:
        month = _resolve_month(inp.get("month", "last"))
        remote = _find_file_for_month(month)
        if not remote:
            return json.dumps({
                "status": "not_found",
                "month": month,
                "error": (
                    f"В папке Я.Диска 'Roastberry/MG' не нашёл отчёт за {month}. "
                    f"Проверь что файл выгружен из 1С."
                ),
            }, ensure_ascii=False)
        local = _yadisk_fetch(remote)
        parsed = _parse_report(local)
        if not parsed["items"]:
            return json.dumps({
                "status": "error", "month": month,
                "error": f"В файле {remote} не нашёл строк номенклатуры. "
                         f"Возможно изменился формат выгрузки.",
            }, ensure_ascii=False)
        out = _build_calc_xlsx(month, parsed)
        totals = _compute_totals(parsed)

        # Текст подписи под файлом
        lines = [f"💰 Бонус Monkey Grinder · {month}"]
        if parsed.get("period"):
            lines.append(f"Период: {parsed['period']}")
        lines.append("")
        for it in totals["items"]:
            short = it["nom"]
            if len(short) > 48: short = short[:45] + "…"
            if it["sum_premium"] is not None:
                lines.append(
                    f"• {short}\n"
                    f"   {it['qty_clients_sum']} × {it['rate']:.2f} = "
                    f"{it['sum_premium']:,.2f} ₽".replace(",", " ")
                )
            else:
                lines.append(f"• {short} — нет ставки, пропущено")
        lines.append("")
        lines.append(f"ИТОГО к выплате: {totals['grand_total']:,.2f} ₽".replace(",", " "))

        return json.dumps({
            "status": "ready",
            "month": month,
            "file_path": str(out),
            "filename": out.name,
            "caption": "\n".join(lines),
            "totals": totals,
            "source_file": remote,
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("mg_bonus_calculate failed")
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def _tool_summary(inp: dict) -> str:
    try:
        month = _resolve_month(inp.get("month", "last"))
        remote = _find_file_for_month(month)
        if not remote:
            return json.dumps({
                "status": "not_found", "month": month,
                "error": f"Нет отчёта за {month} в Roastberry/MG.",
            }, ensure_ascii=False)
        local = _yadisk_fetch(remote)
        parsed = _parse_report(local)
        totals = _compute_totals(parsed)
        return json.dumps({
            "status": "ok", "month": month,
            "period": parsed.get("period"),
            "totals": totals,
            "source_file": remote,
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("mg_bonus_summary failed")
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def _tool_check_pending(inp: dict) -> str:
    """Лежит ли отчёт за прошлый месяц на Я.Диске?"""
    try:
        month = _resolve_month("last")
        remote = _find_file_for_month(month)
        return json.dumps({
            "status": "ready" if remote else "missing",
            "month": month,
            "file": remote,
            "folder": YADISK_FOLDER,
        }, ensure_ascii=False)
    except Exception as e:
        log.exception("mg_bonus_check_pending failed")
        return json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


_DISPATCH = {
    "mg_bonus_calculate": _tool_calculate,
    "mg_bonus_summary": _tool_summary,
    "mg_bonus_check_pending": _tool_check_pending,
}


def execute_tool(name: str, inp: dict) -> str:
    fn = _DISPATCH.get(name)
    if not fn:
        return json.dumps({"status": "error", "error": f"unknown tool: {name}"}, ensure_ascii=False)
    return fn(inp)


# ─── Планировщик: 1-го числа каждого месяца ───────────────────────────────


async def monthly_bonus_job(bot) -> None:
    """Запускается 1-го числа в 11:00 МСК. Если отчёт есть — считаем и шлём
    владельцу файлом. Если нет — алерт «закинь файл руками»."""
    from config import settings as _settings
    if not _settings.owner_telegram_id:
        return
    owner_id = _settings.owner_telegram_id

    try:
        result_json = _tool_check_pending({})
        check = json.loads(result_json)
        month = check.get("month", "")
    except Exception as e:
        log.exception("mg monthly job: check_pending failed")
        try:
            await bot.send_message(
                owner_id,
                f"⚠️ MG бонус: не смог проверить Я.Диск — {type(e).__name__}: {e}",
            )
        except Exception:
            pass
        return

    if check.get("status") != "ready":
        # Файла нет — сигналим владельцу
        try:
            await bot.send_message(
                owner_id,
                (
                    f"📭 Бонус Monkey Grinder · {month}\n\n"
                    f"Сегодня 1-е, а отчёта за {month} в папке Я.Диска "
                    f"«Roastberry/MG» ещё нет.\n\n"
                    f"Когда придёт — закинь файл туда руками, а я посчитаю. "
                    f"Или просто напиши мне «посчитай MG за {month}» — "
                    f"я попробую ещё раз."
                ),
            )
        except Exception as e:
            log.error(f"mg monthly job: alert send failed: {e}")
        return

    # Файл есть — считаем и шлём
    try:
        result_json = _tool_calculate({"month": month})
        result = json.loads(result_json)
    except Exception as e:
        log.exception("mg monthly job: calc failed")
        try:
            await bot.send_message(
                owner_id,
                f"⚠️ MG бонус {month}: ошибка расчёта — {type(e).__name__}: {e}",
            )
        except Exception:
            pass
        return

    if result.get("status") != "ready":
        try:
            await bot.send_message(
                owner_id,
                f"⚠️ MG бонус {month}: {result.get('error', 'неизвестная ошибка')}",
            )
        except Exception:
            pass
        return

    # Отправляем файл владельцу
    file_path = result.get("file_path")
    caption = result.get("caption", "")
    if not file_path or not Path(file_path).exists():
        try:
            await bot.send_message(owner_id, f"⚠️ MG бонус {month}: файл расчёта не сгенерировался.")
        except Exception:
            pass
        return

    try:
        from aiogram.types import FSInputFile
        await bot.send_document(
            owner_id,
            FSInputFile(file_path, filename=result.get("filename") or Path(file_path).name),
            caption=caption[:1000],
        )
        log.info(f"mg monthly job: sent calc for {month} to owner {owner_id}")
    except Exception as e:
        log.error(f"mg monthly job: send_document failed: {e}")
        try:
            await bot.send_message(owner_id, f"⚠️ MG бонус {month}: не смог отправить файл — {e}")
        except Exception:
            pass
