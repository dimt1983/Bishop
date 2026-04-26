"""
Обёртка над Anthropic API через ProxyAPI.

ProxyAPI — прозрачный прокси, формат запросов идентичен Anthropic.
Документация: https://proxyapi.ru/docs
"""
from __future__ import annotations

import os
from typing import Any

import aiohttp


PROXYAPI_URL = "https://api.proxyapi.ru/anthropic/v1/messages"

# Модель по умолчанию. Поменять можно одной строкой.
# Варианты: claude-haiku-4-5, claude-sonnet-4-5, claude-opus-4-7
DEFAULT_MODEL = "claude-sonnet-4-5"


class ClaudeError(Exception):
    pass


class ClaudeService:
    """Минимальный клиент Claude через ProxyAPI."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.getenv("PROXYAPI_KEY")
        if not self.api_key:
            raise ValueError("PROXYAPI_KEY должен быть установлен")
        self.model = model

    async def ask(
        self,
        user_message: str,
        system: str = "",
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> str:
        """Простой запрос: отправили текст — получили текст."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user_message}],
        }
        if system:
            payload["system"] = system

        async with aiohttp.ClientSession() as session:
            async with session.post(
                PROXYAPI_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise ClaudeError(f"ProxyAPI [{resp.status}]: {text}")
                data = await resp.json()

        # Достаём текст из ответа
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ClaudeError(f"Неожиданный формат ответа: {data}") from exc
