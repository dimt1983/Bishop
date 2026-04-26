"""
Analytics & Business Intelligence Service
==========================================
Продвинутая аналитика для OZON: тренды, прогнозы, рекомендации.
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from services.claude_service import ClaudeService
from services.ozon_super_api import OzonSuperAPIService


class AnalyticsService:
    def __init__(self):
        self.claude_service = ClaudeService()
        self.ozon_api = OzonSuperAPIService()
    
    # ==================== АНАЛИЗ ПРОДАЖ ====================
    
    def get_sales_analytics(self, days: int = 30) -> Dict:
        """Комплексная аналитика продаж за период."""
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Получаем данные из разных источников
        analytics_data = self.ozon_api.get_analytics_data(
            date_from, date_to, 
            ["hits_view_search", "hits_view_pdp", "hits_tocart", "revenue"]
        )
        
        finance_data = self.ozon_api.get_finance_realization(date_from, date_to)
        
        # Анализируем тренды
        trends = self.analyze_sales_trends(analytics_data)
        
        # Ищем проблемные товары
        problem_products = self.identify_problem_products(analytics_data)
        
        # Топ товары
        top_products = self.get_top_performing_products(analytics_data, limit=10)
        
        return {
            "period": {"from": date_from, "to": date_to, "days": days},
            "summary": self.calculate_summary_metrics(finance_data),
            "trends": trends,
            "top_products": top_products,
            "problem_products": problem_products,
            "recommendations": self.generate_sales_recommendations(analytics_data, trends)
        }
    
    def analyze_sales_trends(self, analytics_data: Dict) -> Dict:
        """Анализ трендов продаж."""
        data_rows = analytics_data.get("data", [])
        if not data_rows:
            return {"trend": "no_data", "message": "Недостаточно данных"}
        
        # Группируем по дням (упрощённый анализ)
        daily_revenue = {}
        daily_views = {}
        
        for row in data_rows:
            # Здесь можно добавить более сложную логику группировки по дням
            metrics = row.get("metrics", [])
            for metric in metrics:
                key = metric.get("key", "")
                value = float(metric.get("value", 0))
                
                if "revenue" in key:
                    daily_revenue[key] = daily_revenue.get(key, 0) + value
                elif "hits_view" in key:
                    daily_views[key] = daily_views.get(key, 0) + value
        
        # Анализируем тренд
        total_revenue = sum(daily_revenue.values())
        total_views = sum(daily_views.values())
        
        conversion_rate = (total_revenue / total_views * 100) if total_views > 0 else 0
        
        # Определяем тренд (упрощённая логика)
        if total_revenue > 100000:
            trend = "growing"
        elif total_revenue > 50000:
            trend = "stable"
        else:
            trend = "declining"
        
        return {
            "trend": trend,
            "total_revenue": total_revenue,
            "total_views": total_views,
            "conversion_rate": round(conversion_rate, 2),
            "analysis": self.interpret_trend(trend, conversion_rate)
        }
    
    def identify_problem_products(self, analytics_data: Dict) -> List[Dict]:
        """Выявить проблемные товары."""
        problems = []
        data_rows = analytics_data.get("data", [])
        
        for row in data_rows:
            dimensions = row.get("dimensions", [])
            metrics = row.get("metrics", [])
            
            # Получаем ID товара из dimensions
            product_info = {}
            for dim in dimensions:
                if dim.get("name") == "sku":
                    product_info["sku"] = dim.get("id", "")
            
            if not product_info.get("sku"):
                continue
            
            # Анализируем метрики
            views = 0
            cart_adds = 0
            revenue = 0
            
            for metric in metrics:
                key = metric.get("key", "")
                value = float(metric.get("value", 0))
                
                if "hits_view" in key:
                    views += value
                elif "hits_tocart" in key:
                    cart_adds += value
                elif "revenue" in key:
                    revenue += value
            
            # Выявляем проблемы
            issues = []
            if views > 1000 and cart_adds / views < 0.01:  # Низкая конверсия в корзину
                issues.append("low_cart_conversion")
            if views < 100:  # Низкая видимость
                issues.append("low_visibility")
            if cart_adds > 50 and revenue == 0:  # Добавляют в корзину, но не покупают
                issues.append("low_purchase_conversion")
            
            if issues:
                problems.append({
                    "sku": product_info["sku"],
                    "views": views,
                    "cart_adds": cart_adds,
                    "revenue": revenue,
                    "issues": issues,
                    "recommendations": self.get_product_fix_recommendations(issues)
                })
        
        # Сортируем по серьёзности проблем
        problems.sort(key=lambda x: len(x["issues"]), reverse=True)
        return problems[:20]  # Топ-20 проблемных товаров
    
    def get_top_performing_products(self, analytics_data: Dict, limit: int = 10) -> List[Dict]:
        """Получить топ товары по выручке."""
        data_rows = analytics_data.get("data", [])
        products = []
        
        for row in data_rows:
            dimensions = row.get("dimensions", [])
            metrics = row.get("metrics", [])
            
            product_info = {}
            for dim in dimensions:
                if dim.get("name") == "sku":
                    product_info["sku"] = dim.get("id", "")
            
            if not product_info.get("sku"):
                continue
            
            revenue = 0
            views = 0
            for metric in metrics:
                if "revenue" in metric.get("key", ""):
                    revenue += float(metric.get("value", 0))
                elif "hits_view" in metric.get("key", ""):
                    views += float(metric.get("value", 0))
            
            if revenue > 0:
                products.append({
                    "sku": product_info["sku"],
                    "revenue": revenue,
                    "views": views,
                    "revenue_per_view": round(revenue / views, 2) if views > 0 else 0
                })
        
        products.sort(key=lambda x: x["revenue"], reverse=True)
        return products[:limit]
    
    # ==================== АНАЛИЗ КОНКУРЕНТОВ ====================
    
    def analyze_competitor_pricing(self, category_id: int, 
                                 your_products: List[int]) -> Dict:
        """Анализ цен конкурентов в категории."""
        # Здесь должна быть логика получения цен конкурентов
        # Пока что возвращаем заглушку
        return {
            "category_id": category_id,
            "analysis": "Анализ цен конкурентов требует дополнительных API",
            "recommendations": [
                "Проверьте цены вручную на сайте OZON",
                "Используйте сторонние сервисы аналитики",
                "Настройте автоматический мониторинг"
            ]
        }
    
    # ==================== ПРОГНОЗИРОВАНИЕ ====================
    
    def forecast_demand(self, product_id: int, days_ahead: int = 30) -> Dict:
        """Прогноз спроса на товар."""
        # Получаем исторические данные
        performance = self.ozon_api.get_product_performance(product_id, days=60)
        
        if not performance.get("metrics"):
            return {
                "product_id": product_id,
                "forecast": "no_data",
                "message": "Недостаточно данных для прогноза"
            }
        
        # Упрощённый прогноз (в реальности нужно использовать ML модели)
        metrics = performance["metrics"]
        avg_daily_revenue = 0
        avg_daily_views = 0
        
        for metric in metrics:
            if "revenue" in metric.get("key", ""):
                avg_daily_revenue = float(metric.get("value", 0)) / 60
            elif "hits_view" in metric.get("key", ""):
                avg_daily_views = float(metric.get("value", 0)) / 60
        
        # Прогнозируем на указанный период
        forecasted_revenue = avg_daily_revenue * days_ahead
        forecasted_views = avg_daily_views * days_ahead
        
        # Добавляем сезонные корректировки (упрощённо)
        current_month = datetime.now().month
        seasonal_multiplier = self.get_seasonal_multiplier(current_month, product_id)
        
        forecasted_revenue *= seasonal_multiplier
        forecasted_views *= seasonal_multiplier
        
        return {
            "product_id": product_id,
            "period_days": days_ahead,
            "forecasted_revenue": round(forecasted_revenue, 2),
            "forecasted_views": int(forecasted_views),
            "confidence": self.calculate_forecast_confidence(performance),
            "seasonal_factor": seasonal_multiplier,
            "recommendations": self.get_demand_recommendations(forecasted_revenue, avg_daily_revenue)
        }
    
    def get_seasonal_multiplier(self, month: int, product_id: int) -> float:
        """Получить сезонный коэффициент (упрощённая логика)."""
        # Зимние товары
        if month in [12, 1, 2]:
            return 1.2
        # Летние товары
        elif month in [6, 7, 8]:
            return 1.1
        # Предпраздничные месяцы
        elif month in [11, 3]:  # Новый год, 8 марта
            return 1.3
        else:
            return 1.0
    
    # ==================== РЕКОМЕНДАЦИИ И ИНСАЙТЫ ====================
    
    def generate_business_insights(self, sales_data: Dict, 
                                 product_data: List[Dict]) -> List[Dict]:
        """Генерация бизнес-инсайтов с помощью AI."""
        prompt = """Ты — бизнес-аналитик интернет-магазина на OZON.
