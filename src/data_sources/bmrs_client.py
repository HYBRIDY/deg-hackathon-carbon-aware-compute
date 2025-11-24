"""Async client for Elexon BMRS / Insights system price data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List

import httpx

from src.domain import PricePoint, isoformat, parse_datetime

LOGGER = logging.getLogger(__name__)


class BMRSClient:
    BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets/DISEBSP"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ):
        self.api_key = api_key
        self._close_client = http_client is None
        headers = {}
        if api_key:
            headers["x-api-key"] = api_key
        self._headers = headers
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        if self._close_client:
            await self._client.aclose()

    async def get_system_prices(self, start: datetime, end: datetime) -> List[PricePoint]:
        params = {"from": isoformat(start), "to": isoformat(end)}
        try:
            response = await self._client.get(self.BASE_URL, params=params, headers=self._headers)
            response.raise_for_status()
            payload = response.json()
            records = payload.get("data") or payload.get("response", {}).get("data") or []
            if not records:
                LOGGER.warning("BMRS response missing data, falling back.")
                return self._fallback_series(start, end)
            return [self._parse_record(record) for record in records]
        except Exception as exc:
            LOGGER.warning("BMRS API failed (%s). Using fallback series.", exc)
            return self._fallback_series(start, end)

    def _parse_record(self, record: dict) -> PricePoint:
        timestamp_raw = (
            record.get("settlementPeriodStart")
            or record.get("time")
            or record.get("timestamp")
            or record.get("startTime")
        )
        buy_price = record.get("systemBuyPrice") or record.get("buyPrice") or record.get("price") or 0
        sell_price = record.get("systemSellPrice") or record.get("sellPrice") or record.get("sell_price") or 0
        return PricePoint(
            timestamp=parse_datetime(timestamp_raw),
            system_buy_price_gbp_per_mwh=float(buy_price),
            system_sell_price_gbp_per_mwh=float(sell_price),
        )

    def _fallback_series(self, start: datetime, end: datetime) -> List[PricePoint]:
        start_slot = start.replace(minute=0, second=0, microsecond=0)
        end_slot = end.replace(minute=0, second=0, microsecond=0)
        series = []
        current = start_slot
        slot = 0
        while current <= end_slot:
            buy_price = 100 + 20 * ((slot % 12) / 12)
            sell_price = buy_price - 30
            series.append(
                PricePoint(
                    timestamp=current,
                    system_buy_price_gbp_per_mwh=buy_price,
                    system_sell_price_gbp_per_mwh=sell_price,
                )
            )
            current += timedelta(minutes=30)
            slot += 1
        return series


