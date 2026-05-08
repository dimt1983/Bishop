"""Личные финансы Дмитрия — Bishop tool-use модуль.

Работает поверх /root/projects/ai-agents-rb/Финансы/db/finance.db.
Все запросы по умолчанию фильтруют is_business=0 (личное),
Roastberry-расходы в БД помечены is_business=1 и сюда не попадают.

Денежные суммы в БД хранятся в копейках со знаком: + доход, − расход.
Наружу (в JSON для Claude) отдаются в рублях с двумя знаками.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, date
from pathlib import Path

DB_PATH = Path("/root/projects/ai-agents-rb/Финансы/db/finance.db")


# ─── helpers ─────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _rub(kop: int | None) -> float:
    if kop is None:
        return 0.0
    return round(kop / 100.0, 2)


def _to_kop(rub: float | int) -> int:
    return int(round(float(rub) * 100))


def _today() -> date:
    return date.today()


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.fromisoformat(s).date()


def _resolve_category(c: sqlite3.Connection, category: str | int | None, kind: str) -> int | None:
    """category может быть id (int), точное имя или None. kind = 'income'|'expense'.
    Если не нашли по имени — None (попадёт в 'Прочие …')."""
    if category is None:
        return None
    if isinstance(category, int) or (isinstance(category, str) and category.isdigit()):
        cid = int(category)
        row = c.execute("SELECT id FROM categories WHERE id=?", (cid,)).fetchone()
        return row["id"] if row else None
    row = c.execute(
        "SELECT id FROM categories WHERE name=? AND kind=? AND is_business=0",
        (category, kind),
    ).fetchone()
    if row:
        return row["id"]
    # fallback: нечеткий поиск
    row = c.execute(
        "SELECT id FROM categories WHERE name LIKE ? AND kind=? AND is_business=0 LIMIT 1",
        (f"%{category}%", kind),
    ).fetchone()
    return row["id"] if row else None


def _resolve_account(c: sqlite3.Connection, account: str | int) -> int | None:
    if isinstance(account, int) or (isinstance(account, str) and account.isdigit()):
        cid = int(account)
        row = c.execute("SELECT id FROM accounts WHERE id=?", (cid,)).fetchone()
        return row["id"] if row else None
    row = c.execute(
        "SELECT id FROM accounts WHERE name=? OR last4=? LIMIT 1",
        (account, account),
    ).fetchone()
    if row:
        return row["id"]
    row = c.execute(
        "SELECT id FROM accounts WHERE name LIKE ? LIMIT 1", (f"%{account}%",)
    ).fetchone()
    return row["id"] if row else None


# ─── tool: accounts_list ─────────────────────────────────────────────────────

def _tool_accounts_list(inp: dict) -> str:
    only_active = bool(inp.get("only_active", True))
    with _conn() as c:
        q = "SELECT id, bank, account_type, name, last4, currency, is_active FROM accounts"
        if only_active:
            q += " WHERE is_active=1"
        q += " ORDER BY bank, account_type"
        rows = [dict(r) for r in c.execute(q)]
    return json.dumps({"accounts": rows}, ensure_ascii=False)


# ─── tool: categories_list ───────────────────────────────────────────────────

def _tool_categories_list(inp: dict) -> str:
    kind = inp.get("kind")  # 'income'|'expense'|'transfer'|None
    include_business = bool(inp.get("include_business", False))
    with _conn() as c:
        q = "SELECT id, name, kind, icon, is_business FROM categories WHERE 1=1"
        params: list = []
        if kind:
            q += " AND kind=?"
            params.append(kind)
        if not include_business:
            q += " AND is_business=0"
        q += " ORDER BY kind, name"
        rows = [dict(r) for r in c.execute(q, params)]
    return json.dumps({"categories": rows}, ensure_ascii=False)


# ─── tool: balance ───────────────────────────────────────────────────────────

def _tool_balance(inp: dict) -> str:
    """Баланс по каждому активному счёту (сумма транзакций) + общая сумма.
    Для кредитных счетов это ОСТАТОК (отрицательный = долг)."""
    with _conn() as c:
        rows = c.execute("""
            SELECT a.id, a.name, a.bank, a.account_type, a.last4, a.currency,
                   COALESCE(SUM(t.amount), 0) AS balance_kop,
                   COUNT(t.id) AS tx_count
            FROM accounts a
            LEFT JOIN transactions t ON t.account_id = a.id
            WHERE a.is_active = 1
            GROUP BY a.id
            ORDER BY a.account_type, a.name
        """).fetchall()
    by_acc = []
    by_type: dict[str, float] = {}
    for r in rows:
        bal = _rub(r["balance_kop"])
        by_acc.append({
            "id": r["id"],
            "name": r["name"],
            "bank": r["bank"],
            "account_type": r["account_type"],
            "last4": r["last4"],
            "balance_rub": bal,
            "tx_count": r["tx_count"],
        })
        by_type[r["account_type"]] = round(by_type.get(r["account_type"], 0) + bal, 2)
    return json.dumps({
        "accounts": by_acc,
        "totals_by_type_rub": by_type,
        "note": "Для кредитных счетов отрицательный баланс = непогашенный долг.",
    }, ensure_ascii=False)


# ─── tool: recent ────────────────────────────────────────────────────────────

def _tool_recent(inp: dict) -> str:
    limit = max(1, min(int(inp.get("limit", 20)), 200))
    account_id = inp.get("account_id")
    days = inp.get("days")  # за последние N дней
    include_business = bool(inp.get("include_business", False))

    where = ["1=1"]
    params: list = []
    if account_id:
        where.append("t.account_id = ?")
        params.append(int(account_id))
    if days:
        since = (_today() - timedelta(days=int(days))).isoformat()
        where.append("date(t.occurred_at) >= ?")
        params.append(since)
    if not include_business:
        where.append("(c.is_business IS NULL OR c.is_business = 0)")

    sql = f"""
        SELECT t.id, t.occurred_at, t.amount, t.description, t.merchant,
               c.name AS category, c.kind AS cat_kind,
               a.name AS account, t.is_transfer
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        WHERE {' AND '.join(where)}
        ORDER BY t.occurred_at DESC
        LIMIT ?
    """
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return json.dumps({
        "transactions": [
            {
                "id": r["id"],
                "date": r["occurred_at"],
                "amount_rub": _rub(r["amount"]),
                "description": r["description"],
                "merchant": r["merchant"],
                "category": r["category"],
                "kind": r["cat_kind"],
                "account": r["account"],
                "is_transfer": bool(r["is_transfer"]),
            }
            for r in rows
        ]
    }, ensure_ascii=False)


# ─── tool: summary ───────────────────────────────────────────────────────────

def _tool_summary(inp: dict) -> str:
    """Сводка доходы/расходы по категориям за период.
    period: 'this_month'|'last_month'|'last_30d'|'last_60d'|'last_90d'|'ytd'|'custom'
    """
    period = inp.get("period", "this_month")
    today = _today()
    if period == "this_month":
        start = today.replace(day=1)
        end = today
    elif period == "last_month":
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
    elif period == "ytd":
        start = today.replace(month=1, day=1)
        end = today
    elif period == "last_30d":
        start, end = today - timedelta(days=30), today
    elif period == "last_60d":
        start, end = today - timedelta(days=60), today
    elif period == "last_90d":
        start, end = today - timedelta(days=90), today
    elif period == "custom":
        start = _parse_date(inp.get("start_date")) or (today - timedelta(days=30))
        end = _parse_date(inp.get("end_date")) or today
    else:
        return json.dumps({"error": f"unknown period: {period}"}, ensure_ascii=False)

    include_business = bool(inp.get("include_business", False))
    biz_filter = "" if include_business else "AND (c.is_business IS NULL OR c.is_business = 0)"

    with _conn() as c:
        # переводы между своими счетами игнорируем
        rows = c.execute(f"""
            SELECT
                COALESCE(c.kind, 'unknown') AS kind,
                COALESCE(c.name, '— без категории') AS category,
                COUNT(*) AS cnt,
                SUM(t.amount) AS sum_kop
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE date(t.occurred_at) BETWEEN ? AND ?
              AND t.is_transfer = 0
              AND (c.kind IS NULL OR c.kind != 'transfer')
              {biz_filter}
            GROUP BY c.id
            ORDER BY ABS(SUM(t.amount)) DESC
        """, (start.isoformat(), end.isoformat())).fetchall()

    income_total = 0
    expense_total = 0
    income, expense, other = [], [], []
    for r in rows:
        item = {"category": r["category"], "amount_rub": _rub(r["sum_kop"]), "count": r["cnt"]}
        if r["kind"] == "income":
            income.append(item)
            income_total += r["sum_kop"] or 0
        elif r["kind"] == "expense":
            expense.append(item)
            expense_total += r["sum_kop"] or 0
        else:
            other.append(item)
    days_n = (end - start).days + 1
    return json.dumps({
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days_n,
        "income_total_rub": _rub(income_total),
        "expense_total_rub": _rub(expense_total),
        "net_rub": _rub(income_total + expense_total),
        "avg_daily_expense_rub": _rub(expense_total // days_n) if days_n else 0,
        "income": income,
        "expense": expense,
        "uncategorized": other,
    }, ensure_ascii=False)


# ─── tool: recurring_due ─────────────────────────────────────────────────────

def _tool_recurring_due(inp: dict) -> str:
    """Регулярные платежи (кредиты, ЖКУ, подписки) — что грядёт в ближайшие N дней."""
    days = max(1, min(int(inp.get("days", 30)), 365))
    today = _today()
    until = today + timedelta(days=days)
    with _conn() as c:
        rows = c.execute("""
            SELECT id, name, kind, amount, next_due_date, period_days, account_id, notes
            FROM recurring_payments
            WHERE is_active = 1 AND date(next_due_date) <= ?
            ORDER BY next_due_date
        """, (until.isoformat(),)).fetchall()
    items = []
    total = 0
    for r in rows:
        days_left = (datetime.fromisoformat(r["next_due_date"]).date() - today).days
        items.append({
            "id": r["id"],
            "name": r["name"],
            "kind": r["kind"],
            "amount_rub": _rub(r["amount"]),
            "next_due_date": r["next_due_date"],
            "days_left": days_left,
            "period_days": r["period_days"],
        })
        total += r["amount"] or 0
    return json.dumps({
        "horizon_days": days,
        "today": today.isoformat(),
        "items": items,
        "total_rub": _rub(total),
        "note": "Сумма отрицательная = столько уйдёт со счетов в горизонте.",
    }, ensure_ascii=False)


# ─── tool: cashflow_forecast ─────────────────────────────────────────────────

def _tool_cashflow_forecast(inp: dict) -> str:
    """Прогноз кэшфлоу на N дней.

    Outflow = recurring (предсказуемое: кредиты/ЖКУ/подписки) + средние дискретные расходы
    из истории за `lookback_days`.
    Inflow = средние доходы из истории за `lookback_days` (можно переопределить
    expected_income_rub).

    Возвращаем по неделям + общий нетто-результат + точку «дыры» (когда совокупный
    остаток на текущих счетах уйдёт в минус).
    """
    horizon = max(7, min(int(inp.get("days", 60)), 180))
    lookback = max(30, min(int(inp.get("lookback_days", 60)), 365))
    today = _today()

    with _conn() as c:
        # 1. Текущий кэш на дебетовых/текущих счетах (без кредитов)
        cash_row = c.execute("""
            SELECT COALESCE(SUM(t.amount), 0) AS bal
            FROM accounts a
            LEFT JOIN transactions t ON t.account_id = a.id
            WHERE a.is_active = 1 AND a.account_type IN ('card', 'deposit')
        """).fetchone()
        current_cash_kop = cash_row["bal"] if cash_row else 0

        # 2. Запланированные recurring в горизонте (кредиты, аренда, ЖКУ)
        recur = c.execute("""
            SELECT name, amount, next_due_date, period_days
            FROM recurring_payments
            WHERE is_active = 1 AND date(next_due_date) <= ?
        """, ((today + timedelta(days=horizon)).isoformat(),)).fetchall()

        # 3. История за lookback — средняя дискретная трата и средний доход
        # Исключаем переводы и сами recurring-категории (Кредиты/проценты, ЖКУ),
        # чтобы дважды не считать
        hist = c.execute("""
            SELECT c.kind, c.name, SUM(t.amount) AS s, COUNT(*) AS n
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE date(t.occurred_at) >= ?
              AND t.is_transfer = 0
              AND (c.is_business IS NULL OR c.is_business = 0)
              AND (c.kind IS NULL OR c.kind != 'transfer')
            GROUP BY c.id
        """, ((today - timedelta(days=lookback)).isoformat(),)).fetchall()

    discretionary_kop = 0  # расходы кроме кредитов/ЖКУ (их учитываем через recurring)
    historical_income_kop = 0
    skip_expense_cats = {"Кредиты/проценты", "ЖКУ", "Аренда (бизнес)"}
    for h in hist:
        s = h["s"] or 0
        if h["kind"] == "expense" and (h["name"] or "") not in skip_expense_cats:
            discretionary_kop += s  # отрицательное
        elif h["kind"] == "income":
            historical_income_kop += s  # положительное

    avg_daily_discretionary = discretionary_kop / lookback  # отрицательное
    expected_daily_income_override = inp.get("expected_income_rub")
    if expected_daily_income_override is not None:
        # пользователь задал ожидаемый доход за горизонт целиком
        avg_daily_income = _to_kop(float(expected_daily_income_override)) / horizon
    else:
        avg_daily_income = historical_income_kop / lookback

    # 4. Развернём recurring в конкретные даты внутри горизонта
    recurring_events: list[tuple[date, int, str]] = []
    for r in recur:
        nd = datetime.fromisoformat(r["next_due_date"]).date()
        period = max(1, int(r["period_days"] or 30))
        cur = nd
        while cur <= today + timedelta(days=horizon):
            if cur >= today:
                recurring_events.append((cur, r["amount"], r["name"]))
            cur = cur + timedelta(days=period)

    # 5. Помесячная (4 недели) развёртка
    weekly = []
    running_kop = current_cash_kop
    deficit_date: str | None = None
    cursor = today
    week_idx = 0
    while cursor <= today + timedelta(days=horizon):
        week_end = min(cursor + timedelta(days=6), today + timedelta(days=horizon))
        # recurring в этой неделе
        wk_recur = sum(amt for d, amt, _ in recurring_events if cursor <= d <= week_end)
        wk_recur_items = [{"date": d.isoformat(), "name": n, "amount_rub": _rub(amt)}
                          for d, amt, n in recurring_events if cursor <= d <= week_end]
        wk_days = (week_end - cursor).days + 1
        wk_discr = int(avg_daily_discretionary * wk_days)
        wk_income = int(avg_daily_income * wk_days)

        running_kop += wk_recur + wk_discr + wk_income
        if running_kop < 0 and deficit_date is None:
            deficit_date = week_end.isoformat()

        weekly.append({
            "week": week_idx + 1,
            "from": cursor.isoformat(),
            "to": week_end.isoformat(),
            "recurring_rub": _rub(wk_recur),
            "recurring_items": wk_recur_items,
            "estimated_discretionary_rub": _rub(wk_discr),
            "estimated_income_rub": _rub(wk_income),
            "running_cash_rub": _rub(running_kop),
        })
        cursor = week_end + timedelta(days=1)
        week_idx += 1

    total_recurring_kop = sum(amt for _, amt, _ in recurring_events)
    total_discretionary_kop = int(avg_daily_discretionary * horizon)
    total_income_kop = int(avg_daily_income * horizon)

    return json.dumps({
        "horizon_days": horizon,
        "lookback_days": lookback,
        "today": today.isoformat(),
        "starting_cash_rub": _rub(current_cash_kop),
        "expected_recurring_rub": _rub(total_recurring_kop),
        "expected_discretionary_rub": _rub(total_discretionary_kop),
        "expected_income_rub": _rub(total_income_kop),
        "expected_net_rub": _rub(total_recurring_kop + total_discretionary_kop + total_income_kop),
        "ending_cash_rub": _rub(current_cash_kop + total_recurring_kop +
                                total_discretionary_kop + total_income_kop),
        "first_deficit_week_end": deficit_date,
        "weekly": weekly,
        "assumptions": {
            "discretionary_basis": (
                f"Средние личные расходы за {lookback} дн., исключая категории "
                f"{sorted(skip_expense_cats)} (они учтены в recurring)"
            ),
            "income_basis": (
                "Задано пользователем" if expected_daily_income_override is not None
                else f"Средние доходы за {lookback} дн., экстраполировано на горизонт"
            ),
            "recurring_basis": (
                "Из таблицы recurring_payments, развернуто по period_days в горизонте"
            ),
        },
    }, ensure_ascii=False)


# ─── tool: add_expense ───────────────────────────────────────────────────────

def _tool_add_expense(inp: dict) -> str:
    amount_rub = float(inp["amount_rub"])
    if amount_rub <= 0:
        return json.dumps({"error": "amount_rub должен быть положительным числом (сумма траты)"},
                          ensure_ascii=False)
    description = (inp.get("description") or "Ручной ввод").strip()
    account = inp["account"]
    category = inp.get("category")
    merchant = (inp.get("merchant") or None)
    occurred_at = inp.get("occurred_at") or datetime.now().isoformat(timespec="minutes")

    amount_kop = -_to_kop(amount_rub)  # расход → минус
    with _conn() as c:
        acc_id = _resolve_account(c, account)
        if acc_id is None:
            return json.dumps({"error": f"Не нашёл счёт '{account}'. "
                                       "Используй finance_accounts_list."},
                              ensure_ascii=False)
        cat_id = _resolve_category(c, category, "expense") if category else None
        if cat_id is None:
            # дефолт — Прочие расходы
            row = c.execute(
                "SELECT id FROM categories WHERE name='Прочие расходы' AND is_business=0"
            ).fetchone()
            cat_id = row["id"] if row else None

        source_ref = f"manual_{datetime.now().timestamp()}"
        cur = c.execute("""
            INSERT INTO transactions
                (account_id, occurred_at, amount, currency, description, merchant,
                 category_id, category_source, source_type, source_ref)
            VALUES (?, ?, ?, 'RUB', ?, ?, ?, 'manual', 'manual', ?)
        """, (acc_id, occurred_at, amount_kop, description, merchant, cat_id, source_ref))
        tx_id = cur.lastrowid
        c.commit()
        cat_name = c.execute("SELECT name FROM categories WHERE id=?", (cat_id,)).fetchone()
        acc_name = c.execute("SELECT name FROM accounts WHERE id=?", (acc_id,)).fetchone()
    return json.dumps({
        "status": "added",
        "id": tx_id,
        "amount_rub": -_rub(amount_kop) * -1,  # отображаем как отрицательное
        "saved_amount_rub": _rub(amount_kop),
        "account": acc_name["name"] if acc_name else None,
        "category": cat_name["name"] if cat_name else None,
        "occurred_at": occurred_at,
    }, ensure_ascii=False)


# ─── tool: add_income ────────────────────────────────────────────────────────

def _tool_add_income(inp: dict) -> str:
    amount_rub = float(inp["amount_rub"])
    if amount_rub <= 0:
        return json.dumps({"error": "amount_rub должен быть положительным"},
                          ensure_ascii=False)
    description = (inp.get("description") or "Ручной доход").strip()
    account = inp["account"]
    category = inp.get("category")
    occurred_at = inp.get("occurred_at") or datetime.now().isoformat(timespec="minutes")

    amount_kop = _to_kop(amount_rub)  # доход → плюс
    with _conn() as c:
        acc_id = _resolve_account(c, account)
        if acc_id is None:
            return json.dumps({"error": f"Не нашёл счёт '{account}'."}, ensure_ascii=False)
        cat_id = _resolve_category(c, category, "income") if category else None
        if cat_id is None:
            row = c.execute(
                "SELECT id FROM categories WHERE name='Прочие доходы' AND is_business=0"
            ).fetchone()
            cat_id = row["id"] if row else None
        source_ref = f"manual_{datetime.now().timestamp()}"
        cur = c.execute("""
            INSERT INTO transactions
                (account_id, occurred_at, amount, currency, description,
                 category_id, category_source, source_type, source_ref)
            VALUES (?, ?, ?, 'RUB', ?, ?, 'manual', 'manual', ?)
        """, (acc_id, occurred_at, amount_kop, description, cat_id, source_ref))
        tx_id = cur.lastrowid
        c.commit()
    return json.dumps({
        "status": "added",
        "id": tx_id,
        "amount_rub": _rub(amount_kop),
        "occurred_at": occurred_at,
    }, ensure_ascii=False)


# ─── tool schemas ────────────────────────────────────────────────────────────

_T_ACCOUNTS = {
    "name": "finance_accounts_list",
    "description": "Список банковских счетов и карт. Используй чтобы узнать id/имя счёта "
                   "перед добавлением транзакции.",
    "input_schema": {
        "type": "object",
        "properties": {
            "only_active": {"type": "boolean", "default": True},
        },
    },
}

_T_CATEGORIES = {
    "name": "finance_categories_list",
    "description": "Список категорий расходов/доходов (личные). Используй чтобы понять "
                   "какие категории есть. По умолчанию бизнес-категории Roastberry скрыты.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["income", "expense", "transfer"]},
            "include_business": {"type": "boolean", "default": False},
        },
    },
}

_T_BALANCE = {
    "name": "finance_balance",
    "description": "Текущий баланс по всем активным счетам (рассчитывается как сумма транзакций). "
                   "Для кредитных счетов отрицательный баланс = непогашенный долг.",
    "input_schema": {"type": "object", "properties": {}},
}

_T_RECENT = {
    "name": "finance_recent",
    "description": "Последние транзакции (по умолчанию только личные, без переводов между "
                   "своими счетами).",
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 20, "maximum": 200},
            "account_id": {"type": "integer", "description": "Опционально — фильтр по счёту"},
            "days": {"type": "integer", "description": "Опционально — за последние N дней"},
            "include_business": {"type": "boolean", "default": False},
        },
    },
}

_T_SUMMARY = {
    "name": "finance_summary",
    "description": "Сводка доходы/расходы по категориям за период. Чисто личные финансы — "
                   "Roastberry-категории по умолчанию исключены, переводы между своими "
                   "счетами не считаются.",
    "input_schema": {
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "enum": ["this_month", "last_month", "last_30d", "last_60d",
                         "last_90d", "ytd", "custom"],
                "default": "this_month",
            },
            "start_date": {"type": "string", "description": "ISO дата для period=custom"},
            "end_date": {"type": "string", "description": "ISO дата для period=custom"},
            "include_business": {"type": "boolean", "default": False},
        },
    },
}

_T_RECURRING = {
    "name": "finance_recurring_due",
    "description": "Регулярные платежи (кредиты, ипотека, ЖКУ, подписки), которые наступят "
                   "в ближайшие N дней. По умолчанию N=30.",
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 30, "maximum": 365},
        },
    },
}

_T_FORECAST = {
    "name": "finance_cashflow_forecast",
    "description": (
        "Прогноз кэшфлоу личных финансов на N дней (60 по умолчанию). Считает: "
        "стартовый кэш на дебетовых счетах + recurring (кредиты/ЖКУ/подписки в горизонте) "
        "+ средние дискретные расходы из истории + средние доходы. Возвращает понедельную "
        "развёртку и дату возможной 'дыры' (когда кэш уйдёт в минус). "
        "Используй когда пользователь спрашивает 'хватит ли денег', 'когда будет дыра', "
        "'прогноз на N дней'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 60, "maximum": 180,
                     "description": "Горизонт прогноза в днях (мин 7)"},
            "lookback_days": {"type": "integer", "default": 60, "maximum": 365,
                              "description": "Сколько дней истории брать для усреднения"},
            "expected_income_rub": {
                "type": "number",
                "description": "Опционально: ожидаемый суммарный доход за горизонт в рублях. "
                               "Если задан — используется вместо средних из истории.",
            },
        },
    },
}

_T_ADD_EXPENSE = {
    "name": "finance_add_expense",
    "description": (
        "Добавить ручной расход в БД. Используй когда пользователь говорит 'потратил X на Y'. "
        "amount_rub — ВСЕГДА положительное число (сумма расхода в рублях). "
        "account — имя счёта (можно частичное, например 'Сбер 5038' или 'Тинькофф Дебет') "
        "или id из finance_accounts_list. category — название из finance_categories_list "
        "(не обязательно, по умолчанию 'Прочие расходы')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "amount_rub": {"type": "number", "description": "Сумма траты в рублях, положительная"},
            "account": {"type": "string", "description": "Имя/последние4/id счёта"},
            "category": {"type": "string", "description": "Имя категории расхода"},
            "description": {"type": "string", "description": "Что купил, заметка"},
            "merchant": {"type": "string", "description": "Магазин/контрагент (опц.)"},
            "occurred_at": {"type": "string",
                            "description": "ISO datetime, по умолчанию — сейчас"},
        },
        "required": ["amount_rub", "account"],
    },
}

_T_ADD_INCOME = {
    "name": "finance_add_income",
    "description": "Добавить ручной доход. amount_rub — положительное число.",
    "input_schema": {
        "type": "object",
        "properties": {
            "amount_rub": {"type": "number"},
            "account": {"type": "string"},
            "category": {"type": "string"},
            "description": {"type": "string"},
            "occurred_at": {"type": "string"},
        },
        "required": ["amount_rub", "account"],
    },
}

TOOLS_OWNER = [
    _T_ACCOUNTS,
    _T_CATEGORIES,
    _T_BALANCE,
    _T_RECENT,
    _T_SUMMARY,
    _T_RECURRING,
    _T_FORECAST,
    _T_ADD_EXPENSE,
    _T_ADD_INCOME,
]
TOOLS_READONLY: list[dict] = []  # личные финансы — только владелец

TOOL_NAMES = {t["name"] for t in TOOLS_OWNER}


_EXECUTORS = {
    "finance_accounts_list": _tool_accounts_list,
    "finance_categories_list": _tool_categories_list,
    "finance_balance": _tool_balance,
    "finance_recent": _tool_recent,
    "finance_summary": _tool_summary,
    "finance_recurring_due": _tool_recurring_due,
    "finance_cashflow_forecast": _tool_cashflow_forecast,
    "finance_add_expense": _tool_add_expense,
    "finance_add_income": _tool_add_income,
}


def execute_tool(name: str, inp: dict) -> str:
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"}, ensure_ascii=False)
    try:
        return fn(inp)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
