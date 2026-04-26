"""
OZON API 2024 - актуальные endpoints
====================================
Обновленные методы для работы с OZON Seller API.
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

# Router для актуального OZON API
ozon_2024_router = Router()


class OzonAPI2024:
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
    
    def test_all_endpoints(self):
        """Тестирует все возможные endpoints для определения рабочих."""
        endpoints = [
            # Товары (обычно работают)
            ("v2/product/list", "POST", {"filter": {"visibility": "ALL"}, "limit": 1}),
            ("v3/products/info/attributes", "POST", {"filter": {"visibility": "ALL"}, "limit": 1}),
            ("v4/product/info", "POST", {"sku": []}),
            
            # Заказы - пробуем разные варианты
            ("v3/posting/fbs/unfulfilled/list", "POST", {"limit": 10}),
            ("v2/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}),
            ("v3/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}),
            ("v1/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}),
            ("v2/posting/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}),
            
            # Аналитика
            ("v1/analytics/data", "POST", {"date_from": "2024-04-20", "date_to": "2024-04-26", "metrics": ["hits_view"], "dimension": ["sku"]}),
            ("v2/analytics/stock_on_warehouses", "POST", {"limit": 1}),
            
            # Финансы
            ("v3/finance/realization", "POST", {"date": {"from": "2024-04-20", "to": "2024-04-26"}}),
            ("v1/finance/cash-flow", "POST", {"date": {"from": "2024-04-20", "to": "2024-04-26"}, "posting_number": []}),
            
            # Остатки
            ("v3/product/info/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 1}),
            ("v2/products/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 1}),
            
            # Отзывы
            ("v1/review/list", "POST", {"filter": {}, "limit": 1}),
            
            # Общая информация
            ("v1/seller/info", "GET", None),
            ("v1/company/info", "GET", None),
        ]
        
        working = []
        failed = []
        
        for endpoint, method, payload in endpoints:
            try:
                url = f"{self.base_url}/{endpoint}"
                
                if method == "GET":
                    response = requests.get(url, headers=self.headers, timeout=10)
                else:
                    response = requests.post(url, headers=self.headers, json=payload, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    working.append((endpoint, method, len(str(data))))
                elif response.status_code == 403:
                    failed.append((endpoint, f"HTTP 403 - нет прав"))
                else:
                    failed.append((endpoint, f"HTTP {response.status_code}"))
                    
            except Exception as e:
                failed.append((endpoint, f"Ошибка: {str(e)[:30]}"))
        
        return working, failed
    
    def get_orders_working(self):
        """Пробует все методы получения заказов и возвращает рабочий."""
        methods = [
            ("v3/posting/fbs/unfulfilled/list", {"limit": 50}),
            ("v2/posting/fbs/list", {"dir": "ASC", "filter": {}, "limit": 50}),
            ("v3/posting/fbs/list", {"dir": "ASC", "filter": {}, "limit": 50}),
            ("v2/posting/list", {"dir": "ASC", "filter": {}, "limit": 50}),
        ]
        
        for endpoint, payload in methods:
            try:
                url = f"{self.base_url}/{endpoint}"
                response = requests.post(url, headers=self.headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    orders = data.get("result", {}).get("postings", []) or data.get("result", [])
                    if isinstance(orders, list):
                        return endpoint, orders
                        
            except Exception as e:
                logger.error(f"Ошибка в {endpoint}: {e}")
                continue
        
        return None, []
    
    def get_products_working(self):
        """Получает товары рабочим методом."""
        methods = [
            ("v2/product/list", {"filter": {"visibility": "ALL"}, "limit": 100}),
            ("v3/products/info/attributes", {"filter": {"visibility": "ALL"}, "limit": 100}),
            ("v4/product/info", {"sku": []}),
        ]
        
        for endpoint, payload in methods:
            try:
                url = f"{self.base_url}/{endpoint}"
                response = requests.post(url, headers=self.headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    products = data.get("result", {}).get("items", []) or data.get("result", [])
                    if isinstance(products, list):
                        return endpoint, products
                        
            except Exception as e:
                logger.error(f"Ошибка в {endpoint}: {e}")
                continue
        
        return None, []


@ozon_2024_router.message(Command("ozon_2024"))
async def ozon_2024_menu(message: Message) -> None:
    """Главное меню OZON 2024."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧪 Тест всех API", callback_data="test_all_2024"),
            InlineKeyboardButton(text="📦 Товары", callback_data="products_2024")
        ],
        [
            InlineKeyboardButton(text="🛒 Заказы", callback_data="orders_2024"),
            InlineKeyboardButton(text="📊 Аналитика", callback_data="analytics_2024")
        ]
    ])
    
    text = """🚀 **OZON API 2024**

🔄 *Тестирование актуальных endpoints*

🎯 **Функции:**
• Тест всех доступных API методов
• Автопоиск рабочих endpoints
• Получение реальных данных

Выберите действие:"""
    
    await message.reply(text, parse_mode='Markdown', reply_markup=keyboard)


