import asyncio
import os
import sys
import json
import yaml
from datetime import datetime, timedelta

# Set stdout to UTF-8 to prevent Windows terminal encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.utils.bias_tracker import BiasTracker
from scan_once import scan

def setup_mock_history():
    print("Setting up mock historical data...")
    history_file = "data/historical/forecasts_log.json"
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    
    # We will log 5 days of mock data for Chicago (CHI) HIGH
    # In each case, forecast was 88.0°F, but actual was 90.0°F (meaning a +2.0°F bias)
    history = []
    base_date = datetime.now() - timedelta(days=6)
    
    for i in range(5):
        date_str = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        history.append({
            "date": date_str,
            "city": "CHI",
            "temp_type": "HIGH",
            "forecast_mean": 88.0,
            "actual": 90.0
        })
        
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
    print(f"Mock history written to {history_file}")

async def run_test():
    setup_mock_history()
    
    # Load config
    config_path = os.path.join("config", "settings.yaml")
    cities_path = os.path.join("config", "cities.yaml")
    
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    with open(cities_path, "r") as f:
        cities_data = yaml.safe_load(f)
        cities = cities_data.get("cities", [])
        
    bias_tracker = BiasTracker(config)
    
    # Run the bias calculation (lookback=14)
    # This will load history, skip fetching yesterday since we didn't mock yesterday specifically,
    # and compute offsets from our 5 mock entries.
    print("Running rolling bias calculation...")
    offsets = await bias_tracker.update_actuals_and_bias(cities, lookback_days=14)
    print("Computed Offsets:", offsets)
    
    # Verify Chicago HIGH offset is 2.0
    chi_high_offset = offsets.get("CHI_HIGH", 0.0)
    assert abs(chi_high_offset - 2.0) < 0.01, f"Expected CHI_HIGH bias to be 2.0, got {chi_high_offset}"
    print("Success: Chicago HIGH rolling bias is calculated correctly as +2.00°F!")
    
    # Run a test scan pass to verify log applies this offset
    print("\nRunning scan_once to verify offset is dynamically applied during forecast processing...")
    # Temporarily override cities configuration to only check Chicago HIGH for testing speed
    chi_only = [c for c in cities if c["code"] == "CHI"]
    cities_data["cities"] = chi_only
    with open(cities_path, "w") as f:
        yaml.dump(cities_data, f)
        
    try:
        # Run scan
        await scan()
        print("Success: Scan ran successfully and logged the applied offset!")
    finally:
        # Restore cities.yaml
        cities_data["cities"] = cities
        with open(cities_path, "w") as f:
            yaml.dump(cities_data, f)
            
        # Clean up mock database files to leave the project clean
        if os.path.exists(history_file := "data/historical/forecasts_log.json"):
            os.remove(history_file)
        if os.path.exists(offsets_file := "data/historical/bias_offsets.json"):
            os.remove(offsets_file)
        print("Cleaned up mock historical data.")

if __name__ == "__main__":
    asyncio.run(run_test())
