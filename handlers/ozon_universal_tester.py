"""
OZON Universal API Tester
=========================
Тестирует ВСЕ возможные endpoints OZON API для поиска рабочих методов.
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

# Router для универсального тестера
ozon_universal_router = Router()


class OzonUniversalTester:
    def __init__(self):
        self.client_id = os.getenv("OZON_CLIENT_ID")
        self.api_key = os.getenv("OZON_API_KEY")
        self.base_url = "https://api-seller.ozon.ru"
        
        self.headers = {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
    
    def get_comprehensive_endpoints_list(self):
        """Возвращает максимально полный список endpoints для тестирования."""
        
        # Базовые даты для тестов
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        endpoints = [
            # ==================== ЗАКАЗЫ ====================
            # FBS (Fulfillment by Seller) - разные версии
            ("v1/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v2/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v3/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v4/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            
            # FBS с фильтрами по датам
            ("v2/posting/fbs/list", "POST", {"dir": "ASC", "filter": {"since": f"{week_ago}T00:00:00Z", "to": f"{today}T23:59:59Z"}, "limit": 10}),
            ("v3/posting/fbs/list", "POST", {"dir": "ASC", "filter": {"since": f"{week_ago}T00:00:00Z", "to": f"{today}T23:59:59Z"}, "limit": 10}),
            
            # FBS незавершённые заказы
            ("v1/posting/fbs/unfulfilled/list", "POST", {"limit": 10}),
            ("v2/posting/fbs/unfulfilled/list", "POST", {"limit": 10}),
            ("v3/posting/fbs/unfulfilled/list", "POST", {"limit": 10}),
            
            # FBO (Fulfillment by OZON)
            ("v1/posting/fbo/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v2/posting/fbo/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v3/posting/fbo/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            
            # Общие методы заказов
            ("v1/posting/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v2/posting/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v3/posting/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            
            # Кроссдок
            ("v1/posting/crossdock/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            ("v2/posting/crossdock/list", "POST", {"dir": "ASC", "filter": {}, "limit": 10}),
            
            # ==================== ТОВАРЫ ====================
            ("v1/product/list", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v2/product/list", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v3/product/list", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}), # ✅ РАБОТАЕТ
            ("v4/product/list", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            
            # Информация о товарах
            ("v1/product/info", "POST", {"product_id": 0}),
            ("v2/product/info", "POST", {"product_id": 0}),
            ("v3/product/info", "POST", {"product_id": 0}),
            ("v4/product/info", "POST", {"product_id": 0}),
            
            # Атрибуты товаров
            ("v1/products/info/attributes", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v2/products/info/attributes", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v3/products/info/attributes", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            
            # ==================== ОСТАТКИ ====================
            ("v1/product/info/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v2/product/info/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v3/product/info/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v4/product/info/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            
            ("v1/products/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v2/products/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            
            # ==================== АНАЛИТИКА ====================
            ("v1/analytics/data", "POST", {"date_from": week_ago, "date_to": today, "metrics": ["hits_view"], "dimension": ["sku"]}),
            ("v2/analytics/data", "POST", {"date_from": week_ago, "date_to": today, "metrics": ["hits_view"], "dimension": ["sku"]}),
            
            ("v1/analytics/stock_on_warehouses", "POST", {"limit": 10}),
            ("v2/analytics/stock_on_warehouses", "POST", {"limit": 10}), # ✅ РАБОТАЕТ
            ("v3/analytics/stock_on_warehouses", "POST", {"limit": 10}),
            
            # ==================== ФИНАНСЫ ====================
            ("v1/finance/realization", "POST", {"date": {"from": week_ago, "to": today}}),
            ("v2/finance/realization", "POST", {"date": {"from": week_ago, "to": today}}),
            ("v3/finance/realization", "POST", {"date": {"from": week_ago, "to": today}}),
            
            ("v1/finance/cash-flow", "POST", {"date": {"from": week_ago, "to": today}, "posting_number": []}),
            ("v2/finance/cash-flow", "POST", {"date": {"from": week_ago, "to": today}, "posting_number": []}),
            
            # ==================== ОТЗЫВЫ И ВОПРОСЫ ====================
            ("v1/review/list", "POST", {"filter": {}, "limit": 10}),
            ("v2/review/list", "POST", {"filter": {}, "limit": 10}),
            
            ("v1/customer/question/list", "POST", {"filter": {}, "limit": 10}),
            ("v2/customer/question/list", "POST", {"filter": {}, "limit": 10}),
            
            # ==================== ЦЕНЫ ====================
            ("v1/product/info/prices", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v4/product/info/prices", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            
            # ==================== ИНФОРМАЦИЯ О ПРОДАВЦЕ ====================
            ("v1/seller/info", "GET", None),
            ("v2/seller/info", "GET", None),
            ("v1/company/info", "GET", None),
            ("v2/company/info", "GET", None),
            
            # ==================== КАТЕГОРИИ ====================
            ("v1/category/tree", "POST", {}),
            ("v2/category/tree", "POST", {}),
            ("v3/category/tree", "POST", {}),
            
            # ==================== СКЛАДЫ ====================
            ("v1/warehouse/list", "POST", {}),
            ("v2/warehouse/list", "POST", {}),
            
            # ==================== НОВЫЕ/ЭКСПЕРИМЕНТАЛЬНЫЕ ====================
            ("v5/product/list", "POST", {"filter": {"visibility": "ALL"}, "limit": 10}),
            ("v1/posting/tracking", "POST", {"posting_number": []}),
            ("v1/report/info", "POST", {}),
            ("v1/brand/list", "POST", {}),
        ]
        
        return endpoints
    
    def test_all_comprehensive(self):
        """Тестирует ВСЕ возможные endpoints."""
        endpoints = self.get_comprehensive_endpoints_list()
        
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
                    data_size = len(str(data))
                    
                    # Попробуем определить, есть ли полезные данные
                    has_data = False
                    if isinstance(data, dict):
                        result = data.get("result", data)
                        if result:
                            if isinstance(result, dict):
                                items = result.get("items", result.get("postings", result.get("rows", [])))
                                if items and len(items) > 0:
                                    has_data = True
                            elif isinstance(result, list) and len(result) > 0:
                                has_data = True
                            elif result != {} and result != []:
                                has_data = True
                    
                    working.append({
                        "endpoint": endpoint,
                        "method": method, 
                        "data_size": data_size,
                        "has_data": has_data,
                        "response": data
                    })
                    
                elif response.status_code == 403:
                    failed.append((endpoint, "403 - нет прав"))
                elif response.status_code == 404:
                    failed.append((endpoint, "404 - не найден"))
                elif response.status_code == 400:
                    failed.append((endpoint, "400 - неверный запрос"))
                else:
                    failed.append((endpoint, f"HTTP {response.status_code}"))
                    
            except requests.exceptions.Timeout:
                failed.append((endpoint, "таймаут"))
            except Exception as e:
                failed.append((endpoint, f"ошибка: {str(e)[:20]}"))
        
        return working, failed


@ozon_universal_router.message(Command("ozon_full"))
async def ozon_full_test_command(message: Message) -> None:
    """Максимально полное тестирование ВСЕХ OZON API endpoints."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧪 Запустить полный тест", callback_data="run_full_test"),
            InlineKeyboardButton(text="📊 Быстрый тест", callback_data="run_quick_test")
        ]
    ])
    
    text = """🔬 **УНИВЕРСАЛЬНЫЙ OZON API ТЕСТЕР**

🎯 **Максимально полное тестирование**

🧪 **Полный тест:**
• 80+ различных endpoints
• Все версии API (v1, v2, v3, v4, v5)
• Заказы, товары, аналитика, финансы
• Точное определение рабочих методов

📊 **Быстрый тест:**
• Основные endpoints
• Быстрая диагностика

Выберите тип тестирования:"""
    
    await message.reply(text, parse_mode='Markdown', reply_markup=keyboard)


