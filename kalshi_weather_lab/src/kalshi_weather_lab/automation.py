from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import AppConfig
from .domain import TemperatureType
from .ledger import Ledger
from .pipeline import Scanner

logger = logging.getLogger(__name__)


async def run_scheduled_scans(
    config: AppConfig,
    ledger: Ledger,
    *,
    paper_execute: bool = False,
) -> list[dict]:
    scanner = Scanner(config, ledger)
    results: list[dict] = []
    for city in config.cities:
        if not city.active:
            continue
        local_now = datetime.now(ZoneInfo(city.timezone))
        checks = (
            (
                TemperatureType.LOW,
                config.scan_windows.low_start_hour <= local_now.hour < config.scan_windows.low_end_hour,
            ),
            (
                TemperatureType.HIGH,
                config.scan_windows.high_start_hour <= local_now.hour < config.scan_windows.high_end_hour,
            ),
        )
        for temp_type, inside_window in checks:
            if not inside_window or not city.series_for(temp_type):
                continue
            try:
                results.append(
                    await scanner.scan_city_event(
                        city,
                        temp_type,
                        local_now.date(),
                        paper_execute=paper_execute,
                    )
                )
            except Exception as exc:
                logger.exception("Scan failed for %s %s", city.name, temp_type.value)
                results.append(
                    {
                        "city": city.name,
                        "temp_type": temp_type.value,
                        "target_date": local_now.date().isoformat(),
                        "error": str(exc),
                    }
                )
    return results
