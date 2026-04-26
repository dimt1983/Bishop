"""
OZON Agent Handler
==================
Обработчик команд для работы с OZON агентом.
Интегрируется в существующий Telegram бот.
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from services.ozon_api import OzonAPIService
from services.claude_service import ClaudeService

logger = logging.getLogger(__name__)


async def ozon_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /ozon_report - получить сводку вручную."""
    try:
        await update.message.reply_text("🔄 Собираю данные из OZON...")
        
        # Получаем данные из OZON
        ozon_service = OzonAPIService()
        daily_data = ozon_service.get_daily_summary()
        
        # Генерируем сводку через Claude
        claude_service = ClaudeService()
        summary = claude_service.generate_daily_summary(daily_data)
        
        # Отправляем сводку
        await update.message.reply_text(
            summary,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        # Если есть новые отзывы, предлагаем обработать
        if daily_data["reviews"]["total"] > 0:
            keyboard = [[
                InlineKeyboardButton("📝 Обработать отзывы", callback_data="process_reviews")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Найдено {daily_data['reviews']['total']} новых отзывов. Обработать?",
                reply_markup=reply_markup
            )
    
    except Exception as e:
        logger.error(f"Ошибка в ozon_report_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def process_reviews_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка callback для обработки отзывов."""
    query = update.callback_query
    await query.answer()
    
    try:
        await query.edit_message_text("🔄 Обрабатываю отзывы...")
        
        ozon_service = OzonAPIService()
        claude_service = ClaudeService()
        
        reviews = ozon_service.fetch_reviews()
        if not reviews:
            await query.edit_message_text("✅ Новых отзывов не найдено")
            return
        
        processed = []
        for review in reviews[:5]:  # Обрабатываем только первые 5
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
        message = "📝 *Предлагаемые ответы на отзывы:*\n\n"
        for i, item in enumerate(processed, 1):
            message += f"*{i}. Отзыв ({item['rating']}/5):*\n"
            message += f"_{item['text']}_\n\n"
            message += f"*Предлагаемый ответ:*\n{item['response']}\n\n"
            message += "---\n\n"
        
        keyboard = [[
            InlineKeyboardButton("✅ Опубликовать все", callback_data="publish_all_responses"),
            InlineKeyboardButton("❌ Отменить", callback_data="cancel_reviews")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Сохраняем обработанные отзывы в контексте
        context.user_data['processed_reviews'] = processed
        
    except Exception as e:
        logger.error(f"Ошибка в process_reviews_callback: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")


async def publish_responses_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Публикация ответов на отзывы в OZON."""
    query = update.callback_query
    await query.answer()
    
    # Здесь должна быть логика публикации ответов в OZON
    # Пока просто подтверждаем
    await query.edit_message_text(
        "✅ Ответы подготовлены к публикации.\n\n"
        "_Примечание: Автоматическая публикация ответов будет добавлена в следующей версии._"
    )
    
    # Очищаем данные из контекста
    context.user_data.pop('processed_reviews', None)


async def cancel_reviews_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена обработки отзывов."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("❌ Обработка отзывов отменена")
    context.user_data.pop('processed_reviews', None)


async def ozon_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /ozon_stats - быстрая статистика."""
    try:
        ozon_service = OzonAPIService()
        
        # Получаем только метрики заказов
        orders = ozon_service.fetch_orders()
        metrics = ozon_service.aggregate_metrics(orders)
        
        message = f"📊 *Быстрая статистика за вчера:*\n\n"
        message += f"🛒 Заказов: {metrics['total_orders']}\n"
        message += f"💰 Выручка: {metrics['total_revenue']:,.2f} ₽\n"
        message += f"📦 Товаров продано: {metrics['total_items']}\n"
        message += f"❌ Отмен: {metrics['cancelled']}\n\n"
        
        if metrics['top_5_skus']:
            message += "*🏆 Топ-5 товаров:*\n"
            for sku, qty in metrics['top_5_skus']:
                message += f"• {sku}: {qty} шт.\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в ozon_stats_command: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def send_daily_summary_to_chat(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить утреннюю сводку в чат (для cron)."""
    try:
        chat_id = context.job.data.get('chat_id')
        if not chat_id:
            logger.error("Chat ID не задан для daily summary")
            return
        
        # Получаем данные и генерируем сводку
        ozon_service = OzonAPIService()
        daily_data = ozon_service.get_daily_summary()
        
        claude_service = ClaudeService()
        summary = claude_service.generate_daily_summary(daily_data)
        
        # Отправляем в чат
        await context.bot.send_message(
            chat_id=chat_id,
            text=summary,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        logger.info(f"Daily summary sent to chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Ошибка в send_daily_summary_to_chat: {e}")


# Обработчики для регистрации в main.py
ozon_handlers = [
    CommandHandler("ozon_report", ozon_report_command),
    CommandHandler("ozon_stats", ozon_stats_command),
    CallbackQueryHandler(process_reviews_callback, pattern="^process_reviews$"),
    CallbackQueryHandler(publish_responses_callback, pattern="^publish_all_responses$"),
    CallbackQueryHandler(cancel_reviews_callback, pattern="^cancel_reviews$"),
]
