import os
import sys
import json
import yaml
import asyncio
import logging
import re
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

# Add project root to python path so we can import src modules
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from core_scanner import run_scan

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("server")

app = FastAPI(title="Kalshi Weather Arbitrage API")

# Enable CORS for frontend Vite development server (port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE_FILE = os.path.join(BASE_DIR, "data", "edges_cache.json")
MD_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "theoretical_edges.md"))

# In-memory scan status
scan_status = {
    "status": "idle",  # "idle" or "scanning"
    "progress": "",
    "error": None,
    "last_completed": None
}

def parse_settled_trades(md_path: str):
    trades = []
    if not os.path.exists(md_path):
        logger.warning(f"Markdown file not found at {md_path}")
        return trades
    
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        in_settled_section = False
        for line in lines:
            if "Historical Weather Trades" in line:
                in_settled_section = True
                continue
            if in_settled_section and line.startswith("##"):
                in_settled_section = False
                
            if in_settled_section and line.startswith("|") and not "Target Date" in line and not "---" in line:
                parts = [p.strip() for p in line.split("|")][1:-1]
                if len(parts) >= 9:
                    loc_raw = parts[1]
                    location = loc_raw.split("**")[1] if "**" in loc_raw else loc_raw
                    # Remove HTML breaks and formatting
                    location = location.split("<br>")[0].replace("([NOAA Link", "").strip()
                    
                    ticker = ""
                    ticker_match = re.search(r'`([^`]+)`', loc_raw)
                    if ticker_match:
                        ticker = ticker_match.group(1)
                        
                    trades.append({
                        "date": parts[0],
                        "location": location,
                        "ticker": ticker,
                        "play": parts[2].replace("**", "").strip(),
                        "qty": parts[3].strip(),
                        "cost": parts[4].replace("<br>", " ").replace("**", "").strip(),
                        "prob": parts[5].strip(),
                        "ev": parts[6].strip(),
                        "payout": parts[7].strip(),
                        "status": parts[8].strip()
                    })
    except Exception as e:
        logger.error(f"Error parsing settled trades: {e}")
    return trades

async def execute_scanner_task():
    global scan_status
    scan_status["status"] = "scanning"
    scan_status["error"] = None
    
    try:
        # Load configs
        config_path = os.path.join(BASE_DIR, "config", "settings.yaml")
        cities_path = os.path.join(BASE_DIR, "config", "cities.yaml")
        
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        with open(cities_path, "r") as f:
            cities_data = yaml.safe_load(f)
            cities = cities_data.get("cities", [])

        def on_progress(msg):
            scan_status["progress"] = msg

        all_edges = await run_scan(config, cities, on_progress=on_progress)
        
        # Save cache
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        timestamp = datetime.now().isoformat()
        with open(CACHE_FILE, "w") as f:
            json.dump({
                "edges": all_edges,
                "last_scan": timestamp
            }, f, indent=4)
            
        scan_status["status"] = "idle"
        scan_status["progress"] = "Scan completed."
        scan_status["last_completed"] = timestamp
        logger.info("Scan successfully completed and cached.")
        
    except Exception as e:
        logger.error(f"Scan failed with error: {e}")
        scan_status["status"] = "idle"
        scan_status["progress"] = "Scan failed."
        scan_status["error"] = str(e)

@app.get("/api/edges")
def get_edges():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read cache file: {e}")
            
    return {"edges": [], "last_scan": None}

@app.get("/api/settled")
def get_settled():
    trades = parse_settled_trades(MD_FILE)
    return {"trades": trades}

@app.get("/api/status")
def get_status():
    return scan_status

@app.post("/api/scan")
def trigger_scan(background_tasks: BackgroundTasks):
    global scan_status
    if scan_status["status"] == "scanning":
        return {"status": "scanning", "message": "Scan already in progress."}
        
    background_tasks.add_task(execute_scanner_task)
    return {"status": "scanning", "message": "Scan triggered in background."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