@ozon_2024_router.callback_query(F.data == "test_all_2024")
async def test_all_2024_callback(callback: CallbackQuery) -> None:
    """Тест всех endpoints."""
    await callback.answer()
    await callback.message.edit_text("🧪 Тестирую ВСЕ доступные OZON API endpoints...")
    
    try:
        api = OzonAPI2024()
        working, failed = api.test_all_endpoints()
        
        text = f"🧪 **Результаты тестирования API:**\n\n"
        
        if working:
            text += f"✅ **Работающих endpoints: {len(working)}**\n"
            for endpoint, method, data_size in working[:10]:
                text += f"✅ `{endpoint}` ({method}) - {data_size} символов\n"
            
            if len(working) > 10:
                text += f"... и ещё {len(working) - 10} endpoints\n"
        else:
            text += "❌ **Рабочих endpoints не найдено**\n"
        
        if failed:
            text += f"\n❌ **Не работают: {len(failed)}**\n"
            for endpoint, error in failed[:5]:
                text += f"❌ `{endpoint}` - {error}\n"
            
            if len(failed) > 5:
                text += f"... и ещё {len(failed) - 5} endpoints\n"
        
        text += f"\n⏰ Тестирование: {datetime.now().strftime('%H:%M:%S')}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Повторить", callback_data="test_all_2024"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_2024")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка тестирования: {str(e)}")


@ozon_2024_router.callback_query(F.data == "orders_2024")
async def orders_2024_callback(callback: CallbackQuery) -> None:
    """Получение заказов актуальным методом."""
    await callback.answer()
    await callback.message.edit_text("🛒 Ищу рабочий метод получения заказов...")
    
    try:
        api = OzonAPI2024()
        endpoint, orders = api.get_orders_working()
        
        if endpoint:
            text = f"🛒 **Заказы получены через `{endpoint}`:**\n\n"
            
            if not orders:
                text += "📋 Заказов не найдено\n"
                text += "Возможно, все заказы обработаны или нет новых заказов."
            else:
                text += f"📊 **Найдено заказов: {len(orders)}**\n\n"
                
                for i, order in enumerate(orders[:5], 1):
                    posting_number = order.get("posting_number", "N/A")
                    status = order.get("status", "N/A")
                    created = order.get("created_at", "")[:10]
                    
                    text += f"{i}. **{posting_number}**\n"
                    text += f"   Статус: {status}\n"
                    text += f"   Дата: {created}\n\n"
                
                if len(orders) > 5:
                    text += f"... и ещё {len(orders) - 5} заказов"
        else:
            text = "❌ **Ни один метод получения заказов не работает**\n\n"
            text += "Возможные причины:\n"
            text += "• API endpoints изменились\n"
            text += "• Нужны дополнительные права\n"
            text += "• Временные проблемы OZON API"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="orders_2024"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_2024")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка получения заказов: {str(e)}")


@ozon_2024_router.callback_query(F.data == "products_2024")
async def products_2024_callback(callback: CallbackQuery) -> None:
    """Получение товаров актуальным методом."""
    await callback.answer()
    await callback.message.edit_text("📦 Ищу рабочий метод получения товаров...")
    
    try:
        api = OzonAPI2024()
        endpoint, products = api.get_products_working()
        
        if endpoint:
            text = f"📦 **Товары получены через `{endpoint}`:**\n\n"
            
            if not products:
                text += "📋 Товары не найдены"
            else:
                text += f"📊 **Найдено товаров: {len(products)}**\n\n"
                
                for i, product in enumerate(products[:5], 1):
                    name = product.get("name", "Без названия")[:40]
                    product_id = product.get("product_id", "N/A")
                    
                    text += f"{i}. **{name}**\n"
                    text += f"   ID: `{product_id}`\n\n"
                
                if len(products) > 5:
                    text += f"... и ещё {len(products) - 5} товаров"
        else:
            text = "❌ **Не удалось получить товары**"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="products_2024"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_2024")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка получения товаров: {str(e)}")


@ozon_2024_router.callback_query(F.data == "back_2024")
async def back_2024_callback(callback: CallbackQuery) -> None:
    """Возврат в меню."""
    await ozon_2024_menu(callback.message)


# Экспорт
__all__ = ['ozon_2024_router']
