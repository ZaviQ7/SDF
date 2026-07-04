import logging
import os
import json
import pytz
import aiohttp
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class BIasTracker:
    """Track forecasts vs actual observations, and compute rolling bias adjustments (MOS)."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.log_file = "data/historical/forecasts_log.json"
        self.offsets_file = "data/historical/bias_offsets.json"
        
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        
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
        Query NWS hourly observations for a target date, convert to local time,
        and find the actual daily High or Low.
        """
        url = f"https://api.weather.gov/stations/{station_id}/observations"
        headers = {"User-Agent": "KalshiWeatherBot/1.0 (contact@kalshiedgebot.com)"}
        
        logger.info(f"Fetching actual observed temperatures for {station_id} on {target_date_str}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=12) as resp:
                    if resp.status != 200:
                        logger.warning(f"Failed to fetch NWS observations for {station_id} ({resp.status})")
                        return None
                        
                    data = await resp.json()
                    features = data.get("features", [])
                    if not features:
                        return None
                        
                    tz = pytz.timezone(timezone_str)
                    local_temps = []
                    
                    for f in features:
                        props = f.get("properties", {})
                        timestamp_str = props.get("timestamp")
                        temp_c = props.get("temperature", {}).get("value")
                        
                        if timestamp_str and temp_c is not None:
                            # Parse UTC time and convert to local time
                            utc_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                            local_dt = utc_dt.astimezone(tz)
                            
                            # Check if the observation date matches our target local date
                            if local_dt.strftime("%Y-%m-%d") == target_date_str:
                                temp_f = temp_c * 9/5 + 32
                                local_temps.append(temp_f)
                                
                    if not local_temps:
                        logger.warning(f"No NWS hourly temperatures found matching target local date {target_date_str} for station {station_id}")
                        return None
                        
                    # Calculate true High or Low
                    actual_val = max(local_temps) if temp_type == "HIGH" else min(local_temps)
                    logger.info(f"✅ Found {temp_type} actual for {station_id} on {target_date_str}: {actual_val:.1f}°F (from {len(local_temps)} observations)")
                    return float(actual_val)
                    
        except Exception as e:
            logger.error(f"Error fetching actuals for {station_id}: {e}")
        return None

    async def update_actuals_and_bias(self, cities: List[Dict[str, Any]], lookback_days: int = 14) -> Dict[str, float]:
        """
        Scan history to fill missing actuals, update bias calculations, and write offsets.
        """
        history = self.load_history()
        updated = False
        
        # We look for yesterday's date relative to the local time of each city
        for city in cities:
            city_code = city["code"]
            station = city["nws_station_id"]
            tz_str = city["timezone"]
            
            tz = pytz.timezone(tz_str)
            local_yesterday = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")
            
            for temp_type in ["HIGH", "LOW"]:
                # Find matching history entry
                for entry in history:
                    if (entry["city"] == city_code and 
                        entry["temp_type"] == temp_type and 
                        entry["date"] == local_yesterday and 
                        entry["actual"] is None):
                        
                        # Fetch NWS actual observed High/Low
                        actual_val = await self.fetch_yesterday_actual(station, local_yesterday, tz_str, temp_type)
                        if actual_val is not None:
                            entry["actual"] = actual_val
                            updated = True
                            
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
