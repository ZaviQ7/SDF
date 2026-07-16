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

            # Same-day afternoon CLI products are preliminary and may say
            # "VALID TODAY AS OF 0400 PM". They must not settle markets.
            if re.search(r"VALID\s+TODAY\s+AS\s+OF", text, re.I):
                continue
            match = value_pattern.search(text)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _tenths_c_to_f(sign: str, digits: str) -> float:
        value_c = int(digits) / 10.0
        if sign == "1":
            value_c = -value_c
        return value_c * 9.0 / 5.0 + 32.0

    @classmethod
    def _raw_metar_temperatures(
        cls,
        raw_message: str,
        temp_type: TemperatureType,
        *,
        include_six_hour: bool = True,
        include_twenty_four_hour: bool = True,
    ) -> list[float]:
        """Extract instantaneous and reported period extrema from METAR remarks.

        Supported groups:
        TsnTTT             precise instantaneous temperature
        1snTTT             six-hour maximum
        2snTTT             six-hour minimum
        4snTTTsnTTT        24-hour maximum and minimum
        """
        values: list[float] = []

        precise = re.search(
            r"(?<!\S)T([01])(\d{3})[01]\d{3}(?=\s|$)",
            raw_message,
        )
        if precise:
            values.append(cls._tenths_c_to_f(precise.group(1), precise.group(2)))

        six_hour = None
        if include_six_hour:
            if temp_type is TemperatureType.HIGH:
                six_hour = re.search(
                    r"(?<!\S)1([01])(\d{3})(?=\s|$)",
                    raw_message,
                )
            else:
                six_hour = re.search(
                    r"(?<!\S)2([01])(\d{3})(?=\s|$)",
                    raw_message,
                )

        if six_hour:
            values.append(
                cls._tenths_c_to_f(
                    six_hour.group(1),
                    six_hour.group(2),
                )
            )

        twenty_four_hour = None
        if include_twenty_four_hour:
            twenty_four_hour = re.search(
                r"(?<!\S)4([01])(\d{3})([01])(\d{3})(?=\s|$)",
                raw_message,
            )

        if twenty_four_hour:
            if temp_type is TemperatureType.HIGH:
                values.append(
                    cls._tenths_c_to_f(
                        twenty_four_hour.group(1),
                        twenty_four_hour.group(2),
                    )
                )
            else:
                values.append(
                    cls._tenths_c_to_f(
                        twenty_four_hour.group(3),
                        twenty_four_hour.group(4),
                    )
                )

        return values

    async def observed_extreme_so_far(
        self,
        station_id: str,
        target_date: date,
        timezone_name: str,
        temp_type: TemperatureType,
    ) -> float | None:
        payload = await self._json(
            f"https://api.weather.gov/stations/{station_id}/observations?limit=500"
        )
        local_zone = ZoneInfo(timezone_name)
        values: list[float] = []

        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            timestamp = props.get("timestamp")
            if timestamp is None:
                continue

            observed = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            ).astimezone(local_zone)

            # A report just after 00Z can still belong to the prior local date.
            if observed.date() != target_date:
                continue

            celsius = (props.get("temperature") or {}).get("value")
            if celsius is not None:
                values.append(float(celsius) * 9.0 / 5.0 + 32.0)

            raw_message = props.get("rawMessage") or ""

            # A six-hour extrema group is usable only when the entire
            # six-hour reporting window lies inside the target local day.
            local_midnight = observed.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            hours_since_midnight = (
                observed - local_midnight
            ).total_seconds() / 3600.0

            values.extend(
                self._raw_metar_temperatures(
                    raw_message,
                    temp_type,
                    include_six_hour=hours_since_midnight >= 6.0,
                    # A rolling 24-hour group can contain the previous
                    # calendar day's extreme and must not be used for a
                    # live same-day running maximum or minimum.
                    include_twenty_four_hour=False,
                )
            )

        if not values:
            return None

        return (
            max(values)
            if temp_type is TemperatureType.HIGH
            else min(values)
        )
