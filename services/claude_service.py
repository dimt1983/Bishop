"""
Claude API Service
==================
Сервис для работы с Claude через ProxyAPI.
Генерирует аналитические сводки, отвечает на отзывы.
"""

import os
import json
import requests
from typing import Dict, List


class ClaudeService:
    def __init__(self):
        self.api_key = os.getenv("PROXYAPI_KEY")
        self.base_url = "https://api.proxyapi.ru/anthropic/v1/messages"
        
        if not self.api_key:
            raise ValueError("PROXYAPI_KEY должен быть установлен")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        # Промпт для утренних сводок
        self.summary_prompt = """Ты — опытный аналитик магазина на маркетплейсе OZON.
Твоя задача — каждое утро готовить краткую сводку для владельца магазина.

Правила:
- Пиши на русском, по-деловому, без воды
- Используй формат для Telegram (поддерживается Markdown: *жирный*, _курсив_)
- Структура: заголовок → 3-5 ключевых цифр → 2-3 наблюдения → 1-2 рекомендации
- Если есть проблемы (отмены, низкие остатки, негатив) — выноси их в начало
- Не выдумывай данные. Опирайся только на то, что в JSON
- Длина ответа — максимум 1500 символов, чтобы влезло в Telegram"""
        
        # Промпт для ответов на отзывы
        self.review_prompt = """Ты — менеджер по работе с клиентами интернет-магазина на OZON.
Твоя задача — написать профессиональный ответ на отзыв покупателя.

Правила:
- Всегда благодари за отзыв
- Если отзыв негативный — извинись и предложи решение
- Если позитивный — поблагодари и подчеркни, что ценим клиента
- Тон: вежливый, профессиональный, по-человечески
- Длина: до 300 символов
- Не упоминай конкретные товары, если не указано"""
    
    def call_claude(self, system_prompt: str, user_message: str, model: str = "claude-haiku-4-5") -> str:
        """Базовый вызов Claude API через ProxyAPI."""
        payload = {
            "model": model,
            "max_tokens": 1500,
            "system": system_prompt,
            "messages": [{
                "role": "user",
                "content": user_message
            }]
        }
        
        try:
            response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
        except requests.exceptions.RequestException as e:
            return f"Ошибка обращения к Claude API: {e}"
        except KeyError as e:
            return f"Ошибка парсинга ответа Claude: {e}"
    
    def generate_daily_summary(self, data: Dict) -> str:
        """Сгенерировать утреннюю сводку на основе данных OZON."""
        user_message = f"Сделай утреннюю сводку на основе этих данных:\n\n{json.dumps(data, ensure_ascii=False, indent=2)}"
        return self.call_claude(self.summary_prompt, user_message)
    
    def generate_review_response(self, review_text: str, rating: int, product_name: str = "") -> str:
        """Сгенерировать ответ на отзыв."""
        user_message = f"""Отзыв покупателя:
Оценка: {rating}/5
Товар: {product_name if product_name else "не указан"}
Текст: "{review_text}"

Напиши профессиональный ответ на этот отзыв."""
        
        return self.call_claude(self.review_prompt, user_message)
    
    def generate_price_recommendation(self, sku: str, current_price: float, competitor_prices: List[float]) -> str:
        """Сгенерировать рекомендацию по цене товара."""
        prompt = """Ты — аналитик цен для интернет-магазина.
Проанализируй цену товара относительно конкурентов и дай краткую рекомендацию.

Правила:
- Учитывай среднюю цену конкурентов
- Предложи конкретное действие (поднять/опустить/оставить)
- Обоснуй рекомендацию в 1-2 предложениях
- Длина ответа: до 200 символов"""
        
        avg_competitor = sum(competitor_prices) / len(competitor_prices) if competitor_prices else current_price
        
        user_message = f"""SKU: {sku}
Наша цена: {current_price} ₽
Цены конкурентов: {competitor_prices}
Средняя цена конкурентов: {avg_competitor:.2f} ₽

Дай рекомендацию по цене."""
        
        return self.call_claude(prompt, user_message)
