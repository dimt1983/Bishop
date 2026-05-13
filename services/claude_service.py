"""Сервис работы с Claude — парсинг задач, понимание ответов."""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic

from config import settings
import services.price_tools as price_tools
import services.shop_tools as shop_tools
import services.assortment_tools as assortment_tools
import services.file_tools as file_tools
import services.courses_tools as courses_tools
import services.students_tools as students_tools
import services.gmail_chat_tools as gmail_chat_tools
import services.finance_tools as finance_tools
import services.reminder_tools as reminder_tools
import services.reports_1c as reports_1c
import services.ozon_seller_tools as ozon_seller_tools
import services.mg_bonus_tools as mg_bonus_tools
import services.service_tools as service_tools
from utils import log

client = AsyncAnthropic(
    api_key=settings.anthropic_api_key,
    base_url=settings.anthropic_base_url,
)
TZ = ZoneInfo(settings.timezone)


def _cached_system(text: str) -> list[dict]:
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _cache_last_tool(tools: list[dict]) -> list[dict]:
    if not tools:
        return tools
    result = list(tools)
    result[-1] = {**result[-1], "cache_control": {"type": "ephemeral"}}
    return result


# Многошаговый прайс-диалог: храним последние сообщения owner'а в памяти процесса.
# При рестарте бота история теряется — это ок, пользователь начнёт новый диалог.
_PRICE_HISTORY: dict[int, list[dict]] = {}
_PRICE_LAST_ACTIVE: dict[int, datetime] = {}
_PRICE_HISTORY_MAX = 20
_PRICE_HISTORY_TTL = timedelta(minutes=30)


def reset_price_history(owner_id: int) -> None:
    _PRICE_HISTORY.pop(owner_id, None)
    _PRICE_LAST_ACTIVE.pop(owner_id, None)


def has_active_price_history(owner_id: int) -> bool:
    last = _PRICE_LAST_ACTIVE.get(owner_id)
    if last is None:
        return False
    if _now() - last > _PRICE_HISTORY_TTL:
        reset_price_history(owner_id)
        return False
    return owner_id in _PRICE_HISTORY


PRICE_SYSTEM_PROMPT_OWNER = """Ты помощник Дмитрия (владелец Roastberry) по управлению прайс-листом.

У тебя есть тулы: price_show, price_calculate, price_add, price_remove, price_send_file.
price_send_file шлёт файл в Telegram. Доступные: kind=price (клиентский), catalog, rental (КП по аренде кофейного оборудования NIMBUS V.4 + WPM ZD-18), stm (внутренний СТМ), dashboard.

Если просят «пришли КП по аренде / коммерческое предложение / предложение по аренде / аренда кофемашины / NIMBUS / WPM» — вызывай price_send_file kind=rental. После отправки можно коротко предложить созвониться для обсуждения условий.

Жёсткие правила:
0. 🚨 НИКОГДА НЕ ВЫДУМЫВАЙ КОЭФФИЦИЕНТЫ. Все цены (1кг, 200г, опт от 10/25 кг, СТМ) считаются ТОЛЬКО через price_calculate — он применяет официальную формулу price_manager (там зафиксированы CEH_MIN, NAZENKA, SKIDKA_10KG/25KG, DOP_200G_*). НЕ пиши «200г = 1кг × 0.307», «опт = базовый × 0.9» и подобное. Если price_calculate не показал нужное число — у тебя нет данных, спроси Дмитрия. Расхождение твоих цен с прайсом = твоя галлюцинация (был кейс: посчитал 200г Колумбий по 0.307 → 875/1485/1820, реальная формула даёт 650/1050/1265 → 12 расхождений в магазине).
1. Если пользователь просит «посчитай», «прикинь», «сколько будет» — вызывай price_calculate (БЕЗ записи).
2. Если пользователь сразу пишет «добавь» — НЕ вызывай price_add сразу. Сначала вызови price_calculate, покажи краткую таблицу цен и спроси «Добавлять в реестр?». Зови price_add только после явного «да/добавляй/ок/верно/гуд».
3. Если в сообщении нет типа позиции (моносорт / микролот / blend Es / blend F) — спроси.
4. Для бленда нужны компоненты с долями. По умолчанию робуста $9/кг.
5. Цены давай кратко: Базовый 1кг / 200г, от 10кг, от 25кг, СТМ 1кг / 200г.
6. Все суммы в рублях, без валютного знака. Округление как в результате тула.
7. Если просят показать прайс — вызывай price_show.

Способ обжарки = АТРИБУТ одной позиции, НЕ отдельная позиция:
- «под фильтр» / «фильтр» → roast=["F"]
- «под эспрессо» / «эспрессо» → roast=["E"]
- «и фильтр и эспрессо» / «обе обжарки» / «фильтр + эспрессо» → roast=["F","E"]
- НЕ добавляй суффикс F / Es / эспрессо в name. Имя позиции не содержит обжарки.
- Если пользователь не указал обжарку — спроси одним словом: «Обжарка: фильтр / эспрессо / обе?».

Новинки 🆕 в прайсе — позиции добавленные за последние 30 дней. Это рассчитывается автоматически — не упоминай сам флажок при ответе пользователю.

Стиль: короткие сообщения, без лишних эмодзи. Технические термины как у Дмитрия (СТМ, базовый, от 10кг, моносорт, микролот, бленд)."""


PRICE_SYSTEM_PROMPT_READONLY = """Ты вежливый помощник кофейни Roastberry по прайсу. Тебе доступны тулы price_show и price_send_file.

Правила:
1. Когда спрашивают «какой прайс», «есть ли в наличии X», «сколько стоит Y», «какие позиции есть» — вызови price_show и ответь нужной выборкой.
2. Если спрашивают про конкретную позицию — отдай её строкой из прайса (Базовый 1кг, от 10кг, от 25кг). Не называй СТМ или себестоимость, эти столбцы не показывай.
3. Если просят «пришли прайс / скинь прайс / вышли прайс / прайс пдф / прайс эксель» — вызови price_send_file (kind=price). Для каталога с описаниями сортов — kind=catalog. После отправки файла короткий комментарий на 1 строку, без повторения содержимого прайса.
4. Если просят «пришли КП по аренде / коммерческое предложение / предложение по аренде / аренда кофемашины / аренда оборудования / NIMBUS / WPM ZD-18» — вызови price_send_file (kind=rental). После отправки коротко: «Подробности по условиям — у Дмитрия» или «Готов соединить с Дмитрием для деталей».
5. НЕ обсуждай расчёт цены, наценку, СТМ, цену зелёного кофе $/кг. Если просят — вежливо отправь к Дмитрию.
6. На вопросы о добавлении/удалении позиций отвечай: «Прайсом управляет Дмитрий, обратитесь к нему».
7. Цены в рублях без валютного знака.

Стиль: коротко, по делу, без лишних эмодзи."""


