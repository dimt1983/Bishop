"""
Automation Service
==================
Автоматизация процессов OZON: репрайсинг, управление остатками, автоответы.
"""

import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable
from services.ozon_super_api import OzonSuperAPIService
from services.claude_service import ClaudeService
from services.analytics_service import AnalyticsService


class AutomationService:
    def __init__(self):
        self.ozon_api = OzonSuperAPIService()
        self.claude_service = ClaudeService()
        self.analytics = AnalyticsService()
        
        # Настройки автоматизации
        self.automation_rules = {
            "auto_pricing": True,
            "auto_stock_alerts": True,
            "auto_review_responses": True,
            "auto_seo_optimization": True,
            "auto_competitor_monitoring": False  # Требует внешние API
        }
    
    # ==================== АВТОМАТИЧЕСКИЙ РЕПРАЙСИНГ ====================
    
    async def auto_repricing_cycle(self, categories: List[int] = None) -> Dict:
        """Цикл автоматического репрайсинга."""
        if not self.automation_rules.get("auto_pricing", False):
            return {"status": "disabled", "message": "Автоматический репрайсинг отключён"}
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "processed_products": 0,
            "price_changes": 0,
            "errors": [],
            "recommendations": []
        }
        
        try:
            # Получаем список товаров
            products = self.ozon_api.get_product_list(limit=500)
            
            if categories:
                products = [p for p in products if p.get("category_id") in categories]
            
            price_updates = []
            
            for product in products:
                product_id = product.get("product_id")
                current_price = float(product.get("price", 0))
                
                if not product_id or current_price <= 0:
                    continue
                
                # Анализируем производительность товара
                performance = self.ozon_api.get_product_performance(product_id, days=7)
                
                # Рассчитываем оптимальную цену
                new_price = await self.calculate_optimal_price(
                    product, performance, current_price
                )
                
                # Проверяем, нужно ли менять цену
                price_change_threshold = 0.05  # 5% изменение
                if abs(new_price - current_price) / current_price > price_change_threshold:
                    price_updates.append({
                        "product_id": product_id,
                        "price": str(round(new_price, 2)),
                        "old_price": current_price,
                        "change_reason": self.get_price_change_reason(performance, new_price, current_price)
                    })
                
                results["processed_products"] += 1
                
                # Пауза между товарами чтобы не нагружать API
                await asyncio.sleep(0.1)
            
            # Применяем изменения цен пакетно
            if price_updates:
                success = self.ozon_api.update_prices(price_updates)
                if success:
                    results["price_changes"] = len(price_updates)
                    results["recommendations"].append(f"Обновлено цен: {len(price_updates)}")
                else:
                    results["errors"].append("Ошибка обновления цен в OZON API")
            
        except Exception as e:
            results["errors"].append(f"Ошибка в auto_repricing_cycle: {str(e)}")
        
        return results
    
    async def calculate_optimal_price(self, product: Dict, performance: Dict, current_price: float) -> float:
        """Рассчитать оптимальную цену товара с помощью AI."""
        # Собираем данные для анализа
        analysis_data = {
            "product": {
                "name": product.get("name", ""),
                "category": product.get("category_id", 0),
                "current_price": current_price,
                "rating": product.get("rating", 0)
            },
            "performance": performance,
            "market_context": {
                "season": self.get_current_season(),
                "day_of_week": datetime.now().weekday(),
                "month": datetime.now().month
            }
        }
        
        # Используем Claude для расчёта цены
        prompt = """Ты — эксперт по ценообразованию на маркетплейсах.
Рассчитай оптимальную цену товара на основе данных о производительности.

Учитывай:
1. Конверсию товара (просмотры → корзина → покупка)
2. Сезонность и тренды
3. Конкурентную ситуацию
4. Маржинальность

Правила ценообразования:
- Если конверсия высокая (>3%) — можно поднять цену на 5-15%
- Если конверсия низкая (<1%) — снизить цену на 10-20%
- Учитывай сезонные колебания спроса
- Минимальная маржа 20%

Ответь ТОЛЬКО числом — новой ценой в рублях."""
        
        user_message = f"""Данные для расчёта цены:
{json.dumps(analysis_data, ensure_ascii=False, indent=2)}

Текущая цена: {current_price} ₽
Рассчитай оптимальную цену."""
        
        try:
            price_response = self.claude_service.call_claude(prompt, user_message)
            # Извлекаем число из ответа
            import re
            price_match = re.search(r'(\d+(?:\.\d+)?)', price_response)
            if price_match:
                new_price = float(price_match.group(1))
                # Ограничения на изменение цены
                max_increase = current_price * 1.3  # Максимум +30%
                min_decrease = current_price * 0.7  # Минимум -30%
                return max(min_decrease, min(new_price, max_increase))
        except:
            pass
        
        # Fallback: простая логика ценообразования
        return self.calculate_price_fallback(performance, current_price)
    
    def calculate_price_fallback(self, performance: Dict, current_price: float) -> float:
        """Резервная логика расчёта цены."""
        metrics = performance.get("metrics", [])
        
        # Ищем метрики конверсии
        views = 0
        cart_adds = 0
        
        for metric in metrics:
            key = metric.get("key", "")
            value = float(metric.get("value", 0))
            
            if "hits_view" in key:
                views += value
            elif "hits_tocart" in key:
                cart_adds += value
        
        if views > 0:
            conversion_rate = cart_adds / views
            
            if conversion_rate > 0.03:  # Высокая конверсия
                return current_price * 1.1  # +10%
            elif conversion_rate < 0.01:  # Низкая конверсия
                return current_price * 0.9  # -10%
        
        return current_price  # Без изменений
    
    # ==================== МОНИТОРИНГ ОСТАТКОВ ====================
    
    async def stock_monitoring_cycle(self) -> Dict:
        """Мониторинг остатков и автоматические уведомления."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "checked_products": 0,
            "low_stock_alerts": [],
            "out_of_stock": [],
            "recommendations": []
        }
        
        try:
            # Получаем остатки всех товаров
            stocks = self.ozon_api.get_product_stocks()
            
            for stock_item in stocks:
                results["checked_products"] += 1
                
                offer_id = stock_item.get("offer_id", "")
                stocks_data = stock_item.get("stocks", [])
                
                total_stock = sum(s.get("present", 0) for s in stocks_data)
                reserved_stock = sum(s.get("reserved", 0) for s in stocks_data)
                available_stock = total_stock - reserved_stock
                
                # Проверяем критические остатки
                if available_stock <= 0:
                    results["out_of_stock"].append({
                        "offer_id": offer_id,
                        "total": total_stock,
                        "available": available_stock
                    })
                elif available_stock <= 5:  # Низкий остаток
                    # Прогнозируем, когда закончится товар
                    days_until_zero = await self.predict_stock_depletion(offer_id, available_stock)
                    
                    results["low_stock_alerts"].append({
                        "offer_id": offer_id,
                        "available": available_stock,
                        "days_until_zero": days_until_zero,
                        "urgency": "high" if days_until_zero <= 7 else "medium"
                    })
        
        except Exception as e:
            results["errors"] = [f"Ошибка в stock_monitoring_cycle: {str(e)}"]
        
        # Генерируем рекомендации
        if results["out_of_stock"]:
            results["recommendations"].append(f"Срочно: {len(results['out_of_stock'])} товаров закончились")
        
        if results["low_stock_alerts"]:
            high_urgency = len([a for a in results["low_stock_alerts"] if a["urgency"] == "high"])
            if high_urgency > 0:
                results["recommendations"].append(f"Критично: {high_urgency} товаров заканчиваются на этой неделе")
        
        return results
    
    async def predict_stock_depletion(self, offer_id: str, current_stock: int) -> int:
        """Прогноз истечения остатков товара."""
        try:
            # Ищем товар по offer_id
            products = self.ozon_api.search_products_by_text(offer_id, limit=10)
            product_id = None
            
            for product in products:
                if product.get("offer_id") == offer_id:
                    product_id = product.get("product_id")
                    break
            
            if not product_id:
                return 30  # Дефолтный прогноз
            
            # Получаем статистику продаж за последние 14 дней
            performance = self.ozon_api.get_product_performance(product_id, days=14)
            
            # Рассчитываем среднесуточные продажи (упрощённо)
            daily_sales = 1  # Дефолт
            
            metrics = performance.get("metrics", [])
            for metric in metrics:
                if "hits_tocart" in metric.get("key", ""):
                    total_cart_adds = float(metric.get("value", 0))
                    # Примерно 30% из корзины покупают
                    estimated_sales = total_cart_adds * 0.3
                    daily_sales = max(1, estimated_sales / 14)
                    break
            
            # Прогнозируем дни до исчерпания
            days_left = max(1, int(current_stock / daily_sales))
            return min(days_left, 365)  # Максимум год
            
        except:
            return 30  # Безопасный дефолт
    
    # ==================== АВТООТВЕТЫ НА ОТЗЫВЫ ====================
    
    async def auto_review_responses_cycle(self) -> Dict:
        """Автоматические ответы на отзывы."""
        if not self.automation_rules.get("auto_review_responses", False):
            return {"status": "disabled"}
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "processed_reviews": 0,
            "responses_generated": 0,
            "errors": []
        }
        
        try:
            # Получаем неотвеченные отзывы
            reviews = self.ozon_api.get_reviews(status="UNPROCESSED")
            
            for review in reviews:
                review_id = review.get("id")
                rating = review.get("rating", 5)
                text = review.get("text", "")
                product_name = review.get("product", {}).get("name", "")
                
                results["processed_reviews"] += 1
                
                # Генерируем ответ только для отзывов <= 3 звёзд или особо позитивных
                if rating <= 3 or (rating >= 5 and len(text) > 50):
                    response_text = await self.generate_smart_review_response(
                        text, rating, product_name
                    )
                    
                    if response_text and len(response_text.strip()) > 10:
                        # В реальности здесь можно добавить одобрение перед отправкой
                        success = self.ozon_api.reply_to_review(review_id, response_text)
                        
                        if success:
                            results["responses_generated"] += 1
                        else:
                            results["errors"].append(f"Ошибка отправки ответа на отзыв {review_id}")
                
                await asyncio.sleep(0.5)  # Пауза между отзывами
        
        except Exception as e:
            results["errors"].append(f"Ошибка в auto_review_responses_cycle: {str(e)}")
        
        return results
    
    async def generate_smart_review_response(self, review_text: str, 
                                           rating: int, product_name: str) -> str:
        """Генерация умного ответа на отзыв."""
        # Анализируем тон и содержание отзыва
        sentiment = await self.analyze_review_sentiment(review_text)
        
        # Определяем стиль ответа
        if rating <= 2:
            style = "apologetic_helpful"
        elif rating == 3:
            style = "understanding_improving"
        else:
            style = "grateful_encouraging"
        
        prompt = f"""Напиши профессиональный ответ на отзыв покупателя.

