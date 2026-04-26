"""
OZON AI-Manager - МАКСИМАЛЬНЫЙ ФУНКЦИОНАЛ
==========================================
Полнофункциональный AI-помощник для управления магазином OZON
"""

import logging
import asyncio
import requests
import json
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command
from services.ozon_api_full import OzonAPIServiceFull
from services.claude_service_full import ClaudeServiceFull

logger = logging.getLogger(__name__)
ozon_router = Router()


# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

@ozon_router.message(Command("ozon_menu"))
async def show_main_menu(message: Message) -> None:
    """Главное меню AI-менеджера."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Аналитика", callback_data="menu_analytics"),
            InlineKeyboardButton(text="🛍️ Товары", callback_data="menu_products")
        ],
        [
            InlineKeyboardButton(text="💰 Цены", callback_data="menu_pricing"),
            InlineKeyboardButton(text="📝 Контент", callback_data="menu_content")
        ],
        [
            InlineKeyboardButton(text="🎯 SEO", callback_data="menu_seo"),
            InlineKeyboardButton(text="📸 Изображения", callback_data="menu_images")
        ],
        [
            InlineKeyboardButton(text="⭐ Отзывы", callback_data="menu_reviews"),
            InlineKeyboardButton(text="🔄 Автоматизация", callback_data="menu_automation")
        ],
        [
            InlineKeyboardButton(text="📈 Отчёты", callback_data="menu_reports"),
            InlineKeyboardButton(text="🏆 Конкуренты", callback_data="menu_competitors")
        ]
    ])
    
    text = """🤖 **OZON AI-Менеджер**

Ваш персональный помощник для управления магазином:

📊 **Аналитика** — глубокий анализ продаж и метрик
🛍️ **Товары** — управление карточками и характеристиками  
💰 **Цены** — ценовые стратегии и оптимизация
📝 **Контент** — генерация и оптимизация описаний
🎯 **SEO** — поисковая оптимизация
📸 **Изображения** — загрузка и оптимизация фото
⭐ **Отзывы** — автоматические ответы
🔄 **Автоматизация** — настройка правил
📈 **Отчёты** — детальная отчётность
🏆 **Конкуренты** — конкурентный анализ

