"""
Улучшенная диагностика OZON API
===============================
Тестирует все возможные endpoints для определения доступных методов.
"""

import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

logger = logging.getLogger(__name__)

# Router для расширенной диагностики
ozon_diag_router = Router()


@ozon_diag_router.message(Command("ozon_full_test"))
async def ozon_full_test_command(message: Message) -> None:
    """Полная диагностика всех OZON API endpoints."""
    try:
        await message.reply("🔬 Запускаю полную диагностику OZON API...")
        
        client_id = os.getenv("OZON_CLIENT_ID")
        api_key = os.getenv("OZON_API_KEY")
        
        if not client_id or not api_key:
            await message.reply("❌ Переменные OZON_CLIENT_ID или OZON_API_KEY не установлены")
            return
        
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json",
        }
        
        base_url = "https://api-seller.ozon.ru"
        
        # Список всех возможных endpoints для тестирования
        endpoints_to_test = [
            # Информационные endpoints (обычно всегда работают)
            ("v1/seller/info", "GET", None, "Информация о продавце"),
            ("v2/product/list", "POST", {"filter": {"visibility": "ALL"}, "limit": 1}, "Список товаров"),
            
            # Заказы - разные версии и типы
            ("v2/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}, "FBS заказы v2"),
            ("v3/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}, "FBS заказы v3"),
            ("v2/posting/fbo/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}, "FBO заказы v2"),
            ("v1/posting/fbs/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}, "FBS заказы v1"),
            ("v2/posting/crossdock/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}, "Crossdock заказы"),
            ("v1/posting/list", "POST", {"dir": "ASC", "filter": {}, "limit": 1}, "Общий список заказов"),
            
            # Аналитика и финансы
            ("v1/analytics/data", "POST", {"date_from": "2024-04-20", "date_to": "2024-04-26", "metrics": ["hits_view"], "dimension": ["sku"]}, "Аналитика"),
            ("v3/finance/realization", "POST", {"date": {"from": "2024-04-20", "to": "2024-04-26"}}, "Финансовый отчет"),
            
            # Отзывы и вопросы
            ("v1/review/list", "POST", {"filter": {}, "limit": 1}, "Отзывы"),
            ("v1/customer/question/list", "POST", {"filter": {}, "limit": 1}, "Вопросы покупателей"),
            
            # Остатки и склад
            ("v2/products/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 1}, "Остатки v2"),
            ("v1/product/info/stocks", "POST", {"filter": {"visibility": "ALL"}, "limit": 1}, "Остатки v1"),
        ]
        
        results = []
        working_endpoints = []
        
        for endpoint, method, payload, description in endpoints_to_test:
            try:
                url = f"{base_url}/{endpoint}"
                
                if method == "GET":
                    response = requests.get(url, headers=headers, timeout=10)
                else:
                    response = requests.post(url, headers=headers, json=payload, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    # Проверяем есть ли данные
                    if data and isinstance(data, dict):
                        result_data = data.get("result", data)
                        if result_data:
                            results.append(f"✅ {description}: РАБОТАЕТ")
                            working_endpoints.append((endpoint, method, description))
                        else:
                            results.append(f"⚪ {description}: пустой ответ")
                    else:
                        results.append(f"✅ {description}: OK")
                        working_endpoints.append((endpoint, method, description))
                        
                elif response.status_code == 403:
                    results.append(f"🔒 {description}: нет прав доступа")
                elif response.status_code == 404:
                    results.append(f"❌ {description}: endpoint не найден")
                else:
                    results.append(f"⚠️ {description}: HTTP {response.status_code}")
                    
            except requests.exceptions.Timeout:
                results.append(f"⏱️ {description}: таймаут")
            except Exception as e:
                results.append(f"💥 {description}: {str(e)[:30]}")
        
        # Формируем отчёт
        report = f"🔬 **Полная диагностика OZON API**\n\n"
        
        if working_endpoints:
            report += f"✅ **Работающих endpoints: {len(working_endpoints)}**\n\n"
            for result in results[:10]:  # Первые 10 результатов
                report += f"{result}\n"
            
            if len(results) > 10:
                report += f"\n... и ещё {len(results) - 10} endpoints\n"
            
            # Рекомендации для работающих endpoints
            report += f"\n💡 **Рекомендации:**\n"
            for endpoint, method, desc in working_endpoints[:3]:
                report += f"• Используйте `{endpoint}` для получения {desc.lower()}\n"
                
        else:
            report += "❌ **Ни один endpoint не работает**\n\n"
            report += "Возможные причины:\n"
            report += "• Неверные API ключи\n"
            report += "• Аккаунт не активен\n"
            report += "• Нет прав на API\n\n"
            
            for result in results[:5]:
                report += f"{result}\n"
        
        report += f"\n⏰ Тестирование: {datetime.now().strftime('%H:%M:%S')}"
        
        await message.reply(report, parse_mode='Markdown')
        
    except Exception as e:
        await message.reply(f"❌ Ошибка полной диагностики: {str(e)}")


@ozon_diag_router.message(Command("ozon_account_type"))
async def ozon_account_type_command(message: Message) -> None:
    """Определить тип аккаунта OZON."""
    try:
        await message.reply("🔍 Определяю тип аккаунта OZON...")
        
        client_id = os.getenv("OZON_CLIENT_ID")
        api_key = os.getenv("OZON_API_KEY")
        
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json",
        }
        
        base_url = "https://api-seller.ozon.ru"
        
        # Тестируем базовую информацию
        try:
            response = requests.get(f"{base_url}/v1/seller/info", headers=headers, timeout=10)
            if response.status_code == 200:
                seller_info = response.json()
                
                report = "🏪 **Информация об аккаунте:**\n\n"
                report += f"✅ Подключение: работает\n"
                
                # Извлекаем информацию о продавце
                if seller_info:
                    report += f"📊 Данные получены: {len(str(seller_info))} символов\n"
                
                # Проверяем доступные типы заказов
                fbs_available = False
                fbo_available = False
                
                # Тест FBS
                try:
                    fbs_response = requests.post(
                        f"{base_url}/v2/posting/fbs/list",
                        headers=headers,
                        json={"dir": "ASC", "filter": {}, "limit": 1},
                        timeout=5
                    )
                    fbs_available = fbs_response.status_code == 200
                except:
                    pass
                
                # Тест FBO  
                try:
                    fbo_response = requests.post(
                        f"{base_url}/v2/posting/fbo/list",
                        headers=headers,
                        json={"dir": "ASC", "filter": {}, "limit": 1},
                        timeout=5
                    )
                    fbo_available = fbo_response.status_code == 200
                except:
                    pass
                
                report += f"\n📦 **Доступные типы заказов:**\n"
                report += f"{'✅' if fbs_available else '❌'} FBS (склад продавца)\n"
                report += f"{'✅' if fbo_available else '❌'} FBO (склад OZON)\n"
                
                if not fbs_available and not fbo_available:
                    report += f"\n⚠️ **Возможные причины:**\n"
                    report += f"• Новый аккаунт без заказов\n"
                    report += f"• Ограниченные права API\n"
                    report += f"• Другой тип интеграции\n"
                
            else:
                report = f"❌ Ошибка получения информации: HTTP {response.status_code}\n"
                report += f"Ответ: {response.text[:100]}"
                
        except Exception as e:
            report = f"❌ Ошибка подключения: {str(e)}"
        
        await message.reply(report, parse_mode='Markdown')
        
    except Exception as e:
        await message.reply(f"❌ Ошибка: {str(e)}")