Стиль: {style}
Тональность отзыва: {sentiment}
Оценка: {rating}/5

Правила:
- Всегда благодари за отзыв
- Если проблема — признай, извинись, предложи решение
- Если хвалят — поддержи радость
- Упомяни товар естественно
- Длина: до 250 символов
- Человечный, не шаблонный тон
- Без чрезмерных извинений"""
        
        user_message = f"""Товар: {product_name}
Отзыв покупателя: "{review_text}"
Оценка: {rating} звёзд

Напиши ответ на этот отзыв."""
        
        return self.claude_service.call_claude(prompt, user_message)
    
    async def analyze_review_sentiment(self, review_text: str) -> str:
        """Анализ тональности отзыва."""
        # Простой анализ по ключевым словам
        positive_words = ["отлично", "супер", "классно", "рекомендую", "доволен", "хорошо"]
        negative_words = ["плохо", "ужасно", "не рекомендую", "разочарован", "проблема", "брак"]
        
        text_lower = review_text.lower()
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        else:
            return "neutral"
    
    # ==================== АВТОМАТИЧЕСКАЯ SEO ОПТИМИЗАЦИЯ ====================
    
    async def auto_seo_optimization_cycle(self, max_products: int = 50) -> Dict:
        """Автоматическая SEO оптимизация товаров."""
        if not self.automation_rules.get("auto_seo_optimization", False):
            return {"status": "disabled"}
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "analyzed_products": 0,
            "optimized_products": 0,
            "optimizations": [],
            "errors": []
        }
        
        try:
            # Получаем товары с низкой видимостью
            products = self.ozon_api.get_product_list(limit=max_products)
            
            for product in products:
                product_id = product.get("product_id")
                current_name = product.get("name", "")
                
                if not product_id or len(current_name) < 20:
                    continue
                
                results["analyzed_products"] += 1
                
                # Анализируем производительность
                performance = self.ozon_api.get_product_performance(product_id, days=30)
                
                # Проверяем, нужна ли оптимизация
                needs_optimization = await self.check_seo_optimization_need(product, performance)
                
                if needs_optimization:
                    # Генерируем оптимизированное название
                    optimized_data = await self.generate_seo_optimized_content(product)
                    
                    if optimized_data.get("title"):
                        # Обновляем товар
                        success = self.ozon_api.update_product_info(product_id, {
                            "name": optimized_data["title"]
                        })
                        
                        if success:
                            results["optimized_products"] += 1
                            results["optimizations"].append({
                                "product_id": product_id,
                                "old_title": current_name,
                                "new_title": optimized_data["title"],
                                "seo_score": optimized_data.get("seo_score", 0)
                            })
                        else:
                            results["errors"].append(f"Ошибка обновления товара {product_id}")
                
                await asyncio.sleep(1)  # Пауза между товарами
        
        except Exception as e:
            results["errors"].append(f"Ошибка в auto_seo_optimization_cycle: {str(e)}")
        
        return results
    
    async def check_seo_optimization_need(self, product: Dict, performance: Dict) -> bool:
        """Проверить, нужна ли SEO оптимизация."""
        # Критерии для оптимизации
        current_name = product.get("name", "")
        
        # Проверяем длину названия
        if len(current_name) < 50:
            return True
        
        # Проверяем производительность
        metrics = performance.get("metrics", [])
        total_views = 0
        
        for metric in metrics:
            if "hits_view" in metric.get("key", ""):
                total_views += float(metric.get("value", 0))
        
        # Если мало просмотров — нужна оптимизация
        if total_views < 100:
            return True
        
        return False
    
    async def generate_seo_optimized_content(self, product: Dict) -> Dict:
        """Генерация SEO-оптимизированного контента."""
        from services.content_service import ContentService
        
        content_service = ContentService()
        return content_service.optimize_product_for_seo(product)
    
    # ==================== ОБЩИЕ УТИЛИТЫ ====================
    
    def get_current_season(self) -> str:
        """Определить текущий сезон."""
        month = datetime.now().month
        if month in [12, 1, 2]:
            return "winter"
        elif month in [3, 4, 5]:
            return "spring"
        elif month in [6, 7, 8]:
            return "summer"
        else:
            return "autumn"
    
    def get_price_change_reason(self, performance: Dict, new_price: float, old_price: float) -> str:
        """Получить причину изменения цены."""
        change_percent = ((new_price - old_price) / old_price) * 100
        
        if change_percent > 5:
            return "Повышение из-за высокой конверсии"
        elif change_percent < -5:
            return "Снижение для повышения конверсии"
        else:
            return "Микрокорректировка по алгоритму"
    
    async def run_full_automation_cycle(self) -> Dict:
        """Запустить полный цикл автоматизации."""
        start_time = datetime.now()
        
        results = {
            "start_time": start_time.isoformat(),
            "cycles": {}
        }
        
        # Запускаем все циклы автоматизации
        tasks = [
            ("repricing", self.auto_repricing_cycle()),
            ("stock_monitoring", self.stock_monitoring_cycle()),
            ("review_responses", self.auto_review_responses_cycle()),
            ("seo_optimization", self.auto_seo_optimization_cycle(max_products=20))
        ]
        
        for task_name, task_coroutine in tasks:
            try:
                result = await task_coroutine
                results["cycles"][task_name] = result
            except Exception as e:
                results["cycles"][task_name] = {
                    "status": "error",
                    "error": str(e)
                }
        
        end_time = datetime.now()
        results["end_time"] = end_time.isoformat()
        results["duration_seconds"] = (end_time - start_time).total_seconds()
        
        return results
