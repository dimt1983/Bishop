"""
OZON Agent Handler для aiogram
==============================
Обработчик команд для работы с OZON агентом.
Совместим с aiogram 3.x
"""

import logging
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from services.ozon_api import OzonAPIService
from services.claude_service import ClaudeService

logger = logging.getLogger(__name__)

# Создаём router для OZON команд
ozon_router = Router()


@ozon_router.message(Command("ozon_report"))
async def ozon_report_command(message: Message) -> None:
    """Команда /ozon_report - получить сводку вручную."""
    try:
        await message.reply("🔄 Собираю данные из OZON...")
        
        # Получаем данные из OZON
        ozon_service = OzonAPIService()
        daily_data = ozon_service.get_daily_summary()
        
        # Генерируем сводку через Claude
        claude_service = ClaudeService()
        summary = claude_service.generate_daily_summary(daily_data)
        
        # Отправляем сводку
        await message.reply(
            summary,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        # Если есть новые отзывы, предлагаем обработать
        if daily_data["reviews"]["total"] > 0:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="📝 Обработать отзывы", 
                    callback_data="process_reviews"
                )
            ]])
            await message.reply(
                f"Найдено {daily_data['reviews']['total']} новых отзывов. Обработать?",
                reply_markup=keyboard
            )
    
    except Exception as e:
        logger.error(f"Ошибка в ozon_report_command: {e}")
        await message.reply(f"❌ Ошибка: {str(e)}")


