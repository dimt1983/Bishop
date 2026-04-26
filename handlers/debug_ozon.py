"""
Простая OZON команда для отладки
"""

import logging
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

logger = logging.getLogger(__name__)

# Простой router
debug_ozon_router = Router()


@debug_ozon_router.message(Command("oztest"))
async def oztest_command(message: Message) -> None:
    """Простая тестовая команда."""
    await message.reply("✅ OZON команда работает! Интеграция успешна!")


@debug_ozon_router.message(Command("ozstatus"))
async def ozstatus_command(message: Message) -> None:
    """Статус OZON переменных."""
    import os
    
    client_id = os.getenv("OZON_CLIENT_ID")
    api_key = os.getenv("OZON_API_KEY") 
    proxyapi = os.getenv("PROXYAPI_KEY")
    
    status = "🔍 **Статус OZON переменных:**\n\n"
    status += f"{'✅' if client_id else '❌'} OZON_CLIENT_ID\n"
    status += f"{'✅' if api_key else '❌'} OZON_API_KEY\n"
    status += f"{'✅' if proxyapi else '❌'} PROXYAPI_KEY\n"
    
    await message.reply(status, parse_mode='Markdown')