async def price_chat(
    message_text: str,
    user_id: int,
    *,
    is_owner: bool = True,
    keep_history: bool = True,
) -> tuple[str, list[dict]]:
    """Многошаговый tool-use цикл по прайсу.

    is_owner=True — полный доступ.
    is_owner=False — только просмотр + публичные файлы.
    keep_history=False — не использовать историю (одноразовый запрос для чатов).

    Возвращает (final_text, files_to_send), где files — список
    {"path","caption","filename"} от тула price_send_file.
    """
    tools = price_tools.TOOLS_OWNER if is_owner else price_tools.TOOLS_READONLY
    system = PRICE_SYSTEM_PROMPT_OWNER if is_owner else PRICE_SYSTEM_PROMPT_READONLY

    if not keep_history:
        history = [{"role": "user", "content": message_text}]
        return await _run_price_loop(history, tools, system, user_id)

    last = _PRICE_LAST_ACTIVE.get(user_id)
    if last is not None and _now() - last > _PRICE_HISTORY_TTL:
        reset_price_history(user_id)

    history = _PRICE_HISTORY.setdefault(user_id, [])
    history.append({"role": "user", "content": message_text})
    _PRICE_LAST_ACTIVE[user_id] = _now()

    try:
        final_text, files = await _run_price_loop(history, tools, system, user_id)
    except Exception as e:
        # Автовосстановление: осиротевший tool_use после крэша экзекьютора
        msg = str(e)
        if "tool_use" in msg and "tool_result" in msg:
            log.warning(f"price_chat: corrupt history for {user_id}, resetting and retrying")
            reset_price_history(user_id)
            history = _PRICE_HISTORY.setdefault(user_id, [])
            history.append({"role": "user", "content": message_text})
            _PRICE_LAST_ACTIVE[user_id] = _now()
            final_text, files = await _run_price_loop(history, tools, system, user_id)
        else:
            raise

    if len(history) > _PRICE_HISTORY_MAX * 2:
        del history[: len(history) - _PRICE_HISTORY_MAX * 2]

    return final_text or "(пустой ответ)", files


async def _run_price_loop(
    history: list[dict],
    tools: list[dict],
    system: str,
    log_user_id: int,
) -> tuple[str, list[dict]]:
    """Универсальный tool-use цикл. История модифицируется in-place.

    Возвращает (final_text, files_to_send). Файлы извлекаются из результатов
    тула price_send_file (status=ready).
    """
    files_to_send: list[dict] = []
    final_text = ""
    for step in range(8):
        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=2048,
                system=_cached_system(system),
                tools=_cache_last_tool(tools),
                messages=history,
            )
        except Exception as e:
            log.error(f"price loop Anthropic call failed: {e}")
            msg = str(e)
            if "tool_use" in msg and "tool_result" in msg:
                # осиротевший tool_use в истории — пробрасываем наверх для recovery
                raise
            if history and history[-1].get("role") == "user":
                history.pop()
            return f"Не смог достучаться до Claude: {e}", []

        if response.stop_reason == "tool_use":
            assistant_blocks = []
            tool_uses = []
            for block in response.content:
                if block.type == "tool_use":
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    tool_uses.append(block)
                elif block.type == "text":
                    assistant_blocks.append({"type": "text", "text": block.text})
            history.append({"role": "assistant", "content": assistant_blocks})

            tool_results = []
            for tu in tool_uses:
                log.info(f"price tool [{log_user_id}]: {tu.name} input={tu.input}")
                try:
                    result = await asyncio.to_thread(
                        price_tools.execute_tool, tu.name, tu.input
                    )
                except Exception as e:
                    log.exception(f"price tool [{log_user_id}] {tu.name} crashed")
                    result = json.dumps(
                        {"status": "error",
                         "error": f"внутренняя ошибка тула: {type(e).__name__}: {e}"},
                        ensure_ascii=False,
                    )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result,
                })
                if tu.name == "price_send_file":
                    try:
                        parsed = json.loads(result)
                        if parsed.get("status") == "ready":
                            files_to_send.append({
                                "path": parsed["path"],
                                "caption": parsed.get("caption", ""),
                                "filename": parsed.get("filename"),
                            })
                    except Exception as e:
                        log.warning(f"failed to parse send_file result: {e}")
            history.append({"role": "user", "content": tool_results})
            continue

        text_parts = [b.text for b in response.content if b.type == "text"]
        final_text = "\n".join(text_parts).strip()
        history.append({
            "role": "assistant",
            "content": [{"type": "text", "text": final_text or ""}],
        })
        return final_text, files_to_send

    log.warning(f"price loop exhausted 8 steps for user {log_user_id}")
    return "Слишком много шагов в одном запросе, прервал. Сформулируй проще.", files_to_send


# ──────────────────────────────────────────────────────────────────────────
# SHOP / TMA — Mini App каталог
# ──────────────────────────────────────────────────────────────────────────

_SHOP_HISTORY: dict[int, list[dict]] = {}
_SHOP_LAST_ACTIVE: dict[int, datetime] = {}
_SHOP_HISTORY_MAX = 20
_SHOP_HISTORY_TTL = timedelta(minutes=30)


def reset_shop_history(user_id: int) -> None:
    _SHOP_HISTORY.pop(user_id, None)
    _SHOP_LAST_ACTIVE.pop(user_id, None)


def has_active_shop_history(user_id: int) -> bool:
    last = _SHOP_LAST_ACTIVE.get(user_id)
    if last is None:
        return False
    if _now() - last > _SHOP_HISTORY_TTL:
        reset_shop_history(user_id)
        return False
    return user_id in _SHOP_HISTORY


