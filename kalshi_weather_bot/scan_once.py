import asyncio
import logging
import os
import sys
import yaml

# Add project root to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core_scanner import run_scan

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
        
    all_edges = await run_scan(config, cities)
    
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
            print(f"{e['date']:<10} | {e['city']:<12} | {e['temp_type']:<4} | {e['ticker']:<28} | {e['play']:<4} | {e['price']:>3}¢ | {e['model_prob']:>5.1%} | {e['net_ev']:>+6.1%} | {e['suggested_size']:>4}")
            
    print("="*95 + "\n")

if __name__ == "__main__":
    asyncio.run(scan())
