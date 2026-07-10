from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .domain import CityConfig


@dataclass(frozen=True, slots=True)
class RiskConfig:
    starting_bankroll: float = 15.0
    max_event_loss_fraction: float = 0.05
    max_daily_loss_fraction: float = 0.10
    max_contracts_per_market: int = 1
    max_positions_per_event: int = 3
    min_dollar_ev: float = 0.03
    min_return_on_cost: float = 0.08
    calibration_error_floor: float = 0.035
    confidence_z: float = 1.0


@dataclass(frozen=True, slots=True)
class FeeConfig:
    taker_rate: float = 0.07
    maker_rate: float = 0.0175
    taker_multiplier: float = 1.0
    maker_multiplier: float = 0.0


@dataclass(frozen=True, slots=True)
class ScanWindowConfig:
    low_start_hour: int = 0
    low_end_hour: int = 3
    high_start_hour: int = 11
    high_end_hour: int = 15


@dataclass(frozen=True, slots=True)
class AppConfig:
    database_path: Path
    report_path: Path
    risk: RiskConfig
    fees: FeeConfig
    scan_windows: ScanWindowConfig
    cities: tuple[CityConfig, ...]
    api_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    open_meteo_timeout_seconds: int = 25


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config(settings_path: str | Path, cities_path: str | Path) -> AppConfig:
    settings_file = Path(settings_path)
    cities_file = Path(cities_path)
    settings = _load_yaml(settings_file)
    city_document = _load_yaml(cities_file)

    risk_raw = settings.get("risk", {})
    fee_raw = settings.get("fees", {})
    scan_raw = settings.get("scan_windows", {})
    paths_raw = settings.get("paths", {})

    risk = RiskConfig(**{k: v for k, v in risk_raw.items() if k in RiskConfig.__dataclass_fields__})
    fees = FeeConfig(**{k: v for k, v in fee_raw.items() if k in FeeConfig.__dataclass_fields__})
    scan_windows = ScanWindowConfig(**{k: v for k, v in scan_raw.items() if k in ScanWindowConfig.__dataclass_fields__})

    cities: list[CityConfig] = []
    for raw in city_document.get("cities", []):
        # Accept both the new names and the user's legacy cities.yaml names.
        cities.append(
            CityConfig(
                name=raw["name"],
                code=raw.get("code", raw["name"].upper().replace(" ", "")[:5]),
                latitude=float(raw.get("latitude", raw.get("lat"))),
                longitude=float(raw.get("longitude", raw.get("lon"))),
                timezone=raw["timezone"],
                station_id=raw.get("station_id", raw.get("nws_station_id")),
                series_high=raw.get("series_high", raw.get("kalshi_market_prefix")),
                series_low=raw.get("series_low", raw.get("kalshi_market_prefix_low")),
                active=bool(raw.get("active", True)),
            )
        )

    root = settings_file.resolve().parent.parent
    database_path = root / paths_raw.get("database", "data/kalshi_weather.sqlite3")
    report_path = root / paths_raw.get("report", "reports/dashboard.md")

    return AppConfig(
        database_path=database_path,
        report_path=report_path,
        risk=risk,
        fees=fees,
        scan_windows=scan_windows,
        cities=tuple(cities),
        api_base_url=settings.get("kalshi", {}).get(
            "api_base_url", "https://external-api.kalshi.com/trade-api/v2"
        ),
        open_meteo_timeout_seconds=int(settings.get("weather", {}).get("timeout_seconds", 25)),
    )