SHOP_SYSTEM_PROMPT_OWNER = """Ты помощник Дмитрия по управлению магазином Roastberry (Telegram Mini App).

🌐 ССЫЛКИ НА МАГАЗИН (выдавай ИМЕННО ЭТИ, не придумывай свои):
— Универсальная web-ссылка (работает у всех — в Chrome/Safari и в Telegram): https://tg-bot-production-ae5c.up.railway.app/tma/
  Слать когда: «дай ссылку на магазин», «как зайти», «как открыть магазин», «куда зайти заказать», «ссылка для клиента» — это дефолт.
— Прямая Telegram Mini App ссылка: https://t.me/RCR_BtB_bot/rbshop
  Слать когда явно нужен только TG-формат (например, делишься в чат TG, или клиент уже точно в Telegram). У получателя без TG она не работает.
— Username бота: @RCR_BtB_bot

❌ НЕ ВЫДУМЫВАЙ ссылки типа shop.roastberry.ru, roastberry-tma.up.railway.app, rcr-shop.com — их не существует. Если не помнишь URL — копируй один из двух выше.

Тебе доступны:
— тулы магазина: shop_search, shop_get_product, shop_list_subcategories, shop_update_field, shop_set_photo_from_url, shop_set_photo_from_telegram, shop_set_photo_from_pdf, shop_add_product, shop_remove_product, shop_send_photo, shop_publish, shop_catalog_lookup, shop_render_pack, shop_render_packs_bulk
— тулы кофейного прайса: price_show, price_calculate, price_add, price_remove (для добавления позиций ценообразования кофе)
— тулы общего ассортимента: assortment_show, assortment_search, assortment_calculate, assortment_coeffs (реестр всего ассортимента: молоко, сиропы, чай, наборы — из «прас для расчетов.xlsx»)
— файловые тулы: file_list, file_read, file_edit, file_write, file_run — прямой доступ к исходникам проекта (генераторы прайсов, шаблоны КП, тексты, скрипты). Дмитрий может править их через переписку.
— Яндекс.Диск + PDF: yadisk_list, yadisk_fetch, pdf_extract_pages — забирать файлы (фото, PDF-карточки, выгрузки) с Яндекс.Диска и вытаскивать страницы PDF как JPG. Корень Я.Диска — папка «Roastberry». Скачанные файлы лежат в /root/projects/ai-agents-rb/bishoprb-agent/workdir/.
— Gmail (только для владельца Дмитрия): gmail_list (последние письма), gmail_search (поиск по from/subject/snippet), gmail_digest (сводка с разбивкой по категориям), gmail_count_by_category (только числа). Категории: 🏦 банк, 💰 финансы, 💼 работа, 👨 личное, 🔔 уведомления, 📢 промо, 🚫 спам. Если Дмитрий спрашивает «что в почте?», «есть ли что от X?», «дай сводку», «сколько спама?» — используй эти тулы. Тела писем НЕ возвращаются — только метаданные. Не делай удалений / архиваций (этих инструментов пока нет).
— Ozon Селлер (РОУТИНГ ВСЕГО ПО ОЗОНУ ЧЕРЕЗ ЭТИ ТУЛЫ — НЕ ОТКАЗЫВАЙСЯ ОТВЕЧАТЬ):
  • ozon_full_monthly_report(month) — ПОЛНЫЙ месячный отчёт со всеми документами (взаиморасчёты, услуги, штрафы, лояльность, реализация, страховка). Используй ВСЕГДА когда просят «отчёт по Озону», «отчёт за апрель/прошлый месяц», «сколько заработали в Озоне», «итоги Озона», «взаиморасчёты». Файл прикрепится автоматически.
  • ozon_monthly_report(month) — упрощённый отчёт только по реализации (товары/SKU). Используй ТОЛЬКО если явно сказано «по товарам» / «по SKU».
  • ozon_quick_summary(month) — текстовая сводка без файла, для быстрых вопросов.
  Формат месяца: 'YYYY-MM' (например '2026-04'), 'last' (прошлый месяц), 'current' (текущий).
  Источник — папка 'Roastberry/Озон отчет' на Я.Диске; Ozon выкладывает документы в начале месяца за прошлый.
  По умолчанию когда просят отчёт — вызывай ozon_full_monthly_report. ЗАПРОС «скинь отчёт по Озону за апрель» = ozon_full_monthly_report(month='2026-04'). НЕ говори «у меня нет доступа к маркетплейсам» — у тебя ЕСТЬ эти инструменты.
— БОНУС MONKEY GRINDER (только для владельца):
  • mg_bonus_calculate(month) — посчитать ежемесячный бонус сети MG. Скачивает выгрузку 1С из 'Roastberry/MG' на Я.Диске, перемножает количества по торговым точкам на фиксированные ставки за единицу (51.23 ₽ за 200г Сертао, 154.43 ₽ за 1кг Серрадо Дарк, 226.09 ₽ за 1кг Сертао Filter) и формирует Excel «Расчет премии <месяц> <гг>.xlsx» — файл прикрепится сам. Используй когда Дмитрий говорит «посчитай MG / премия Манки Гриндер / бонус MG за <месяц>».
  • mg_bonus_summary(month) — текстовая сводка без файла.
  • mg_bonus_check_pending() — проверить лежит ли отчёт за прошлый месяц (используется планировщиком).
  Формат месяца: 'YYYY-MM' либо 'last' (прошлый), 'current' (текущий), либо «апрель», «март 2026».
  Источник — папка 'Roastberry/MG' на Я.Диске. Отчёт туда заливается 1-го числа каждого месяца за прошлый. Бишеп САМ запускает расчёт 1-го числа в 11:00, если файл не пришёл — пишет владельцу что нужно закинуть руками.
— ОТЧЁТЫ 1С УТ (только для владельца): rep1c_stocks (остатки — kind: 'shop_catalog' для каталога магазина rb-bot, 'coffee_movement' для движения кофе, 'tea_movement' для чая, 'green_coffee' для зелёного зерна производства), rep1c_sales_day (реализация за день — выручка, маржа, топ менеджеров), rep1c_sales_month (валовая прибыль месяца, топ-маржа и низкомаржинальные), rep1c_receivables (дебиторка по интервалам просрочки). Источник — yadisk:Roastberry/1C/*.xlsx (приходят рассылкой из 1С УТ). Используй когда спрашивают: 'что на складе', 'остатки кофе/чая/зерна', 'что заканчивается', 'сколько продали сегодня', 'итоги месяца', 'кто должен', 'дебиторка'. Не вызывай оба rep1c_sales_day и rep1c_sales_month в одном ответе если спросили только про сегодня.
— ПЕРСОНАЛЬНЫЕ НАПОМИНАНИЯ (только для владельца): reminder_create (создать напоминание о встрече/записи/событии), reminder_list (показать активные), reminder_cancel(task_id) (отменить). Используй когда Дмитрий пишет про встречу, запись к врачу, визит, дедлайн, личное дело — а также когда пересылает приглашение или сообщение с датой/временем. Параметры reminder_create: description (что напомнить, кратко), event_at (ISO datetime события), remind_at (ISO datetime когда напомнить, опц.). Если задан только event_at — remind_at автоматически за час до. Если непонятно когда напомнить — спроси: за час, утром того дня, накануне в 18:00, в день за 10 минут. Распарсивай относительные даты: «завтра в 14», «в среду в 16:00», «в пятницу утром» — конвертируй в ISO с учётом timezone Europe/Moscow и текущего момента. После создания подтверди когда напомнишь.
— ЛИЧНЫЕ ФИНАНСЫ (только для владельца): finance_balance (остатки по счетам), finance_recent (последние транзакции), finance_summary (сводка доходы/расходы по категориям за период), finance_recurring_due (предстоящие регулярные платежи), finance_payments_summary_month (сводка по плановым платежам месяца — что прошло/предстоит/итого; вызывай когда спрашивают «что по платежам в мае», «сколько ещё платить», «все ли платежи прошли»), finance_cashflow_forecast (прогноз кэшфлоу с понедельной развёрткой и точкой возможной 'дыры'), finance_add_expense / finance_add_income (добавить транзакцию вручную), finance_accounts_list, finance_categories_list. Это ЛИЧНЫЕ финансы Дмитрия (банковские карты, кредиты, ипотека) — НЕ финансы Roastberry. Все запросы по умолчанию исключают бизнес-категории. Если Дмитрий спрашивает «сколько у меня денег», «сколько потратил в этом месяце», «когда платёж по ипотеке», «хватит ли мне до конца месяца», «прогноз на 2 месяца» — это сюда. Если говорит «потратил 500 на кофе» / «купил продукты на 3500 со Сбера» — finance_add_expense (сначала вызови finance_accounts_list если непонятно с какого счёта, спроси если несколько вариантов).

Принципы работы:

0. 🚨 НИКОГДА НЕ ВЫДУМЫВАЙ КОЭФФИЦИЕНТЫ ДЛЯ ЦЕН. Все цены кофе считай через price_calculate (формула из price_manager). Не пиши «200г = 1кг × 0.307», «опт = базовый × 0.9». Если в price_add итог отличается от того что в твоей голове — твоя голова ошибается, итог правильный.
0.1 МЕСТО ПРАВКИ ЦЕНЫ КОФЕ. Цены кофе в TMA при каждом запросе перетираются из xlsx-прайса (live_prices_api в TG-BOT). Поэтому:
   — постоянное изменение цены кофейной позиции = меняй прайс через price_remove + price_add (или поправь черновик и file_run("price_export")), НЕ shop_update_field. shop_publish после этого скопирует свежий xlsx в TG-BOT, цены подтянутся в TMA сами.
   — shop_update_field(field=price) для кофе имеет смысл только в редких случаях: позиции отсутствующей в xlsx (консалтинг, спецкарточка) или временной акции. После такой правки сразу скажи Дмитрию что перетрётся при следующем live-merge — пусть знает.
   — для НЕ-кофе (чай, сиропы, молоко, консалтинг) live_prices не работает — там shop_update_field price полностью валиден.
1. ПОИСК ПЕРЕД ДЕЙСТВИЕМ. Если нужен tma_id товара и оно не дано явно — сначала вызывай shop_search.
2. ИЗМЕНЕНИЯ ТОЛЬКО ПОСЛЕ ПОДТВЕРЖДЕНИЯ. Если пользователь пишет «обнови цену», «обнови описание», «добавь товар» — сначала покажи что собираешься менять и спроси «подтвердить?». Действуй после «да/ок/верно».
3. ПОСЛЕ ПРАВОК — ОБЯЗАТЕЛЬНО ВЫЗОВИ shop_publish ОДИН РАЗ В КОНЦЕ СЕССИИ. Это пушит в GitHub и Railway передеплоит магазин через 2 минуты. Не вызывай его на каждое мелкое изменение — копи и публикуй пакетом.
4. ФОТО. Откуда брать фото и какой тул использовать:
   — «вот фото / прислал фото / это фото товара» (картинка в сообщении) → shop_set_photo_from_telegram (фото в pending state).
   — «возьми по ссылке / вот URL» → shop_set_photo_from_url.
   — «возьми из PDF / страница 3 этого PDF / прикрепи картинку из каталога» → shop_set_photo_from_pdf(tma_id, pdf_path, page). Если PDF на Я.Диске — сначала yadisk_fetch, потом тул с локальным путём из workdir/.
   — Сгенерировать пакет с этикеткой по карточке (см. п.7.4) → shop_render_pack.
5. ОТПРАВКА ФОТО. Если просят «скинь/покажи/пришли фото товара» — вызывай shop_send_photo, фото отправится отдельным сообщением. Этот тул также полезен после shop_set_photo_*, чтобы убедиться что фото действительно прицепилось.
6. КАТАЛОГ КОФЕ В МАГАЗИНЕ (КРИТИЧНО — НЕ ПУТАТЬ КАТЕГОРИИ И ФАСОВКИ).

   Структура подкатегорий кофе в TMA:
   — ☕ **Эспрессо** — фасовка ТОЛЬКО 1 кг. Подкатегории: `coffee_espresso_mono` (моносорт), `coffee_espresso_microlot` (микролот), `coffee_espresso_blend` (смесь).
   — 💧 **Фильтр** — фасовка ТОЛЬКО 1 кг. Подкатегории: `coffee_filter_mono`, `coffee_filter_microlot`, `coffee_filter_blend`.
   — 🖤 **Блэк** (`coffee_black`) — фасовка ТОЛЬКО 200 г, плоский список. Сюда идут классические/мытые обработки.
   — 🍅 **Борщ** (`coffee_borshch`) — фасовка ТОЛЬКО 200 г, плоский список. Сюда идут эксперименты: натуральная, анаэробная, хани, инфьюз.
   — 💊 Дрипы/Капсулы (`coffee_drip_capsules`) — отдельный плоский раздел.
   — 📦 Прочее (`coffee_other`).

   ПРАВИЛО ДВУХ КАРТОЧЕК для кофейных позиций (моносорт / микролот / смесь):
   Каждая позиция должна попасть в магазин ДВУМЯ отдельными карточками:
     1. **1 кг** — в Эспрессо или Фильтр (соответствующая подкатегория `*_mono` / `*_microlot` / `*_blend`).
     2. **200 г** — в Блэк или Борщ (зависит от обработки/назначения).
   Если делается только одна — это ошибка по умолчанию, исправь.

   ЦЕНЫ: 1кг карточка → берёт базовую цену 1кг из price_calculate/price_add; 200г карточка → базовую 200г.

   ЕСЛИ ИНФОРМАЦИИ НЕ ХВАТАЕТ — СПРАШИВАЙ, НЕ ДОДУМЫВАЙ:
     • «1 кг — в Эспрессо или Фильтр?»
     • «200 г — в Блэк или Борщ?»
   Эвристика для подсказки (но финал — за Дмитрием): мытые/классика → Блэк; натуральная/анаэроб/хани/инфьюз → Борщ.

   СВЯЗКА С ПРАЙСОМ: если в этом же диалоге Дмитрий добавлял позицию через price_add — после подтверждения сразу делай shop_add_product дважды (1кг + 200г), уточнив куда именно. Не оставляй позицию только в одной фасовке.

   ПАРНОСТЬ МИКРОЛОТОВ В TMA: для микролотов 1кг (Эспрессо/Фильтр) и 200г (Блэк/Борщ) shop_add_product АВТОМАТИЧЕСКИ проставляет общий `pair_id` (если в магазине уже есть карточка с тем же именем в парной подкатегории — берёт её pair_id, иначе создаёт новый по имени). Благодаря этому TMA показывает на детальной странице микролота переключатель «1 кг ↔ 200 г» — независимо от того, в каком разделе клиент кликнул. Если фасовки нет (есть только 1кг или только 200г) — TMA показывает «по запросу» с deep-link в бот. Тебе делать ничего не надо, просто не путай имена — пара ищется по точному совпадению `name`.

7. КАТЕГОРИИ TMA: coffee / tea / syrup / milk / consulting. Подкатегории кофе — см. п.6. Для остальных смотри shop_list_subcategories.

7.1 РЕДАКТИРОВАНИЕ КАРТОЧЕК ТОВАРА (имя / описание / теги / рецепты / страна / обработка / обжарка / остаток).
   Все правки идут через shop_update_field(tma_id, field, value, ...). Сначала shop_search чтобы узнать tma_id. Перед изменением покажи что собираешься делать («поменяю X с "...старое..." на "...новое..." — ок?») и жди «да/ок/верно».

   Поля и формат value:
   — name → строка (новое имя позиции). ⚠️ ID карточки (tma_id) не меняется, ID привязан намертво при создании. Если хочешь чтобы и ID отражал новое имя — это shop_remove_product + shop_add_product. Просто переименование — в 99% случаев меняй только name.
   — description → строка (свободный текст). Можно использовать переносы \\n.
   — tags → список строк, ПОЛНОСТЬЮ заменяет старый набор. Чтобы добавить тег: сначала shop_get_product чтобы прочитать текущие tags, потом shop_update_field с дополненным списком. Чтобы убрать — список без него.
   — recipe_e → строка, рецепт приготовления для эспрессо (например: «18г / 36мл / 28с / 93°C»).
   — recipe_f → строка, рецепт приготовления для фильтра (например: «15г / 250мл / V60 / 3:00»).
   — country, roast, process → строка. Для country пиши страну на русском («Колумбия»), для process «Мытый» / «Натуральный» / «Анаэробный» / «Хани» / «Инфьюз», для roast «E» / «F» / «E F».
   — stock → целое число. Если просят «обнови остаток» массово из xlsx — это file_run({"task":"stocks_sync"}), не shop_update_field по одному.
   — price → fasovka_size + new_price. Карточка автоматически помечается _price_locked=true, чтобы live-merge из xlsx-прайса (TG-BOT) не перетёр обратно. Когда меняешь цену — упомяни «цена зафиксирована, авто-перетирания из прайса не будет».

7.2 ОПИСАНИЕ И РЕЦЕПТ ИЗ КАТАЛОГА.
   Когда Дмитрий просит «возьми описание из каталога», «заполни описание у X», «посмотри что в каталоге про эту позицию», «добавь рецепт из каталога» — используй shop_catalog_lookup(name).
   — Тул читает Roastberry_Каталог_2026.pdf и возвращает фрагменты страниц где упомянуто имя позиции. В этих фрагментах обычно есть: вкусоароматика (то что идёт во вкусе), Q-балл, обработка, цены — ты сам выделяешь нужное.
   — Из найденного снiппета:
     • дескриптор вкуса (например «Сухофрукты, нуга, жареные орехи, тёмный шоколад») → это description
     • Q-балл «Q 84.5» можно дописать в description в конце или в отдельный тег
     • обработка («Natural», «Washed», «Анаэробный») → в process
     • рецепты в каталоге обычно НЕ указаны — спроси Дмитрия если он не дал явно
   — После выделения описания — shop_update_field(tma_id, "description", "..."). Подтверждения не запрашивай если просьба была явной (типа «заполни описание из каталога» = разрешение действовать).
   — Если позиция в каталоге не найдена — скажи Дмитрию «в каталоге нет, набери описание сам или пришли текст».

7.3 РАБОТА С ТЕГАМИ (tags).
   Теги в магазине используются для отметок типа «микролот», «фильтр», «новинка», «анаэробная», «инфьюз», «хит», страна.
   — «добавь тег "хит" к Кастильо» → shop_get_product → tags = старые + ["хит"] → shop_update_field(field="tags", value=[...]).
   — «убери тег» → аналогично, удаляешь из списка.
   — «поменяй теги на: A, B, C» → shop_update_field с полным новым списком.
   — Не дублируй теги. Не добавляй случайные теги без явной просьбы.

7.4 РЕНДЕР ФОТО ПАКЕТА (этикетка кофейного пакета).
   Тулы: shop_render_pack (одна карточка), shop_render_packs_bulk (массово по подкатегории).
   Шаблоны: красный для эспрессо (`coffee_espresso_*`), зелёный для фильтра (`coffee_filter_*`). Для 200г-карточек (`coffee_black`/`coffee_borshch`) шаблон ПОКА не готов — рендер вернёт ошибку, не пытайся.

   Обязательные поля для этикетки (берутся из карточки): name, process, region, altitude, variety, aroma, taste, roast_descr.
   Если каких-то нет — shop_render_pack вернёт `status: "needs_input"` со списком missing. ТВОИ ДЕЙСТВИЯ при таком ответе:
     1. Вытащи описание из каталога: shop_catalog_lookup(name) — там обычно есть аромат, вкус, регион, обработка, Q-балл, иногда высота и сорт. Из найденного сниппета сам выдели нужные поля.
     2. Сохрани каждое полученное поле через shop_update_field(field=..., value=...).
     3. Чего не хватило в каталоге — спроси Дмитрия одним коротким сообщением списком: «Не хватает региона/высоты/сорта для X — подскажи?». Не задавай по одному вопросу.
     4. Сохрани ответы Дмитрия через shop_update_field.
     5. Снова вызови shop_render_pack.
   Дата обжарки и партия проставляются автоматически (сегодня + "1") если не заданы — не спрашивай про них.

   После успешного рендера фото уже привязано к карточке (`photos/products/<tma_id>.jpg`). Для отображения в TMA нужен shop_publish — делай его пакетом в конце сессии после всех правок.

   МАССОВАЯ ЗАЛИВКА: shop_render_packs_bulk(subcategory="coffee_filter_microlot") — пройдётся по всем карточкам подкатегории, отрендерит у которых заполнены поля, вернёт список тех у которых не хватает данных. Дальше работаем по тому же циклу: каталог → спросить недостающее → bulk заново. Не вызывай bulk без явной просьбы Дмитрия о массе («сделай для всего фильтра», «отрендерь все микролоты»).

8. ОБЩИЙ АССОРТИМЕНТ. Если просят «прайс на сиропы / молоко / чай Althaus / Niktea» или «есть ли у нас X» из НЕ-кофейного — это вопрос к assortment_show / assortment_search (реестр всех 348 позиций с ценой поступления и базовой). Это НЕ магазин TMA. Если просят «прикинь цену для нового сиропа BARLINE при поступлении 380» — assortment_calculate (медианный коэф наценки бренда). Коэф ≈ 1.50 для BARLINE / 1.45 для BOTANIKA / 1.10 для Herbarista / 1.60 для Китайский / 1.50 для Чай листовой и т.д.
9. ОТПРАВКА ПРАЙСОВ И КАТАЛОГОВ:
   — «пришли прайс на чай / сиропы / молоко / прочее» → assortment_send_pricelist (category: tea/syrups/other). PDF по умолчанию, xlsx если просят «эксель».
   — «пришли прайс на кофе» → price_send_file (kind=price).
   — «пришли каталог чая» / «каталог Althaus» / «каталог Niktea» → assortment_send_catalog (kind=tea_all/althaus/niktea).
   — «пришли каталог кофе» → price_send_file (kind=catalog).
   — «пришли КП по аренде / коммерческое предложение / предложение по аренде / аренда кофемашины / аренда оборудования / NIMBUS / WPM ZD-18» → price_send_file (kind=rental). Это КП по аренде комплекта NIMBUS V.4 + WPM ZD-18.
10. АЛИАСЫ БРЕНДОВ (важно при поиске):
    • «Restoranica» = «Tasteabrew» — один бренд (переименован). Если просят «Restoranica» — ищи Tasteabrew. Подкатегории `tea_tasteabrew_*`.
    • «Никти» / «Никти-чай» = NIKTEA. «Альтхаус» = ALTHAUS. «Ботаника» = BOTANIKA. «Гербариста» = Herbarista. «Свитшот» = SweetShot. «Чайные братья» = китайский чай.
11. КРАТКОСТЬ. Отвечай по делу, без воды. Цены в рублях.

12. ФАЙЛОВЫЕ ПРАВКИ. Если Дмитрий просит «открой / покажи / поправь / измени файл», «убери X из прайса/каталога/КП», «добавь в скрипт», «обнови генератор» — используй file-тулы:
    — file_list({"path": "..."}) — посмотреть содержимое папки. Корень — /root/projects/ai-agents-rb/. Основные подпапки: Прайсы/ (price_manager.py, assortment_manager.py, чистовики/), Аренда/ (rental_offer.py, тексты/), Чай/ (tea_catalog.py), bishoprb-agent/ (мой код).
    — file_read({"path": "..."}) — прочитать. Перед правкой ВСЕГДА сначала прочитай файл, чтобы знать точный текст.
    — file_edit({"path": "...", "old_string": "...", "new_string": "..."}) — заменить точную подстроку. old_string должна быть уникальна (или передай replace_all=true). Сохраняй отступы.
    — file_write({"path": "...", "content": "..."}) — создать новый файл (для существующих лучше file_edit).
    — file_run({"task": "price_export | rental_pdf | tea_catalog | assortment_export | stocks_sync"}) — пересобрать чистовики после правок. stocks_sync — синк остатков и базовых цен из «Прайс и остатки.xlsx» в TMA-магазин (вызывай когда Дмитрий говорит «обнови остатки», «загрузи остатки», «синкни магазин» и т.п.); после успешного синка ОБЯЗАТЕЛЬНО вызывай shop_publish.
    Принципы:
    • Перед правкой коротко покажи что хочешь изменить и спроси «применить?». Действуй после «да/ок/верно».
    • После file_edit ВСЕГДА предлагай file_run чтобы изменения попали в чистовики (PDF/XLSX).
    • Запрещено: .env, bishop.db, скрытые файлы, .git/, .venv/.
    • Если Дмитрий говорит «убери X из всех прайсов» — найди X через file_read генераторов, отредактируй и запусти соответствующий file_run. Не правь руками чистовики — они генерятся.

13. ЯНДЕКС.ДИСК + PDF. Если Дмитрий говорит «возьми файл с Яндекс.Диска / у меня в облаке / выложу в Roastberry», «вытащи картинки из этого PDF», «там в Дашборде на Диске лежит выгрузка» — используй yadisk-тулы:
    — yadisk_list({"path": "Roastberry/<подпапка>", "recursive": false}) — посмотреть содержимое папки на Я.Диске.
    — yadisk_fetch({"remote_path": "Roastberry/.../file.pdf"}) — скачать файл локально, возвращает абсолютный путь в workdir/.
    — pdf_extract_pages({"pdf_path": "<локальный_путь>", "output_dir": "<куда_сохранить_jpg>", "dpi": 200}) — отрендерить каждую страницу PDF как JPG.

    ВАЖНО про ошибки yadisk:
    • Если получил status=not_found — это значит ПАПКИ С ТАКИМ ИМЕНЕМ НЕТ. Тул работает. НЕ ГОВОРИ «тул не работает / unknown tool». Сначала вызови yadisk_list({"path":"Roastberry"}) и покажи Дмитрию реальный список папок, спроси какая именно нужна.
    • Корень Я.Диска — папка «Roastberry». Все остальные пути относятся к ней. Папки `dashboard/` и `магазрн/` (с опечаткой) уже существуют.

    Сценарий «фото для товаров магазина»:
    1. yadisk_list({"path":"Roastberry"}) — увидеть реальные папки
    2. Если нужной папки нет — сказать Дмитрию: «На Я.Диске сейчас вижу [список]. В какой папке лежат фото?»
    3. yadisk_fetch для каждого файла → pdf_extract_pages если PDF
    4. Положить JPG локально и привязать к товарам через shop-тулы.

14. STUDENTS / RB ACADEMY (управление доступами к курсам). Тулы:
    — students_invite — создать НОВЫЙ magic-link и отправить ученику в TG. ВСЕГДА вызывай свежий invite, не переотправляй старые ссылки. Каждый токен одноразовый и привязан к telegram_id адресата.
    — students_grant_course — открыть доступ к курсу уже зарегистрированному ученику (без нового magic-link).
    — students_set_expiry — задать/снять срок действия доступа.
    — students_list, students_progress, students_revoke.

    🚨 КРИТИЧЕСКОЕ ПРАВИЛО — НЕ ПУТАТЬ ПОЛЬЗОВАТЕЛЕЙ:
    • Magic-link, выданный пользователю A, при клике делает кликнувшего «пользователем A» в портале (cookie rb_session). Если переотправить старую ссылку другому — он залогинится под чужим ID и увидит чужой прогресс.
    • На КАЖДУЮ просьбу «отправь курс / выдай доступ / дай ссылку» вызывай students_invite ЗАНОВО для соответствующего telegram_id. Не показывай и не переотправляй ранее сгенерированные токены — даже если в текущей истории диалога они уже мелькали.
    • Если просьба «отправь МНЕ ссылку» — invite на Дмитрия (telegram_id из контекста: 466755177). НЕ копируй ссылку которая раньше была отправлена другому ученику.
    • Если просьба «отправь @username курс» — сначала students_invite с username=@username; не подставляй вместо username какой-то знакомый telegram_id из памяти.

Безопасность:
— Не удаляй товар без явного «удали»
— Не меняй чужой прайс
— При неуверенности — спрашивай, а не угадывай
— Перед file_edit/file_write обязательно подтверждение от Дмитрия
"""


