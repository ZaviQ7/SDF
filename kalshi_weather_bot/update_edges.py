import asyncio
import logging
import os
import sys
import yaml
import pytz
import re
import aiohttp
import subprocess
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
from src.utils.helpers import parse_range, calculate_maker_fee
from src.utils.bias_tracker import BIasTracker

# Suppress debug logs
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("updater")
logger.setLevel(logging.INFO)

# Map city names to NWS airport stations and timezones
CITY_STATIONS = {
    "Philadelphia": {"station": "KPHL", "timezone": "America/New_York"},
    "Chicago": {"station": "KORD", "timezone": "America/Chicago"},
    "Denver": {"station": "KDEN", "timezone": "America/Denver"},
    "Austin": {"station": "KAUS", "timezone": "America/Chicago"},
    "Miami": {"station": "KMIA", "timezone": "America/New_York"},
    "New Orleans": {"station": "KMSY", "timezone": "America/Chicago"},
    "Boston": {"station": "KBOS", "timezone": "America/New_York"}
}

async def fetch_nws_actual_high_low(station_id: str, target_date_str: str, timezone_str: str, temp_type: str) -> float | None:
    """Query NWS hourly observations to find yesterday's actual high/low."""
    url = f"https://api.weather.gov/stations/{station_id}/observations"
    headers = {"User-Agent": "KalshiWeatherBot/1.0 (contact@kalshiedgebot.com)"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                features = data.get("features", [])
                
                tz = pytz.timezone(timezone_str)
                local_temps = []
                
                for f in features:
                    props = f.get("properties", {})
                    timestamp_str = props.get("timestamp")
                    temp_c = props.get("temperature", {}).get("value")
                    
                    if timestamp_str and temp_c is not None:
                        utc_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        local_dt = utc_dt.astimezone(tz)
                        
                        if local_dt.strftime("%Y-%m-%d") == target_date_str:
                            temp_f = temp_c * 9/5 + 32
                            local_temps.append(temp_f)
                            
                if not local_temps:
                    return None
                    
                return max(local_temps) if temp_type == "HIGH" else min(local_temps)
    except Exception as e:
        logger.error(f"Error fetching actual for station {station_id}: {e}")
    return None

def evaluate_contract(ticker: str, actual_temp: float) -> bool | None:
    """Evaluate if a weather range contract settled YES (True) or NO (False)."""
    parts = ticker.split("-")
    if len(parts) < 3:
        return None
    suffix = parts[-1]
    temp_type = "HIGH" if "HIGH" in parts[0] else "LOW"
    
    actual_rounded = int(round(actual_temp))
    
    if suffix.startswith("B"):
        # Range is Between, e.g. B92.5 -> 92 to 93
        mid = float(suffix[1:])
        val1 = int(mid - 0.5)
        val2 = int(mid + 0.5)
        return (actual_rounded >= val1) and (actual_rounded <= val2)
    elif suffix.startswith("T"):
        # Range is Threshold, e.g. T101 -> >= 101 (HIGH) or <= 101 (LOW)
        val = float(suffix[1:])
        if temp_type == "HIGH":
            return actual_rounded >= val
        else:
            return actual_rounded <= val
    return None

def parse_logged_trades(file_path: str) -> list:
    """Parse existing weather trades from theoretical_edges.md."""
    if not os.path.exists(file_path):
        return []
        
    trades = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        # Fallback to CP1252 if UTF-8 fails (for Windows)
        with open(file_path, "r", encoding="cp1252") as f:
            content = f.read()
            
    lines = content.split("\n")
    for line in lines:
        if line.strip().startswith("|") and not "Target Date" in line and not ":---" in line:
            parts = [p.strip() for p in line.split("|")][1:-1]
            if len(parts) < 9:
                continue
                
            ticker_match = re.search(r"`([^`]+)`", parts[1])
            ticker = ticker_match.group(1) if ticker_match else ""
            if not ticker:
                continue
                
            trades.append({
                "formatted_date": parts[0],
                "location_line": parts[1],
                "play_desc": parts[2],
                "qty": int(parts[3]),
                "total_cost_line": parts[4],
                "true_prob": parts[5],
                "net_ev": parts[6],
                "est_payout": parts[7],
                "status": parts[8],
                "ticker": ticker
            })
    return trades

async def send_discord_report(active_trades: list):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.info("No DISCORD_WEBHOOK_URL environment variable set. Discord notification skipped.")
        return
        
    if not active_trades:
        payload = {
            "embeds": [{
                "title": "☀️ Live +EV Weather Trades Report",
                "description": "No active weather trades currently meet the >53% probability and positive EV criteria.",
                "color": 16711680 # Red
            }]
        }
    else:
        fields = []
        for t in active_trades:
            location = t["location_line"].split("**")[1] if "**" in t["location_line"] else "Weather Trade"
            ticker = t["ticker"]
            play = t["play_desc"]
            prob = t["true_prob"]
            ev = t["net_ev"]
            
            cost_match = re.search(r"\(\$([\d\.]+)\s+total\)", t["total_cost_line"])
            cost_str = f"${cost_match.group(1)}" if cost_match else t["total_cost_line"]
            
            fields.append(
                f"**{location}** (`{ticker}`)\n👉 {play} (Cost: {cost_str})\n📈 Prob: **{prob}** | EV: **{ev}**"
            )
            
        description = "\n\n".join(fields)
        if len(description) > 4000:
            description = description[:3900] + "\n... (truncated)"
            
        payload = {
            "embeds": [{
                "title": "☀️ Live +EV Weather Trades Report",
                "description": description,
                "color": 3066993, # Green
                "timestamp": datetime.now(pytz.utc).isoformat()
            }]
        }
        
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.info("Successfully sent edge report to Discord.")
                else:
                    text = await resp.text()
                    logger.error(f"Failed to send Discord notification ({resp.status}): {text}")
    except Exception as e:
        logger.error(f"Error sending Discord notification: {e}")

async def run_update():
    logger.info("Running weather scan for today and tomorrow...")
    
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
    config['kalshi']['trading']['min_edge_threshold'] = 0.00  # Fetch any positive edge
    
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
    
    # Load previously logged trades from the MD file
    edges_file_path = os.path.join("..", "theoretical_edges.md")
    if not os.path.exists(edges_file_path):
        edges_file_path = "theoretical_edges.md"
        
    logged_trades = parse_logged_trades(edges_file_path)
    logger.info(f"Loaded {len(logged_trades)} existing trades from log.")
    
    # Scan tomorrow's new edges
    new_edges = []
    live_market_stats = {}
    
    for city in cities:
        if not city.get("active", True):
            continue
            
        city_name = city["name"]
        lat = city["lat"]
        lon = city["lon"]
        timezone_str = city["timezone"]
        
        tz = pytz.timezone(timezone_str)
        local_now = datetime.now(tz)
        
        # We only generate tomorrow's new trades (to keep the active table clean)
        target_date = (local_now + timedelta(days=1)).strftime("%Y-%m-%d")
        
        try:
            dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
            date_ticker_str = dt_obj.strftime("%y%b%d").upper()
            date_formatted_str = dt_obj.strftime("%b %d, %Y")
        except Exception:
            continue
            
        scans = [
            ("HIGH", city["kalshi_market_prefix"]),
            ("LOW", city["kalshi_market_prefix_low"])
        ]
        
        for temp_type, prefix in scans:
            markets = await client.get_weather_markets(prefix)
            if not markets:
                continue
                
            date_markets = [m for m in markets if date_ticker_str in m["ticker"]]
            if not date_markets:
                continue
                
            gfs_forecast = await gfs_downloader.download_ensemble_forecast(lat, lon, target_date, timezone_str)
            ecmwf_forecast = await ecmwf_downloader.download_ensemble_forecast(lat, lon, target_date, timezone_str)
            hrrr_forecast = await hrrr_downloader.download_forecast(lat, lon, target_date, timezone_str)
            
            if not gfs_forecast and not ecmwf_forecast:
                continue
                
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
            
            bias_tracker.log_forecast(city["code"], temp_type, target_date, mean_val)
            
            model_probabilities = {}
            for m in date_markets:
                title = m["title"]
                ticker = m["ticker"]
                rtype, val1, val2 = parse_range(title)
                if not rtype:
                    continue
                    
                prob = calculate_market_probability(rtype, val1, val2, pooled_temps)
                model_probabilities[ticker] = prob
                
                # Store live stats for updating existing logged trades
                live_market_stats[ticker] = {
                    "model_prob": prob,
                    "yes_ask": m["yes_ask"],
                    "no_ask": m["no_ask"],
                    "yes_bid": m["yes_bid"],
                    "no_bid": m["no_bid"],
                    "title": title
                }
                
            edges = edge_detector.find_edges(date_markets, model_probabilities)
            for edge in edges:
                if edge["model_prob"] > 0.53 and edge["net_ev"] > 0.0:
                    edge["city"] = city_name
                    edge["temp_type"] = temp_type
                    edge["formatted_date"] = date_formatted_str
                    edge["target_date"] = target_date
                    size = risk_manager.calculate_position_size(edge, risk_manager.bankroll, 0.0)
                    edge["suggested_size"] = size if size > 0 else 1
                    new_edges.append(edge)
                    
    await client.close()
    
    # 2.1 Update existing open weather trades with current live stats
    logger.info("Updating existing open weather trades with live stats...")
    updated_logged_trades = []
    for t in logged_trades:
        ticker = t["ticker"]
        if "Open" in t["status"] and ticker in live_market_stats:
            stats = live_market_stats[ticker]
            side = "YES" if "YES" in t["play_desc"] else "NO"
            
            current_ask = stats["yes_ask"] if side == "YES" else stats["no_ask"]
            prob_play = stats["model_prob"] if side == "YES" else (1.0 - stats["model_prob"])
            
            if current_ask > 0:
                current_ev = (prob_play / current_ask) - 1.0
            else:
                current_ev = 0.0
                
            # Keep the trade ONLY if true prob > 53% AND EV > 0%
            if prob_play > 0.53 and current_ev > 0.0:
                size = t["qty"]
                cost = current_ask * size
                fee = calculate_maker_fee(current_ask, size)
                total = cost + fee
                payout = size * 1.00
                
                try:
                    t["play_desc"] = f"**Buy {side}** {stats['title'].split(' be ')[1].split(' on ')[0]} @ {int(current_ask*100)}¢"
                except Exception:
                    pass
                t["total_cost_line"] = f"${cost:.2f} + ${fee:.2f} fee<br>**(${total:.2f} total)**"
                t["true_prob"] = f"{prob_play:.1%}"
                t["net_ev"] = f"{current_ev:>+6.1%}"
                t["est_payout"] = f"${payout:.2f}"
                updated_logged_trades.append(t)
            else:
                logger.info(f"Removing open trade {ticker} from log: True Prob ({prob_play:.1%}) <= 53% or EV ({current_ev:+.1%}) <= 0%")
        else:
            updated_logged_trades.append(t)
            
    logged_trades = updated_logged_trades
            
    # 2.2 Add tomorrow's new edges to logged_trades (if not already logged)
    for ne in new_edges:
        ticker = ne["ticker"]
        # Check if already logged
        if not any(t["ticker"] == ticker for t in logged_trades):
            # Resolve NWS weather.gov station observation link for this city
            city = ne["city"]
            ttype = ne["temp_type"]
            station_info = CITY_STATIONS.get(city, {"station": "KMIA"})
            nws_station = station_info["station"]
            nws_link = f"https://forecast.weather.gov/data/obhistory/{nws_station}.html"
            
            price = ne["entry_price"]
            size = ne["suggested_size"]
            side = ne["side"].upper()
            cost = price * size
            fee = calculate_maker_fee(price, size)
            total = cost + fee
            payout = size * 1.00
            
            play_desc = f"**Buy {side}** {ne['title'].split(' be ')[1].split(' on ')[0]} @ {int(price*100)}¢"
            location_line = f"**{city} {ttype.capitalize()}** ([NOAA Link]({nws_link}))<br>`{ticker}`"
            total_cost_line = f"${cost:.2f} + ${fee:.2f} fee<br>**(${total:.2f} total)**"
            
            logged_trades.append({
                "formatted_date": ne["formatted_date"],
                "location_line": location_line,
                "play_desc": play_desc,
                "qty": size,
                "total_cost_line": total_cost_line,
                "true_prob": f"{ne['model_prob']:.1%}",
                "net_ev": f"{ne['net_ev']:>+6.1%}",
                "est_payout": f"${payout:.2f}",
                "status": "**Open** / *Pending*",
                "ticker": ticker
            })

    # 3. Auto-Settle Open Trades that have passed
    logger.info("Checking for open weather trades to auto-settle...")
    for t in logged_trades:
        # We check if the trade is currently open
        if "Open" in t["status"]:
            # Parse target date from formatted_date (e.g. "Jul 03, 2026" -> "2026-07-03")
            try:
                dt_obj = datetime.strptime(t["formatted_date"], "%b %d, %Y")
                trade_date_str = dt_obj.strftime("%Y-%m-%d")
            except Exception:
                continue
                
            # If target date <= today, let's fetch outcomes
            # Find city name from location line
            city_name = "Miami"
            for c in CITY_STATIONS.keys():
                if c in t["location_line"]:
                    city_name = c
                    break
                    
            station_info = CITY_STATIONS[city_name]
            timezone_str = station_info["timezone"]
            station_id = station_info["station"]
            temp_type = "HIGH" if "High" in t["location_line"] else "LOW"
            
            # Fetch actual temp
            actual_temp = await fetch_nws_actual_high_low(station_id, trade_date_str, timezone_str, temp_type)
            if actual_temp is not None:
                # Settle contract
                result = evaluate_contract(t["ticker"], actual_temp)
                if result is not None:
                    # Calculate cost and payouts
                    cost_match = re.search(r"\(\$([\d\.]+)\s+total\)", t["total_cost_line"])
                    cost = float(cost_match.group(1)) if cost_match else 0.0
                    
                    payout_match = re.search(r"\$([\d\.]+)", t["est_payout"])
                    est_payout = float(payout_match.group(1)) if payout_match else 0.0
                    
                    # Settle
                    side = "YES" if "YES" in t["play_desc"] else "NO"
                    # If result is True, YES wins. If result is False, NO wins.
                    contract_won = (result and side == "YES") or (not result and side == "NO")
                    
                    if contract_won:
                        net_profit = est_payout - cost
                        t["status"] = f"✅ **Won (+${net_profit:.2f})**"
                    else:
                        t["status"] = f"❌ **Lost (-${cost:.2f})**"
                    logger.info(f"Auto-settled trade {t['ticker']} on {trade_date_str}: {t['status']}")

    # 4. Separate active (Open) and historical (Won/Lost)
    active_trades = []
    historical_trades = []
    
    for t in logged_trades:
        if "Open" in t["status"]:
            active_trades.append(t)
        else:
            historical_trades.append(t)
            
    # Sort active trades by formatted date
    active_trades.sort(key=lambda x: x["formatted_date"])
    # Sort historical trades by date descending (latest at top of history)
    historical_trades.sort(key=lambda x: datetime.strptime(x["formatted_date"], "%b %d, %Y") if "%" not in x["formatted_date"] else datetime.now(), reverse=True)

    # 5. Calculate Running Performance Stats & Daily Breakdown
    total_trades = len(historical_trades)
    wins = sum(1 for t in historical_trades if "Won" in t["status"])
    losses = total_trades - wins
    
    total_cost = 0.0
    total_payout = 0.0
    daily_stats = {}
    
    for t in historical_trades:
        date = t["formatted_date"]
        if date not in daily_stats:
            daily_stats[date] = {
                "wins": 0,
                "losses": 0,
                "cost": 0.0,
                "payout": 0.0
            }
            
        cost_match = re.search(r"\(\$([\d\.]+)\s+total\)", t["total_cost_line"])
        cost = float(cost_match.group(1)) if cost_match else 0.0
        total_cost += cost
        daily_stats[date]["cost"] += cost
        
        if "Won" in t["status"]:
            daily_stats[date]["wins"] += 1
            payout_match = re.search(r"\$([\d\.]+)", t["est_payout"])
            payout = float(payout_match.group(1)) if payout_match else 0.0
            total_payout += payout
            daily_stats[date]["payout"] += payout
        else:
            daily_stats[date]["losses"] += 1
            
    net_profit = total_payout - total_cost
    roi = (net_profit / total_cost * 100) if total_cost > 0 else 0.0
    
    # 6. Rebuild Markdown Content
    markdown_lines = [
        "# Theoretical Edges & Trade Tracking Log",
        "",
        "Use this file to log and track your +EV trades, expected probabilities, and actual outcomes to verify your edge.",
        "",
        "## 📊 Running Performance Summary",
        f"*   **Total Trades Logged:** {total_trades}",
        f"*   **Win/Loss Record:** {wins} wins / {losses} losses",
        f"*   **Total Capital Risked:** ${total_cost:.2f}",
        f"*   **Total Payout:** ${total_payout:.2f}",
        f"*   **Net Profit:** {'+' if net_profit >= 0 else ''}${net_profit:.2f} (ROI: {roi:.1f}%)",
        "",
        "### 📅 Daily Performance History",
        "",
        "| Date | Win / Loss | Risked | Payout | Net PnL | ROI |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |"
    ]
    
    # Sort daily dates chronologically descending
    sorted_dates = sorted(daily_stats.keys(), key=lambda x: datetime.strptime(x, "%b %d, %Y") if "%" not in x else datetime.now(), reverse=True)
    for d in sorted_dates:
        stats = daily_stats[d]
        d_net = stats["payout"] - stats["cost"]
        d_roi = (d_net / stats["cost"] * 100) if stats["cost"] > 0 else 0.0
        markdown_lines.append(
            f"| {d} | {stats['wins']} W / {stats['losses']} L | ${stats['cost']:.2f} | ${stats['payout']:.2f} | {'+' if d_net >= 0 else ''}${d_net:.2f} | {d_roi:.1f}% |"
        )
        
    markdown_lines.extend([
        "",
        "---",
        "",
        "## 🔮 Active Weather Trades (Targeting Tomorrow)",
        "*These represent tomorrow's predictions. Spreads and EV are live as of generating.*",
        "",
        "| Target Date | Location & Ticker | Action / Play | Qty | Total Cost | True Prob | Net EV | Est. Payout | Status / Profit |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ])
    
    for t in active_trades:
        markdown_lines.append(
            f"| {t['formatted_date']} | {t['location_line']} | {t['play_desc']} | {t['qty']} | {t['total_cost_line']} | {t['true_prob']} | {t['net_ev']} | {t['est_payout']} | {t['status']} |"
        )
        
    if not active_trades:
        markdown_lines.append("| - | *No active trades* | - | - | - | - | - | - | - |")
        
    markdown_lines.extend([
        "",
        "---",
        "",
        "## 📜 Historical Weather Trades (Settled Outcomes)",
        "*These represent past days' resolved outcomes, verified against official NOAA weather observations.*",
        "",
        "| Target Date | Location & Ticker | Action / Play | Qty | Total Cost | True Prob | Net EV | Est. Payout | Status / Profit |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ])
    
    for t in historical_trades:
        markdown_lines.append(
            f"| {t['formatted_date']} | {t['location_line']} | {t['play_desc']} | {t['qty']} | {t['total_cost_line']} | {t['true_prob']} | {t['net_ev']} | {t['est_payout']} | {t['status']} |"
        )
        
    if not historical_trades:
        markdown_lines.append("| - | *No historical trades settled yet* | - | - | - | - | - | - | - |")
        
    markdown_lines.append("")
    
    # Write the file back in UTF-8
    with open(edges_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown_lines))
        
    logger.info("theoretical_edges.md rewritten and updated successfully!")
    
    # Send Discord notification report
    await send_discord_report(active_trades)
    
    # 7. Git commit and push
    try:
        subprocess.run(["git", "add", edges_file_path, "data/historical/"], check=True)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if status.stdout.strip():
            subprocess.run(["git", "commit", "-m", "Add daily PnL breakdown to tracking dashboard"], check=True)
            subprocess.run(["git", "push"], check=True)
            logger.info("Successfully pushed updates to Git remote.")
        else:
            logger.info("No modifications detected in theoretical_edges.md. Git push skipped.")
    except Exception as git_err:
        logger.error(f"Git execution failed: {git_err}")

if __name__ == "__main__":
    asyncio.run(run_update())
