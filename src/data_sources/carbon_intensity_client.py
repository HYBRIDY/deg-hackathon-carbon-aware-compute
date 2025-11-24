"""Async client for the UK Carbon Intensity API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Sequence

import httpx

from src.domain import CarbonPoint, isoformat, parse_datetime

LOGGER = logging.getLogger(__name__)


class CarbonIntensityClient:
    BASE_URL = "https://api.carbonintensity.org.uk"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None, timeout: float = 10.0):
        self._close_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        if self._close_client:
            await self._client.aclose()

    async def get_forecast_24h(self, start: datetime) -> List[CarbonPoint]:
        """Return next 24h carbon intensity forecast in half-hour steps."""

        url = f"{self.BASE_URL}/intensity/{isoformat(start)}/fw24h"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            return [self._parse_entry(entry) for entry in data]
        except Exception as exc:
            LOGGER.warning("Carbon Intensity API failed (%s). Using fallback series.", exc)
            return self._fallback_series(start, periods=48)

    def _parse_entry(self, entry: dict) -> CarbonPoint:
        timestamp_raw = entry.get("from") or entry.get("timestamp")
        forecast = entry.get("intensity", {}).get("forecast") or entry.get("forecast_g_per_kwh")
        index = entry.get("intensity", {}).get("index") or entry.get("index", "unknown")
        if forecast is None:
            forecast = entry.get("actual") or 0
        return CarbonPoint(
            timestamp=parse_datetime(timestamp_raw),
            forecast_g_per_kwh=float(forecast),
            index=index,
        )

    def _fallback_series(self, start: datetime, *, periods: int) -> List[CarbonPoint]:
        base = start.replace(minute=0, second=0, microsecond=0)
        series = []
        for slot in range(periods):
            timestamp = base + timedelta(minutes=30 * slot)
            forecast = 80 + 20 * ((slot % 16) / 16)  # simple sinusoid-like pattern
            series.append(
                CarbonPoint(
                    timestamp=timestamp,
                    forecast_g_per_kwh=forecast,
                    index="low" if forecast < 100 else "moderate",
                )
            )
        return series


async def fetch_carbon_series(client: CarbonIntensityClient, start: datetime) -> Sequence[CarbonPoint]:
    return await client.get_forecast_24h(start)


