"""
core_scanner.py — Single source of truth for the weather edge scanning pipeline.

Called by: scan_once.py, server.py, update_edges.py
"""
import asyncio
import logging
import os
import json
import time
import yaml
import pytz
import aiohttp
import numpy as np
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable

from src.data_ingestion.kalshi_client import KalshiWeatherClient
from src.data_ingestion.gfs_downloader import GFSDownloader
from src.data_ingestion.ecmwf_downloader import ECMWFDownloader
from src.data_ingestion.hrrr_downloader import HRRRDownloader
from src.models.weather_model import WeatherModelProcessor
from src.models.probability import calculate_market_probability
from src.trading.edge_detector import EdgeDetector
from src.trading.risk_manager import RiskManager
from src.utils.helpers import parse_range
from src.utils.bias_tracker import BiasTracker

logger = logging.getLogger("core_scanner")

# ---------------------------------------------------------------------------
# Weather API response cache (in-memory, keyed by request URL)
# ---------------------------------------------------------------------------
_weather_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 1800  # 30 minutes

# Semaphore to throttle concurrent Open-Meteo requests (free tier rate limit)
_api_semaphore = asyncio.Semaphore(2)


def _cache_key(model: str, lat: float, lon: float, target_date: str) -> str:
    return f"{model}|{lat}|{lon}|{target_date}"


def _get_cached(key: str) -> Optional[Any]:
    entry = _weather_cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL_SECONDS:
        return entry["data"]
    return None


def _set_cached(key: str, data: Any):
    _weather_cache[key] = {"data": data, "ts": time.time()}


