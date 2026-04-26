"""
Клиент OZON Seller API.

Использует актуальные endpoints (проверено по докам на апрель 2026):
- v3/product/list           — список товаров
- v3/product/info/list      — информация о товарах (батчем)
- v3/posting/fbs/list       — заказы FBS
- v1/product/info/stocks    — остатки
- v1/review/list            — отзывы (требует подписку Premium)
- v2/product/pictures/info  — фото товара
- v1/product/pictures/import — загрузка фото

Документация: https://docs.ozon.ru/api/seller/
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any

import aiohttp


OZON_BASE_URL = "https://api-seller.ozon.ru"


class OzonAPIError(Exception):
    """Ошибка при работе с OZON API."""

    def __init__(self, status: int, message: str, endpoint: str = ""):
        self.status = status
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"[{status}] {endpoint}: {message}")


class OzonAPI:
    """Асинхронный клиент OZON Seller API."""

    def __init__(self, client_id: str | None = None, api_key: str | None = None):
        self.client_id = client_id or os.getenv("OZON_CLIENT_ID")
        self.api_key = api_key or os.getenv("OZON_API_KEY")
        if not self.client_id or not self.api_key:
            raise ValueError(
                "OZON_CLIENT_ID и OZON_API_KEY должны быть установлены"
            )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Client-Id": str(self.client_id),
            "Api-Key": str(self.api_key),
            "Content-Type": "application/json",
        }

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Базовый POST-запрос к OZON API."""
        url = f"{OZON_BASE_URL}{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=self.headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise OzonAPIError(resp.status, text, endpoint)
                return await resp.json()

    # ------------------------------------------------------------------ #
    # ТОВАРЫ
    # ------------------------------------------------------------------ #

    async def get_products_list(
        self, limit: int = 100, last_id: str = "", visibility: str = "ALL"
    ) -> dict[str, Any]:
        """
        Список товаров.
        visibility: ALL | VISIBLE | INVISIBLE | EMPTY_STOCK | NOT_MODERATED |
                    MODERATED | DISABLED | STATE_FAILED | READY_TO_SUPPLY |
                    VALIDATION_STATE_PENDING | VALIDATION_STATE_FAIL |
                    VALIDATION_STATE_SUCCESS | TO_SUPPLY | IN_SALE |
                    REMOVED_FROM_SALE | BANNED | OVERPRICED | CRITICALLY_OVERPRICED |
                    EMPTY_BARCODE | BARCODE_EXISTS | QUARANTINE | ARCHIVED |
                    OVERPRICED_WITH_STOCK | PARTIAL_APPROVED | IMAGE_ABSENT |
                    MODERATION_BLOCK
        """
        payload = {
            "filter": {"visibility": visibility},
            "last_id": last_id,
            "limit": limit,
        }
        return await self._post("/v3/product/list", payload)

    async def get_products_info(self, product_ids: list[int]) -> dict[str, Any]:
        """Подробная информация о товарах (до 1000 за раз)."""
        payload = {"product_id": [str(pid) for pid in product_ids]}
        return await self._post("/v3/product/info/list", payload)

    async def get_product_stocks(self, last_id: str = "", limit: int = 100) -> dict[str, Any]:
        """Остатки на складах по товарам."""
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": limit,
        }
        return await self._post("/v4/product/info/stocks", payload)

    # ------------------------------------------------------------------ #
    # ЗАКАЗЫ FBS
    # ------------------------------------------------------------------ #

    async def get_fbs_orders(
        self,
        since: datetime | None = None,
        to: datetime | None = None,
        status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Список заказов FBS за период.

        ВАЖНО: даты должны быть в UTC и в формате ISO 8601 с 'Z' на конце.
        Это причина 404 в прошлой реализации — формат даты был неправильный.
        """
        if to is None:
            to = datetime.now(timezone.utc)
        if since is None:
            since = to - timedelta(days=1)

        # Гарантируем UTC
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        if to.tzinfo is None:
            to = to.replace(tzinfo=timezone.utc)

        filter_block: dict[str, Any] = {
            "since": since.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "to": to.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        if status:
            filter_block["status"] = status

        payload = {
            "dir": "DESC",
            "filter": filter_block,
            "limit": limit,
            "offset": offset,
            "with": {
                "analytics_data": True,
                "financial_data": True,
            },
        }
        return await self._post("/v3/posting/fbs/list", payload)

    async def get_fbs_order_details(self, posting_number: str) -> dict[str, Any]:
        """Детали одного отправления FBS."""
        payload = {
            "posting_number": posting_number,
            "with": {
                "analytics_data": True,
                "financial_data": True,
                "product_exemplars": True,
            },
        }
        return await self._post("/v3/posting/fbs/get", payload)

    async def get_fbs_unfulfilled(self, limit: int = 100) -> dict[str, Any]:
        """Необработанные заказы FBS — что нужно собрать прямо сейчас."""
        payload = {
            "dir": "ASC",
            "filter": {
                "cutoff_from": (datetime.now(timezone.utc) - timedelta(days=30))
                .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "cutoff_to": (datetime.now(timezone.utc) + timedelta(days=30))
                .strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            },
            "limit": limit,
            "offset": 0,
            "with": {"analytics_data": True, "financial_data": True},
        }
        return await self._post("/v3/posting/fbs/unfulfilled/list", payload)

    # ------------------------------------------------------------------ #
    # АНАЛИТИКА И СКЛАД
    # ------------------------------------------------------------------ #

    async def get_stock_on_warehouses(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Остатки по складам (это endpoint, который у нас уже работал)."""
        payload = {"limit": limit, "offset": offset, "warehouse_type": "ALL"}
        return await self._post("/v2/analytics/stock_on_warehouses", payload)

    # ------------------------------------------------------------------ #
    # ОТЗЫВЫ (требуется подписка OZON Premium)
    # ------------------------------------------------------------------ #

    async def get_reviews(
        self, status: str = "UNPROCESSED", limit: int = 50, last_id: str = ""
    ) -> dict[str, Any]:
        """
        Список отзывов.
        status: UNPROCESSED | PROCESSED | ALL
        """
        payload = {"limit": limit, "status": status, "last_id": last_id, "sort_dir": "DESC"}
        return await self._post("/v1/review/list", payload)

    async def reply_to_review(
        self, review_id: str, text: str, mark_as_processed: bool = True
    ) -> dict[str, Any]:
        """Ответить на отзыв."""
        payload = {
            "review_id": review_id,
            "text": text,
            "mark_review_as_processed": mark_as_processed,
        }
        return await self._post("/v1/review/comment/create", payload)

    # ------------------------------------------------------------------ #
    # ФОТО ТОВАРОВ
    # ------------------------------------------------------------------ #

    async def get_product_pictures(self, product_ids: list[int]) -> dict[str, Any]:
        """Получить фото товаров."""
        payload = {"product_id": [str(pid) for pid in product_ids]}
        return await self._post("/v2/product/pictures/info", payload)

    async def upload_product_pictures(
        self,
        product_id: int,
        images: list[str],
        color_image: str = "",
        images360: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Загрузить фото в карточку товара.
        images — список URL картинок (OZON сам их скачает).
        Первое фото в списке становится главным.
        """
        payload = {
            "product_id": product_id,
            "images": images,
            "images360": images360 or [],
            "color_image": color_image,
        }
        return await self._post("/v1/product/pictures/import", payload)

    # ------------------------------------------------------------------ #
    # ЦЕНЫ
    # ------------------------------------------------------------------ #

    async def get_prices(self, last_id: str = "", limit: int = 100) -> dict[str, Any]:
        """Текущие цены товаров."""
        payload = {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": limit,
        }
        return await self._post("/v5/product/info/prices", payload)

    async def update_prices(self, prices: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Обновить цены товаров.

        prices — список словарей вида:
        {
            "offer_id": "SKU-123",
            "price": "1990",
            "old_price": "2490",
            "min_price": "1500",
            "auto_action_enabled": "ENABLED"
        }
        """
        payload = {"prices": prices}
        return await self._post("/v1/product/import/prices", payload)
