import asyncio
import logging
import os
import sys
import yaml
import pytz
from datetime import datetime, timedelta

# Add project root to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.data_ingestion.kalshi_client import KalshiWeatherClient
from src.data_ingestion.gfs_downloader import GFSDownloader
from src.data_ingestion.ecmwf_downloader import ECMWFDownloader
from src.data_ingestion.hrrr_downloader import HRRRDownloader
from src.models.weather_model import WeatherModelProcessor
from src.models.probability import calculate_market_probability
from src.trading.edge_detector import EdgeDetector
from src.trading.risk_manager import RiskManager
from src.utils.helpers import parse_range
from src.utils.bias_tracker import BIasTracker

# Suppress debug logs to keep output clean
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("scanner")
logger.setLevel(logging.INFO)

async def scan():
    logger.info("Initializing Live Production Scanner...")
    
    # 1. Load Configurations
    config_path = os.path.join("config", "settings.yaml")
    cities_path = os.path.join("config", "cities.yaml")
    
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    with open(cities_path, "r") as f:
        cities_data = yaml.safe_load(f)
        cities = cities_data.get("cities", [])
        
    # Configure production simulation
    config['kalshi']['environment'] = 'prod'
    config['kalshi']['simulation'] = True
    config['kalshi']['trading']['min_edge_threshold'] = 0.05  # Scan for any edge >= 5%
    
    client = KalshiWeatherClient(config)
    gfs_downloader = GFSDownloader(config)
    ecmwf_downloader = ECMWFDownloader(config)
    hrrr_downloader = HRRRDownloader(config)
    model_processor = WeatherModelProcessor(config)
    edge_detector = EdgeDetector(config)
    risk_manager = RiskManager(config)
    bias_tracker = BIasTracker(config)
    bias_offsets = bias_tracker.load_bias_offsets()
    
    await client.initialize()
    
    all_edges = []
    
    logger.info("Starting scans across all active cities...")
    
    for city in cities:
        if not city.get("active", True):
            continue
            
        city_name = city["name"]
        lat = city["lat"]
        lon = city["lon"]
        timezone_str = city["timezone"]
        
        # Calculate target dates: Today and Tomorrow
        tz = pytz.timezone(timezone_str)
        local_now = datetime.now(tz)
        target_dates = [
            local_now.strftime("%Y-%m-%d"),
            (local_now + timedelta(days=1)).strftime("%Y-%m-%d")
        ]
        
        # Scan both HIGH and LOW
        scans = [
            ("HIGH", city["kalshi_market_prefix"]),
            ("LOW", city["kalshi_market_prefix_low"])
        ]
        
        # Download forecasts once per city for each date
        forecasts_by_date = {}
        for target_date in target_dates:
            gfs = await gfs_downloader.download_ensemble_forecast(lat, lon, target_date, timezone_str)
            await asyncio.sleep(1.0)
            ecmwf = await ecmwf_downloader.download_ensemble_forecast(lat, lon, target_date, timezone_str)
            await asyncio.sleep(1.0)
            hrrr = await hrrr_downloader.download_forecast(lat, lon, target_date, timezone_str)
            await asyncio.sleep(1.0)
            forecasts_by_date[target_date] = (gfs, ecmwf, hrrr)

        for temp_type, prefix in scans:
            # Fetch Kalshi Markets
            markets = await client.get_weather_markets(prefix)
            if not markets:
                continue
                
            for target_date in target_dates:
                try:
                    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
                    date_ticker_str = dt_obj.strftime("%y%b%d").upper()
                except Exception:
                    continue
                    
                date_markets = [m for m in markets if date_ticker_str in m["ticker"]]
                if not date_markets:
                    continue
                    
                gfs_forecast, ecmwf_forecast, hrrr_forecast = forecasts_by_date.get(target_date, (None, None, None))
                if not gfs_forecast and not ecmwf_forecast:
                    logger.warning(f"  Failed to retrieve weather forecasts for {city_name} on {target_date}.")
                    continue
                    
                logger.info(f"Checking {city_name} {temp_type} for {target_date}...")
                
                # Process & Pool Ensembles with MOS rolling bias + HRRR shift
                bias_key = f"{city['code']}_{temp_type}"
                bias_offset = bias_offsets.get(bias_key, 0.0)
                if bias_offset != 0.0:
                    logger.info(f"  Applying MOS rolling bias offset for {bias_key}: {bias_offset:+.2f}°F")
                    
                pooled_temps = model_processor.process_ensembles(
                    gfs_forecast, 
                    ecmwf_forecast, 
                    temp_type, 
                    bias_offset=bias_offset, 
                    hrrr_data=hrrr_forecast
                )
                if len(pooled_temps) == 0:
                    continue
                    
                stats = model_processor.get_distribution_stats(pooled_temps)
                mean_val = stats["mean"]
                std_val = stats["std"]
                
                logger.info(f"  {city_name} {temp_type} forecast distribution: Mean={mean_val:.1f}°F, Std={std_val:.1f}°F")
                
                # Calculate probabilities
                model_probabilities = {}
                for m in date_markets:
                    title = m["title"]
                    ticker = m["ticker"]
                    rtype, val1, val2 = parse_range(title)
                    if not rtype:
                        continue
                        
                    prob = calculate_market_probability(rtype, val1, val2, pooled_temps)
                    model_probabilities[ticker] = prob
                    
                # Find edges
                edges = edge_detector.find_edges(date_markets, model_probabilities)
                for edge in edges:
                    # Add metadata
                    edge["city"] = city_name
                    edge["temp_type"] = temp_type
                    edge["date"] = target_date
                    # Calculate size
                    size = risk_manager.calculate_position_size(edge, risk_manager.bankroll, 0.0)
                    edge["suggested_size"] = size
                    all_edges.append(edge)
                    
    # Print results
    print("\n" + "="*95)
    print(f"                     LIVE +EV WEATHER PLAYS REPORT (TODAY & TOMORROW)")
    print("="*95)
    if not all_edges:
        print("No positive EV plays found meeting the 5% threshold.")
    else:
        print(f"{'Date':<10} | {'City':<12} | {'Type':<4} | {'Ticker':<28} | {'Play':<4} | {'Price':<5} | {'Model%':<6} | {'Net EV%':<7} | {'Size':<4}")
        print("-"*95)
        for e in all_edges:
            print(f"{e['date']:<10} | {e['city']:<12} | {e['temp_type']:<4} | {e['ticker']:<28} | {e['side'].upper():<4} | {int(e['entry_price']*100):>3}¢ | {e['model_prob']:>5.1%} | {e['net_ev']:>+6.1%} | {e['suggested_size']:>4}")
            
    print("="*95 + "\n")
    await client.close()

if __name__ == "__main__":
    asyncio.run(scan())
