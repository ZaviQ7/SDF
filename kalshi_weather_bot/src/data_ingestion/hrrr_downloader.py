import asyncio
import logging
from typing import Dict, Any, Optional
import aiohttp

logger = logging.getLogger(__name__)

class HRRRDownloader:
    """Download NOAA short-term hourly forecast data (HRRR/NDFD) using weather.gov API."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config['weather'].get('hrrr', {}).get('enabled', True)
        self.grid_cache = {}  # Cache forecastHourly URLs by (lat, lon)

    async def get_forecast_url(self, lat: float, lon: float) -> Optional[str]:
        """Resolve and cache the grid hourly forecast URL from lat/lon coordinates."""
        key = (lat, lon)
        if key in self.grid_cache:
            return self.grid_cache[key]
            
        url_points = f"https://api.weather.gov/points/{lat},{lon}"
        headers = {"User-Agent": "KalshiWeatherBot/1.0 (contact@kalshiedgebot.com)"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url_points, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        logger.error(f"NWS points resolution failed for ({lat}, {lon}) with status {resp.status}")
                        return None
                    data = await resp.json()
                    forecast_url = data.get("properties", {}).get("forecastHourly")
                    if forecast_url:
                        self.grid_cache[key] = forecast_url
                        return forecast_url
        except Exception as e:
            logger.error(f"Error resolving grid points for ({lat}, {lon}): {e}")
        return None

    async def download_forecast(
        self,
        lat: float,
        lon: float,
        target_date: str,
        timezone: str
    ) -> Optional[Dict[str, Any]]:
        """
        Download NOAA NWS hourly forecast (derived from HRRR) for target date.
        """
        if not self.enabled:
            return None
            
        forecast_url = await self.get_forecast_url(lat, lon)
        if not forecast_url:
            return None
            
        headers = {"User-Agent": "KalshiWeatherBot/1.0 (contact@kalshiedgebot.com)"}
        logger.info(f"Downloading short-term NWS/HRRR forecast from: {forecast_url} for date {target_date}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(forecast_url, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        logger.error(f"NWS hourly forecast fetch failed ({resp.status})")
                        return None
                        
                    data = await resp.json()
                    periods = data.get("properties", {}).get("periods", [])
                    
                    day_temps = []
                    for period in periods:
                        start_time = period.get("startTime", "")
                        temp_val = period.get("temperature")
                        
                        # startTime matches target_date in local timezone, e.g. "2026-07-03T10:00:00-05:00"
                        if start_time.startswith(target_date) and temp_val is not None:
                            # NWS provides temperatures in Fahrenheit by default
                            day_temps.append(float(temp_val))
                            
                    if not day_temps:
                        logger.warning(f"No NWS/HRRR hourly temperatures found matching target date {target_date}")
                        return None
                        
                    logger.info(f"Successfully processed NWS/HRRR forecast for {target_date} ({len(day_temps)} hours).")
                    return {
                        "source": "HRRR_NWS",
                        "target_date": target_date,
                        "temps": day_temps
                    }
        except Exception as e:
            logger.error(f"Error downloading NWS hourly forecast data: {e}")
        return None
