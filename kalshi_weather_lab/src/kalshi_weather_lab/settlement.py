from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import AppConfig
from .contracts import parse_contract_rule
from .domain import Side, TemperatureType
from .kalshi_client import KalshiPublicClient
from .ledger import Ledger
from .nws import NWSClient


async def settle_event_from_final_cli(
    ledger: Ledger,
    *,
    station_id: str,
    target_date: date,
    temp_type: TemperatureType,
    ticker_titles: dict[str, str],
) -> dict:
    """Final-report-only settlement. No preliminary observation fallback is allowed."""
    actual = await NWSClient().final_cli_temperature(station_id, target_date, temp_type)
    if actual is None:
        return {"settled": 0, "actual": None, "reason": "final NWS CLI report not yet available"}
    rounded = int(round(actual))
    count = 0
    for position in ledger.open_positions():
        ticker = position["ticker"]
        if ticker not in ticker_titles:
            continue
        rule = parse_contract_rule(ticker_titles[ticker])
        official_yes = rule.contains(rounded)
        changed = ledger.settle_position(
            ticker,
            Side(position["side"]),
            official_yes,
            source=f"NWS final CLI {station_id} {target_date.isoformat()} ({actual:.0f}F)",
        )
        count += int(changed)
    return {"settled": count, "actual": actual, "reason": "ok"}


async def settle_all_open(config: AppConfig, ledger: Ledger) -> list[dict]:
    """Settle both paper positions and every unresolved forecast snapshot.

    Forecast learning must not depend on whether the optimizer happened to buy a
    contract. Every scanned city/type/date can therefore become a residual once
    the final NWS CLI report is available.
    """
    positions = ledger.open_positions_with_metadata()
    cities = {city.code: city for city in config.cities}
    nws = NWSClient(config.open_meteo_timeout_seconds)
    actual_cache: dict[tuple, float | None] = {}
    results: list[dict] = []

    # Resolve forecast snapshots independently of trading activity.
    try:
        with ledger.connect() as conn:
            snapshot_groups = [
                dict(row)
                for row in conn.execute(
                    """SELECT city_code, temp_type, target_date, COUNT(*) AS snapshots
                       FROM forecast_snapshots
                       WHERE residual_recorded=0
                       GROUP BY city_code, temp_type, target_date
                       ORDER BY target_date, city_code, temp_type"""
                ).fetchall()
            ]
    except Exception as exc:
        snapshot_groups = []
        results.append({"kind": "forecast_residuals", "recorded": 0, "reason": f"snapshot query failed: {exc}"})

    for group in snapshot_groups:
        city = cities.get(group["city_code"])
        if city is None:
            results.append({
                "kind": "forecast_residuals",
                "city_code": group["city_code"],
                "target_date": group["target_date"],
                "recorded": 0,
                "reason": "unknown city code",
            })
            continue
        target = date.fromisoformat(group["target_date"])
        temp_type = TemperatureType(group["temp_type"])
        local_today = datetime.now(ZoneInfo(city.timezone)).date()
        if target >= local_today:
            continue
        cache_key = (city.station_id, target, temp_type)
        if cache_key not in actual_cache:
            actual_cache[cache_key] = await nws.final_cli_temperature(
                city.station_id,
                target,
                temp_type,
            )
        actual = actual_cache[cache_key]
        if actual is None:
            results.append({
                "kind": "forecast_residuals",
                "city_code": city.code,
                "temp_type": temp_type.value,
                "target_date": target.isoformat(),
                "recorded": 0,
                "reason": "final NWS CLI unavailable",
            })
            continue
        snapshots = ledger.unresolved_forecast_snapshots(
            city_code=city.code,
            temp_type=temp_type.value,
            target_date=target.isoformat(),
        )
        for snapshot in snapshots:
            ledger.finalize_forecast_snapshot(
                snapshot_id=int(snapshot["id"]),
                actual_f=float(actual),
            )
        results.append({
            "kind": "forecast_residuals",
            "city_code": city.code,
            "temp_type": temp_type.value,
            "target_date": target.isoformat(),
            "actual": actual,
            "recorded": len(snapshots),
        })

    # Settle open paper positions using the same cached official values.
    if positions:
        async with KalshiPublicClient(config.api_base_url) as kalshi:
            for position in positions:
                city = cities.get(position.get("city_code"))
                target_raw = position.get("target_date")
                temp_raw = position.get("temp_type")
                if city is None or not target_raw or not temp_raw:
                    results.append({"ticker": position["ticker"], "settled": False, "reason": "missing decision metadata"})
                    continue
                target = date.fromisoformat(target_raw)
                temp_type = TemperatureType(temp_raw)

                # Never settle a position while its target date is still
                # the current local date. Same-day CLI products can be
                # preliminary reports such as "VALID TODAY AS OF 0400 PM".
                local_today = datetime.now(ZoneInfo(city.timezone)).date()
                if target >= local_today:
                    results.append({
                        "ticker": position["ticker"],
                        "settled": False,
                        "reason": "target date not complete in city timezone",
                    })
                    continue

                cache_key = (city.station_id, target, temp_type)
                if cache_key not in actual_cache:
                    actual_cache[cache_key] = await nws.final_cli_temperature(city.station_id, target, temp_type)
                actual = actual_cache[cache_key]
                if actual is None:
                    results.append({"ticker": position["ticker"], "settled": False, "reason": "final NWS CLI unavailable"})
                    continue
                market = await kalshi.get_market(position["ticker"])
                title = market.get("subtitle") or market.get("title") or market.get("yes_sub_title") or ""
                official_yes = parse_contract_rule(title).contains(int(round(actual)))
                changed = ledger.settle_position(
                    position["ticker"],
                    Side(position["side"]),
                    official_yes,
                    source=f"NWS final CLI {city.station_id} {target.isoformat()} ({actual:.0f}F)",
                )
                results.append({"ticker": position["ticker"], "settled": changed, "actual": actual})
    return results

