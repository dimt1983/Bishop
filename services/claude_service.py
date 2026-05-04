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
import services.gmail_chat_tools as gmail_chat_tools
from utils import log

client = AsyncAnthropic(
    api_key=settings.anthropic_api_key,
    base_url=settings.anthropic_base_url,
)
TZ = ZoneInfo(settings.timezone)


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

    final_text, files = await _run_price_loop(history, tools, system, user_id)

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
                system=system,
                tools=tools,
                messages=history,
            )
        except Exception as e:
            log.error(f"price loop Anthropic call failed: {e}")
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

Тебе доступны:
— тулы магазина: shop_search, shop_get_product, shop_list_subcategories, shop_update_field, shop_set_photo_from_url, shop_set_photo_from_telegram, shop_add_product, shop_remove_product, shop_send_photo, shop_publish
— тулы кофейного прайса: price_show, price_calculate, price_add, price_remove (для добавления позиций ценообразования кофе)
— тулы общего ассортимента: assortment_show, assortment_search, assortment_calculate, assortment_coeffs (реестр всего ассортимента: молоко, сиропы, чай, наборы — из «прас для расчетов.xlsx»)
— файловые тулы: file_list, file_read, file_edit, file_write, file_run — прямой доступ к исходникам проекта (генераторы прайсов, шаблоны КП, тексты, скрипты). Дмитрий может править их через переписку.
— Яндекс.Диск + PDF: yadisk_list, yadisk_fetch, pdf_extract_pages — забирать файлы (фото, PDF-карточки, выгрузки) с Яндекс.Диска и вытаскивать страницы PDF как JPG. Корень Я.Диска — папка «Roastberry». Скачанные файлы лежат в /root/projects/ai-agents-rb/bishoprb-agent/workdir/.
— Gmail (только для владельца Дмитрия): gmail_list (последние письма), gmail_search (поиск по from/subject/snippet), gmail_digest (сводка с разбивкой по категориям), gmail_count_by_category (только числа). Категории: 🏦 банк, 💰 финансы, 💼 работа, 👨 личное, 🔔 уведомления, 📢 промо, 🚫 спам. Если Дмитрий спрашивает «что в почте?», «есть ли что от X?», «дай сводку», «сколько спама?» — используй эти тулы. Тела писем НЕ возвращаются — только метаданные. Не делай удалений / архиваций (этих инструментов пока нет).

Принципы работы:

1. ПОИСК ПЕРЕД ДЕЙСТВИЕМ. Если нужен tma_id товара и оно не дано явно — сначала вызывай shop_search.
2. ИЗМЕНЕНИЯ ТОЛЬКО ПОСЛЕ ПОДТВЕРЖДЕНИЯ. Если пользователь пишет «обнови цену», «обнови описание», «добавь товар» — сначала покажи что собираешься менять и спроси «подтвердить?». Действуй после «да/ок/верно».
3. ПОСЛЕ ПРАВОК — ОБЯЗАТЕЛЬНО ВЫЗОВИ shop_publish ОДИН РАЗ В КОНЦЕ СЕССИИ. Это пушит в GitHub и Railway передеплоит магазин через 2 минуты. Не вызывай его на каждое мелкое изменение — копи и публикуй пакетом.
4. ФОТО. Если пользователь говорит «вот фото / прислал фото / это фото товара» — он отправил картинку в сообщении. Используй shop_set_photo_from_telegram (фото лежит в pending state).
5. ОТПРАВКА ФОТО. Если просят «скинь/покажи/пришли фото товара» — вызывай shop_send_photo, фото отправится отдельным сообщением. Этот тул также полезен после shop_set_photo_*, чтобы убедиться что фото действительно прицепилось.
6. СВЯЗКА С ПРАЙСОМ. Если в этом же диалоге пользователь добавлял позицию в прайс через price_add (моносорт/микролот/смесь) — предложи добавить её и в магазин через shop_add_product. Бери цены 1кг и 200г из результата price_calculate / price_add. category="coffee", subcategory подбирается:
   - моносорт → "monosorta"
   - микролот Black Edition → "mikroloty_black_edition"
   - микролот Борщ Edition → "mikroloty_borshh_edition"
   - смесь/blend → "smesi"
7. КАТЕГОРИИ TMA: coffee/tea/syrup/milk. Подкатегории смотри через shop_list_subcategories.
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
    — file_run({"task": "price_export | rental_pdf | tea_catalog | assortment_export"}) — пересобрать чистовики после правок.
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

Безопасность:
— Не удаляй товар без явного «удали»
— Не меняй чужой прайс
— При неуверенности — спрашивай, а не угадывай
— Перед file_edit/file_write обязательно подтверждение от Дмитрия
"""


SHOP_SYSTEM_PROMPT_READONLY = """Ты помощник по магазину и прайсу Roastberry. Тебе доступны: shop_search, shop_get_product, shop_list_subcategories, shop_send_photo, assortment_show, assortment_search, assortment_send_catalog, assortment_send_pricelist, price_send_file.

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
            + list(gmail_chat_tools.TOOLS_OWNER)
        )
        system = SHOP_SYSTEM_PROMPT_OWNER
    else:
        tools = (
            list(shop_tools.TOOLS_READONLY)
            + list(assortment_tools.TOOLS_READONLY)
            + list(courses_tools.TOOLS_READONLY)
        )
        system = SHOP_SYSTEM_PROMPT_READONLY

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
                system=system,
                tools=tools,
                messages=history,
            )
        except Exception as e:
            log.error(f"shop loop Anthropic call failed: {e}")
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
                    elif tu.name.startswith("gmail_"):
                        # Gmail-tools нативно async (IMAP + Claude HTTP)
                        if log_user_id != settings.owner_telegram_id:
                            result = json.dumps({"status": "error",
                                                 "error": "gmail tools только для владельца"},
                                                ensure_ascii=False)
                        else:
                            result = await gmail_chat_tools.execute_tool_async(tu.name, tu.input)
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
                               "assortment_send_pricelist", "price_send_file"):
                    try:
                        parsed = json.loads(result)
                        if parsed.get("status") == "ready":
                            photos_to_send.append({
                                "path": parsed["path"],
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
