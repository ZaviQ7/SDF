from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import aiohttp

from .domain import TemperatureType


class NWSClient:
    def __init__(self, timeout_seconds: int = 15):
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.headers = {
            "User-Agent": "kalshi-weather-lab/0.1 (weather-market research; contact via repository)"
        }

    async def _json(self, url: str) -> dict:
        backoff = 1.0
        for attempt in range(4):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
                    async with session.get(url) as response:
                        if response.status in {429, 500, 502, 503, 504} and attempt < 3:
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue
                        response.raise_for_status()
                        return await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == 3:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
        raise RuntimeError("unreachable")

    async def final_cli_temperature(
        self, station_id: str, target_date: date, temp_type: TemperatureType
    ) -> float | None:
        cli_location = station_id[1:] if station_id.startswith("K") else station_id
        listing = await self._json(f"https://api.weather.gov/products/types/CLI/locations/{cli_location}")
        graph = listing.get("@graph", [])
        month = target_date.strftime("%B").upper()
        pattern = re.compile(rf"FOR\s+{month}\s+0?{target_date.day}\s+{target_date.year}", re.I)
        value_pattern = re.compile(
            r"MAXIMUM\s+(-?\d+)" if temp_type is TemperatureType.HIGH else r"MINIMUM\s+(-?\d+)",
            re.I,
        )
        for entry in graph[:10]:
            product_url = entry.get("@id")
            if not product_url:
                continue
            product = await self._json(product_url)
            text = product.get("productText", "")
            if not pattern.search(text):
                continue
            match = value_pattern.search(text)
            if match:
                return float(match.group(1))
        return None

    async def observed_extreme_so_far(
        self,
        station_id: str,
        target_date: date,
        timezone_name: str,
        temp_type: TemperatureType,
    ) -> float | None:
        payload = await self._json(f"https://api.weather.gov/stations/{station_id}/observations")
        local_zone = ZoneInfo(timezone_name)
        values: list[float] = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            timestamp = props.get("timestamp")
            celsius = (props.get("temperature") or {}).get("value")
            if timestamp is None or celsius is None:
                continue
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(local_zone)
            if observed.date() == target_date:
                values.append(float(celsius) * 9 / 5 + 32)
        if not values:
            return None
        return max(values) if temp_type is TemperatureType.HIGH else min(values)
