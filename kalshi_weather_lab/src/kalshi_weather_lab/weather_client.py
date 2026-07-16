from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .domain import CityConfig, ForecastBundle, ModelForecast, TemperatureType


ENSEMBLE_MODELS = {
    "ecmwf": ("ecmwf_ifs025_ensemble", "ecmwf_ifs025_ensemble"),
    "gfs": ("gfs_seamless", "ncep_gefs_seamless"),
    "icon": ("icon_seamless", "icon_seamless_eps"),
    "gem": ("gem_global", "gem_global_ensemble"),
}


class OpenMeteoClient:
    def __init__(self, timeout_seconds: int = 25):
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def _get_json(self, url: str) -> dict:
        backoff = 1.0
        headers = {"User-Agent": "kalshi-weather-lab/0.1 research-contact"}
        for attempt in range(4):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout, headers=headers) as session:
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

    async def fetch_bundle(
        self,
        city: CityConfig,
        target_date: date,
        temp_type: TemperatureType,
        *,
        observed_extreme: float | None = None,
    ) -> ForecastBundle:
        model_param = ",".join(request_name for request_name, _ in ENSEMBLE_MODELS.values())
        ensemble_url = (
            "https://ensemble-api.open-meteo.com/v1/ensemble"
            f"?latitude={city.latitude}&longitude={city.longitude}"
            "&hourly=temperature_2m"
            f"&models={model_param}&temperature_unit=fahrenheit"
            f"&timezone={city.timezone}"
        )
        hrrr_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={city.latitude}&longitude={city.longitude}"
            "&hourly=temperature_2m&models=ncep_hrrr_conus"
            "&temperature_unit=fahrenheit"
            f"&timezone={city.timezone}&forecast_days=3"
        )
        ensemble_payload, hrrr_payload = await asyncio.gather(
            self._get_json(ensemble_url), self._get_json(hrrr_url), return_exceptions=True
        )
        local_now = datetime.now(ZoneInfo(city.timezone))
        same_local_day = target_date == local_now.date()
        not_before = local_now.replace(minute=0, second=0, microsecond=0) if same_local_day else None

        forecasts: list[ModelForecast] = []
        if isinstance(ensemble_payload, dict):
            forecasts.extend(
                self._parse_ensembles(
                    ensemble_payload,
                    target_date,
                    temp_type,
                    not_before=not_before,
                    observed_extreme=observed_extreme,
                )
            )
        if isinstance(hrrr_payload, dict):
            hrrr = self._parse_hrrr(
                hrrr_payload,
                target_date,
                temp_type,
                not_before=not_before,
                observed_extreme=observed_extreme,
            )
            if hrrr:
                forecasts.append(hrrr)

        target_clock = time(16, 0) if temp_type is TemperatureType.HIGH else time(7, 0)
        target_dt = datetime.combine(target_date, target_clock, ZoneInfo(city.timezone))
        hours_to_target = (target_dt - local_now).total_seconds() / 3600.0
        return ForecastBundle(
            city_code=city.code,
            target_date=target_date,
            temp_type=temp_type,
            hours_to_target=hours_to_target,
            forecasts=tuple(forecasts),
            observed_extreme=observed_extreme,
        )

    @staticmethod
    def _indices_for_date(
        times: list[str],
        target_date: date,
        not_before: datetime | None = None,
    ) -> list[int]:
        prefix = target_date.isoformat()
        indices = [
            idx for idx, timestamp in enumerate(times)
            if timestamp.startswith(prefix)
        ]
        if not_before is None:
            return indices

        cutoff = not_before.strftime("%Y-%m-%dT%H:%M")
        return [idx for idx in indices if times[idx] >= cutoff]

    def _parse_ensembles(
        self,
        payload: dict,
        target_date: date,
        temp_type: TemperatureType,
        *,
        not_before: datetime | None = None,
        observed_extreme: float | None = None,
    ) -> list[ModelForecast]:
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        indices = self._indices_for_date(times, target_date, not_before)
        if not indices:
            return []
        results: list[ModelForecast] = []
        for model, (_, response_suffix) in ENSEMBLE_MODELS.items():
            member_keys = [
                key for key in hourly
                if key.startswith("temperature_2m") and key.endswith(f"_{response_suffix}")
            ]
            daily_values: list[float] = []
            for key in member_keys:
                values = [hourly[key][idx] for idx in indices if hourly[key][idx] is not None]
                if values:
                    projected = max(values) if temp_type is TemperatureType.HIGH else min(values)
                    if observed_extreme is not None:
                        projected = (
                            max(projected, observed_extreme)
                            if temp_type is TemperatureType.HIGH
                            else min(projected, observed_extreme)
                        )
                    daily_values.append(projected)
            if daily_values:
                results.append(ModelForecast(model=model, values=tuple(daily_values), deterministic=False))
        return results

    def _parse_hrrr(
        self,
        payload: dict,
        target_date: date,
        temp_type: TemperatureType,
        *,
        not_before: datetime | None = None,
        observed_extreme: float | None = None,
    ) -> ModelForecast | None:
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        indices = self._indices_for_date(times, target_date, not_before)
        values_raw = hourly.get("temperature_2m_ncep_hrrr_conus") or hourly.get("temperature_2m") or []
        values = [values_raw[idx] for idx in indices if idx < len(values_raw) and values_raw[idx] is not None]
        if not values:
            return None
        extreme = max(values) if temp_type is TemperatureType.HIGH else min(values)
        if observed_extreme is not None:
            extreme = (
                max(extreme, observed_extreme)
                if temp_type is TemperatureType.HIGH
                else min(extreme, observed_extreme)
            )
        return ModelForecast(model="hrrr", values=(float(extreme),), deterministic=True)
