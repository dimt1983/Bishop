"""
OZON API Service
================
Сервис для работы с OZON Seller API.
Получает заказы, отзывы, остатки товаров.
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional


class OzonAPIService:
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
    
    def get_yesterday_range(self) -> tuple[str, str]:
        """Получить диапазон дат для вчерашнего дня в UTC."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yesterday.replace(hour=23, minute=59, second=59, microsecond=0)
        return start.isoformat(), end.isoformat()
    
    def fetch_orders(self) -> List[Dict]:
        """Получить заказы за вчера."""
        since, to = self.get_yesterday_range()
        url = f"{self.base_url}/v2/posting/fbs/list"
        
        payload = {
            "dir": "ASC",
            "filter": {"since": since, "to": to, "status": ""},
            "limit": 100,
            "offset": 0,
            "with": {"analytics_data": True, "financial_data": True},
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("result", {}).get("postings", [])
        except requests.exceptions.RequestException as e:
            print(f"Ошибка получения заказов: {e}")
            return []
    
    def fetch_reviews(self) -> List[Dict]:
        """Получить новые неотвеченные отзывы."""
        url = f"{self.base_url}/v1/review/list"
        payload = {"limit": 50, "status": "UNPROCESSED", "sort_dir": "DESC"}
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("reviews", [])
        except requests.exceptions.RequestException as e:
            print(f"Ошибка получения отзывов: {e}")
            return []
    
    def fetch_stock_warnings(self) -> List[Dict]:
        """Получить товары с низким остатком."""
        url = f"{self.base_url}/v4/product/info/stocks"
        payload = {"filter": {"visibility": "IN_SALE"}, "last_id": "", "limit": 100}
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])
            
            low_stock = []
            for item in items:
                for stock in item.get("stocks", []):
                    present = stock.get("present", 0)
                    if 0 < present < 5:  # Менее 5 штук в наличии
                        low_stock.append({
                            "offer_id": item.get("offer_id"),
                            "warehouse": stock.get("type"),
                            "qty": present,
                        })
            return low_stock
        except requests.exceptions.RequestException as e:
            print(f"Ошибка получения остатков: {e}")
            return []
    
    def aggregate_metrics(self, orders: List[Dict]) -> Dict:
        """Агрегировать метрики из заказов."""
        total_revenue = 0
        total_orders = len(orders)
        total_items = 0
        cancelled = 0
        by_product = {}

        for order in orders:
            if order.get("status") == "cancelled":
                cancelled += 1
                continue
                
            for product in order.get("products", []):
                qty = product.get("quantity", 0)
                price = float(product.get("price", 0))
                total_revenue += qty * price
                total_items += qty
                
                sku = product.get("offer_id", "unknown")
                by_product[sku] = by_product.get(sku, 0) + qty

        # Топ-5 самых продаваемых SKU
        top_5_skus = sorted(by_product.items(), key=lambda x: -x[1])[:5]
        
        return {
            "total_orders": total_orders,
            "cancelled": cancelled,
            "total_revenue": round(total_revenue, 2),
            "total_items": total_items,
            "top_5_skus": top_5_skus,
        }
    
    def get_daily_summary(self) -> Dict:
        """Получить полную сводку за день."""
        orders = self.fetch_orders()
        reviews = self.fetch_reviews()
        low_stock = self.fetch_stock_warnings()
        metrics = self.aggregate_metrics(orders)
        
        return {
            "date": (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y"),
            "metrics": metrics,
            "reviews": {
                "total": len(reviews),
                "negative": [
                    {"rating": r.get("rating"), "text": r.get("text", "")[:200]}
                    for r in reviews if r.get("rating", 5) <= 3
                ][:5]  # Только первые 5 негативных
            },
            "low_stock": low_stock[:10],  # Только первые 10
        }
