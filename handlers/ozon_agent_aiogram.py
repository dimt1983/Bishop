"""
OZON Agent Handler для aiogram
==============================
Обработчик команд для работы с OZON агентом.
Совместим с aiogram 3.x
"""

import logging
import asyncio
from datetime import datetime
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