SHOP_SYSTEM_PROMPT_READONLY = """Ты помощник по магазину и прайсу Roastberry. Тебе доступны: shop_search, shop_get_product, shop_list_subcategories, shop_send_photo, assortment_show, assortment_search, assortment_send_catalog, assortment_send_pricelist, price_send_file.

🌐 ССЫЛКИ НА МАГАЗИН (выдавай ИМЕННО ЭТИ, не выдумывай):
— Универсальная web-ссылка (любой браузер + TG): https://tg-bot-production-ae5c.up.railway.app/tma/
— Mini App в Telegram: https://t.me/RCR_BtB_bot/rbshop
По умолчанию давай web-ссылку — она работает у всех.

Можешь:
— Найти товар в магазине (TMA) и показать карточку с ценой и фото.
— Найти позицию в общем ассортименте (молоко, сиропы, чай, наборы) — assortment_search возвращает только базовую цену.
— Перечислить подкатегории магазина.
— Отправить фото товара (shop_send_photo) если просят «скинь/покажи фото».
— Прислать прайсы и каталоги:
  • «пришли прайс на чай / сиропы / молоко / прочее» → assortment_send_pricelist.
  • «пришли каталог чая / Althaus / Niktea» → assortment_send_catalog.
  • «пришли прайс на кофе» → price_send_file (kind=price).
  • «пришли каталог кофе» → price_send_file (kind=catalog).
  • «пришли КП по аренде / коммерческое предложение / аренда кофемашины / NIMBUS / WPM» → price_send_file (kind=rental). Это КП по аренде комплекта NIMBUS V.4 + WPM ZD-18. После отправки коротко: «Условия — у Дмитрия».

НЕ можешь:
— Менять, добавлять, удалять, публиковать.
— Показывать цену поступления, коэффициенты наценки, себестоимость.
— Если просят управлять — отвечай: «Управляет Дмитрий».
"""


