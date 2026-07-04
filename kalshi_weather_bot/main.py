import asyncio
import logging
import os
import sys
import yaml
import time
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Add project root to python path to avoid import errors
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.data_ingestion.kalshi_client import KalshiWeatherClient
from src.data_ingestion.gfs_downloader import GFSDownloader
from src.data_ingestion.ecmwf_downloader import ECMWFDownloader
from src.data_ingestion.hrrr_downloader import HRRRDownloader
from src.models.weather_model import WeatherModelProcessor
from src.models.probability import calculate_market_probability
from src.trading.edge_detector import EdgeDetector
from src.trading.risk_manager import RiskManager
from src.trading.order_executor import OrderExecutor
from src.monitoring.logger import setup_logging
from src.monitoring.dashboard import TerminalDashboard
from src.utils.validators import validate_config, validate_cities
from src.utils.bias_tracker import BIasTracker

# Capture log stream in memory to display on terminal dashboard
class DashboardLogHandler(logging.Handler):
    def __init__(self, limit=8):
        super().__init__()
        self.limit = limit
        self.log_queue = []
        self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S"))

    def emit(self, record):
        log_entry = self.format(record)
        # Style color based on log level
        if record.levelno >= logging.ERROR:
            log_entry = f"[bold red]{log_entry}[/]"
        elif record.levelno >= logging.WARNING:
            log_entry = f"[yellow]{log_entry}[/]"
        elif "Edge detected" in record.getMessage() or "FILLED" in record.getMessage():
            log_entry = f"[green]{log_entry}[/]"
        
        self.log_queue.append(log_entry)
        if len(self.log_queue) > self.limit:
            self.log_queue.pop(0)