@ozon_router.message(Command("ozon_stats"))
async def ozon_stats_command(message: Message) -> None:
    """Команда /ozon_stats - быстрая статистика."""
    try:
        ozon_service = OzonAPIService()
        
        # Получаем только метрики заказов
        orders = ozon_service.fetch_orders()
        metrics = ozon_service.aggregate_metrics(orders)
        
        text = f"📊 *Быстрая статистика за вчера:*\n\n"
        text += f"🛒 Заказов: {metrics['total_orders']}\n"
        text += f"💰 Выручка: {metrics['total_revenue']:,.2f} ₽\n"
        text += f"📦 Товаров продано: {metrics['total_items']}\n"
        text += f"❌ Отмен: {metrics['cancelled']}\n\n"
        
        if metrics['top_5_skus']:
            text += "*🏆 Топ-5 товаров:*\n"
            for sku, qty in metrics['top_5_skus']:
                text += f"• {sku}: {qty} шт.\n"
        
        await message.reply(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в ozon_stats_command: {e}")
        await message.reply(f"❌ Ошибка: {str(e)}")


@ozon_router.callback_query(F.data == "process_reviews")
async def process_reviews_callback(callback: CallbackQuery) -> None:
    """Обработка callback для обработки отзывов."""
    await callback.answer()
    
    try:
        await callback.message.edit_text("🔄 Обрабатываю отзывы...")
        
        ozon_service = OzonAPIService()
        claude_service = ClaudeService()
        
        reviews = ozon_service.fetch_reviews()
        if not reviews:
            await callback.message.edit_text("✅ Новых отзывов не найдено")
            return
        
        processed = []
        for review in reviews[:3]:  # Обрабатываем только первые 3 для примера
            response = claude_service.generate_review_response(
                review.get("text", ""),
                review.get("rating", 5),
                review.get("product", {}).get("name", "")
            )
            
            processed.append({
                "review_id": review.get("id"),
                "rating": review.get("rating"),
                "text": review.get("text", "")[:100] + "...",
                "response": response
            })
        
        # Формируем сообщение с предложенными ответами
        text = "📝 *Предлагаемые ответы на отзывы:*\n\n"
        for i, item in enumerate(processed, 1):
            text += f"*{i}. Отзыв ({item['rating']}/5):*\n"
            text += f"_{item['text']}_\n\n"
            text += f"*Предлагаемый ответ:*\n{item['response']}\n\n"
            text += "---\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Одобрить", callback_data="approve_responses"),
            InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_reviews")
        ]])
        
        await callback.message.edit_text(
            text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Ошибка в process_reviews_callback: {e}")
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")


@ozon_router.callback_query(F.data == "approve_responses")
async def approve_responses_callback(callback: CallbackQuery) -> None:
    """Одобрение ответов на отзывы."""
    await callback.answer()
    
    await callback.message.edit_text(
        "✅ Ответы одобрены.\n\n"
        "_Автоматическая публикация будет добавлена в следующей версии._"
    )


@ozon_router.callback_query(F.data == "cancel_reviews")
async def cancel_reviews_callback(callback: CallbackQuery) -> None:
    """Отмена обработки отзывов."""
    await callback.answer()
    await callback.message.edit_text("❌ Обработка отзывов отменена")


async def send_daily_summary_to_chat(bot, chat_id: str) -> None:
    """Отправить утреннюю сводку в чат."""
    try:
        # Получаем данные и генерируем сводку
        ozon_service = OzonAPIService()
        daily_data = ozon_service.get_daily_summary()
        
        claude_service = ClaudeService()
        summary = claude_service.generate_daily_summary(daily_data)
        
        # Отправляем в чат
        await bot.send_message(
            chat_id=chat_id,
            text=summary,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        logger.info(f"Daily summary sent to chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в send_daily_summary_to_chat: {e}")


@ozon_router.message(Command("ozon_debug"))
async def ozon_debug_command(message: Message) -> None:
    """Диагностика OZON API - проверка данных."""
    try:
        await message.reply("🔍 Диагностирую OZON API...")
        
        ozon_service = OzonAPIService()
        
        # Получаем диапазон дат
        since, to = ozon_service.get_yesterday_range()
        
        debug_info = f"🔍 *Диагностика OZON API*\n\n"
        debug_info += f"📅 Ищу заказы в диапазоне:\n"
        debug_info += f"С: `{since}`\n"
        debug_info += f"До: `{to}`\n\n"
        
        # Пробуем разные endpoint'ы
        endpoints_to_try = [
            ("v2/posting/fbs/list", "FBS v2"),
            ("v3/posting/fbs/list", "FBS v3"),
            ("v2/posting/fbo/list", "FBO v2"),
            ("v1/posting/fbs/list", "FBS v1")
        ]
        
        for endpoint, description in endpoints_to_try:
            try:
                url = f"{ozon_service.base_url}/{endpoint}"
                payload = {
                    "dir": "ASC",
                    "filter": {"since": since, "to": to, "status": ""},
                    "limit": 10,
                    "offset": 0,
                    "with": {"analytics_data": True, "financial_data": True},
                }
                
                response = requests.post(url, headers=ozon_service.headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    postings = data.get("result", {}).get("postings", [])
                    debug_info += f"✅ {description}: {len(postings)} заказов\n"
                    
                    if postings:
                        # Показываем первый заказ
                        first_order = postings[0]
                        debug_info += f"   Пример: {first_order.get('posting_number', 'N/A')} - {first_order.get('status', 'N/A')}\n"
                else:
                    debug_info += f"❌ {description}: HTTP {response.status_code}\n"
                    
            except Exception as e:
                debug_info += f"❌ {description}: {str(e)[:50]}...\n"
        
        # Проверяем заказы за последние 3 дня
        debug_info += f"\n📊 *Заказы за последние дни:*\n"
        
        for days_ago in range(3):
            try:
                now = datetime.now(timezone.utc)
                target_day = now - timedelta(days=days_ago)
                start = target_day.replace(hour=0, minute=0, second=0, microsecond=0)
                end = target_day.replace(hour=23, minute=59, second=59, microsecond=0)
                
                url = f"{ozon_service.base_url}/v2/posting/fbs/list"
                payload = {
                    "dir": "ASC",
                    "filter": {"since": start.isoformat(), "to": end.isoformat(), "status": ""},
                    "limit": 100,
                    "offset": 0
                }
                
                response = requests.post(url, headers=ozon_service.headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    count = len(data.get("result", {}).get("postings", []))
                    day_name = "Сегодня" if days_ago == 0 else f"{days_ago} дня назад"
                    debug_info += f"• {day_name}: {count} заказов\n"
                    
            except Exception as e:
                debug_info += f"• Ошибка для {days_ago} дня назад: {str(e)}\n"
        
        await message.reply(debug_info, parse_mode='Markdown')
        
    except Exception as e:
        await message.reply(f"❌ Ошибка диагностики: {str(e)}")


@ozon_router.message(Command("ozon_today"))
async def ozon_today_command(message: Message) -> None:
    """Получить заказы за сегодня."""
    try:
        await message.reply("🔄 Получаю заказы за сегодня...")
        
        ozon_service = OzonAPIService()
        
        # Сегодняшний день
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
        
        url = f"{ozon_service.base_url}/v2/posting/fbs/list"
        payload = {
            "dir": "ASC",
            "filter": {"since": start.isoformat(), "to": end.isoformat(), "status": ""},
            "limit": 100,
            "offset": 0,
            "with": {"analytics_data": True, "financial_data": True},
        }
        
        response = requests.post(url, headers=ozon_service.headers, json=payload, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        orders = data.get("result", {}).get("postings", [])
        
        if not orders:
            await message.reply("📊 За сегодня заказов пока нет")
            return
        
        metrics = ozon_service.aggregate_metrics(orders)
        
        text = f"📊 *Заказы за сегодня:*\n\n"
        text += f"🛒 Заказов: {metrics['total_orders']}\n"
        text += f"💰 Выручка: {metrics['total_revenue']:,.2f} ₽\n"
        text += f"📦 Товаров: {metrics['total_items']}\n"
        text += f"❌ Отмен: {metrics['cancelled']}\n\n"
        
        if metrics['top_5_skus']:
            text += "*🏆 Топ товары сегодня:*\n"
            for sku, qty in metrics['top_5_skus'][:3]:
                text += f"• {sku}: {qty} шт.\n"
        
        await message.reply(text, parse_mode='Markdown')
        
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")