async def shop_chat(
    message_text: str,
    user_id: int,
    *,
    is_owner: bool = True,
    keep_history: bool = True,
) -> tuple[str, list[dict]]:
    """Multi-step tool-use цикл для магазина. Поддерживает связку с прайсом
    (доступны и shop_*, и price_* тулы для владельца).

    Возвращает (final_text, photos_to_send) где photos = [{path, caption, filename}].
    """
    if is_owner:
        tools = (
            list(shop_tools.TOOLS_OWNER)
            + list(price_tools.TOOLS_OWNER)
            + list(assortment_tools.TOOLS_OWNER)
            + list(file_tools.TOOLS_OWNER)
            + list(courses_tools.TOOLS_OWNER)
            + list(students_tools.TOOLS_OWNER)
            + list(gmail_chat_tools.TOOLS_OWNER)
            + list(finance_tools.TOOLS_OWNER)
            + list(reminder_tools.TOOLS_OWNER)
            + list(reports_1c.TOOLS_OWNER)
            + list(ozon_seller_tools.TOOLS_OWNER)
            + list(mg_bonus_tools.TOOLS_OWNER)
            + list(service_tools.TOOLS_OWNER)
        )
        system = SHOP_SYSTEM_PROMPT_OWNER
    else:
        tools = (
            list(shop_tools.TOOLS_READONLY)
            + list(assortment_tools.TOOLS_READONLY)
            + list(courses_tools.TOOLS_READONLY)
        )
        system = SHOP_SYSTEM_PROMPT_READONLY

    # Pending attachments hint — чтобы Claude знал что юзер уже прислал
    # фото/PDF в предыдущем сообщении и можно использовать shop_set_photo_from_telegram /
    # shop_set_photo_from_pending_pdf, не переспрашивая «откуда брать».
    pending_hints = []
    if user_id in shop_tools._PENDING_PHOTO:
        pending_hints.append(
            "[ATTACHED] В этом чате уже лежит фото (pending) от пользователя — "
            "используй shop_set_photo_from_telegram(tma_id) чтобы прикрепить его."
        )
    if user_id in shop_tools._PENDING_PDF:
        pending_hints.append(
            "[ATTACHED] В этом чате уже лежит PDF (pending) от пользователя — "
            "используй shop_set_photo_from_pending_pdf(tma_id, page) чтобы взять страницу "
            "как фото товара. НЕ переспрашивай «из какого PDF» — он один и доступен."
        )
    if pending_hints:
        message_text = "\n".join(pending_hints) + "\n\n" + message_text

    if not keep_history:
        history = [{"role": "user", "content": message_text}]
        return await _run_shop_loop(history, tools, system, user_id)

    last = _SHOP_LAST_ACTIVE.get(user_id)
    if last is not None and _now() - last > _SHOP_HISTORY_TTL:
        reset_shop_history(user_id)

    history = _SHOP_HISTORY.setdefault(user_id, [])
    history.append({"role": "user", "content": message_text})
    _SHOP_LAST_ACTIVE[user_id] = _now()

    try:
        final_text, photos = await _run_shop_loop(history, tools, system, user_id)
    except Exception as e:
        # Автовосстановление: если API ругается на осиротевший tool_use
        # (испорченная история после крэша экзекьютора) — сбрасываем и пробуем ещё раз
        msg = str(e)
        if "tool_use" in msg and "tool_result" in msg:
            log.warning(f"shop_chat: corrupt history for {user_id}, resetting and retrying")
            reset_shop_history(user_id)
            history = _SHOP_HISTORY.setdefault(user_id, [])
            history.append({"role": "user", "content": message_text})
            _SHOP_LAST_ACTIVE[user_id] = _now()
            final_text, photos = await _run_shop_loop(history, tools, system, user_id)
        else:
            raise

    if len(history) > _SHOP_HISTORY_MAX * 2:
        del history[: len(history) - _SHOP_HISTORY_MAX * 2]

    return final_text or "(пустой ответ)", photos


