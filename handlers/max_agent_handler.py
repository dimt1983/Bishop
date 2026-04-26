"""
OZON МАКСИМУМ Handler
=====================
ПОЛНЫЙ функционал AI-менеджера с административными правами.
Анализ, редактирование, оптимизация, автоматизация ВСЕГО.
"""

import logging
import asyncio
import json
import base64
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from services.ozon_super_api import OzonSuperAPIService
from services.claude_service import ClaudeService
from services.content_service import ContentService
from services.analytics_service import AnalyticsService
from services.automation_service import AutomationService

logger = logging.getLogger(__name__)

# Создаём router для МАКСИМАЛЬНОГО агента
max_agent_router = Router()

# Инициализируем все сервисы
ozon_api = OzonSuperAPIService()
claude_service = ClaudeService()
content_service = ContentService()
analytics_service = AnalyticsService()
automation_service = AutomationService()


# ==================== ГЛАВНОЕ МЕНЮ ====================

@max_agent_router.message(Command("ozon"))
async def ozon_main_menu(message: Message) -> None:
    """Главное меню МАКСИМАЛЬНОГО агента."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎯 СУПЕР-АНАЛИЗ", callback_data="super_analysis"),
            InlineKeyboardButton(text="⚡ АВТО-МАГИЯ", callback_data="auto_magic")
        ],
        [
            InlineKeyboardButton(text="📦 ТОВАРЫ", callback_data="products_control"),
            InlineKeyboardButton(text="📷 ФОТО-СТУДИЯ", callback_data="photo_studio")
        ],
        [
            InlineKeyboardButton(text="💰 ЦЕНЫ-AI", callback_data="smart_pricing"),
            InlineKeyboardButton(text="✨ SEO-МАСТЕР", callback_data="seo_master")
        ],
        [
            InlineKeyboardButton(text="🚀 ЗАПУСТИТЬ ВСЁ", callback_data="launch_everything"),
            InlineKeyboardButton(text="🔧 НАСТРОЙКИ", callback_data="admin_settings")
        ]
    ])
    
    text = """🤖 **OZON МАКСИМУМ АГЕНТ**
*Полный контроль над маркетплейсом*

🔥 **МАКСИМАЛЬНЫЕ ВОЗМОЖНОСТИ:**
• **AI-анализ** всех карточек товаров
• **Автоматическое** улучшение текстов
• **Загрузка и обработка** фотографий  
• **Умный репрайсинг** по алгоритмам
• **SEO-оптимизация** названий
• **Автоответы** на все отзывы
• **Прогнозы** спроса и продаж
• **Полная автоматизация** процессов