async def main():
    # 1. Load Configurations and Dotenv
    load_dotenv()
    
    config_path = os.path.join("config", "settings.yaml")
    cities_path = os.path.join("config", "cities.yaml")
    
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        
    with open(cities_path, "r") as f:
        cities_data = yaml.safe_load(f)
        cities = cities_data.get("cities", [])

    # 2. Setup Logging
    logger = setup_logging(config)
    dash_log_handler = DashboardLogHandler(limit=6)
    logging.getLogger().addHandler(dash_log_handler)
    
    # 3. Validate Inputs
    if not validate_config(config) or not validate_cities(cities):
        logger.error("Configuration validation failed. Exiting.")
        return
        
    # 4. Instantiate components
    client = KalshiWeatherClient(config)
    gfs_downloader = GFSDownloader(config)
    ecmwf_downloader = ECMWFDownloader(config)
    hrrr_downloader = HRRRDownloader(config)
    model_processor = WeatherModelProcessor(config)
    edge_detector = EdgeDetector(config)
    risk_manager = RiskManager(config)
    executor = OrderExecutor(client, config)
    dashboard = TerminalDashboard()
    bias_tracker = BIasTracker(config)
    bias_offsets = bias_tracker.load_bias_offsets()
    
    # Initialize API client
    initialized = await client.initialize()
    if not initialized:
        logger.error("Client initialization failed.")
        return
        
    # Main bot event loop
    loop_count = 0
    refresh_seconds = config['dashboard'].get('refresh_interval_seconds', 15)
    
    logger.info("Bot starting main scanning loops...")
    
    try:
        while True:
            logger.info(f"--- Starting Scan Loop #{loop_count} ---")
            
            # Fetch observations and update rolling bias offsets
            try:
                bias_offsets = await bias_tracker.update_actuals_and_bias(cities, lookback_days=14)
            except Exception as e:
                logger.error(f"Failed to update MOS bias tracker: {e}")
            
            # Retrieve all markets to pool for simulation matching
            markets_by_ticker = {}
            all_detected_edges = []
            
            # Loop over configured cities
            for city in cities:
                if not city.get("active", True):
                    continue
                    
                city_name = city["name"]
                lat = city["lat"]
                lon = city["lon"]
                timezone_str = city["timezone"]
                
                # Get current time and target dates in local timezone
                tz = pytz.timezone(timezone_str)
                local_now = datetime.now(tz)
                
                # Scan both Today and Tomorrow
                target_dates = [
                    local_now.strftime("%Y-%m-%d"),
                    (local_now + timedelta(days=1)).strftime("%Y-%m-%d")
                ]
                
                # Download forecasts once per city for each date
                city_forecasts = {}
                for target_date in target_dates:
                    gfs = await gfs_downloader.download_ensemble_forecast(lat, lon, target_date, timezone_str)
                    await asyncio.sleep(1.0)
                    ecmwf = await ecmwf_downloader.download_ensemble_forecast(lat, lon, target_date, timezone_str)
                    await asyncio.sleep(1.0)
                    hrrr = await hrrr_downloader.download_forecast(lat, lon, target_date, timezone_str)
                    await asyncio.sleep(1.0)
                    city_forecasts[target_date] = (gfs, ecmwf, hrrr)

                # Scan both High and Low markets
                scans = [
                    ("HIGH", city["kalshi_market_prefix"]),
                    ("LOW", city["kalshi_market_prefix_low"])
                ]
                
                for temp_type, prefix in scans:
                    # Fetch active Kalshi markets for this prefix
                    raw_markets = await client.get_weather_markets(prefix)
                    
                    if not raw_markets:
                        continue
                        
                    # Map markets for simulation pricing lookup
                    for m in raw_markets:
                        markets_by_ticker[m["ticker"]] = m
                        
                    for target_date in target_dates:
                        # Find Kalshi markets targeting this date
                        # Weather markets contain resolving dates in their tickers (e.g. 26JUL04)
                        # We convert the target_date to Kalshi ticker format, e.g. "2026-07-04" -> "26JUL04"
                        try:
                            dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
                            # Convert year to 2 digits, month abbreviation in caps, day in 2 digits
                            date_ticker_str = dt_obj.strftime("%y%b%d").upper()
                        except Exception as e:
                            logger.error(f"Error parsing date format: {e}")
                            continue
                            
                        # Filter markets for this target date
                        date_markets = [m for m in raw_markets if date_ticker_str in m["ticker"]]
                        if not date_markets:
                            continue
                            
                        gfs_forecast, ecmwf_forecast, hrrr_forecast = city_forecasts.get(target_date, (None, None, None))
                        if not gfs_forecast and not ecmwf_forecast:
                            logger.warning(f"No weather ensemble forecasts downloaded for {city_name} on {target_date}")
                            continue
                            
                        logger.info(f"Scanning {city_name} {temp_type} for date {target_date} ({len(date_markets)} markets)")
                        
                        # Pool forecasts and calculate distribution stats with MOS rolling bias + HRRR shift
                        bias_key = f"{city['code']}_{temp_type}"
                        bias_offset = bias_offsets.get(bias_key, 0.0)
                        if bias_offset != 0.0:
                            logger.info(f"Applying MOS rolling bias offset for {bias_key}: {bias_offset:+.2f}°F")
                            
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
                        
                        # Log forecast mean for future comparison with actuals
                        bias_tracker.log_forecast(city["code"], temp_type, target_date, mean_val)
                        
                        logger.info(f"Model pooled stats (MOS corrected): Mean={mean_val:.2f}°F, Std={std_val:.2f}°F")
                        
                        # Compute fair probability for each market contract
                        model_probabilities = {}
                        for m in date_markets:
                            title = m["title"]
                            ticker = m["ticker"]
                            # Parse target range from title, e.g. "85 to 86" or ">= 85"
                            rtype, val1, val2 = parse_range(title)
                            if not rtype:
                                continue
                                
                            prob = calculate_market_probability(rtype, val1, val2, pooled_temps)
                            model_probabilities[ticker] = prob
                            
                        # Detect edges
                        city_edges = edge_detector.find_edges(date_markets, model_probabilities)
                        all_detected_edges.extend(city_edges)
            
            # Sort all detected edges by net EV
            all_detected_edges.sort(key=lambda x: x["net_ev"], reverse=True)
            
            # 5. Simulation Engine update (Matching engine)
            client.update_simulation(markets_by_ticker)
            
            # 6. Resting order timeout management
            await executor.manage_resting_orders()
            
            # 7. Evaluate and Execute Edges
            # Compute total current exposure (positions + resting orders)
            positions = await client.get_positions()
            current_positions_val = sum(p["size"] * p["avg_price"] for p in positions)
            resting_exposure = executor.get_resting_orders_exposure()
            total_current_exposure = current_positions_val + resting_exposure
            
            # Check if global risk limits allow new trades
            if risk_manager.can_trade(client.simulated_balance if client.dry_run else await client.get_balance(), total_current_exposure):
                for edge in all_detected_edges:
                    ticker = edge["ticker"]
                    side = edge["side"]
                    
                    # Avoid duplicate orders for the same market
                    already_ordered = any(o["ticker"] == ticker and o["side"] == side for o in executor.open_orders.values())
                    already_positioned = any(p["ticker"] == ticker and p["side"] == side for p in positions)
                    
                    if already_ordered or already_positioned:
                        continue
                        
                    # Calculate sizing using risk controls
                    size = risk_manager.calculate_position_size(
                        edge,
                        client.simulated_balance if client.dry_run else await client.get_balance(),
                        total_current_exposure
                    )
                    
                    if size > 0:
                        # Place limit resting order
                        order = await executor.place_order(edge, size)
                        if order:
                            # Recalculate exposure
                            resting_exposure = executor.get_resting_orders_exposure()
                            total_current_exposure = current_positions_val + resting_exposure
                            
            # 8. Render Terminal Dashboard
            # Gather risk manager details
            risk_summary = {
                "bankroll": risk_manager.bankroll,
                "total_exposure": total_current_exposure,
                "exposure_pct": (total_current_exposure / risk_manager.bankroll) * 100.0,
                "daily_pnl": risk_manager.daily_pnl,
                "open_positions": len(positions),
                "max_positions": risk_manager.max_open_positions,
                "daily_loss_limit": risk_manager.daily_loss_limit
            }
            
            dashboard.render(
                risk_summary=risk_summary,
                edges=all_detected_edges,
                positions=positions,
                resting_orders=list(executor.open_orders.values()),
                logs=dash_log_handler.log_queue,
                dry_run=client.dry_run
            )
            
            loop_count += 1
            await asyncio.sleep(refresh_seconds)
            
    except asyncio.CancelledError:
        logger.info("Bot execution cancelled. Cleaning up open orders...")
        # In a real environment, we'd cancel open resting orders on exit
        for oid in list(executor.open_orders.keys()):
            await executor.cancel_order(oid)
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown signal received. Terminating bot.")
