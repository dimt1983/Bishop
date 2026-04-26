"""
OZON Scheduler Service
======================
Сервис для планирования ежедневной отправки сводок.
Интегрируется с существующим scheduler'ом в проекте.
"""

import os
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from handlers.ozon_agent_aiogram import send_daily_summary_to_chat


class OzonSchedulerService:
    def __init__(self, bot):
        self.bot = bot
        self.chat_id = os.getenv("OZON_DAILY_CHAT_ID", "-1003522003335")
    
    def setup_ozon_jobs(self, scheduler: AsyncIOScheduler):
        """Добавить OZON задачи в существующий scheduler."""
        
        # Ежедневная сводка в 9:00 МСК (6:00 UTC)
        scheduler.add_job(
            self._send_daily_summary,
            trigger="cron",
            hour=6,
            minute=0,
            timezone="UTC",
            id="ozon_daily_summary",
            name="OZON Daily Summary",
            replace_existing=True
        )
    
    async def _send_daily_summary(self):
        """Внутренний метод для отправки сводки."""
        await send_daily_summary_to_chat(self.bot, self.chat_id)