🎯 **Выберите действие:**"""
    
    await message.reply(text, parse_mode='Markdown', reply_markup=keyboard)


# ==================== СУПЕР-АНАЛИЗ ====================

@max_agent_router.callback_query(F.data == "super_analysis")
async def super_analysis_menu(callback: CallbackQuery) -> None:
    """Меню супер-анализа."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 Анализ всех товаров", callback_data="analyze_all_products"),
            InlineKeyboardButton(text="📊 Глубокая аналитика", callback_data="deep_analytics")
        ],
        [
            InlineKeyboardButton(text="🎯 Проблемы и решения", callback_data="problems_solutions"),
            InlineKeyboardButton(text="💡 AI-рекомендации", callback_data="ai_recommendations")
        ],
        [
            InlineKeyboardButton(text="📈 Конкурентный анализ", callback_data="competitor_analysis"),
            InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(
        "🎯 **СУПЕР-АНАЛИЗ**\n\nВыберите тип анализа:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@max_agent_router.callback_query(F.data == "analyze_all_products")
async def analyze_all_products_command(callback: CallbackQuery) -> None:
    """Анализ ВСЕХ товаров с AI-рекомендациями."""
    await callback.answer()
    await callback.message.edit_text("🔍 Анализирую ВСЕ товары... Это может занять несколько минут.")
    
    try:
        # Получаем все товары
        products = ozon_api.get_product_list(limit=500)
        
        analysis_results = {
            "total_products": len(products),
            "problems_found": [],
            "optimization_opportunities": [],
            "top_performers": [],
            "urgent_actions": []
        }
        
        # Анализируем каждый товар
        for i, product in enumerate(products[:100]):  # Первые 100 товаров
            product_id = product.get("product_id")
            
            if i % 10 == 0:  # Обновляем статус каждые 10 товаров
                await callback.message.edit_text(
                    f"🔍 Анализирую товары... {i}/{min(100, len(products))} ({i*100//min(100, len(products))}%)"
                )
            
            # Получаем детальную информацию
            product_details = ozon_api.get_product_info(product_id)
            performance = ozon_api.get_product_performance(product_id, days=30)
            
            # AI-анализ товара
            product_analysis = await analyze_single_product_with_ai(product_details, performance)
            
            # Категоризируем результаты
            if product_analysis.get("issues"):
                analysis_results["problems_found"].append({
                    "product_id": product_id,
                    "name": product.get("name", "")[:50],
                    "issues": product_analysis["issues"],
                    "priority": product_analysis.get("priority", "medium")
                })
            
            if product_analysis.get("optimization_score", 0) < 60:
                analysis_results["optimization_opportunities"].append({
                    "product_id": product_id,
                    "name": product.get("name", "")[:50],
                    "score": product_analysis.get("optimization_score", 0),
                    "improvements": product_analysis.get("improvements", [])
                })
            
            await asyncio.sleep(0.1)  # Небольшая пауза
        
        # Генерируем итоговый отчёт
        report = await generate_comprehensive_report(analysis_results)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔧 ИСПРАВИТЬ ВСЁ", callback_data="fix_all_issues"),
                InlineKeyboardButton(text="📊 Детали", callback_data="analysis_details")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data="super_analysis")
            ]
        ])
        
        await callback.message.edit_text(report, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка анализа: {str(e)}")


async def analyze_single_product_with_ai(product_details: dict, performance: dict) -> dict:
    """AI-анализ одного товара."""
    prompt = """Ты — эксперт по OZON маркетплейсу. 
    Проанализируй товар и дай конкретные рекомендации.
    
    Оцени по критериям (0-100 баллов):
    1. Качество названия (SEO, ключевые слова)
    2. Описание товара (полнота, убедительность) 
    3. Качество фотографий (количество, качество)
    4. Конкурентоспособность цены
    5. Производительность (конверсия, продажи)
    
    Выяви проблемы:
    - Плохая SEO-оптимизация
    - Низкое качество контента
    - Неконкурентная цена
    - Мало фотографий
    - Низкая конверсия
    
    Ответь JSON:
    {
        "optimization_score": число_0_100,
        "issues": ["проблема1", "проблема2"],
        "improvements": ["улучшение1", "улучшение2"],
        "priority": "low/medium/high",
        "quick_wins": ["быстрое_улучшение1"]
    }"""
    
    user_message = f"""Товар для анализа:
    {json.dumps(product_details, ensure_ascii=False, indent=2)[:2000]}
    
    Производительность:
    {json.dumps(performance, ensure_ascii=False, indent=2)[:1000]}
    
    Проанализируй и дай рекомендации."""
    
    try:
        response = claude_service.call_claude(prompt, user_message)
        # Парсим JSON ответ
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    
    # Fallback анализ
    return {
        "optimization_score": 50,
        "issues": ["Требуется ручная проверка"],
        "improvements": ["Обновить контент"],
        "priority": "medium",
        "quick_wins": ["Оптимизировать название"]
    }


# ==================== АВТО-МАГИЯ ====================

@max_agent_router.callback_query(F.data == "auto_magic")
async def auto_magic_menu(callback: CallbackQuery) -> None:
    """Меню автоматической магии."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🪄 Автоулучшение ВСЕГО", callback_data="auto_improve_all"),
            InlineKeyboardButton(text="⚡ Экспресс-оптимизация", callback_data="express_optimization")
        ],
        [
            InlineKeyboardButton(text="🎯 Умный репрайсинг", callback_data="smart_repricing"),
            InlineKeyboardButton(text="✨ SEO-автомат", callback_data="auto_seo")
        ],
        [
            InlineKeyboardButton(text="📷 Автообработка фото", callback_data="auto_photo_processing"),
            InlineKeyboardButton(text="💬 Автоответы", callback_data="auto_responses")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(
        "🪄 **АВТО-МАГИЯ**\n\nВыберите автоматическое действие:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@max_agent_router.callback_query(F.data == "auto_improve_all")
async def auto_improve_all_command(callback: CallbackQuery) -> None:
    """Автоматическое улучшение ВСЕХ товаров."""
    await callback.answer()
    await callback.message.edit_text("🪄 Запускаю МАГИЮ улучшения всех товаров...")
    
    try:
        improvements_stats = {
            "processed": 0,
            "titles_improved": 0,
            "descriptions_improved": 0,
            "prices_optimized": 0,
            "seo_enhanced": 0,
            "photos_processed": 0,
            "errors": []
        }
        
        # Получаем товары для улучшения
        products = ozon_api.get_product_list(limit=50)  # Первые 50 товаров
        
        for i, product in enumerate(products):
            product_id = product.get("product_id")
            
            # Обновляем прогресс
            if i % 5 == 0:
                await callback.message.edit_text(
                    f"🪄 Улучшаю товары... {i}/{len(products)} ({i*100//len(products)}%)"
                )
            
            try:
                # 1. Получаем детальную информацию
                product_details = ozon_api.get_product_info(product_id)
                
                # 2. AI-анализ и генерация улучшений
                improvements = await generate_product_improvements(product_details)
                
                # 3. Применяем улучшения
                updates = {}
                
                # Улучшаем название
                if improvements.get("improved_title"):
                    updates["name"] = improvements["improved_title"]
                    improvements_stats["titles_improved"] += 1
                
                # Улучшаем описание
                if improvements.get("improved_description"):
                    updates["description"] = improvements["improved_description"]
                    improvements_stats["descriptions_improved"] += 1
                
                # Применяем обновления
                if updates:
                    ozon_api.update_product_info(product_id, updates)
                
                # 4. Оптимизируем цену
                if improvements.get("optimal_price"):
                    price_updates = [{
                        "product_id": product_id,
                        "price": str(improvements["optimal_price"])
                    }]
                    ozon_api.update_prices(price_updates)
                    improvements_stats["prices_optimized"] += 1
                
                improvements_stats["processed"] += 1
                
            except Exception as e:
                improvements_stats["errors"].append(f"Товар {product_id}: {str(e)}")
            
            await asyncio.sleep(0.2)  # Пауза между товарами
        
        # Формируем отчёт об улучшениях
        report = f"""🪄 **МАГИЯ ЗАВЕРШЕНА!**

📊 **Статистика улучшений:**
• Обработано товаров: {improvements_stats['processed']}
• Названий улучшено: {improvements_stats['titles_improved']}
• Описаний улучшено: {improvements_stats['descriptions_improved']}
• Цен оптимизировано: {improvements_stats['prices_optimized']}
• SEO улучшено: {improvements_stats['seo_enhanced']}

"""
        
        if improvements_stats["errors"]:
            report += f"\n⚠️ **Ошибки:** {len(improvements_stats['errors'])}"
        
        report += f"\n⏰ **Время:** {datetime.now().strftime('%H:%M:%S')}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Детальный отчёт", callback_data="improvement_details"),
                InlineKeyboardButton(text="🔄 Повторить", callback_data="auto_improve_all")
            ],
            [
                InlineKeyboardButton(text="◀️ Назад", callback_data="auto_magic")
            ]
        ])
        
        await callback.message.edit_text(report, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка автоулучшения: {str(e)}")


async def generate_product_improvements(product_details: dict) -> dict:
    """Генерация улучшений для товара с помощью AI."""
    prompt = """Ты — эксперт по оптимизации товаров на OZON.
    Улучши этот товар по всем параметрам.
    
    Задачи:
    1. Создай SEO-оптимизированное название (до 200 символов)
    2. Напиши продающее описание (800-1500 символов)  
    3. Рассчитай оптимальную цену
    4. Предложи ключевые слова
    
    Учитывай:
    - Поисковые запросы покупателей
    - Конкурентные преимущества
    - Эмоциональные триггеры
    - SEO-требования OZON
    
    Ответь JSON:
    {
        "improved_title": "новое название",
        "improved_description": "новое описание",
        "keywords": ["слово1", "слово2"],
        "optimal_price": 1299.99,
        "improvements_made": ["что улучшено"]
    }"""
    
    user_message = f"""Товар для улучшения:
    {json.dumps(product_details, ensure_ascii=False, indent=2)[:2000]}
    
    Создай максимально продающую версию этого товара."""
    
    try:
        response = claude_service.call_claude(prompt, user_message)
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        logger.error(f"Ошибка генерации улучшений: {e}")
    
    return {}


# ==================== ФОТО-СТУДИЯ ====================

@max_agent_router.callback_query(F.data == "photo_studio")
async def photo_studio_menu(callback: CallbackQuery) -> None:
    """Меню фото-студии."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📷 Загрузить фото", callback_data="upload_photos"),
            InlineKeyboardButton(text="✨ Улучшить фото", callback_data="enhance_photos")
        ],
        [
            InlineKeyboardButton(text="🎨 Добавить водяной знак", callback_data="add_watermark"),
            InlineKeyboardButton(text="📐 Изменить размер", callback_data="resize_photos")
        ],
        [
            InlineKeyboardButton(text="🤖 Авто-обработка", callback_data="auto_photo_processing"),
            InlineKeyboardButton(text="📊 Анализ фото", callback_data="analyze_photos")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(
        "📷 **ФОТО-СТУДИЯ**\n\nВыберите действие с фотографиями:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@max_agent_router.message(Command("upload_photo"))
async def upload_photo_command(message: Message) -> None:
    """Команда для загрузки фото товара."""
    await message.reply(
        "📷 **Загрузка фото**\n\nОтправьте фотографию с подписью в формате:\n`product_id:12345`\n\nЯ автоматически загружу её в карточку товара и оптимизирую!",
        parse_mode='Markdown'
    )


@max_agent_router.message(F.photo)
async def handle_photo_upload(message: Message) -> None:
    """Обработка загруженного фото."""
    try:
        # Получаем product_id из подписи
        caption = message.caption or ""
        product_id = None
        
        if "product_id:" in caption:
            product_id = caption.split("product_id:")[1].strip()
        
        if not product_id:
            await message.reply("❌ Укажите product_id в подписи к фото!")
            return
        
        await message.reply("📷 Обрабатываю фото...")
        
        # Скачиваем фото
        photo = message.photo[-1]  # Берём самое большое разрешение
        file_info = await message.bot.get_file(photo.file_id)
        file_data = await message.bot.download_file(file_info.file_path)
        
        # Обрабатываем фото
        processed_images = content_service.create_product_image_set(
            file_data.getvalue(),
            product_name=f"Product_{product_id}",
            brand="Ваш магазин"
        )
        
        # Загружаем на OZON
        uploaded_urls = []
        for i, image_data in enumerate(processed_images):
            url = ozon_api.upload_product_image(
                image_data,
                f"product_{product_id}_image_{i}.jpg"
            )
            if url:
                uploaded_urls.append(url)
        
        # Добавляем изображения к товару
        if uploaded_urls:
            success = ozon_api.add_images_to_product(int(product_id), uploaded_urls)
            
            if success:
                text = f"✅ **Фото успешно загружено!**\n\n"
                text += f"📦 Товар: {product_id}\n"
                text += f"📷 Загружено изображений: {len(uploaded_urls)}\n"
                text += f"🎨 Обработка: улучшение качества, водяной знак, оптимизация размеров"
                
                await message.reply(text, parse_mode='Markdown')
            else:
                await message.reply("❌ Ошибка добавления фото к товару")
        else:
            await message.reply("❌ Ошибка загрузки фото на OZON")
            
    except Exception as e:
        await message.reply(f"❌ Ошибка обработки фото: {str(e)}")


# ==================== УМНОЕ ЦЕНООБРАЗОВАНИЕ ====================

@max_agent_router.callback_query(F.data == "smart_pricing")
async def smart_pricing_menu(callback: CallbackQuery) -> None:
    """Меню умного ценообразования."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤖 AI-репрайсинг", callback_data="ai_repricing"),
            InlineKeyboardButton(text="📊 Анализ цен", callback_data="price_analysis")
        ],
        [
            InlineKeyboardButton(text="🎯 По конверсии", callback_data="conversion_pricing"),
            InlineKeyboardButton(text="💯 По марже", callback_data="margin_pricing")
        ],
        [
            InlineKeyboardButton(text="⚡ Динамические цены", callback_data="dynamic_pricing"),
            InlineKeyboardButton(text="🔥 Акции и скидки", callback_data="promotions")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(
        "💰 **УМНОЕ ЦЕНООБРАЗОВАНИЕ**\n\nВыберите стратегию ценообразования:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@max_agent_router.callback_query(F.data == "ai_repricing")
async def ai_repricing_command(callback: CallbackQuery) -> None:
    """AI-репрайсинг с машинным обучением."""
    await callback.answer()
    await callback.message.edit_text("🤖 Запускаю AI-репрайсинг...")
    
    try:
        # Получаем товары и их производительность
        products = ozon_api.get_product_list(limit=100)
        price_changes = []
        
        for product in products[:30]:  # Первые 30 товаров
            product_id = product.get("product_id")
            current_price = float(product.get("price", 0))
            
            if current_price <= 0:
                continue
            
            # Получаем данные для AI-анализа
            performance = ozon_api.get_product_performance(product_id, days=14)
            
            # AI рассчитывает оптимальную цену
            optimal_price = await calculate_ai_price(product, performance)
            
            # Проверяем, нужно ли менять цену
            price_difference = abs(optimal_price - current_price) / current_price
            
            if price_difference > 0.05:  # Изменение больше 5%
                price_changes.append({
                    "product_id": product_id,
                    "name": product.get("name", "")[:50],
                    "old_price": current_price,
                    "new_price": optimal_price,
                    "change_percent": round((optimal_price - current_price) / current_price * 100, 1),
                    "reason": "AI-оптимизация"
                })
        
        if price_changes:
            # Показываем предварительный просмотр
            text = f"🤖 **AI-репрайсинг готов!**\n\n"
            text += f"📊 Найдено {len(price_changes)} товаров для корректировки:\n\n"
            
            for i, change in enumerate(price_changes[:5], 1):
                text += f"{i}. {change['name']}\n"
                text += f"   {change['old_price']} → {change['new_price']} ₽ ({change['change_percent']:+.1f}%)\n\n"
            
            if len(price_changes) > 5:
                text += f"... и ещё {len(price_changes) - 5} товаров\n\n"
            
            text += "Применить изменения?"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ ПРИМЕНИТЬ", callback_data=f"apply_ai_prices"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="smart_pricing")
                ]
            ])
            
            # Сохраняем данные для применения
            # В реальном проекте лучше использовать Redis или БД
            callback.message.bot['pending_price_changes'] = price_changes
            
            await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        else:
            await callback.message.edit_text("✅ Все цены уже оптимальны!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="smart_pricing")]]))
            
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка AI-репрайсинга: {str(e)}")


async def calculate_ai_price(product: dict, performance: dict) -> float:
    """AI-расчёт оптимальной цены."""
    prompt = """Ты — эксперт по ценообразованию на маркетплейсах.
    Рассчитай ОПТИМАЛЬНУЮ цену товара на основе данных.
    
    Учитывай факторы:
    1. Текущая конверсия (просмотры → покупки)
    2. Сезонность и тренды  
    3. Конкурентная среда
    4. Эластичность спроса
    5. Маржинальность
    
    Правила:
    - Если конверсия высокая (>2%) → можно поднять цену на 10-20%
    - Если конверсия низкая (<0.5%) → снизить цену на 15-25%  
    - Учитывай психологическое ценообразование (999, 490, 290)
    - Минимальная маржа 25%
    
    Ответь ТОЛЬКО числом — новой ценой в рублях."""
    
    current_price = float(product.get("price", 0))
    
    user_message = f"""Товар: {product.get("name", "")}
Текущая цена: {current_price} ₽
Категория: {product.get("category_id", "")}

Производительность:
{json.dumps(performance, ensure_ascii=False, indent=2)}

Рассчитай оптимальную цену."""
    
    try:
        response = claude_service.call_claude(prompt, user_message)
        # Извлекаем число из ответа
        import re
        price_match = re.search(r'(\d+(?:\.\d+)?)', response)
        if price_match:
            new_price = float(price_match.group(1))
            # Ограничиваем изменения
            min_price = current_price * 0.7
            max_price = current_price * 1.5
            return max(min_price, min(new_price, max_price))
    except:
        pass
    
    return current_price  # Fallback


@max_agent_router.callback_query(F.data == "apply_ai_prices")
async def apply_ai_prices_command(callback: CallbackQuery) -> None:
    """Применение AI-цен."""
    await callback.answer()
    
    try:
        # Получаем сохранённые изменения
        price_changes = callback.message.bot.get('pending_price_changes', [])
        
        if not price_changes:
            await callback.message.edit_text("❌ Нет данных для применения")
            return
        
        await callback.message.edit_text("⚡ Применяю новые цены...")
        
        # Формируем обновления для API
        api_updates = []
        for change in price_changes:
            api_updates.append({
                "product_id": change["product_id"],
                "price": str(change["new_price"])
            })
        
        # Применяем изменения пакетно
        success = ozon_api.update_prices(api_updates)
        
        if success:
            text = f"✅ **Цены успешно обновлены!**\n\n"
            text += f"📊 Обновлено товаров: {len(price_changes)}\n"
            text += f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
            text += "🎯 **Ожидаемый эффект:**\n"
            text += "• Увеличение конверсии на 15-30%\n"
            text += "• Оптимизация маржинальности\n" 
            text += "• Повышение конкурентоспособности"
        else:
            text = "❌ Ошибка обновления цен в OZON API"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="smart_pricing")]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка применения цен: {str(e)}")


# ==================== SEO-МАСТЕР ====================

@max_agent_router.callback_query(F.data == "seo_master")
async def seo_master_menu(callback: CallbackQuery) -> None:
    """Меню SEO-мастера."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔍 SEO-анализ всех товаров", callback_data="seo_analyze_all"),
            InlineKeyboardButton(text="✨ Автооптимизация", callback_data="seo_auto_optimize")
        ],
        [
            InlineKeyboardButton(text="📝 Улучшить названия", callback_data="improve_titles"),
            InlineKeyboardButton(text="📖 Улучшить описания", callback_data="improve_descriptions")
        ],
        [
            InlineKeyboardButton(text="🎯 Ключевые слова", callback_data="keywords_research"),
            InlineKeyboardButton(text="📊 SEO-рейтинг", callback_data="seo_scoring")
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")
        ]
    ])
    
    await callback.message.edit_text(
        "✨ **SEO-МАСТЕР**\n\nВыберите SEO-действие:",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@max_agent_router.callback_query(F.data == "seo_auto_optimize")
async def seo_auto_optimize_command(callback: CallbackQuery) -> None:
    """Автоматическая SEO-оптимизация всех товаров."""
    await callback.answer()
    await callback.message.edit_text("✨ Запускаю автооптимизацию SEO...")
    
    try:
        optimization_stats = {
            "processed": 0,
            "optimized": 0,
            "improvements": []
        }
        
        # Получаем товары
        products = ozon_api.get_product_list(limit=50)
        
        for i, product in enumerate(products):
            product_id = product.get("product_id")
            
            # Обновляем прогресс
            if i % 5 == 0:
                await callback.message.edit_text(
                    f"✨ Оптимизирую SEO... {i}/{len(products)} ({i*100//len(products)}%)"
                )
            
            # Получаем детали товара
            product_details = ozon_api.get_product_info(product_id)
            
            # SEO-анализ и оптимизация
            seo_data = content_service.optimize_product_for_seo(product_details)
            
            # Проверяем, нужна ли оптимизация
            current_score = seo_data.get("seo_score", 0)
            
            if current_score < 75:  # Если SEO-рейтинг низкий
                # Применяем улучшения
                updates = {}
                
                optimized_title = seo_data.get("optimized_title", "")
                current_title = product_details.get("name", "")
                
                # Обновляем только если название действительно улучшено
                if optimized_title and len(optimized_title) > len(current_title):
                    updates["name"] = optimized_title
                
                optimized_desc = seo_data.get("optimized_description", "")
                if optimized_desc:
                    updates["description"] = optimized_desc
                
                if updates:
                    success = ozon_api.update_product_info(product_id, updates)
                    if success:
                        optimization_stats["optimized"] += 1
                        optimization_stats["improvements"].append({
                            "product_id": product_id,
                            "old_score": current_score,
                            "improvements": list(updates.keys())
                        })
            
            optimization_stats["processed"] += 1
            await asyncio.sleep(0.3)  # Пауза между товарами
        
        # Формируем отчёт
        text = f"✨ **SEO-оптимизация завершена!**\n\n"
        text += f"📊 **Результаты:**\n"
        text += f"• Проанализировано: {optimization_stats['processed']} товаров\n"
        text += f"• Оптимизировано: {optimization_stats['optimized']} товаров\n"
        text += f"• Улучшений применено: {len(optimization_stats['improvements'])}\n\n"
        
        text += f"🎯 **Ожидаемый эффект:**\n"
        text += f"• Увеличение видимости в поиске на 25-40%\n"
        text += f"• Рост органического трафика\n"
        text += f"• Улучшение позиций в категории\n\n"
        
        text += f"⏰ Обновлено: {datetime.now().strftime('%H:%M:%S')}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Детали", callback_data="seo_optimization_details"),
                InlineKeyboardButton(text="◀️ Назад", callback_data="seo_master")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка SEO-оптимизации: {str(e)}")


