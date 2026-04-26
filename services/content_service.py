"""
Content Management Service
==========================
Сервис для работы с изображениями, генерации контента, SEO оптимизации.
"""

import os
import requests
import base64
from PIL import Image, ImageEnhance, ImageDraw, ImageFont
from io import BytesIO
from typing import List, Dict, Optional, Union
from services.claude_service import ClaudeService


class ContentService:
    def __init__(self):
        self.claude_service = ClaudeService()
    
    # ==================== РАБОТА С ИЗОБРАЖЕНИЯМИ ====================
    
    def process_image(self, image_data: bytes, operations: Dict) -> bytes:
        """Обработать изображение по заданным параметрам."""
        image = Image.open(BytesIO(image_data))
        
        # Изменение размера
        if "resize" in operations:
            width, height = operations["resize"]
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        
        # Обрезка по центру
        if "crop_center" in operations:
            width, height = operations["crop_center"]
            img_width, img_height = image.size
            
            left = (img_width - width) // 2
            top = (img_height - height) // 2
            right = left + width
            bottom = top + height
            
            image = image.crop((left, top, right, bottom))
        
        # Улучшение качества
        if "enhance" in operations:
            enhancers = operations["enhance"]
            if "brightness" in enhancers:
                enhancer = ImageEnhance.Brightness(image)
                image = enhancer.enhance(enhancers["brightness"])
            if "contrast" in enhancers:
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(enhancers["contrast"])
            if "color" in enhancers:
                enhancer = ImageEnhance.Color(image)
                image = enhancer.enhance(enhancers["color"])
            if "sharpness" in enhancers:
                enhancer = ImageEnhance.Sharpness(image)
                image = enhancer.enhance(enhancers["sharpness"])
        
        # Добавление водяного знака
        if "watermark" in operations:
            watermark_text = operations["watermark"].get("text", "")
            position = operations["watermark"].get("position", "bottom_right")
            opacity = operations["watermark"].get("opacity", 128)
            
            if watermark_text:
                image = self.add_text_watermark(image, watermark_text, position, opacity)
        
        # Конвертация в нужный формат
        output_format = operations.get("format", "JPEG")
        output_buffer = BytesIO()
        
        if output_format.upper() == "JPEG" and image.mode in ("RGBA", "LA", "P"):
            # Конвертация для JPEG
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
            image = background
        
        image.save(output_buffer, format=output_format, quality=95, optimize=True)
        return output_buffer.getvalue()
    
    def add_text_watermark(self, image: Image.Image, text: str, 
                          position: str = "bottom_right", opacity: int = 128) -> Image.Image:
        """Добавить текстовый водяной знак."""
        # Создаём прозрачный слой для водяного знака
        overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Пытаемся использовать системный шрифт
        try:
            font_size = max(20, min(image.size) // 20)
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            font = ImageFont.load_default()
        
        # Вычисляем размер текста
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Определяем позицию
        margin = 20
        if position == "bottom_right":
            x = image.size[0] - text_width - margin
            y = image.size[1] - text_height - margin
        elif position == "bottom_left":
            x = margin
            y = image.size[1] - text_height - margin
        elif position == "top_right":
            x = image.size[0] - text_width - margin
            y = margin
        elif position == "top_left":
            x = margin
            y = margin
        elif position == "center":
            x = (image.size[0] - text_width) // 2
            y = (image.size[1] - text_height) // 2
        else:
            x, y = margin, margin
        
        # Рисуем текст
        draw.text((x, y), text, fill=(255, 255, 255, opacity), font=font)
        
        # Накладываем водяной знак на оригинальное изображение
        result = Image.alpha_composite(image.convert("RGBA"), overlay)
        return result.convert("RGB")
    
    def create_product_image_set(self, main_image_data: bytes, 
                               product_name: str, brand: str = "") -> List[bytes]:
        """Создать набор изображений для товара (основное + вариации)."""
        images = []
        
        # Основное изображение (1200x1200)
        main_processed = self.process_image(main_image_data, {
            "resize": (1200, 1200),
            "enhance": {"contrast": 1.1, "sharpness": 1.1},
            "format": "JPEG"
        })
        images.append(main_processed)
        
        # Изображение с водяным знаком бренда
        if brand:
            branded = self.process_image(main_image_data, {
                "resize": (1200, 1200),
                "watermark": {"text": brand, "position": "bottom_right", "opacity": 100},
                "format": "JPEG"
            })
            images.append(branded)
        
        # Квадратное для соцсетей (800x800)
        square = self.process_image(main_image_data, {
            "crop_center": (800, 800),
            "enhance": {"contrast": 1.05},
            "format": "JPEG"
        })
        images.append(square)
        
        return images
    
    # ==================== ГЕНЕРАЦИЯ КОНТЕНТА ====================
    
    def generate_product_title(self, product_info: Dict, target_keywords: List[str]) -> str:
        """Сгенерировать SEO-оптимизированное название товара."""
        prompt = """Ты — эксперт по SEO и маркетингу на маркетплейсах.
Создай продающее название товара для OZON, которое:
1. Содержит ключевые слова для поиска
2. Привлекает внимание покупателей
3. Соответствует правилам OZON (до 200 символов)
4. Указывает основные характеристики

Правила:
- Начинай с категории товара или бренда
- Включи цвет, размер, материал (если есть)
- Добавь УТП (уникальное торговое предложение)
- Используй слова-триггеры: "новый", "улучшенный", "премиум"
- БЕЗ капслока и восклицательных знаков
"""
        
        user_message = f"""Информация о товаре:
{json.dumps(product_info, ensure_ascii=False, indent=2)}

Целевые ключевые слова: {', '.join(target_keywords)}

Создай оптимальное название для этого товара."""
        
        return self.claude_service.call_claude(prompt, user_message)
    
    def generate_product_description(self, product_info: Dict, 
                                   competitor_analysis: Dict = None) -> str:
        """Сгенерировать описание товара."""
        prompt = """Ты — копирайтер интернет-магазина.
Напиши продающее описание товара для OZON.

Структура описания:
1. Яркий заголовок с пользой
2. 3-5 ключевых преимуществ (маркированный список)
3. Подробные характеристики
4. Сценарии использования
5. Гарантии и доставка

Стиль:
- Ориентация на выгоду клиента
- Простой, понятный язык
- Убедительные аргументы
- Без воды и лишних слов
- Длина: 800-1500 символов"""
        
        competitor_text = ""
        if competitor_analysis:
            competitor_text = f"\n\nАнализ конкурентов:\n{json.dumps(competitor_analysis, ensure_ascii=False, indent=2)}"
        
        user_message = f"""Информация о товаре:
{json.dumps(product_info, ensure_ascii=False, indent=2)}{competitor_text}

Напиши продающее описание для этого товара."""
        
        return self.claude_service.call_claude(prompt, user_message)
    
    def generate_review_response(self, review_text: str, rating: int, 
                               product_name: str, brand_voice: str = "friendly") -> str:
        """Сгенерировать ответ на отзыв."""
        brand_styles = {
            "friendly": "дружелюбный, неформальный, с эмпатией",
            "professional": "профессиональный, вежливый, деловой",
            "caring": "заботливый, понимающий, личностный",
            "confident": "уверенный, компетентный, авторитетный"
        }
        
        style = brand_styles.get(brand_voice, brand_styles["friendly"])
        
        prompt = f"""Ты — менеджер по работе с клиентами интернет-магазина.
Напиши ответ на отзыв покупателя в стиле: {style}.

Правила для ответа:
- Всегда благодари за обратную связь
- Если отзыв позитивный — поддержи радость клиента
- Если негативный — признай проблему, извинись, предложи решение
- Если нейтральный — узнай, как улучшить опыт
- Упоминай название товара естественно
- Длина: до 300 символов
- Тон: {style}
- БЕЗ шаблонности и формализма"""
        
        user_message = f"""Отзыв покупателя:
Товар: {product_name}
Оценка: {rating}/5 звёзд
Текст отзыва: "{review_text}"

Напиши персональный ответ на этот отзыв."""
        
        return self.claude_service.call_claude(prompt, user_message)
    
    def generate_keywords_for_product(self, product_info: Dict) -> List[str]:
        """Сгенерировать ключевые слова для продвижения товара."""
        prompt = """Ты — специалист по SEO на маркетплейсах.
Создай список из 15-20 ключевых слов для продвижения товара в поиске OZON.

Типы ключевых слов:
1. Прямые (точное название товара)
2. Ассоциативные (синонимы и похожие товары)
3. Низкочастотные (длинные фразы)
4. Потребностные (для чего используется)
5. Сезонные (если применимо)

Формат ответа: список слов через запятую."""
        
        user_message = f"""Информация о товаре:
{json.dumps(product_info, ensure_ascii=False, indent=2)}

Создай список ключевых слов для этого товара."""
        
        keywords_text = self.claude_service.call_claude(prompt, user_message)
        
        # Парсим ответ в список
        keywords = [kw.strip() for kw in keywords_text.split(',')]
        return [kw for kw in keywords if kw and len(kw) > 2]
    
    def optimize_product_for_seo(self, product_info: Dict) -> Dict:
        """Комплексная SEO-оптимизация товара."""
        # Генерируем ключевые слова
        keywords = self.generate_keywords_for_product(product_info)
        
        # Создаём оптимизированное название
        title = self.generate_product_title(product_info, keywords[:5])
        
        # Создаём описание
        description = self.generate_product_description(product_info)
        
        return {
            "optimized_title": title,
            "optimized_description": description,
            "keywords": keywords,
            "seo_score": self.calculate_seo_score(title, description, keywords),
            "recommendations": self.get_seo_recommendations(product_info, keywords)
        }
    
    def calculate_seo_score(self, title: str, description: str, keywords: List[str]) -> int:
        """Рассчитать SEO-рейтинг карточки товара (0-100)."""
        score = 0
        
        # Проверка названия (30 баллов)
        if len(title) >= 50:
            score += 10
        if any(kw.lower() in title.lower() for kw in keywords[:3]):
            score += 15
        if len(title.split()) >= 4:
            score += 5
        
        # Проверка описания (40 баллов)
        if len(description) >= 500:
            score += 15
        if len(description) <= 2000:
            score += 5
        if any(kw.lower() in description.lower() for kw in keywords[:5]):
            score += 20
        
        # Проверка ключевых слов (30 баллов)
        if len(keywords) >= 10:
            score += 15
        if len(keywords) >= 15:
            score += 15
        
        return min(score, 100)
    
    def get_seo_recommendations(self, product_info: Dict, keywords: List[str]) -> List[str]:
        """Получить рекомендации по улучшению SEO."""
        recommendations = []
        
        current_title = product_info.get("name", "")
        current_description = product_info.get("description", "")
        
        # Рекомендации по названию
        if len(current_title) < 50:
            recommendations.append("Увеличьте длину названия до 50+ символов")
        
        if not any(kw.lower() in current_title.lower() for kw in keywords[:3]):
            recommendations.append(f"Добавьте в название ключевые слова: {', '.join(keywords[:3])}")
        
        # Рекомендации по описанию
        if len(current_description) < 500:
            recommendations.append("Расширьте описание до 500+ символов")
        
        if len(current_description) > 2000:
            recommendations.append("Сократите описание до 2000 символов")
        
        # Рекомендации по изображениям
        images_count = len(product_info.get("images", []))
        if images_count < 3:
            recommendations.append(f"Добавьте больше изображений (сейчас: {images_count}, рекомендуется: 5-10)")
        
        return recommendations