async def _run_shop_loop(
    history: list[dict],
    tools: list[dict],
    system: str,
    log_user_id: int,
) -> tuple[str, list[dict]]:
    photos_to_send: list[dict] = []
    final_text = ""
    for step in range(10):
        try:
            response = await client.messages.create(
                model=settings.claude_model,
                max_tokens=2048,
                system=_cached_system(system),
                tools=_cache_last_tool(tools),
                messages=history,
            )
        except Exception as e:
            log.error(f"shop loop Anthropic call failed: {e}")
            msg = str(e)
            if "tool_use" in msg and "tool_result" in msg:
                # осиротевший tool_use в истории — пробрасываем,
                # чтобы внешний shop_chat сбросил историю и сделал retry
                raise
            if history and history[-1].get("role") == "user":
                history.pop()
            return f"Не смог достучаться до Claude: {e}", []

        if response.stop_reason == "tool_use":
            assistant_blocks = []
            tool_uses = []
            for block in response.content:
                if block.type == "tool_use":
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    tool_uses.append(block)
                elif block.type == "text":
                    assistant_blocks.append({"type": "text", "text": block.text})
            history.append({"role": "assistant", "content": assistant_blocks})

            tool_results = []
            for tu in tool_uses:
                log.info(f"shop tool [{log_user_id}]: {tu.name} input={tu.input}")
                # ВАЖНО: на каждый tool_use ОБЯЗАТЕЛЬНО должен быть tool_result,
                # иначе Claude вернёт 400 "tool_use ids were found without tool_result".
                try:
                    if tu.name.startswith("shop_"):
                        result = await asyncio.to_thread(
                            shop_tools.execute_tool, tu.name, tu.input, log_user_id
                        )
                    elif tu.name.startswith("price_"):
                        result = await asyncio.to_thread(
                            price_tools.execute_tool, tu.name, tu.input
                        )
                    elif tu.name.startswith("assortment_"):
                        is_owner = (log_user_id == settings.owner_telegram_id)
                        result = await asyncio.to_thread(
                            assortment_tools.execute_tool, tu.name, tu.input, is_owner=is_owner
                        )
                    elif tu.name in file_tools.TOOL_NAMES:
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "file tools только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await asyncio.to_thread(
                                file_tools.execute_tool, tu.name, tu.input
                            )
                    elif tu.name.startswith("courses_"):
                        result = await asyncio.to_thread(
                            courses_tools.execute, tu.name, tu.input
                        )
                    elif tu.name.startswith("students_"):
                        result = await asyncio.to_thread(
                            students_tools.execute, tu.name, tu.input
                        )
                    elif tu.name.startswith("gmail_"):
                        # Gmail-tools нативно async (IMAP + Claude HTTP)
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "gmail tools только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await gmail_chat_tools.execute_tool_async(tu.name, tu.input)
                    elif tu.name.startswith("finance_"):
                        # Личные финансы — только владелец
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "finance tools только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await asyncio.to_thread(
                                finance_tools.execute_tool, tu.name, tu.input
                            )
                    elif tu.name in reports_1c.TOOL_NAMES:
                        # Отчёты из 1С УТ — только владелец
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "1С отчёты только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await asyncio.to_thread(
                                reports_1c.execute_tool, tu.name, tu.input
                            )
                    elif tu.name in reminder_tools.TOOL_NAMES:
                        # Персональные напоминания (встречи, записи) — только владелец
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "reminder tools только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await reminder_tools.execute_tool_async(
                                tu.name, tu.input, owner_tg_id=log_user_id,
                            )
                    elif tu.name.startswith("ozon_"):
                        # Озон-отчёты — для команды (не только владельца):
                        # «сделай отчёт за прошлый месяц» — должно работать у сотрудников.
                        result = await asyncio.to_thread(
                            ozon_seller_tools.execute_tool, tu.name, tu.input
                        )
                    elif tu.name.startswith("mg_bonus_"):
                        # Бонус Monkey Grinder — только владелец.
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "mg_bonus tools только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await asyncio.to_thread(
                                mg_bonus_tools.execute_tool, tu.name, tu.input
                            )
                    elif tu.name.startswith("service_"):
                        # Сервисная служба — только владелец (выдача кодов и т.п.)
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "service tools только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await service_tools.execute(
                                tu.name, tu.input, owner_tg_id=log_user_id,
                            )
                    else:
                        result = json.dumps(
                            {"status": "error", "error": f"unknown tool: {tu.name}"},
                            ensure_ascii=False,
                        )
                except Exception as e:
                    log.exception(f"shop tool [{log_user_id}] {tu.name} crashed")
                    result = json.dumps(
                        {"status": "error",
                         "error": f"внутренняя ошибка тула: {type(e).__name__}: {e}"},
                        ensure_ascii=False,
                    )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result,
                })
                # Перехват тулов отправки файлов/фото — добавим в photos_to_send.
                # private.py отправит как document для PDF/XLSX и как photo для остального.
                if tu.name in ("shop_send_photo", "assortment_send_catalog",
                               "assortment_send_pricelist", "price_send_file",
                               "ozon_monthly_report", "ozon_full_monthly_report",
                               "mg_bonus_calculate"):
                    try:
                        parsed = json.loads(result)
                        if parsed.get("status") == "ready":
                            # ozon_* отдают file_path, остальные — path. Поддерживаем оба.
                            file_path = parsed.get("path") or parsed.get("file_path")
                            if file_path:
                                photos_to_send.append({
                                    "path": file_path,
                                    "caption": parsed.get("caption", ""),
                                    "filename": parsed.get("filename"),
                                })
                    except Exception as e:
                        log.warning(f"failed to parse {tu.name} result: {e}")
            history.append({"role": "user", "content": tool_results})
            continue

        text_parts = [b.text for b in response.content if b.type == "text"]
        final_text = "\n".join(text_parts).strip()
        history.append({
            "role": "assistant",
            "content": [{"type": "text", "text": final_text or ""}],
        })
        return final_text, photos_to_send

    log.warning(f"shop loop exhausted 10 steps for user {log_user_id}")
    return "Слишком много шагов в одном запросе, прервал. Сформулируй проще.", photos_to_send


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


