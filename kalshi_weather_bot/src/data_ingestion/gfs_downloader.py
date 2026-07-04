import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import aiohttp
import numpy as np

logger = logging.getLogger(__name__)

class GFSDownloader:
    """Download GFS ensemble forecast data using Open-Meteo API."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config['weather']['gfs'].get('enabled', True)
        self.ensemble_members = config['weather']['gfs'].get('ensemble_members', 31)
        self.nws_obs_url = config['weather']['nws'].get('observation_url')

    async def download_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        target_date: str,
        timezone: str
    ) -> Optional[Dict[str, Any]]:
        """
        Download GFS ensemble forecast for a location and local timezone.
        
        Args:
            lat: Latitude
            lon: Longitude
            target_date: Target date in YYYY-MM-DD format
            timezone: Location's local timezone (e.g., "America/New_York")
            
        Returns:
            Dict containing raw forecast values or None
        """
        if not self.enabled:
            logger.info("GFS downloader is disabled in config.")
            return None

        # Build url for Open-Meteo Ensemble API
        url = (
            f"https://ensemble-api.open-meteo.com/v1/ensemble"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m"
            f"&models=gfs_seamless"
            f"&temperature_unit=fahrenheit"
            f"&timezone={timezone}"
        )
        
        logger.info(f"Downloading GFS ensemble for ({lat}, {lon}) on {target_date}...")
        
        max_retries = 3
        backoff = 2.0
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 429:
                            logger.warning(f"Open-Meteo GFS API rate limited (429). Retrying in {backoff}s...")
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue
                        elif resp.status != 200:
                            text = await resp.text()
                            logger.error(f"Open-Meteo GFS API error ({resp.status}): {text}")
                            return None
                            
                        data = await resp.json()
                        hourly = data.get("hourly", {})
                        times = hourly.get("time", [])
                        
                        # Find indices matching the target date (local time)
                        indices = [i for i, t in enumerate(times) if t.startswith(target_date)]
                        if not indices:
                            logger.error(f"No forecast times found matching target date {target_date}")
                            return None
                            
                        # Extract ensemble member keys
                        member_keys = [k for k in hourly.keys() if k.startswith("temperature_2m")]
                        
                        # For each member, extract the temperatures for target date indices
                        member_forecasts = {}
                        for key in member_keys:
                            clean_key = key.replace("temperature_2m_", "").replace("temperature_2m", "control")
                            temps = [hourly[key][idx] for idx in indices if hourly[key][idx] is not None]
                            if temps:
                                member_forecasts[clean_key] = temps
                            
                        logger.info(f"Successfully processed {len(member_forecasts)} GFS ensemble members.")
                        return {
                            "source": "GFS",
                            "target_date": target_date,
                            "timezone": timezone,
                            "forecast_hours": [times[idx] for idx in indices],
                            "members": member_forecasts
                        }
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Error downloading GFS ensemble data: {e}")
                    return None
                logger.warning(f"Error downloading GFS ensemble data (attempt {attempt+1}/{max_retries}): {e}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff *= 2

    async def get_current_observations(self, station_id: str) -> Optional[Dict[str, Any]]:
        """Get latest observations from the NWS station (public endpoint)."""
        url = self.nws_obs_url.format(station=station_id) if self.nws_obs_url else f"https://api.weather.gov/stations/{station_id}/observations/latest"
        headers = {"User-Agent": "KalshiWeatherBot/1.0 (contact@kalshiedgebot.com)"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        props = data.get("properties", {})
                        temp_c = props.get("temperature", {}).get("value")
                        
                        if temp_c is not None:
                            temp_f = temp_c * 9/5 + 32
                            return {
                                "station": station_id,
                                "temperature": float(temp_f),
                                "timestamp": props.get("timestamp"),
                                "text": props.get("textDescription", "Unknown")
                            }
                    else:
                        logger.warning(f"NWS observation fetch failed ({resp.status}) for station {station_id}")
        except Exception as e:
            logger.error(f"Error getting NWS observations for {station_id}: {e}")
        return None