Выберите раздел:"""
    
    await message.reply(text, parse_mode='Markdown', reply_markup=keyboard)


# ==================== МЕНЮ АНАЛИТИКИ ====================

@ozon_router.callback_query(F.data == "menu_analytics")
async def analytics_menu(callback: CallbackQuery) -> None:
    """Меню аналитики."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Полный анализ магазина", callback_data="full_store_analysis")],
        [InlineKeyboardButton(text="💰 Финансовая аналитика", callback_data="finance_analysis")],
        [InlineKeyboardButton(text="📦 Анализ остатков", callback_data="stock_analysis")],
        [InlineKeyboardButton(text="📈 Динамика продаж", callback_data="sales_dynamics")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(
        "📊 **Аналитический центр**\n\nВыберите тип анализа:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@ozon_router.callback_query(F.data == "full_store_analysis")
async def full_store_analysis(callback: CallbackQuery) -> None:
    """Полный анализ магазина."""
    await callback.answer()
    await callback.message.edit_text("🔄 Провожу полный анализ магазина...")
    
    try:
        ozon_service = OzonAPIServiceFull()
        claude_service = ClaudeServiceFull()
        
        # Получаем данные за последние 30 дней
        analysis_data = ozon_service.get_full_store_analysis(days=30)
        
        # Анализируем через Claude
        analysis_prompt = """Проведи комплексный анализ интернет-магазина на OZON и дай стратегические рекомендации:

АНАЛИЗИРУЙ:
1. Общие показатели эффективности
2. Товарную линейку и ассортимент  
3. Финансовые метрики
4. Проблемные зоны
5. Возможности роста

ДАЙ РЕКОМЕНДАЦИИ:
- Срочные действия (что делать сейчас)
- Тактические шаги (1-3 месяца)
- Стратегические направления (3+ месяца)

Структурированный отчёт для владельца бизнеса."""
        
        analysis_text = claude_service.call_claude(
            analysis_prompt,
            f"Данные магазина:\n{json.dumps(analysis_data, ensure_ascii=False, indent=2)}",
            "claude-opus-4-7"
        )
        
        # Разбиваем длинный текст на части если нужно
        if len(analysis_text) > 4000:
            parts = [analysis_text[i:i+4000] for i in range(0, len(analysis_text), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    await callback.message.edit_text(f"📊 **Анализ магазина (часть {i+1}):**\n\n{part}", parse_mode='Markdown')
                else:
                    await callback.message.reply(f"📊 **Анализ магазина (часть {i+1}):**\n\n{part}", parse_mode='Markdown')
        else:
            await callback.message.edit_text(f"📊 **Анализ магазина:**\n\n{analysis_text}", parse_mode='Markdown')
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка анализа: {str(e)}")


# ==================== МЕНЮ ТОВАРОВ ====================

@ozon_router.callback_query(F.data == "menu_products")
async def products_menu(callback: CallbackQuery) -> None:
    """Меню управления товарами."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Анализ карточки товара", callback_data="analyze_product")],
        [InlineKeyboardButton(text="✏️ Оптимизация названий", callback_data="optimize_titles")],
        [InlineKeyboardButton(text="📝 Генерация описаний", callback_data="generate_descriptions")],
        [InlineKeyboardButton(text="📊 Топ товары", callback_data="top_products")],
        [InlineKeyboardButton(text="⚠️ Проблемные товары", callback_data="problem_products")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(
        "🛍️ **Управление товарами**\n\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@ozon_router.message(Command("analyze_product"))
async def analyze_product_command(message: Message) -> None:
    """Анализ конкретного товара."""
    # Извлекаем ID товара из команды
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply(
            "Использование: `/analyze_product <product_id>`\n"
            "Пример: `/analyze_product 123456789`",
            parse_mode='Markdown'
        )
        return
    
    product_id = parts[1]
    await message.reply(f"🔍 Анализирую товар {product_id}...")
    
    try:
        ozon_service = OzonAPIServiceFull()
        claude_service = ClaudeServiceFull()
        
        # Получаем информацию о товаре
        product_info = ozon_service.get_product_info(product_id=int(product_id))
        
        # Анализируем через Claude
        analysis = claude_service.analyze_product_card(product_info)
        
        await message.reply(f"📋 **Анализ товара {product_id}:**\n\n{analysis}", parse_mode='Markdown')
        
    except Exception as e:
        await message.reply(f"❌ Ошибка анализа товара: {str(e)}")


# ==================== МЕНЮ ЦЕН ====================

@ozon_router.callback_query(F.data == "menu_pricing")
async def pricing_menu(callback: CallbackQuery) -> None:
    """Меню управления ценами."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Анализ ценовой стратегии", callback_data="pricing_analysis")],
        [InlineKeyboardButton(text="🔄 Динамическое ценообразование", callback_data="dynamic_pricing")],
        [InlineKeyboardButton(text="🏷️ Массовое обновление цен", callback_data="bulk_price_update")],
        [InlineKeyboardButton(text="📊 Конкурентные цены", callback_data="competitor_prices")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(
        "💰 **Управление ценами**\n\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@ozon_router.message(Command("update_price"))
async def update_price_command(message: Message) -> None:
    """Обновление цены товара."""
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply(
            "Использование: `/update_price <offer_id> <новая_цена>`\n"
            "Пример: `/update_price SKU-123 1500`",
            parse_mode='Markdown'
        )
        return
    
    offer_id = parts[1]
    new_price = float(parts[2])
    
    try:
        ozon_service = OzonAPIServiceFull()
        
        # Обновляем цену
        result = ozon_service.update_product_prices([{
            "offer_id": offer_id,
            "price": str(new_price),
            "old_price": "",
            "premium_price": "",
            "currency_code": "RUB"
        }])
        
        await message.reply(f"✅ Цена товара {offer_id} обновлена на {new_price} ₽")
        
    except Exception as e:
        await message.reply(f"❌ Ошибка обновления цены: {str(e)}")


# ==================== РАБОТА С ИЗОБРАЖЕНИЯМИ ====================

@ozon_router.callback_query(F.data == "menu_images")
async def images_menu(callback: CallbackQuery) -> None:
    """Меню работы с изображениями."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить изображение", callback_data="upload_image")],
        [InlineKeyboardButton(text="🖼️ Добавить фото к товару", callback_data="add_image_to_product")],
        [InlineKeyboardButton(text="✨ Оптимизировать изображения", callback_data="optimize_images")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(
        "📸 **Управление изображениями**\n\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@ozon_router.message(Command("upload_image"))
async def upload_image_command(message: Message) -> None:
    """Загрузка изображения."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "Использование: `/upload_image <URL_изображения>`\n"
            "Пример: `/upload_image https://example.com/image.jpg`",
            parse_mode='Markdown'
        )
        return
    
    image_url = parts[1]
    await message.reply("📤 Загружаю изображение...")
    
    try:
        ozon_service = OzonAPIServiceFull()
        
        # Загружаем изображение в OZON
        uploaded_url = ozon_service.upload_image(image_url=image_url)
        
        await message.reply(f"✅ Изображение загружено!\nURL: {uploaded_url}")
        
    except Exception as e:
        await message.reply(f"❌ Ошибка загрузки изображения: {str(e)}")


# ==================== ОТЗЫВЫ ====================

@ozon_router.callback_query(F.data == "menu_reviews")
async def reviews_menu(callback: CallbackQuery) -> None:
    """Меню работы с отзывами."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Обработать новые отзывы", callback_data="process_new_reviews")],
        [InlineKeyboardButton(text="⭐ Статистика отзывов", callback_data="reviews_stats")],
        [InlineKeyboardButton(text="🤖 Автоответы", callback_data="auto_replies")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(
        "⭐ **Управление отзывами**\n\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@ozon_router.callback_query(F.data == "process_new_reviews")
async def process_new_reviews(callback: CallbackQuery) -> None:
    """Обработка новых отзывов."""
    await callback.answer()
    await callback.message.edit_text("🔄 Получаю новые отзывы...")
    
    try:
        ozon_service = OzonAPIServiceFull()
        claude_service = ClaudeServiceFull()
        
        # Получаем неотвеченные отзывы
        reviews_data = ozon_service.get_reviews(status="UNPROCESSED")
        reviews = reviews_data.get("reviews", [])
        
        if not reviews:
            await callback.message.edit_text("✅ Новых отзывов для обработки нет")
            return
        
        # Обрабатываем первые 3 отзыва
        processed_reviews = []
        for review in reviews[:3]:
            response_text = claude_service.call_claude(
                "Ты — менеджер по работе с клиентами. Напиши профессиональный ответ на отзыв. Будь вежлив, благодари за обратную связь, предложи решение если есть проблема.",
                f"Отзыв: {review.get('text', '')}\nОценка: {review.get('rating', 0)}/5"
            )
            
            processed_reviews.append({
                "id": review.get("id"),
                "text": review.get("text", "")[:100] + "...",
                "rating": review.get("rating", 0),
                "response": response_text
            })
        
        # Формируем сообщение
        text = "📝 **Предложенные ответы на отзывы:**\n\n"
        for i, review in enumerate(processed_reviews, 1):
            text += f"**{i}. Отзыв ({review['rating']}/5):**\n{review['text']}\n\n"
            text += f"**Предлагаемый ответ:**\n{review['response']}\n\n---\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Опубликовать ответы", callback_data=f"publish_reviews_{','.join([r['id'] for r in processed_reviews])}")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="menu_reviews")]
        ])
        
        # Разбиваем длинное сообщение если нужно
        if len(text) > 4000:
            await callback.message.edit_text(text[:4000] + "\n\n...", parse_mode='Markdown')
            await callback.message.reply(text[4000:], parse_mode='Markdown', reply_markup=keyboard)
        else:
            await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка обработки отзывов: {str(e)}")


# ==================== АВТОМАТИЗАЦИЯ ====================

@ozon_router.callback_query(F.data == "menu_automation")
async def automation_menu(callback: CallbackQuery) -> None:
    """Меню автоматизации."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Создать правила автоматизации", callback_data="create_automation")],
        [InlineKeyboardButton(text="📋 Текущие правила", callback_data="current_rules")],
        [InlineKeyboardButton(text="⚙️ Настройки мониторинга", callback_data="monitoring_settings")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_main")]
    ])
    
    await callback.message.edit_text(
        "🔄 **Автоматизация процессов**\n\nВыберите действие:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


# ==================== ВОЗВРАТ В ГЛАВНОЕ МЕНЮ ====================

@ozon_router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    await show_main_menu(callback.message)


# ==================== КОМАНДЫ БЫСТРОГО ДОСТУПА ====================

@ozon_router.message(Command("quick_report"))
async def quick_report_command(message: Message) -> None:
    """Быстрая сводка."""
    await message.reply("📊 Генерирую быструю сводку...")
    
    try:
        ozon_service = OzonAPIServiceFull()
        claude_service = ClaudeServiceFull()
        
        # Получаем данные за 7 дней
        analysis_data = ozon_service.get_full_store_analysis(days=7)
        
        # Генерируем краткую сводку
        summary = claude_service.call_claude(
            "Создай краткую еженедельную сводку для интернет-магазина. Выдели ключевые метрики, проблемы и возможности. Максимум 1000 символов.",
            f"Данные за неделю:\n{json.dumps(analysis_data, ensure_ascii=False)}"
        )
        
        await message.reply(f"📊 **Недельная сводка:**\n\n{summary}", parse_mode='Markdown')
        
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")


@ozon_router.message(Command("ozon_help"))
async def help_command(message: Message) -> None:
    """Справка по командам."""
    help_text = """🤖 **OZON AI-Менеджер - Справка**

**Основные команды:**
• `/ozon_menu` — главное меню со всеми функциями
• `/quick_report` — быстрая сводка за неделю
• `/analyze_product <ID>` — анализ товара
• `/update_price <SKU> <цена>` — обновить цену
• `/upload_image <URL>` — загрузить изображение

**Аналитические команды:**
• `/ozon_report` — детальная сводка за вчера  
• `/ozon_stats` — статистика продаж
• `/ozon_debug` — диагностика API
• `/ozon_today` — заказы за сегодня

**Возможности AI-менеджера:**
📊 Глубокая аналитика и отчёты
🛍️ Анализ и оптимизация товаров
💰 Управление ценами и стратегиями
📝 Генерация продающих описаний
🎯 SEO-оптимизация карточек
📸 Загрузка и обработка изображений
⭐ Автоматические ответы на отзывы
🔄 Правила автоматизации
🏆 Конкурентный анализ

Начните с команды `/ozon_menu` для доступа ко всем функциям!"""
    
    await message.reply(help_text, parse_mode='Markdown')


# ==================== ДОПОЛНИТЕЛЬНЫЕ УТИЛИТЫ ====================

async def send_daily_summary_to_chat(bot, chat_id: str) -> None:
    """Отправить утреннюю сводку в чат."""
    try:
        ozon_service = OzonAPIServiceFull()
        claude_service = ClaudeServiceFull()
        
        # Получаем полный анализ за день
        daily_data = ozon_service.get_full_store_analysis(days=1)
        
        # Генерируем развёрнутую сводку
        summary = claude_service.call_claude(
            "Создай подробную утреннюю сводку для владельца интернет-магазина. Включи ключевые метрики, анализ проблем, рекомендации на день. Профессиональный стиль.",
            f"Данные за вчера:\n{json.dumps(daily_data, ensure_ascii=False, indent=2)}"
        )
        
        # Отправляем с кнопкой быстрых действий
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Подробный анализ", callback_data="full_store_analysis")],
            [InlineKeyboardButton(text="⚙️ Открыть меню", callback_data="back_to_main")]
        ])
        
        await bot.send_message(
            chat_id=chat_id,
            text=f"🌅 **Утренняя сводка:**\n\n{summary}",
            parse_mode='Markdown',
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        
        logger.info(f"Daily summary sent to chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в send_daily_summary_to_chat: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Ошибка генерации утренней сводки: {str(e)}"
        )