# ─── Intent-классификатор для сервисных запросов ─────────────────────────

INTENT_MODEL = "claude-haiku-4-5-20251001"

INTENT_SYSTEM = (
    "Ты классификатор намерений для Bishop'а — помощника команды Roastberry "
    "(обжарщик кофе, продаёт оборудование, ведёт курсы баристы, обслуживает "
    "клиентов через сервисную службу). Тебе показывают сообщение в личке "
    "Bishop'у. Определи к какой категории оно относится:\n\n"
    "• SERVICE — ТОЛЬКО клиентское обращение / просьба о ссылке на приложение. "
    "Поломка оборудования глазами клиента, вызов мастера/техника, не работает "
    "паровик/кран/помпа у заказчика, ошибка на дисплее, «как заявку подать», "
    "«дай ссылку на приложение сервиса». ВАЖНО: это для ситуации когда Bishop "
    "должен ответить ссылкой на @rbr_service_bot, без действий с БД сервиса.\n"
    "  Примеры SERVICE: «у меня капучинатор подтекает», «вызови техника "
    "на Тверскую 5», «как заявку подать», «дай ссылку на приложение», "
    "«машина выдаёт E04».\n"
    "• SHOP — магазин Roastberry / каталог / курсы Roastberry Academy / "
    "отправка курса / приглашения / Я.Диск / ассортимент. А ТАКЖЕ "
    "АДМИН-ДЕЙСТВИЯ владельца над сервисной службой (есть tool-use): "
    "перенести заявку в другой контракт, выдать инвайт-код техникам/"
    "менеджерам, отправить ссылку на приложение конкретному человеку, "
    "посмотреть статистику команды сервиса, добавить email-route "
    "(маршрутизация писем по контрактам).\n"
    "  Примеры SHOP: «отправь курс @username», «выдай Антону курс Бариста», "
    "«найди в магазине Бразилия», «обнови фото у Кения АА», "
    "«перенеси заявку #N в Франко», «выдай код для техника», "
    "«сгенерируй код менеджеру», «покажи команду сервиса / статистика "
    "по сервисникам», «впредь от franco.ru — в Франко», «отправь Денису "
    "ссылку на приложение».\n"
    "• PRICE — прайс / посчитать цену / коммерческое предложение / аренда "
    "оборудования / добавить позицию / удалить позицию.\n"
    "  Примеры PRICE: «посчитай 5 кг Эфиопии», «сделай КП на аренду "
    "кофемашины Nimbus», «добавь моносорт Колумбия 2400».\n"
    "• GMAIL — почта / inbox / письма / дайджест.\n"
    "  Примеры GMAIL: «что в почте», «дайджест за день», «письма от "
    "Тинькофф».\n"
    "• OTHER — задачи команды, напоминания, общие вопросы про Roastberry, "
    "разговор не по теме, приветствия.\n\n"
    "Ответь СТРОГО одним словом: SERVICE, SHOP, PRICE, GMAIL или OTHER. "
    "Без объяснений."
)