Проанализируй данные и дай 5-7 конкретных инсайтов и рекомендаций.

Фокусируйся на:
1. Возможностях роста выручки
2. Проблемах, которые нужно решить срочно
3. Товарах-драйверах роста
4. Неэффективных направлениях
5. Сезонных возможностях

Каждый инсайт должен содержать:
- Суть проблемы/возможности
- Конкретное действие
- Ожидаемый результат"""
        
        user_message = f"""Данные для анализа:
        
Аналитика продаж:
{json.dumps(sales_data, ensure_ascii=False, indent=2)}

Товарные данные:
{json.dumps(product_data[:10], ensure_ascii=False, indent=2)}

Дай детальные бизнес-инсайты и рекомендации."""
        
        insights_text = self.claude_service.call_claude(prompt, user_message)
        
        # Парсим инсайты в структурированном виде
        insights = []
        lines = insights_text.split('\n')
        current_insight = ""
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('*') and not line.startswith('-'):
                if current_insight:
                    insights.append({
                        "text": current_insight.strip(),
                        "priority": self.calculate_insight_priority(current_insight),
                        "type": self.categorize_insight(current_insight)
                    })
                current_insight = line
            elif line:
                current_insight += " " + line
        
        if current_insight:
            insights.append({
                "text": current_insight.strip(),
                "priority": self.calculate_insight_priority(current_insight),
                "type": self.categorize_insight(current_insight)
            })
        
        return insights
    
    # ==================== УТИЛИТЫ ====================
    
    def calculate_summary_metrics(self, finance_data: Dict) -> Dict:
        """Рассчитать сводные метрики."""
        # Упрощённый расчёт из финансовых данных
        return {
            "total_revenue": finance_data.get("total_revenue", 0),
            "total_orders": finance_data.get("total_orders", 0),
            "avg_order_value": 0,  # Расчёт среднего чека
            "profit_margin": 0,    # Расчёт маржи
            "growth_rate": 0       # Темп роста
        }
    
    def interpret_trend(self, trend: str, conversion_rate: float) -> str:
        """Интерпретация тренда."""
        interpretations = {
            "growing": f"Позитивная динамика. Конверсия {conversion_rate}% указывает на рост спроса.",
            "stable": f"Стабильные продажи. Конверсия {conversion_rate}% — есть потенциал роста.",
            "declining": f"Снижение продаж. Конверсия {conversion_rate}% требует оптимизации."
        }
        return interpretations.get(trend, "Недостаточно данных для анализа")
    
    def get_product_fix_recommendations(self, issues: List[str]) -> List[str]:
        """Рекомендации по исправлению проблем товара."""
        recommendations = []
        
        if "low_cart_conversion" in issues:
            recommendations.append("Улучшите фотографии и описание товара")
            recommendations.append("Проверьте цену — она может быть слишком высокой")
        
        if "low_visibility" in issues:
            recommendations.append("Оптимизируйте SEO: название и ключевые слова")
            recommendations.append("Запустите рекламную кампанию")
        
        if "low_purchase_conversion" in issues:
            recommendations.append("Проверьте наличие товара и сроки доставки")
            recommendations.append("Улучшите отзывы и рейтинг товара")
        
        return recommendations
    
    def calculate_forecast_confidence(self, performance_data: Dict) -> str:
        """Рассчитать уверенность в прогнозе."""
        metrics = performance_data.get("metrics", [])
        if len(metrics) >= 5:
            return "high"
        elif len(metrics) >= 3:
            return "medium"
        else:
            return "low"
    
    def get_demand_recommendations(self, forecasted_revenue: float, 
                                 avg_daily_revenue: float) -> List[str]:
        """Рекомендации на основе прогноза спроса."""
        recommendations = []
        
        if forecasted_revenue > avg_daily_revenue * 40:  # Рост ожидается
            recommendations.append("Увеличьте закупку товара — ожидается рост спроса")
            recommendations.append("Рассмотрите повышение цены при высоком спросе")
        elif forecasted_revenue < avg_daily_revenue * 20:  # Спад ожидается
            recommendations.append("Запустите акции для стимулирования спроса")
            recommendations.append("Пересмотрите стратегию продвижения")
        else:
            recommendations.append("Поддерживайте текущую стратегию")
        
        return recommendations
    
    def calculate_insight_priority(self, insight_text: str) -> str:
        """Определить приоритет инсайта."""
        high_priority_words = ["срочно", "критично", "падение", "проблема", "потери"]
        medium_priority_words = ["возможность", "рост", "оптимизация"]
        
        text_lower = insight_text.lower()
        
        if any(word in text_lower for word in high_priority_words):
            return "high"
        elif any(word in text_lower for word in medium_priority_words):
            return "medium"
        else:
            return "low"
    
    def categorize_insight(self, insight_text: str) -> str:
        """Категоризировать инсайт."""
        text_lower = insight_text.lower()
        
        if "цена" in text_lower or "стоимость" in text_lower:
            return "pricing"
        elif "товар" in text_lower or "ассортимент" in text_lower:
            return "products"
        elif "реклама" in text_lower or "продвижение" in text_lower:
            return "marketing"
        elif "сезон" in text_lower or "тренд" in text_lower:
            return "seasonality"
        else:
            return "general"