@ozon_universal_router.callback_query(F.data == "run_full_test")
async def run_full_test_callback(callback: CallbackQuery) -> None:
    """Запуск полного тестирования."""
    await callback.answer()
    await callback.message.edit_text("🔬 Запускаю ПОЛНОЕ тестирование всех OZON API endpoints...\n\n⏳ Это займёт 2-3 минуты...")
    
    try:
        tester = OzonUniversalTester()
        working, failed = tester.test_all_comprehensive()
        
        # Анализируем результаты
        working_with_data = [w for w in working if w["has_data"]]
        working_empty = [w for w in working if not w["has_data"]]
        
        text = f"🔬 **ПОЛНЫЙ ТЕСТ ЗАВЕРШЁН**\n\n"
        
        text += f"✅ **Рабочих endpoints: {len(working)}**\n"
        text += f"📊 **С данными: {len(working_with_data)}**\n"
        text += f"⚪ **Пустых: {len(working_empty)}**\n"
        text += f"❌ **Не работают: {len(failed)}**\n\n"
        
        if working_with_data:
            text += "🎯 **ENDPOINTS С ДАННЫМИ:**\n"
            for w in working_with_data[:10]:
                text += f"✅ `{w['endpoint']}` - {w['data_size']} символов\n"
            
            if len(working_with_data) > 10:
                text += f"... и ещё {len(working_with_data) - 10}\n"
        
        if working_empty:
            text += f"\n⚪ **Работают но пустые: {len(working_empty)}**\n"
            for w in working_empty[:5]:
                text += f"⚪ `{w['endpoint']}`\n"
        
        if failed:
            text += f"\n❌ **Основные ошибки:**\n"
            error_types = {}
            for endpoint, error in failed:
                error_types[error] = error_types.get(error, 0) + 1
            
            for error, count in list(error_types.items())[:5]:
                text += f"❌ {error}: {count} endpoints\n"
        
        text += f"\n⏰ Тестирование: {datetime.now().strftime('%H:%M:%S')}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 Детальный отчёт", callback_data="detailed_report"),
                InlineKeyboardButton(text="🔄 Повторить", callback_data="run_full_test")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
        # Сохраняем результаты для детального отчёта
        callback.message.bot['test_results'] = {
            'working_with_data': working_with_data,
            'working_empty': working_empty,
            'failed': failed
        }
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка полного тестирования: {str(e)}")