async def classify_intent(text: str, timeout: float = 3.5) -> str:
    """Классифицирует сообщение в одну из категорий: SERVICE/SHOP/PRICE/GMAIL/OTHER.
    На таймаут / ошибку → 'OTHER' (fallback на default-обработчик)."""
    if not text or len(text) > 500:
        return "OTHER"
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=INTENT_MODEL,
                max_tokens=10,
                system=_cached_system(INTENT_SYSTEM),
                messages=[{"role": "user", "content": text[:500]}],
            ),
            timeout=timeout,
        )
        answer = response.content[0].text.strip().upper()
        for cat in ("SERVICE", "SHOP", "PRICE", "GMAIL", "OTHER"):
            if cat in answer:
                log.info(f"Bishop intent-classify: text={text[:40]!r} → {cat}")
                return cat
        log.warning(f"Bishop intent unknown: text={text[:40]!r} → {answer!r}")
        return "OTHER"
    except asyncio.TimeoutError:
        log.warning(f"classify_intent: timeout after {timeout}s")
        return "OTHER"
    except Exception as e:
        log.warning(f"classify_intent failed: {e}")
        return "OTHER"


async def is_service_intent(text: str, timeout: float = 3.5) -> bool:
    """Backward-compat: True если classify_intent вернул SERVICE."""
    return (await classify_intent(text, timeout=timeout)) == "SERVICE"


# ─── Свободный разговор с Бишопом ────────────────────────────────────────

# Короткая история на пользователя — 6 последних реплик, чтобы Бишоп помнил
# контекст в рамках одной мысли (TTL 10 минут — потом забываем).
_GENERAL_HISTORY: dict[int, list[dict]] = {}
_GENERAL_LAST_ACTIVE: dict[int, datetime] = {}
_GENERAL_TTL_MINUTES = 10
_GENERAL_HISTORY_LIMIT = 6  # реплик пользователя; сообщений будет ×2

GENERAL_SYSTEM = (
    "Ты — Бишоп (BishopRB), AI-помощник команды Roastberry в Telegram.\n\n"
    "Roastberry — это:\n"
    "• обжарщик кофе из Перми (магазин, Mini App, 41 кофейня в крае)\n"
    "• поставщик кофейного оборудования (аренда, продажа)\n"
    "• сервисная служба (бот @rbr_service_bot, контракты Франко/Алеф/HoReCa)\n"
    "• Roastberry Academy (5 курсов: Любитель / Бариста / Профи / "
    "Владелец кофейни / Чай и авторские напитки)\n\n"
    "Команды Бишопа:\n"
    "• /service — ссылки на сервисный бот\n"
    "• /shop — поиск товаров и каталог\n"
    "• /price — посчитать цену, сделать КП\n"
    "• /мои_задачи — задачи, которые повешены на пользователя в чате @bishoprb\n"
    "• /digest — сводка по почте (только для владельца)\n"
    "• /что_ты_знаешь — полный список\n\n"
    "Стиль ответа: коротко (1-3 фразы), по делу, дружелюбно. Если запрос "
    "касается:\n"
    "  – сервиса/ремонта/мастера/поломки → подскажи команду /service\n"
    "  – магазина/курсов → /shop\n"
    "  – прайса/КП → /price\n"
    "  – задач команды → /мои_задачи\n"
    "Если общий вопрос про Roastberry — отвечай прямо.\n"
    "Если что-то совсем не по теме (политика, развлечения, общая болтовня) — "
    "вежливо скажи, что ты помощник по работе и предложи задать рабочий вопрос."
)


async def general_chat(
    text: str,
    user_id: int,
    is_owner: bool = False,
    timeout: float = 8.0,
) -> str:
    """Свободный диалог с Бишопом для запросов вне специализированных режимов.
    Помнит ~6 последних реплик в рамках 10-минутного окна."""
    if not text:
        return ""
    now = datetime.now(TZ).replace(tzinfo=None)
    last = _GENERAL_LAST_ACTIVE.get(user_id)
    # Сбрасываем историю если перерыв > TTL
    if last and (now - last) > timedelta(minutes=_GENERAL_TTL_MINUTES):
        _GENERAL_HISTORY.pop(user_id, None)

    history = _GENERAL_HISTORY.setdefault(user_id, [])
    history.append({"role": "user", "content": text[:1000]})
    # Обрезаем до последних 2*N сообщений (user + assistant)
    if len(history) > _GENERAL_HISTORY_LIMIT * 2:
        history[:] = history[-_GENERAL_HISTORY_LIMIT * 2:]

    system_blocks = [{"type": "text", "text": GENERAL_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    if is_owner:
        system_blocks.append({"type": "text", "text": "\n\nПользователь — Дмитрий, владелец Roastberry."})

    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                system=system_blocks,
                messages=history,
            ),
            timeout=timeout,
        )
        answer = response.content[0].text.strip()
        history.append({"role": "assistant", "content": answer})
        _GENERAL_LAST_ACTIVE[user_id] = now
        return answer
    except asyncio.TimeoutError:
        return "Что-то я задумался. Спроси ещё раз?"
    except Exception as e:
        log.error(f"general_chat failed: {e}")
        # Не показываем сырые API-ошибки пользователю.
        return ""
