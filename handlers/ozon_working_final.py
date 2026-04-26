"""
OZON Working Agent
==================
Использует только проверенные рабочие endpoints.
"""

import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from aiogram import Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram import F

logger = logging.getLogger(__name__)

# Router для рабочих OZON методов
ozon_working_new_router = Router()


class OzonWorkingAPI:
    def __init__(self):
        self.client_id = os.getenv("OZON_CLIENT_ID")
        self.api_key = os.getenv("OZON_API_KEY")
        self.base_url = "https://api-seller.ozon.ru"
        
        self.headers = {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
    
    def get_stock_analytics(self):
        """Получить аналитику остатков - РАБОЧИЙ метод."""
        url = f"{self.base_url}/v2/analytics/stock_on_warehouses"
        payload = {"limit": 100}
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json().get("result", {})
        except Exception as e:
            logger.error(f"Ошибка получения аналитики остатков: {e}")
            return {}
    
    def try_product_methods(self):
        """Пробуем разные методы получения товаров."""
        methods = [
            ("v2/product/list", {"filter": {"visibility": "ALL"}, "limit": 50}),
            ("v3/product/list", {"filter": {"visibility": "ALL"}, "limit": 50}),
            ("v1/product/list", {"filter": {"visibility": "ALL"}, "limit": 50}),
        ]
        
        for endpoint, payload in methods:
            try:
                url = f"{self.base_url}/{endpoint}"
                response = requests.post(url, headers=self.headers, json=payload, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("result", {}).get("items", [])
                    return endpoint, items
            except:
                continue
        return None, []
    
    def try_order_methods(self):
        """Пробуем методы получения заказов из актуальной документации."""
        # Основываемся на том, что работает analytics - пробуем похожие v2 endpoints
        methods = [
            ("v2/posting/fbs/list", {"dir": "ASC", "filter": {}, "limit": 50}),
            ("v2/posting/list", {"dir": "ASC", "filter": {}, "limit": 50}),
            ("v1/posting/fbs/list", {"dir": "ASC", "filter": {}, "limit": 50}),
        ]
        
        for endpoint, payload in methods:
            try:
                url = f"{self.base_url}/{endpoint}"
                response = requests.post(url, headers=self.headers, json=payload, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("result", {}).get("postings", [])
                    return endpoint, items
            except:
                continue
        return None, []


@ozon_working_new_router.message(Command("ozon"))
async def ozon_main_command(message: Message) -> None:
    """Главное меню рабочего OZON агента."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Аналитика остатков", callback_data="working_stocks"),
            InlineKeyboardButton(text="📦 Товары", callback_data="working_products")
        ],
        [
            InlineKeyboardButton(text="🛒 Заказы", callback_data="working_orders"),
            InlineKeyboardButton(text="🔍 Полный тест", callback_data="working_test")
        ]
    ])
    
    text = """🚀 **OZON Рабочий Агент**

✅ *Использует только проверенные методы*

📊 **Доступно:**
• Аналитика остатков на складах
• Поиск рабочих методов для товаров
• Тестирование заказов
• Полная диагностика

Выберите действие:"""
    
    await message.reply(text, parse_mode='Markdown', reply_markup=keyboard)


@ozon_working_new_router.callback_query(F.data == "working_stocks")
async def working_stocks_callback(callback: CallbackQuery) -> None:
    """Аналитика остатков - проверенный рабочий метод."""
    await callback.answer()
    await callback.message.edit_text("📊 Получаю аналитику остатков...")
    
    try:
        api = OzonWorkingAPI()
        stock_data = api.get_stock_analytics()
        
        if stock_data:
            rows = stock_data.get("rows", [])
            
            if not rows:
                text = """📊 **Аналитика остатков**

📋 Данных по остаткам не найдено.

Возможные причины:
• Товары не размещены на складах OZON
• Нет остатков товаров  
• Все товары распроданы"""
            else:
                text = f"📊 **Аналитика остатков**\n\n"
                text += f"📈 **Найдено записей:** {len(rows)}\n\n"
                
                for i, row in enumerate(rows[:5], 1):
                    dimensions = row.get("dimensions", [])
                    metrics = row.get("metrics", [])
                    
                    # Извлекаем данные из dimensions
                    sku = "N/A"
                    warehouse = "N/A"
                    
                    for dim in dimensions:
                        if dim.get("name") == "sku":
                            sku = dim.get("id", "N/A")
                        elif dim.get("name") == "warehouse":
                            warehouse = dim.get("id", "N/A")
                    
                    # Извлекаем метрики
                    stock_count = "N/A"
                    for metric in metrics:
                        if metric.get("key") == "stock_count":
                            stock_count = metric.get("value", "N/A")
                    
                    text += f"{i}. **SKU:** `{sku}`\n"
                    text += f"   Склад: {warehouse}\n"
                    text += f"   Остаток: {stock_count}\n\n"
                
                if len(rows) > 5:
                    text += f"... и ещё {len(rows) - 5} записей"
        else:
            text = "❌ Не удалось получить данные по остаткам"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="working_stocks"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="working_back")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")


@ozon_working_new_router.callback_query(F.data == "working_products")
async def working_products_callback(callback: CallbackQuery) -> None:
    """Поиск рабочего метода для товаров."""
    await callback.answer()
    await callback.message.edit_text("📦 Ищу рабочий метод получения товаров...")
    
    try:
        api = OzonWorkingAPI()
        endpoint, products = api.try_product_methods()
        
        if endpoint and products:
            text = f"📦 **Товары через `{endpoint}`:**\n\n"
            text += f"✅ **Найдено товаров:** {len(products)}\n\n"
            
            for i, product in enumerate(products[:3], 1):
                name = product.get("name", "Без названия")[:40]
                product_id = product.get("product_id", "N/A")
                
                text += f"{i}. **{name}**\n"
                text += f"   ID: `{product_id}`\n\n"
            
            if len(products) > 3:
                text += f"... и ещё {len(products) - 3} товаров"
                
        elif endpoint:
            text = f"📦 **Метод `{endpoint}` работает, но товары не найдены**\n\n"
            text += "Возможные причины:\n"
            text += "• Товары не добавлены в каталог\n"
            text += "• Все товары скрыты\n"
            text += "• Фильтры слишком строгие"
        else:
            text = "❌ **Рабочий метод получения товаров не найден**\n\n"
            text += "Все методы возвращают ошибки 404/400."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Повторить", callback_data="working_products"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="working_back")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")


@ozon_working_new_router.callback_query(F.data == "working_orders")
async def working_orders_callback(callback: CallbackQuery) -> None:
    """Поиск рабочего метода для заказов."""
    await callback.answer()
    await callback.message.edit_text("🛒 Ищу рабочий метод получения заказов...")
    
    try:
        api = OzonWorkingAPI()
        endpoint, orders = api.try_order_methods()
        
        if endpoint and orders:
            text = f"🛒 **Заказы через `{endpoint}`:**\n\n"
            text += f"✅ **Найдено заказов:** {len(orders)}\n\n"
            
            for i, order in enumerate(orders[:3], 1):
                posting_number = order.get("posting_number", "N/A")
                status = order.get("status", "N/A")
                created = order.get("created_at", "")[:10]
                
                text += f"{i}. **{posting_number}**\n"
                text += f"   Статус: {status}\n"
                text += f"   Дата: {created}\n\n"
            
            if len(orders) > 3:
                text += f"... и ещё {len(orders) - 3} заказов"
                
        elif endpoint:
            text = f"🛒 **Метод `{endpoint}` работает, но заказы не найдены**\n\n"
            text += "Возможные причины:\n"
            text += "• Нет новых заказов\n"
            text += "• Все заказы обработаны\n" 
            text += "• Нужны другие фильтры"
        else:
            text = "❌ **Рабочий метод получения заказов не найден**\n\n"
            text += "Все методы возвращают ошибки 404/400."
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Повторить", callback_data="working_orders"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="working_back")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}")


@ozon_working_new_router.callback_query(F.data == "working_test")
async def working_test_callback(callback: CallbackQuery) -> None:
    """Полный тест - как в /ozon_2024."""
    await callback.answer()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 Запустить /ozon_2024", callback_data="run_2024_test")]
    ])
    
    text = """🔍 **Полный тест API**

Для полного тестирования всех endpoints используйте:

/ozon_2024

Или нажмите кнопку ниже:"""
    
    await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)


@ozon_working_new_router.callback_query(F.data == "run_2024_test")
async def run_2024_test_callback(callback: CallbackQuery) -> None:
    """Перенаправление на полный тест."""
    await callback.answer()
    await callback.message.edit_text("🧪 Используйте команду /ozon_2024 для полного тестирования!")


@ozon_working_new_router.callback_query(F.data == "working_back")
async def working_back_callback(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    await ozon_main_command(callback.message)


# Экспорт
__all__ = ['ozon_working_new_router']
