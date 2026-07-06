import logging
import os
import json
import asyncio
import pytz
import aiohttp
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class BiasTracker:
    """Track forecasts vs actual observations, and compute rolling bias adjustments (MOS)."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.log_file = "data/historical/forecasts_log.json"
        self.offsets_file = "data/historical/bias_offsets.json"
        self.cache_file = "data/historical/actuals_cache.json"
        
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        self.actuals_cache = self.load_actuals_cache()
        
    def load_actuals_cache(self) -> Dict[str, float]:
        """Load NWS actual daily temperatures cache from disk."""
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading actuals cache: {e}")
            return {}
            
    def save_actuals_cache(self):
        """Save NWS actual daily temperatures cache to disk."""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, "w") as f:
                json.dump(self.actuals_cache, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving actuals cache: {e}")
        
    def load_history(self) -> List[Dict[str, Any]]:
        """Load prediction history from disk."""
        if not os.path.exists(self.log_file):
            return []
        try:
            with open(self.log_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading forecasts history: {e}")
            return []
            
    def save_history(self, history: List[Dict[str, Any]]):
        """Save prediction history to disk."""
        try:
            with open(self.log_file, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving forecasts history: {e}")

    def log_forecast(self, city_code: str, temp_type: str, date_str: str, forecast_mean: float):
        """
        Record a forecast mean for a future date.
        """
        history = self.load_history()
        
        # Check if record already exists
        for entry in history:
            if entry["city"] == city_code and entry["temp_type"] == temp_type and entry["date"] == date_str:
                entry["forecast_mean"] = forecast_mean
                self.save_history(history)
                return
                
        # Append new entry
        history.append({
            "date": date_str,
            "city": city_code,
            "temp_type": temp_type,
            "forecast_mean": forecast_mean,
            "actual": None
        })
        self.save_history(history)
        logger.debug(f"Logged forecast mean for {city_code} {temp_type} on {date_str}: {forecast_mean:.2f}°F")

    async def fetch_yesterday_actual(
        self,
        station_id: str,
        target_date_str: str,
        timezone_str: str,
        temp_type: str
    ) -> Optional[float]:
        """
        Query NWS Daily Climate Summary (CLI) or hourly observations for a target date.
        Uses the dynamic CLI-first canonical function from core_scanner and caches the result.
        """
        cache_key = f"{station_id}_{target_date_str}_{temp_type}"
        if cache_key in self.actuals_cache:
            logger.debug(f"Cache hit for {cache_key}: {self.actuals_cache[cache_key]}F")
            return self.actuals_cache[cache_key]
            
        try:
            from core_scanner import fetch_nws_actual_high_low
            val = await fetch_nws_actual_high_low(station_id, target_date_str, timezone_str, temp_type)
            if val is not None:
                self.actuals_cache[cache_key] = val
                self.save_actuals_cache()
            return val
        except Exception as e:
            logger.error(f"Error fetching actuals for {station_id}: {e}")
        return None

    async def update_actuals_and_bias(self, cities: List[Dict[str, Any]], lookback_days: int = 14) -> Dict[str, float]:
        """
        Scan history to fill missing actuals, update bias calculations, and write offsets.
        """
        history = self.load_history()
        updated = False
        
        # Scan history to fill missing actuals for any past dates in log
        for entry in history:
            if entry["actual"] is None:
                city_code = entry["city"]
                city = next((c for c in cities if c["code"] == city_code), None)
                if not city:
                    continue
                    
                target_date = entry["date"]
                station = city["nws_station_id"]
                tz_str = city["timezone"]
                temp_type = entry["temp_type"]
                
                # Check if target date is in the past relative to local timezone
                tz = pytz.timezone(tz_str)
                local_today = datetime.now(tz).strftime("%Y-%m-%d")
                if target_date >= local_today:
                    continue
                    
                # Fetch NWS actual observed High/Low
                actual_val = await self.fetch_yesterday_actual(station, target_date, tz_str, temp_type)
                if actual_val is not None:
                    entry["actual"] = actual_val
                    updated = True
                    await asyncio.sleep(0.5) # Rate limit pacing protection
                            
        if updated:
            self.save_history(history)
            
        # Recompute rolling bias offsets
        offsets = {}
        for city in cities:
            city_code = city["code"]
            for temp_type in ["HIGH", "LOW"]:
                # Gather recent entries for this city & type
                matching_entries = [
                    entry for entry in history 
                    if entry["city"] == city_code and entry["temp_type"] == temp_type and entry["actual"] is not None
                ]
                
                # Sort by date descending and take the last lookback_days
                matching_entries.sort(key=lambda x: x["date"], reverse=True)
                recent_entries = matching_entries[:lookback_days]
                
                key_name = f"{city_code}_{temp_type}"
                if len(recent_entries) >= 3:
                    # Compute rolling average bias: actual - forecast
                    biases = [e["actual"] - e["forecast_mean"] for e in recent_entries]
                    avg_bias = float(np.mean(biases))
                    offsets[key_name] = avg_bias
                    logger.info(f"📈 MOS Rolling Bias for {key_name}: {avg_bias:+.2f}°F (based on {len(recent_entries)} days)")
                else:
                    offsets[key_name] = 0.0
                    logger.info(f"📈 MOS Rolling Bias for {key_name}: 0.00°F (insufficient historical data: {len(recent_entries)}/3 days)")
                    
        # Write offsets to disk
        try:
            with open(self.offsets_file, "w") as f:
                json.dump(offsets, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving bias offsets file: {e}")
            
        return offsets

    def load_bias_offsets(self) -> Dict[str, float]:
        """Load calculated bias offsets from disk."""
        if not os.path.exists(self.offsets_file):
            return {}
        try:
            with open(self.offsets_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading bias offsets: {e}")
            return {}