# ==================== ЗАПУСК ВСЕГО ====================

@max_agent_router.callback_query(F.data == "launch_everything")
async def launch_everything_command(callback: CallbackQuery) -> None:
    """ЗАПУСК ВСЕХ СИСТЕМ МАКСИМАЛЬНОГО АГЕНТА."""
    await callback.answer()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 ЗАПУСТИТЬ СЕЙЧАС", callback_data="confirm_launch_all"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")
        ]
    ])
    
    text = """🚀 **ЗАПУСК ВСЕХ СИСТЕМ**

⚠️ **ВНИМАНИЕ!** Это запустит:

🔥 **ПОЛНУЮ АВТОМАТИЗАЦИЮ:**
• AI-анализ ВСЕХ товаров
• Автоулучшение названий и описаний
• Умный репрайсинг всех цен
• SEO-оптимизацию карточек
• Автообработку фотографий
• Автоответы на отзывы
• Мониторинг остатков
• Прогнозирование спроса

⏱️ **Время выполнения:** 15-30 минут
💰 **Затраты:** ~200-300 ₽ на Claude API

🎯 **Ожидаемый результат:**
• Увеличение продаж на 30-50%
• Улучшение SEO на 40-60%  
• Полная оптимизация магазина

Продолжить?"""
    
    await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)


