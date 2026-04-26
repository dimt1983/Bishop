"""
Claude Service - МАКСИМАЛЬНЫЙ ФУНКЦИОНАЛ
=========================================
AI-сервис для глубокого анализа и управления OZON магазином:
- Анализ карточек товаров
- SEO-оптимизация
- Ценовые стратегии
- Генерация контента
- Анализ конкурентов
"""

import os
import json
import requests
from typing import Dict, List, Optional
import re


class ClaudeServiceFull:
    def __init__(self):
        self.api_key = os.getenv("PROXYAPI_KEY")
        self.base_url = "https://api.proxyapi.ru/anthropic/v1/messages"
        
        if not self.api_key:
            raise ValueError("PROXYAPI_KEY должен быть установлен")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def call_claude(self, system_prompt: str, user_message: str, model: str = "claude-haiku-4-5") -> str:
        """Базовый вызов Claude API."""
        payload = {
            "model": model,
            "max_tokens": 4000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}]
        }
        
        try:
            response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
        except requests.exceptions.RequestException as e:
            return f"Ошибка API: {e}"
        except KeyError as e:
            return f"Ошибка парсинга: {e}"
    
    # ==================== АНАЛИЗ КАРТОЧЕК ====================
    
    def analyze_product_card(self, product_data: Dict) -> str:
        """Анализ карточки товара с рекомендациями."""
        prompt = """Ты — эксперт по маркетплейсам и SEO-оптимизации товарных карточек на OZON.
        
Проанализируй карточку товара и дай конкретные рекомендации по улучшению:

АНАЛИЗИРУЙ:
1. Название товара (SEO, ключевые слова, читаемость)
2. Описание (полнота, структура, преимущества)
3. Характеристики (достаточность, точность)
4. Цену (конкурентоспособность)
5. Категорию (правильность размещения)
6. Изображения (количество, качество описаний)

ДАЙ РЕКОМЕНДАЦИИ:
- Что улучшить СРОЧНО
- Что добавить для SEO
- Как повысить конверсию
- Ценовые рекомендации

Формат ответа: структурированный отчёт до 2000 символов."""
        
        user_message = f"Проанализируй карточку товара:\n\n{json.dumps(product_data, ensure_ascii=False, indent=2)}"
        return self.call_claude(prompt, user_message, "claude-opus-4-7")
    
    def optimize_product_title(self, current_title: str, category: str, keywords: List[str] = None) -> str:
        """Оптимизировать название товара."""
        prompt = """Ты — эксперт по SEO-оптимизации названий товаров на OZON.
        
Оптимизируй название товара для максимальной видимости в поиске:

ТРЕБОВАНИЯ:
- Длина: 100-150 символов (максимум эффективности)
- Ключевые слова в начале
- Читаемость для покупателей
- Соответствие категории OZON
- Без переспама ключевых слов

СТРУКТУРА:
[Основное ключевое слово] [Бренд/Модель] [Характеристики] [Дополнительные преимущества]

Верни только оптимизированное название, без комментариев."""
        
        keywords_text = f"Ключевые слова: {', '.join(keywords)}" if keywords else ""
        user_message = f"""Текущее название: {current_title}
Категория: {category}
{keywords_text}

Оптимизируй название:"""
        
        return self.call_claude(prompt, user_message)
    
    def generate_product_description(self, product_info: Dict) -> str:
        """Сгенерировать описание товара."""
        prompt = """Ты — копирайтер, специализирующийся на описаниях товаров для маркетплейсов.
        
Создай продающее описание товара для OZON:

СТРУКТУРА:
1. Цепляющий заголовок с главным преимуществом
2. Список ключевых преимуществ (3-5 пунктов)
3. Подробное описание характеристик
4. Варианты использования/применения
5. Гарантии и доверие (если есть)

СТИЛЬ:
- Убедительно, но не навязчиво
- Фокус на выгодах покупателя
- Конкретные характеристики
- Эмоциональные триггеры
- Длина: 800-1500 символов

Используй разметку для OZON (жирный текст, списки)."""
        
        user_message = f"Создай описание для товара:\n\n{json.dumps(product_info, ensure_ascii=False, indent=2)}"
        return self.call_claude(prompt, user_message, "claude-opus-4-7")
    
    # ==================== ЦЕНОВЫЕ СТРАТЕГИИ ====================
    
    def analyze_pricing_strategy(self, product_data: Dict, competitor_data: List[Dict] = None) -> str:
        """Анализ ценовой стратегии."""
        prompt = """Ты — эксперт по ценообразованию на маркетплейсах.
        
Проанализируй ценовую стратегию товара и дай рекомендации:

АНАЛИЗИРУЙ:
1. Текущую цену vs конкуренты
2. Маржинальность
3. Ценовую эластичность
4. Психологическое ценообразование
5. Возможности для акций

РЕКОМЕНДАЦИИ:
- Оптимальная цена
- Стратегия скидок
- Конкурентные преимущества
- Риски и возможности

Формат: конкретные действия + обоснование."""
        
        competitor_text = ""
        if competitor_data:
            competitor_text = f"\n\nЦены конкурентов:\n{json.dumps(competitor_data, ensure_ascii=False, indent=2)}"
        
        user_message = f"Товар:\n{json.dumps(product_data, ensure_ascii=False, indent=2)}{competitor_text}"
        return self.call_claude(prompt, user_message, "claude-opus-4-7")
    
    def suggest_dynamic_pricing(self, sales_data: Dict, market_data: Dict = None) -> str:
        """Предложить динамическое ценообразование."""
        prompt = """Ты — эксперт по динамическому ценообразованию.
        
Проанализируй данные продаж и предложи динамическую ценовую стратегию:

УЧИТЫВАЙ:
- Сезонность продаж
- Динамику спроса
- Остатки на складе
- Конкурентную среду
- Маржинальность

ПРЕДЛОЖИ:
- Правила автоматического изменения цен
- Триггеры для скидок/наценок
- Минимальные/максимальные границы
- Временные рамки изменений

Дай конкретный алгоритм действий."""
        
        market_text = ""
        if market_data:
            market_text = f"\n\nРыночные данные:\n{json.dumps(market_data, ensure_ascii=False, indent=2)}"
        
        user_message = f"Данные продаж:\n{json.dumps(sales_data, ensure_ascii=False, indent=2)}{market_text}"
        return self.call_claude(prompt, user_message)
    
    # ==================== SEO И КОНТЕНТ ====================
    
    def generate_seo_keywords(self, product_name: str, category: str, attributes: Dict) -> List[str]:
        """Сгенерировать SEO ключевые слова."""
        prompt = """Ты — SEO-эксперт для маркетплейсов.
        
Сгенерируй список ключевых слов для товара на OZON:

ТИПЫ КЛЮЧЕВЫХ СЛОВ:
1. Основные (название товара)
2. Категорийные (тип товара)
3. Атрибутные (характеристики)
4. Коммерческие (купить, цена, заказать)
5. Длинный хвост (конкретные запросы)

Верни список из 20-30 ключевых фраз, отсортированных по важности.
Формат: одна фраза на строке, без нумерации."""
        
        user_message = f"""Товар: {product_name}
Категория: {category}
Характеристики: {json.dumps(attributes, ensure_ascii=False)}

Сгенерируй ключевые слова:"""
        
        result = self.call_claude(prompt, user_message)
        return [kw.strip() for kw in result.split('\n') if kw.strip()]
    
    def optimize_product_images_alt(self, product_name: str, image_descriptions: List[str]) -> List[str]:
        """Оптимизировать ALT-тексты для изображений."""
        prompt = """Создай SEO-оптимизированные ALT-тексты для изображений товара на OZON.
        
ТРЕБОВАНИЯ:
- Описывают что на изображении
- Содержат ключевые слова товара
- Длина: 50-100 символов
- Естественные для восприятия
- Уникальные для каждого изображения

Верни по одной строке на изображение."""
        
        user_message = f"""Товар: {product_name}
Описания изображений: {json.dumps(image_descriptions, ensure_ascii=False)}

Создай ALT-тексты:"""
        
        result = self.call_claude(prompt, user_message)
        return [alt.strip() for alt in result.split('\n') if alt.strip()]
    
    # ==================== КОНКУРЕНТНЫЙ АНАЛИЗ ====================
    
    def analyze_competitors(self, our_product: Dict, competitor_products: List[Dict]) -> str:
        """Анализ конкурентов."""
        prompt = """Ты — аналитик конкурентной разведки для маркетплейсов.
        
Проведи глубокий анализ конкурентов и дай стратегические рекомендации:

АНАЛИЗИРУЙ:
1. Ценовое позиционирование
2. Качество карточек товаров
3. Уникальные преимущества конкурентов
4. Слабые места конкурентов
5. Возможности для дифференциации

РЕКОМЕНДАЦИИ:
- Как выделиться среди конкурентов
- Ценовая стратегия
- Улучшения карточки товара
- Маркетинговые преимущества

Структурированный отчёт до 2000 символов."""
        
        user_message = f"""НАШ ТОВАР:\n{json.dumps(our_product, ensure_ascii=False, indent=2)}

КОНКУРЕНТЫ:\n{json.dumps(competitor_products, ensure_ascii=False, indent=2)}

Проведи анализ:"""
        
        return self.call_claude(prompt, user_message, "claude-opus-4-7")
    
    # ==================== АВТОМАТИЗАЦИЯ И СТРАТЕГИИ ====================
    
    def generate_automation_rules(self, store_data: Dict) -> str:
        """Сгенерировать правила автоматизации."""
        prompt = """Ты — эксперт по автоматизации процессов интернет-магазинов.
        
На основе данных магазина создай набор правил автоматизации:

ОБЛАСТИ АВТОМАТИЗАЦИИ:
1. Управление ценами
2. Управление остатками
3. Ответы на отзывы
4. Обновление карточек товаров
5. Мониторинг конкурентов
6. Отчётность

ДЛЯ КАЖДОГО ПРАВИЛА УКАЖИ:
- Триггер (что запускает)
- Условие (когда выполнять)
- Действие (что делать)
- Ограничения (границы безопасности)

Конкретные, выполнимые правила."""
        
        user_message = f"Данные магазина:\n{json.dumps(store_data, ensure_ascii=False, indent=2)}"
        return self.call_claude(prompt, user_message, "claude-opus-4-7")
    
    def create_marketing_strategy(self, analytics_data: Dict) -> str:
        """Создать маркетинговую стратегию."""
        prompt = """Ты — маркетинговый стратег для интернет-магазинов.
        
На основе аналитических данных разработай комплексную маркетинговую стратегию:

СТРАТЕГИЧЕСКИЕ НАПРАВЛЕНИЯ:
1. Позиционирование товаров
2. Ценовая политика
3. Продвижение на маркетплейсе
4. Работа с ассортиментом
5. Повышение лояльности

ПЛАН ДЕЙСТВИЙ:
- Краткосрочные тактики (1-3 месяца)
- Среднесрочные стратегии (3-12 месяцев)
- Долгосрочное развитие (1+ год)

КPI И МЕТРИКИ для отслеживания результатов.

Структурированная стратегия до 3000 символов."""
        
        user_message = f"Аналитические данные:\n{json.dumps(analytics_data, ensure_ascii=False, indent=2)}"
        return self.call_claude(prompt, user_message, "claude-opus-4-7")
