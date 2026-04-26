"""
OZON Super API Service
======================
Расширенный сервис для работы с OZON API.
Полный функционал: товары, цены, фото, контент, аналитика.
"""

import os
import json
import requests
import base64
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Union
from io import BytesIO


class OzonSuperAPIService:
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

    # ==================== ТОВАРЫ И КАРТОЧКИ ====================
    
    def get_product_list(self, limit: int = 100, last_id: str = "") -> List[Dict]:
        """Получить список всех товаров."""
        url = f"{self.base_url}/v2/product/list"
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": min(limit, 1000)
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("result", {}).get("items", [])

    def get_product_info(self, product_id: int) -> Dict:
        """Получить детальную информацию о товаре."""
        url = f"{self.base_url}/v2/product/info"
        payload = {"product_id": product_id}
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("result", {})

    def update_product_info(self, product_id: int, updates: Dict) -> bool:
        """Обновить информацию о товаре."""
        url = f"{self.base_url}/v1/product/info/update"
        payload = {
            "product_id": product_id,
            **updates
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        return response.status_code == 200

    def upload_product_image(self, image_data: bytes, file_name: str) -> str:
        """Загрузить изображение товара. Возвращает URL."""
        url = f"{self.base_url}/v1/product/pictures/upload"
        
        # Кодируем изображение в base64
        encoded_image = base64.b64encode(image_data).decode('utf-8')
        
        payload = {
            "file_name": file_name,
            "file_data": encoded_image
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("result", {}).get("url", "")

    def add_images_to_product(self, product_id: int, image_urls: List[str]) -> bool:
        """Добавить изображения к товару."""
        url = f"{self.base_url}/v1/product/pictures/info"
        payload = {
            "product_id": product_id,
            "pictures": [{"file_name": url} for url in image_urls]
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        return response.status_code == 200

    # ==================== ЦЕНЫ И ОСТАТКИ ====================

    def get_product_prices(self, product_ids: List[int]) -> Dict:
        """Получить цены товаров."""
        url = f"{self.base_url}/v4/product/info/prices"
        payload = {
            "filter": {"product_id": product_ids},
            "last_id": "",
            "limit": 1000
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("result", {})

    def update_prices(self, price_updates: List[Dict]) -> bool:
        """Обновить цены товаров массово."""
        url = f"{self.base_url}/v1/product/import/prices"
        payload = {"prices": price_updates}
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        return response.status_code == 200

    def get_product_stocks(self, product_ids: List[int] = None) -> List[Dict]:
        """Получить остатки товаров."""
        url = f"{self.base_url}/v4/product/info/stocks"
        payload = {
            "filter": {
                "product_id": product_ids if product_ids else [],
                "visibility": "ALL"
            },
            "last_id": "",
            "limit": 1000
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("result", {}).get("items", [])

    def update_stocks(self, stock_updates: List[Dict]) -> bool:
        """Обновить остатки товаров."""
        url = f"{self.base_url}/v1/product/import/stocks"
        payload = {"stocks": stock_updates}
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        return response.status_code == 200

    # ==================== ЗАКАЗЫ И ОТЧЁТЫ ====================

    def get_analytics_data(self, date_from: str, date_to: str, metrics: List[str]) -> Dict:
        """Получить аналитические данные."""
        url = f"{self.base_url}/v1/analytics/data"
        payload = {
            "date_from": date_from,
            "date_to": date_to,
            "metrics": metrics,
            "dimension": ["sku"],
            "filters": [],
            "sort": [{"key": "hits_view_search", "order": "DESC"}],
            "limit": 1000
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("result", {})

    def get_finance_realization(self, date_from: str, date_to: str) -> Dict:
        """Получить финансовый отчёт о реализации."""
        url = f"{self.base_url}/v3/finance/realization"
        payload = {
            "date": {
                "from": date_from,
                "to": date_to
            }
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("result", {})

    # ==================== ОТЗЫВЫ И КОММЕНТАРИИ ====================

    def get_reviews(self, product_id: int = None, status: str = "ALL") -> List[Dict]:
        """Получить отзывы."""
        url = f"{self.base_url}/v1/review/list"
        payload = {
            "filter": {
                "product_id": [product_id] if product_id else [],
                "status": status
            },
            "limit": 100,
            "offset": 0
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("reviews", [])

    def reply_to_review(self, review_id: str, reply_text: str) -> bool:
        """Ответить на отзыв."""
        url = f"{self.base_url}/v1/review/reply"
        payload = {
            "review_id": review_id,
            "text": reply_text
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        return response.status_code == 200

    def get_questions(self, status: str = "UNPROCESSED") -> List[Dict]:
        """Получить вопросы покупателей."""
        url = f"{self.base_url}/v1/customer/question/list"
        payload = {
            "filter": {"status": status},
            "limit": 50
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("items", [])

    def answer_question(self, question_id: str, answer_text: str) -> bool:
        """Ответить на вопрос покупателя."""
        url = f"{self.base_url}/v1/customer/question/answer"
        payload = {
            "question_id": question_id,
            "text": answer_text
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        return response.status_code == 200

    # ==================== СОЗДАНИЕ ТОВАРОВ ====================

    def create_product(self, product_data: Dict) -> Dict:
        """Создать новый товар."""
        url = f"{self.base_url}/v2/product/import"
        payload = {
            "items": [product_data]
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json().get("result", {})

    def get_category_attributes(self, category_id: int) -> List[Dict]:
        """Получить атрибуты категории для создания товара."""
        url = f"{self.base_url}/v3/categories/tree"
        payload = {"category_id": category_id}
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("result", [])

    # ==================== УТИЛИТЫ ====================

    def search_products_by_text(self, search_text: str, limit: int = 50) -> List[Dict]:
        """Найти товары по тексту."""
        products = self.get_product_list(limit=1000)
        
        results = []
        search_lower = search_text.lower()
        
        for product in products:
            product_name = product.get("name", "").lower()
            offer_id = product.get("offer_id", "").lower()
            
            if search_lower in product_name or search_lower in offer_id:
                results.append(product)
                if len(results) >= limit:
                    break
        
        return results

    def get_product_performance(self, product_id: int, days: int = 30) -> Dict:
        """Получить показатели товара за период."""
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        metrics = [
            "hits_view_search", "hits_view_pdp", "hits_view",
            "hits_tocart_search", "hits_tocart_pdp", "hits_tocart",
            "session_view_search", "session_view_pdp", "session_view",
            "conv_tocart_search", "conv_tocart_pdp", "conv_tocart"
        ]
        
        analytics = self.get_analytics_data(date_from, date_to, metrics)
        
        # Ищем данные по конкретному товару
        for row in analytics.get("data", []):
            dimensions = row.get("dimensions", [])
            if any(str(product_id) in str(dim.get("id", "")) for dim in dimensions):
                return {
                    "product_id": product_id,
                    "period_days": days,
                    "metrics": row.get("metrics", [])
                }
        
        return {"product_id": product_id, "metrics": [], "message": "Нет данных"}

    def bulk_price_update_by_margin(self, target_margin_percent: float, 
                                   category_ids: List[int] = None) -> Dict:
        """Массовое обновление цен с учётом желаемой маржи."""
        products = self.get_product_list(limit=1000)
        price_updates = []
        
        for product in products:
            # Если указаны категории, фильтруем
            if category_ids and product.get("category_id") not in category_ids:
                continue
            
            product_id = product.get("product_id")
            if not product_id:
                continue
            
            # Получаем текущую цену и себестоимость (если есть)
            current_price = product.get("price", 0)
            # Здесь можно добавить логику расчёта себестоимости
            # cost_price = self.get_product_cost(product_id)
            
            # Пример простого расчёта (можно усложнить)
            if current_price > 0:
                estimated_cost = current_price * 0.7  # Примерная себестоимость
                new_price = estimated_cost * (1 + target_margin_percent / 100)
                
                price_updates.append({
                    "product_id": product_id,
                    "price": str(round(new_price, 2))
                })
        
        if price_updates:
            success = self.update_prices(price_updates)
            return {
                "success": success,
                "updated_count": len(price_updates),
                "products": price_updates
            }
        
        return {"success": False, "message": "Нет товаров для обновления"}