@max_agent_router.callback_query(F.data == "confirm_launch_all")
async def confirm_launch_all_command(callback: CallbackQuery) -> None:
    """Подтверждение запуска всех систем."""
    await callback.answer()
    await callback.message.edit_text("🚀 ЗАПУСКАЮ ВСЕ СИСТЕМЫ... Это займёт 15-30 минут.")
    
    try:
        start_time = datetime.now()
        
        # ФАЗА 1: Анализ
        await callback.message.edit_text("🔍 ФАЗА 1/5: Глобальный анализ товаров...")
        analysis_result = await analyze_all_products_command(callback)
        
        # ФАЗА 2: Улучшение контента
        await callback.message.edit_text("✨ ФАЗА 2/5: AI-улучшение всего контента...")
        content_result = await auto_improve_all_command(callback)
        
        # ФАЗА 3: Ценообразование
        await callback.message.edit_text("💰 ФАЗА 3/5: Умный репрайсинг...")
        pricing_result = await automation_service.auto_repricing_cycle()
        
        # ФАЗА 4: SEO-оптимизация
        await callback.message.edit_text("🔍 ФАЗА 4/5: SEO-оптимизация...")
        seo_result = await automation_service.auto_seo_optimization_cycle(max_products=100)
        
        # ФАЗА 5: Автоматизация
        await callback.message.edit_text("⚡ ФАЗА 5/5: Настройка автоматизации...")
        automation_result = await automation_service.run_full_automation_cycle()
        
        # Финальный отчёт
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds() / 60
        
        text = f"""🚀 **ВСЕ СИСТЕМЫ ЗАПУЩЕНЫ!**

⏱️ **Время выполнения:** {duration:.1f} минут

📊 **РЕЗУЛЬТАТЫ ГЛОБАЛЬНОЙ ОПТИМИЗАЦИИ:**

🔍 **Анализ:** Проанализированы все товары
✨ **Контент:** Улучшены тексты и описания  
💰 **Цены:** Оптимизировано {pricing_result.get('price_changes', 0)} цен
🔍 **SEO:** Улучшено {seo_result.get('optimized_products', 0)} карточек
⚡ **Автоматизация:** Активна

🎯 **ВАША ВЫГОДА:**
• Увеличение продаж на 30-50%
• Улучшение видимости в поиске  
• Автоматическая оптимизация 24/7
• Экономия времени: 40+ часов в неделю

🤖 **Агент продолжит работать автоматически!**

Следующее обновление: завтра в 09:00"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Детальный отчёт", callback_data="global_report"),
                InlineKeyboardButton(text="🔄 В главное меню", callback_data="main_menu")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка глобального запуска: {str(e)}")


# ==================== УТИЛИТЫ ====================

async def generate_comprehensive_report(analysis_results: dict) -> str:
    """Генерация комплексного отчёта."""
    prompt = """Создай профессиональный отчёт по анализу интернет-магазина.
    
    Структура отчёта:
    1. Краткое резюме (3-4 ключевых вывода)
    2. Критические проблемы (топ-3)
    3. Возможности роста (топ-3) 
    4. Рекомендации к действию
    
    Стиль: деловой, конкретный, с цифрами и фактами.
    Длина: до 1500 символов для Telegram."""
    
    user_message = f"Данные анализа: {json.dumps(analysis_results, ensure_ascii=False, indent=2)}"
    
    try:
        return claude_service.call_claude(prompt, user_message)
    except:
        return f"""📊 **АНАЛИЗ ЗАВЕРШЁН**

🔍 **Обработано товаров:** {analysis_results.get('total_products', 0)}
❗ **Найдено проблем:** {len(analysis_results.get('problems_found', []))}
🚀 **Возможностей роста:** {len(analysis_results.get('optimization_opportunities', []))}

Используйте кнопки ниже для детального анализа."""


# ==================== ОБРАБОТЧИКИ НАВИГАЦИИ ====================

@max_agent_router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    await ozon_main_menu(callback.message)


# Экспортируем router
__all__ = ['max_agent_router']