@ozon_universal_router.callback_query(F.data == "detailed_report")
async def detailed_report_callback(callback: CallbackQuery) -> None:
    """Детальный отчёт по результатам."""
    await callback.answer()
    
    results = callback.message.bot.get('test_results', {})
    working_with_data = results.get('working_with_data', [])
    
    if not working_with_data:
        await callback.message.edit_text("❌ Нет данных для детального отчёта")
        return
    
    text = "📄 **ДЕТАЛЬНЫЙ ОТЧЁТ**\n\n"
    text += "🎯 **Рабочие endpoints с данными:**\n\n"
    
    for i, w in enumerate(working_with_data, 1):
        text += f"{i}. **{w['endpoint']}**\n"
        text += f"   Размер: {w['data_size']} символов\n"
        text += f"   Метод: {w['method']}\n"
        
        # Краткая информация о данных
        response = w.get('response', {})
        result = response.get('result', {})
        if isinstance(result, dict):
            items = result.get('items', result.get('postings', result.get('rows', [])))
            if isinstance(items, list):
                text += f"   Записей: {len(items)}\n"
        
        text += "\n"
        
        if len(text) > 3500:  # Ограничение Telegram
            text += f"... и ещё {len(working_with_data) - i} endpoints"
            break
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="run_full_test")]
    ])
    
    await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)


# Экспорт
__all__ = ['ozon_universal_router']
