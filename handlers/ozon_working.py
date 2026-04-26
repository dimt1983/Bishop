"""
OZON Agent - полностью автономный
==================================
"""

import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command

logger = logging.getLogger(__name__)

# Router для OZON команд
ozon_simple_router = Router()


class SimpleOzonAPI:
    def __init__(self):
        self.client_id = os.getenv("OZON_CLIENT_ID")
        self.api_key = os.getenv("OZON_API_KEY")
        self.base_url = "https://api-seller.ozon.ru"
        
        if not self.client_id or not self.api_key:
            raise ValueError("OZON_CLIENT_ID и OZON_API_KEY должны быть установлены")
        
        self.headers = {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
    
    def get_yesterday_range(self):
        """Получить диапазон дат для вчерашнего дня."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yesterday.replace(hour=23, minute=59, second=59, microsecond=0)
        return start.isoformat(), end.isoformat()
    
    def fetch_orders(self):
        """Получить заказы за вчера."""
        since, to = self.get_yesterday_range()
        url = f"{self.base_url}/v2/posting/fbs/list"
        
        payload = {
            "dir": "ASC",
            "filter": {"since": since, "to": to, "status": ""},
            "limit": 100,
            "offset": 0
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("result", {}).get("postings", [])
        except Exception as e:
            logger.error(f"Ошибка получения заказов: {e}")
            return []
    
    def aggregate_metrics(self, orders):
        """Агрегировать метрики заказов."""
        total_orders = len(orders)
        total_revenue = 0
        total_items = 0
        cancelled = 0
        
        for order in orders:
            if order.get("status") == "cancelled":
                cancelled += 1
                continue
            
            # Подсчитываем товары и выручку
            products = order.get("products", [])
            for product in products:
                quantity = product.get("quantity", 0)
                price = float(product.get("price", 0))
                total_items += quantity
                total_revenue += quantity * price
        
        return {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "total_items": total_items,
            "cancelled": cancelled,
            "avg_order_value": total_revenue / max(total_orders - cancelled, 1)
        }


@ozon_simple_router.message(Command("ozon_simple"))
async def ozon_simple_command(message: Message) -> None:
    """Простое меню OZON."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="simple_stats"),
            InlineKeyboardButton(text="📦 Заказы", callback_data="simple_orders")
        ],
        [
            InlineKeyboardButton(text="🔍 Тест API", callback_data="simple_test")
        ]
    ])
    
    text = """🤖 **Простой OZON Агент**

📊 Доступные функции:
• Статистика за вчера
• Список заказов  
• Тест API подключения

Выберите действие:"""
    
    await message.reply(text, parse_mode='Markdown', reply_markup=keyboard)


@ozon_simple_router.callback_query(F.data == "simple_stats")
async def simple_stats_callback(callback: CallbackQuery) -> None:
    """Простая статистика."""
    await callback.answer()
    await callback.message.edit_text("📊 Получаю статистику...")
    
    try:
        ozon_api = SimpleOzonAPI()
        orders = ozon_api.fetch_orders()
        metrics = ozon_api.aggregate_metrics(orders)
        
        text = f"""📊 **Статистика за вчера:**

🛒 Заказов: {metrics['total_orders']}
💰 Выручка: {metrics['total_revenue']:,.2f} ₽
📦 Товаров: {metrics['total_items']}
❌ Отмен: {metrics['cancelled']}
💵 Средний чек: {metrics['avg_order_value']:,.2f} ₽

⏰ Обновлено: {datetime.now().strftime('%H:%M:%S')}"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Обновить", callback_data="simple_stats"),
            InlineKeyboardButton(text="◀️ Назад", callback_data="simple_back")
        ]])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")


@ozon_simple_router.callback_query(F.data == "simple_orders")
async def simple_orders_callback(callback: CallbackQuery) -> None:
    """Список заказов."""
    await callback.answer()
    await callback.message.edit_text("📦 Получаю заказы...")
    
    try:
        ozon_api = SimpleOzonAPI()
        orders = ozon_api.fetch_orders()
        
        if not orders:
            text = "📦 Заказов за вчера не найдено"
        else:
            text = f"📦 **Заказы за вчера ({len(orders)}):**\n\n"
            
            for i, order in enumerate(orders[:5], 1):  # Показываем первые 5
                posting_number = order.get("posting_number", "N/A")
                status = order.get("status", "N/A")
                created = order.get("created_at", "")[:10]  # Дата без времени
                
                text += f"{i}. `{posting_number}`\n"
                text += f"   Статус: {status}\n"
                text += f"   Дата: {created}\n\n"
            
            if len(orders) > 5:
                text += f"... и ещё {len(orders) - 5} заказов"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Обновить", callback_data="simple_orders"),
            InlineKeyboardButton(text="◀️ Назад", callback_data="simple_back")
        ]])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")


@ozon_simple_router.callback_query(F.data == "simple_test")
async def simple_test_callback(callback: CallbackQuery) -> None:
    """Тест API."""
    await callback.answer()
    await callback.message.edit_text("🔍 Тестирую API...")
    
    try:
        ozon_api = SimpleOzonAPI()
        
        # Простой тест - получаем 1 заказ
        url = f"{ozon_api.base_url}/v2/posting/fbs/list"
        payload = {
            "dir": "ASC",
            "filter": {"since": "2024-04-01T00:00:00Z", "to": "2024-04-26T23:59:59Z"},
            "limit": 1,
            "offset": 0
        }
        
        response = requests.post(url, headers=ozon_api.headers, json=payload, timeout=10)
        
        text = f"""🔍 **Тест API:**

📡 **Подключение:** {'✅ Успешно' if response.status_code == 200 else f'❌ Ошибка {response.status_code}'}
🔑 **Client-Id:** {ozon_api.client_id[:8]}...
⏰ **Время ответа:** {response.elapsed.total_seconds():.1f}с

"""
        
        if response.status_code == 200:
            data = response.json()
            orders_count = len(data.get("result", {}).get("postings", []))
            text += f"📊 **Доступ к данным:** ✅ ({orders_count} заказов в тесте)"
        else:
            text += f"📊 **Ошибка:** {response.text[:100]}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Повторить", callback_data="simple_test"),
            InlineKeyboardButton(text="◀️ Назад", callback_data="simple_back")
        ]])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка тестирования: {str(e)}")


@ozon_simple_router.callback_query(F.data == "simple_back")
async def simple_back_callback(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    await callback.answer()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="simple_stats"),
            InlineKeyboardButton(text="📦 Заказы", callback_data="simple_orders")
        ],
        [
            InlineKeyboardButton(text="🔍 Тест API", callback_data="simple_test")
        ]
    ])
    
    text = """🤖 **Простой OZON Агент**

📊 Доступные функции:
• Статистика за вчера
• Список заказов  
• Тест API подключения

Выберите действие:"""
    
    await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)


# Экспорт
__all__ = ['ozon_simple_router']