# ---------------------------------------------------------------------------
# NWS observation fetcher (single canonical implementation)
# ---------------------------------------------------------------------------
async def fetch_nws_cli_temp(station_id: str, target_date_str: str, temp_type: str) -> Optional[float]:
    """Fetch official daily high/low temperature from NWS Daily Climate Summary (CLI) text product."""
    cli_code = station_id[1:] if station_id.startswith("K") else station_id
    url = f"https://api.weather.gov/products/types/CLI/locations/{cli_code}"
    headers = {"User-Agent": "KalshiWeatherBot/1.0 (contact@kalshiedgebot.com)"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                graph = data.get("@graph", [])
                if not graph:
                    return None
                
                # Scan the latest 3 climate products to find the one matching target_date_str
                for product_entry in graph[:3]:
                    product_id = product_entry.get("@id")
                    if not product_id:
                        continue
                        
                    async with session.get(product_id, headers=headers, timeout=10) as prod_resp:
                        if prod_resp.status != 200:
                            continue
                        prod_data = await prod_resp.json()
                        product_text = prod_data.get("productText", "")
                        if not product_text:
                            continue
                            
                        # Verify the date in the product text
                        dt = datetime.strptime(target_date_str, "%Y-%m-%d")
                        month_name = dt.strftime("%B").upper()
                        day_num = dt.day
                        year_num = dt.year
                        
                        # Match FOR MONTH DAY YEAR (e.g. FOR JULY 5 2026 or FOR JULY 05 2026) to avoid matching the header date
                        date_pattern = rf"FOR\s+{month_name}\s+0?{day_num}\s+{year_num}"
                        if not re.search(date_pattern, product_text.upper()):
                            continue
                            
                        # Parse MAXIMUM or MINIMUM value
                        if temp_type == "HIGH":
                            m_max = re.search(r"MAXIMUM\s+(\d+)", product_text.upper())
                            if m_max:
                                val = float(m_max.group(1))
                                logger.info(f"🏆 Found official NWS CLI HIGH for {station_id} on {target_date_str}: {val}F")
                                return val
                        else:
                            m_min = re.search(r"MINIMUM\s+(\d+)", product_text.upper())
                            if m_min:
                                val = float(m_min.group(1))
                                logger.info(f"🏆 Found official NWS CLI LOW for {station_id} on {target_date_str}: {val}F")
                                return val
    except Exception as e:
        logger.error(f"Error fetching NWS CLI temp for {station_id}: {e}")
    return None

async def fetch_nws_actual_high_low(
    station_id: str, target_date_str: str, timezone_str: str, temp_type: str
) -> Optional[float]:
    """Query NWS observations for today's running high or low temperature."""
    # 1. First attempt to fetch the official Daily Climate Summary (CLI) for precise settlement matching
    cli_temp = await fetch_nws_cli_temp(station_id, target_date_str, temp_type)
    if cli_temp is not None:
        return cli_temp
        
    # 2. Fall back to raw hourly observations (useful for running/incomplete days)
    url = f"https://api.weather.gov/stations/{station_id}/observations"
    headers = {"User-Agent": "KalshiWeatherBot/1.0 (contact@kalshiedgebot.com)"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                features = data.get("features", [])

                tz = pytz.timezone(timezone_str)
                local_temps = []

                for f in features:
                    props = f.get("properties", {})
                    timestamp_str = props.get("timestamp")
                    temp_c = props.get("temperature", {}).get("value")

                    if timestamp_str and temp_c is not None:
                        utc_dt = datetime.fromisoformat(
                            timestamp_str.replace("Z", "+00:00")
                        )
                        local_dt = utc_dt.astimezone(tz)

                        if local_dt.strftime("%Y-%m-%d") == target_date_str:
                            temp_f = temp_c * 9 / 5 + 32
                            local_temps.append(temp_f)

                if not local_temps:
                    return None

                return max(local_temps) if temp_type == "HIGH" else min(local_temps)
    except Exception as e:
        logger.error(f"Error fetching actual for station {station_id}: {e}")
    return None


# ---------------------------------------------------------------------------
# Open-Meteo Ensemble and HRRR Forecast Downloaders
# ---------------------------------------------------------------------------
# (short_name, request_model, response_suffix)
# In combined mode, Open-Meteo renames some models in the response keys:
#   gfs_seamless       → ncep_gefs_seamless
#   icon_seamless      → icon_seamless_eps
#   gem_global         → gem_global_ensemble
#   ecmwf_ifs025_ensemble stays the same
ENSEMBLE_MODELS = [
    ("ecmwf", "ecmwf_ifs025_ensemble", "ecmwf_ifs025_ensemble"),
    ("gfs",   "gfs_seamless",          "ncep_gefs_seamless"),
    ("icon",  "icon_seamless",         "icon_seamless_eps"),
    ("gem",   "gem_global",            "gem_global_ensemble"),
]


async def download_all_ensembles(
    lat: float, lon: float, target_date: str, timezone: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Download ALL ensemble models in a single API call to minimise request count.

    Open-Meteo supports comma-separated models.  In combined mode the hourly
    keys use the model name as a **suffix**, e.g.
    ``temperature_2m_member01_ecmwf_ifs025_ensemble``.
    """
    model_names = [req for _, req, _ in ENSEMBLE_MODELS]
    models_param = ",".join(model_names)
    url = (
        f"https://ensemble-api.open-meteo.com/v1/ensemble"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m"
        f"&models={models_param}"
        f"&temperature_unit=fahrenheit"
        f"&timezone={timezone}"
    )
    headers = {"User-Agent": "Mozilla/5.0 (kalshi-ev-scanner-v2)"}

    max_retries = 3
    backoff = 2.0
    for attempt in range(max_retries):
        try:
            async with _api_semaphore:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=20, headers=headers) as resp:
                        if resp.status == 429:
                            logger.warning(
                                f"Rate limited (429) for combined ensemble. Retrying in {backoff}s..."
                            )
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue
                        elif resp.status != 200:
                            text = await resp.text()
                            logger.error(
                                f"Open-Meteo combined ensemble API error ({resp.status}): {text}"
                            )
                            return {s: None for s, _, _ in ENSEMBLE_MODELS}

                        data = await resp.json()
                        hourly = data.get("hourly", {})
                        times = hourly.get("time", [])

                        indices = [
                            i for i, t in enumerate(times) if t.startswith(target_date)
                        ]
                        if not indices:
                            logger.error(
                                f"No forecast times matching {target_date} in combined ensemble"
                            )
                            return {s: None for s, _, _ in ENSEMBLE_MODELS}

                        all_keys = list(hourly.keys())

                        results: Dict[str, Optional[Dict[str, Any]]] = {}
                        for short_name, req_name, resp_suffix in ENSEMBLE_MODELS:
                            # Keys end with the model suffix, e.g.
                            # temperature_2m_ecmwf_ifs025_ensemble  (control)
                            # temperature_2m_member01_ecmwf_ifs025_ensemble
                            member_keys = [
                                k for k in all_keys
                                if k.endswith(f"_{resp_suffix}")
                                and k.startswith("temperature_2m")
                            ]
                            if not member_keys:
                                results[short_name] = None
                                continue

                            member_forecasts = {}
                            for key in member_keys:
                                # Strip the model suffix to get the member part
                                # e.g. "temperature_2m_member01_ecmwf_ifs025_ensemble"
                                #   → base = "temperature_2m_member01"
                                base = key[:-(len(resp_suffix) + 1)]  # strip "_suffix"
                                if base == "temperature_2m":
                                    clean = "control"
                                elif base.startswith("temperature_2m_member"):
                                    clean = base.replace("temperature_2m_", "")  # "member01"
                                else:
                                    continue
                                temps = [
                                    hourly[key][idx]
                                    for idx in indices
                                    if hourly[key][idx] is not None
                                ]
                                if temps:
                                    member_forecasts[clean] = temps

                            if member_forecasts:
                                results[short_name] = {
                                    "source": req_name,
                                    "target_date": target_date,
                                    "timezone": timezone,
                                    "members": member_forecasts,
                                }
                            else:
                                results[short_name] = None

                        ok = sum(1 for v in results.values() if v is not None)
                        logger.info(f"Combined ensemble download: {ok}/{len(ENSEMBLE_MODELS)} models OK")
                        return results
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Error downloading combined ensemble: {e}")
                return {s: None for s, _, _ in ENSEMBLE_MODELS}
            logger.warning(
                f"Error downloading combined ensemble (attempt {attempt+1}/{max_retries}): {e}. Retrying..."
            )
            await asyncio.sleep(backoff)
            backoff *= 2
    return {s: None for s, _ in ENSEMBLE_MODELS}


async def download_hrrr(
    lat: float, lon: float, target_date: str, timezone: str
) -> Optional[Dict[str, Any]]:
    """Download deterministic high-resolution CONUS HRRR forecast from Open-Meteo."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m"
        f"&models=ncep_hrrr_conus"
        f"&temperature_unit=fahrenheit"
        f"&timezone={timezone}"
        f"&forecast_days=3"
    )
    headers = {"User-Agent": "Mozilla/5.0 (kalshi-ev-scanner-v2)"}

    try:
        async with _api_semaphore:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        hourly = data.get("hourly", {})
                        times = hourly.get("time", [])
                        temp_data = hourly.get(
                            "temperature_2m_ncep_hrrr_conus"
                        ) or hourly.get("temperature_2m", [])

                        indices = [
                            i
                            for i, t in enumerate(times)
                            if t.startswith(target_date)
                        ]
                        if not indices:
                            return None

                        temps = [
                            temp_data[idx]
                            for idx in indices
                            if temp_data[idx] is not None
                        ]
                        if temps:
                            return {
                                "source": "HRRR",
                                "target_date": target_date,
                                "temps": temps,
                            }
    except Exception as e:
        logger.error(f"Error downloading HRRR: {e}")
    return None


# ---------------------------------------------------------------------------
# Unified Forecast Retriever (with caching)
# ---------------------------------------------------------------------------
async def get_forecasts_for_date(
    lat: float, lon: float, target_date: str, timezone_str: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Retrieve and cache GFS, ECMWF, ICON, GEM, and HRRR forecasts for a given coordinate & date."""

    # --- Ensemble models (single combined API call) ---
    # Check if ALL ensemble models are cached
    ensemble_cache_keys = {
        s: _cache_key(m, lat, lon, target_date) for s, m, _ in ENSEMBLE_MODELS
    }
    all_cached = all(_get_cached(k) is not None for k in ensemble_cache_keys.values())

    if all_cached:
        results = {s: _get_cached(k) for s, k in ensemble_cache_keys.items()}
    else:
        # One API call fetches all 4 ensemble models
        results = await download_all_ensembles(lat, lon, target_date, timezone_str)
        for short_name, cache_key in ensemble_cache_keys.items():
            if results.get(short_name):
                _set_cached(cache_key, results[short_name])

    # --- HRRR (separate endpoint) ---
    hrrr_key = _cache_key("ncep_hrrr_conus", lat, lon, target_date)
    hrrr_cached = _get_cached(hrrr_key)
    if hrrr_cached is not None:
        results["hrrr"] = hrrr_cached
    else:
        hrrr = await download_hrrr(lat, lon, target_date, timezone_str)
        results["hrrr"] = hrrr
        if hrrr:
            _set_cached(hrrr_key, hrrr)

    return {
        "gfs": results.get("gfs"),
        "ecmwf": results.get("ecmwf"),
        "icon": results.get("icon"),
        "gem": results.get("gem"),
        "hrrr": results.get("hrrr"),
    }


# ---------------------------------------------------------------------------
# Core scan function
# ---------------------------------------------------------------------------
async def run_scan(
    config: Dict[str, Any],
    cities: List[Dict[str, Any]],
    on_progress: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Run the full weather expert mixture ensemble scan across all active cities.
    """

    def progress(msg: str):
        logger.info(msg)
        if on_progress:
            on_progress(msg)

    # Init components
    config["kalshi"]["environment"] = "prod"
    config["kalshi"]["simulation"] = True
    config["kalshi"]["trading"]["min_edge_threshold"] = 0.05

    client = KalshiWeatherClient(config)
    model_processor = WeatherModelProcessor(config)
    edge_detector = EdgeDetector(config)
    risk_manager = RiskManager(config)
    bias_tracker = BiasTracker(config)
    bias_offsets = bias_tracker.load_bias_offsets()

    await client.initialize()

    all_edges = []
    cumulative_exposure = 0.0  # Track across scan for Kelly sizing
    active_cities = [c for c in cities if c.get("active", True)]

    for idx, city in enumerate(active_cities):
        city_name = city["name"]
        lat = city["lat"]
        lon = city["lon"]
        timezone_str = city["timezone"]

        progress(f"Processing {city_name} ({idx + 1}/{len(active_cities)})...")

        tz = pytz.timezone(timezone_str)
        local_now = datetime.now(tz)
        target_dates = [
            local_now.strftime("%Y-%m-%d"),
            (local_now + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]

        scans = [
            ("HIGH", city["kalshi_market_prefix"]),
            ("LOW", city["kalshi_market_prefix_low"]),
        ]

        # Download forecasts once per city (with caching)
        forecasts_by_date = {}
        for target_date in target_dates:
            forecasts_by_date[target_date] = await get_forecasts_for_date(lat, lon, target_date, timezone_str)

        for temp_type, prefix in scans:
            markets = await client.get_weather_markets(prefix)
            if not markets:
                continue

            for target_date in target_dates:
                # Skip already-determined same-day contracts
                today_str = local_now.strftime("%Y-%m-%d")
                if target_date == today_str:
                    local_hour = local_now.hour
                    if temp_type == "HIGH" and local_hour >= 15:
                        logger.info(
                            f"  Skipping {city_name} today HIGH (past 3PM local)."
                        )
                        continue
                    if temp_type == "LOW" and local_hour >= 3:
                        logger.info(
                            f"  Skipping {city_name} today LOW (past 3AM local)."
                        )
                        continue

                try:
                    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
                    date_ticker_str = dt_obj.strftime("%y%b%d").upper()
                    # Compute lead hours to target date
                    target_dt = tz.localize(datetime.combine(dt_obj.date(), datetime.max.time()))
                    hours_to_target = (target_dt - local_now).total_seconds() / 3600.0
                except Exception:
                    continue

                date_markets = [m for m in markets if date_ticker_str in m["ticker"]]
                if not date_markets:
                    continue

                gfs_forecast, ecmwf_forecast, hrrr_forecast, icon_forecast, gem_forecast = forecasts_by_date.get(
                    target_date, (None, None, None, None, None)
                )
                if not any([gfs_forecast, ecmwf_forecast, icon_forecast, gem_forecast]):
                    continue

                logger.info(f"  Checking {city_name} {temp_type} for {target_date}...")

                bias_key = f"{city['code']}_{temp_type}"
                bias_offset = bias_offsets.get(bias_key, 0.0)

                pooled_temps = model_processor.process_ensembles(
                    gfs_data=gfs_forecast,
                    ecmwf_data=ecmwf_forecast,
                    temp_type=temp_type,
                    bias_offset=bias_offset,
                    hrrr_data=hrrr_forecast,
                    icon_data=icon_forecast,
                    gem_data=gem_forecast,
                    hours_to_target=hours_to_target
                )
                if len(pooled_temps) == 0:
                    continue

                # Real-time NWS clipping is disabled to avoid sensor outlier/mismatch contamination.
                # Relying entirely on models (such as hourly HRRR updates) for active predictions.

                stats = model_processor.get_distribution_stats(pooled_temps)
                logger.info(
                    f"  {city_name} {temp_type} forecast: Mean={stats['mean']:.1f}°F, Std={stats['std']:.1f}°F"
                )

                # Calculate model probabilities for each contract
                model_probabilities = {}
                for m in date_markets:
                    ticker = m["ticker"]
                    # Skip cross-contamination from substring matching in Kalshi API
                    ticker_type = "HIGH" if "HIGH" in ticker else "LOW"
                    if ticker_type != temp_type:
                        continue
                        
                    rtype, val1, val2 = parse_range(m["title"])
                    if not rtype:
                        continue
                    prob = calculate_market_probability(
                        rtype, val1, val2, pooled_temps
                    )
                    model_probabilities[ticker] = prob

                # Find edges
                edges = edge_detector.find_edges(date_markets, model_probabilities)
                for edge in edges:
                    size = risk_manager.calculate_position_size(
                        edge, risk_manager.bankroll, cumulative_exposure
                    )
                    # Track cumulative exposure
                    cumulative_exposure += edge["entry_price"] * size

                    all_edges.append(
                        {
                            "date": target_date,
                            "city": city_name,
                            "temp_type": temp_type,
                            "ticker": edge["ticker"],
                            "title": edge["title"],
                            "play": edge["side"].upper(),
                            "price": int(round(edge["entry_price"] * 100)),
                            "model_prob": float(edge["model_prob"]),
                            "net_ev": float(edge["net_ev"]),
                            "suggested_size": int(size),
                            "yes_bid": int(round(edge.get("yes_bid", 0) * 100)),
                            "yes_ask": int(round(edge.get("yes_ask", 0) * 100)),
                            "no_bid": int(round(edge.get("no_bid", 0) * 100)),
                            "no_ask": int(round(edge.get("no_ask", 0) * 100)),
                            "spread": int(round(edge.get("spread", 0) * 100)),
                            "mean": float(stats["mean"]),
                            "std": float(stats["std"]),
                        }
                    )

    await client.close()

    # Sort by descending EV
    all_edges.sort(key=lambda x: x["net_ev"], reverse=True)

    progress(f"Scan completed. {len(all_edges)} edges found.")
    return all_edges
