import asyncio
import logging
import os
import sys
import yaml

# Add current folder to system path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.data_ingestion.kalshi_client import KalshiWeatherClient
from src.data_ingestion.gfs_downloader import GFSDownloader
from src.data_ingestion.ecmwf_downloader import ECMWFDownloader
from src.models.weather_model import WeatherModelProcessor
from src.trading.edge_detector import EdgeDetector
from src.trading.risk_manager import RiskManager
from src.utils.validators import validate_config, validate_cities

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("verify_bot")

async def test_run():
    logger.info("Initializing Verification Run...")
    
    # 1. Load Configs
    config_path = os.path.join("config", "settings.yaml")
    cities_path = os.path.join("config", "cities.yaml")
    
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    with open(cities_path, "r") as f:
        cities_data = yaml.safe_load(f)
        cities = cities_data.get("cities", [])
        
    # Validate
    if not validate_config(config) or not validate_cities(cities):
        logger.error("Configuration validation failed!")
        return
        
    # Override settings for testing
    config['dashboard']['enabled'] = False # Disable UI in test
    
    # 2. Instantiate components
    client = KalshiWeatherClient(config)
    gfs_downloader = GFSDownloader(config)
    ecmwf_downloader = ECMWFDownloader(config)
    model_processor = WeatherModelProcessor(config)
    edge_detector = EdgeDetector(config)
    risk_manager = RiskManager(config)
    
    # Initialize client
    await client.initialize()
    
    # Take a sample city (e.g. Chicago)
    chicago = next((c for c in cities if c["code"] == "CHI"), None)
    if not chicago:
        logger.error("Chicago city configuration not found!")
        return
        
    logger.info(f"Testing City: {chicago['name']} ({chicago['lat']}, {chicago['lon']})")
    
    # Target date: tomorrow (in UTC/local format)
    # For testing, we use tomorrow's calendar date
    target_date = (datetime_now_local(chicago["timezone"]) + timedelta_days(1)).strftime("%Y-%m-%d")
    
    # 3. Test observations NWS
    logger.info("Testing NWS observations fetch...")
    obs = await gfs_downloader.get_current_observations(chicago["nws_station_id"])
    if obs:
        logger.info(f"✅ NWS Observations fetched: {obs['station']} | Temp: {obs['temperature']:.1f}°F | Text: {obs['text']}")
    else:
        logger.warning("❌ NWS Observations fetch failed or skipped.")
        
    # 4. Test downloaders
    logger.info("Testing Open-Meteo downloaders...")
    gfs_forecast = await gfs_downloader.download_ensemble_forecast(
        chicago["lat"], chicago["lon"], target_date, chicago["timezone"]
    )
    ecmwf_forecast = await ecmwf_downloader.download_ensemble_forecast(
        chicago["lat"], chicago["lon"], target_date, chicago["timezone"]
    )
    
    if gfs_forecast:
        logger.info(f"✅ GFS Downloader Success. Members: {len(gfs_forecast['members'])}")
    else:
        logger.warning("❌ GFS Downloader failed.")
        
    if ecmwf_forecast:
        logger.info(f"bold green]✅ ECMWF Downloader Success. Members: {len(ecmwf_forecast['members'])}")
    else:
        logger.warning("❌ ECMWF Downloader failed.")
        
    # 5. Test Weather model pooling
    if gfs_forecast or ecmwf_forecast:
        logger.info("Testing model processor pooling...")
        pooled_highs = model_processor.process_ensembles(gfs_forecast, ecmwf_forecast, "HIGH")
        stats = model_processor.get_distribution_stats(pooled_highs)
        logger.info(f"✅ Model pooling success. Total pooled runs: {stats['count']}")
        logger.info(f"   Distribution Stats: Mean={stats['mean']:.2f}°F | Std={stats['std']:.2f}°F | Min={stats['min']:.2f}°F | Max={stats['max']:.2f}°F")
    
    # 6. Test Kalshi weather market fetch
    logger.info("Testing Kalshi weather market fetch...")
    markets = await client.get_weather_markets(chicago["kalshi_market_prefix"])
    logger.info(f"✅ Kalshi fetched {len(markets)} active High markets for prefix {chicago['kalshi_market_prefix']}")
    if markets:
        logger.info(f"   Sample Market: {markets[0]['ticker']} | Yes Ask: {markets[0]['yes_ask']} | No Ask: {markets[0]['no_ask']}")
        
    logger.info("--- Verification completed successfully ---")
    await client.close()

def datetime_now_local(tz_str: str):
    import pytz
    tz = pytz.timezone(tz_str)
    from datetime import datetime
    return datetime.now(tz)

def timedelta_days(days: int):
    from datetime import timedelta
    return timedelta(days=days)

if __name__ == "__main__":
    asyncio.run(test_run())
