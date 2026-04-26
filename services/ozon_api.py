"""
OZON API Service - МАКСИМАЛЬНЫЙ ФУНКЦИОНАЛ
==========================================
Полноценный сервис для управления магазином OZON:
- Управление товарами (добавление, редактирование, удаление)
- Работа с изображениями
- Управление ценами и акциями
- Аналитика и отчёты
- Автоматизация процессов
"""

import os
import json
import requests
import base64
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Union
from io import BytesIO
from PIL import Image


class OzonAPIServiceFull:
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
    
    def get_products(self, limit: int = 100, last_id: str = "") -> Dict:
        """Получить список товаров."""
        url = f"{self.base_url}/v2/product/list"
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": limit
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def get_product_info(self, product_id: int = None, offer_id: str = None, sku: int = None) -> Dict:
        """Получить детальную информацию о товаре."""
        url = f"{self.base_url}/v2/product/info"
        payload = {}
        
        if product_id:
            payload["product_id"] = product_id
        elif offer_id:
            payload["offer_id"] = offer_id
        elif sku:
            payload["sku"] = sku
        else:
            raise ValueError("Необходимо указать product_id, offer_id или sku")
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def update_product_prices(self, prices: List[Dict]) -> Dict:
        """Обновить цены товаров."""
        url = f"{self.base_url}/v1/product/import/prices"
        payload = {"prices": prices}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def update_product_stocks(self, stocks: List[Dict]) -> Dict:
        """Обновить остатки товаров."""
        url = f"{self.base_url}/v1/product/import/stocks"
        payload = {"stocks": stocks}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def create_product(self, product_data: Dict) -> Dict:
        """Создать новый товар."""
        url = f"{self.base_url}/v2/product/import"
        payload = {"items": [product_data]}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def update_product_attributes(self, product_id: int, attributes: List[Dict]) -> Dict:
        """Обновить атрибуты товара."""
        url = f"{self.base_url}/v1/product/attributes/update"
        payload = {
            "filter": {"product_id": [product_id]},
            "attributes": attributes
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    # ==================== ИЗОБРАЖЕНИЯ ====================
    
    def upload_image(self, image_url: str = None, image_path: str = None, image_data: bytes = None) -> str:
        """Загрузить изображение в OZON."""
        url = f"{self.base_url}/v1/product/pictures/import"
        
        # Подготавливаем данные изображения
        if image_url:
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()
            image_data = img_response.content
        elif image_path:
            with open(image_path, 'rb') as f:
                image_data = f.read()
        elif not image_data:
            raise ValueError("Необходимо указать image_url, image_path или image_data")
        
        # Кодируем в base64
        encoded_image = base64.b64encode(image_data).decode('utf-8')
        
        payload = {
            "pictures": [{
                "file_name": "image.jpg",
                "file": encoded_image
            }]
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        if result.get("result") and result["result"][0].get("url"):
            return result["result"][0]["url"]
        else:
            raise Exception(f"Ошибка загрузки изображения: {result}")
    
    def add_images_to_product(self, product_id: int, image_urls: List[str]) -> Dict:
        """Добавить изображения к товару."""
        url = f"{self.base_url}/v1/product/pictures"
        payload = {
            "product_id": product_id,
            "pictures": [{"file_name": url.split('/')[-1], "url": url} for url in image_urls]
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def optimize_image(self, image_data: bytes, max_size: tuple = (2048, 2048), quality: int = 90) -> bytes:
        """Оптимизировать изображение для OZON."""
        img = Image.open(BytesIO(image_data))
        
        # Конвертируем в RGB если нужно
        if img.mode in ('RGBA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Изменяем размер если нужно
        if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Сохраняем в bytes
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue()
    
    # ==================== ЦЕНЫ И АКЦИИ ====================
    
    def get_pricing_info(self, product_ids: List[int]) -> Dict:
        """Получить информацию о ценах."""
        url = f"{self.base_url}/v4/product/info/prices"
        payload = {"filter": {"product_id": product_ids}, "last_id": "", "limit": 100}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def create_promotion(self, promotion_data: Dict) -> Dict:
        """Создать акцию."""
        url = f"{self.base_url}/v1/actions"
        response = requests.post(url, headers=self.headers, json=promotion_data, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def get_competitor_prices(self, sku: int) -> Dict:
        """Получить цены конкурентов (если доступно)."""
        url = f"{self.base_url}/v1/analytics/data"
        payload = {
            "date_from": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
            "date_to": datetime.now().strftime("%Y-%m-%d"),
            "dimension": ["sku"],
            "filters": [{"key": "sku", "op": "=", "value": str(sku)}],
            "metrics": ["ordered_units", "revenue"],
            "sort": []
        }
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except:
            return {"result": {"data": []}}
    
    # ==================== ОТЗЫВЫ ====================
    
    def get_reviews(self, page: int = 1, page_size: int = 50, status: str = "ALL") -> Dict:
        """Получить отзывы."""
        url = f"{self.base_url}/v1/review/list"
        payload = {
            "limit": page_size,
            "offset": (page - 1) * page_size,
            "status": status,
            "sort_dir": "DESC"
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def reply_to_review(self, review_id: str, text: str) -> Dict:
        """Ответить на отзыв."""
        url = f"{self.base_url}/v1/review/reply"
        payload = {"review_id": review_id, "text": text}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    # ==================== АНАЛИТИКА ====================
    
    def get_analytics_data(self, date_from: str, date_to: str, metrics: List[str], dimension: List[str] = None) -> Dict:
        """Получить аналитические данные."""
        url = f"{self.base_url}/v1/analytics/data"
        payload = {
            "date_from": date_from,
            "date_to": date_to,
            "metrics": metrics,
            "dimension": dimension or [],
            "filters": [],
            "sort": []
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def get_stock_analytics(self) -> Dict:
        """Аналитика остатков."""
        url = f"{self.base_url}/v4/product/info/stocks"
        payload = {"filter": {"visibility": "ALL"}, "last_id": "", "limit": 1000}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    # ==================== ФИНАНСЫ ====================
    
    def get_finance_data(self, date_from: str, date_to: str, posting_number: str = None) -> Dict:
        """Получить финансовые данные."""
        url = f"{self.base_url}/v3/finance/transaction/list"
        payload = {
            "filter": {
                "date": {"from": date_from, "to": date_to},
                "operation_type": [],
                "posting_number": posting_number or "",
                "transaction_type": "all"
            },
            "page": 1,
            "page_size": 1000
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def get_commission_info(self, product_ids: List[int]) -> Dict:
        """Получить информацию о комиссиях."""
        url = f"{self.base_url}/v4/product/info/commission"
        payload = {"product_ids": product_ids}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    # ==================== ЗАКАЗЫ ====================
    
    def get_orders_detailed(self, date_from: str, date_to: str, status: str = "") -> Dict:
        """Получить детальную информацию о заказах."""
        url = f"{self.base_url}/v3/posting/fbs/list"
        payload = {
            "dir": "ASC",
            "filter": {"since": date_from, "to": date_to, "status": status},
            "limit": 1000,
            "offset": 0,
            "with": {"analytics_data": True, "financial_data": True, "translit": True}
        }
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def update_order_status(self, posting_number: str, status: str) -> Dict:
        """Обновить статус заказа."""
        url = f"{self.base_url}/v2/posting/fbs/ship"
        payload = {"posting_number": [posting_number]}
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    
    # ==================== ПОЛНЫЙ АНАЛИЗ МАГАЗИНА ====================
    
    def get_full_store_analysis(self, days: int = 30) -> Dict:
        """Полный анализ магазина за период."""
        date_to = datetime.now().strftime("%Y-%m-%d")
        date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        try:
            # Базовые метрики
            analytics = self.get_analytics_data(
                date_from, date_to,
                metrics=["revenue", "ordered_units", "returns", "cancellations"]
            )
            
            # Остатки
            stocks = self.get_stock_analytics()
            
            # Финансы
            finances = self.get_finance_data(date_from, date_to)
            
            # Товары
            products = self.get_products(limit=1000)
            
            return {
                "period": {"from": date_from, "to": date_to},
                "analytics": analytics,
                "stocks": stocks,
                "finances": finances,
                "products": products,
                "summary": {
                    "total_products": len(products.get("result", {}).get("items", [])),
                    "low_stock_items": len([
                        item for item in stocks.get("result", {}).get("items", [])
                        if any(stock.get("present", 0) < 5 for stock in item.get("stocks", []))
                    ])
                }
            }
        except Exception as e:
            return {"error": str(e)}
