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
import numpy as np

# Add project root to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.data_ingestion.kalshi_client import KalshiWeatherClient
from src.models.weather_model import WeatherModelProcessor
from src.models.probability import calculate_market_probability
from src.trading.edge_detector import EdgeDetector
from src.trading.risk_manager import RiskManager
from src.utils.helpers import parse_range, calculate_maker_fee
from src.utils.bias_tracker import BiasTracker
from core_scanner import get_forecasts_for_date, fetch_nws_actual_high_low

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("updater")
logger.setLevel(logging.INFO)

# Map city names to NWS airport stations and timezones (populated dynamically from cities.yaml)
CITY_STATIONS = {}

# fetch_nws_actual_high_low is imported from core_scanner

def evaluate_contract(ticker: str, play_desc: str, actual_temp: float) -> bool | None:
    """Evaluate if a weather range contract settled YES (True) or NO (False)."""
    # 1. Parse target condition from play_desc to resolve threshold direction ambiguity (e.g. <91 vs >=91)
    rtype, val1, val2 = parse_range(play_desc)
    if not rtype:
        # Fallback to ticker parsing if description is missing/malformed
        parts = ticker.split("-")
        if len(parts) < 3:
            return None
        suffix = parts[-1]
        temp_type = "HIGH" if "HIGH" in parts[0] else "LOW"
        actual_rounded = int(round(actual_temp))
        if suffix.startswith("B"):
            mid = float(suffix[1:])
            val1 = int(mid - 0.5)
            val2 = int(mid + 0.5)
            return (actual_rounded >= val1) and (actual_rounded <= val2)
        elif suffix.startswith("T"):
            val = float(suffix[1:])
            if temp_type == "HIGH":
                return actual_rounded >= val
            else:
                return actual_rounded <= val
        return None
        
    actual_rounded = int(round(actual_temp))
    
    if rtype == "between":
        return (actual_rounded >= val1) and (actual_rounded <= val2)
    elif rtype == "greater":
        return actual_rounded > val1
    elif rtype == "less":
        return actual_rounded < val1
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
                
            location_line = parts[1]
            if ticker:
                # Normalize separator to bullet point
                location_line = location_line.replace(" | [Kalshi Link]", " • [Kalshi Link]")
                if "Kalshi Link" not in location_line:
                    ticker_parts = ticker.split("-")
                    if len(ticker_parts) >= 2:
                        market_series_prefix = ticker_parts[0].lower()
                        event_ticker_prefix = "-".join(ticker_parts[:2]).lower()
                        kalshi_url = f"https://kalshi.com/markets/{market_series_prefix}/a/{event_ticker_prefix}"
                        if "[NOAA Link]" in location_line:
                            location_line = re.sub(
                                r"(\[NOAA Link\]\([^\)]+\))",
                                r"\1 • [Kalshi Link](" + kalshi_url + ")",
                                location_line
                            )
                        else:
                            location_line = f"{location_line} ([Kalshi Link]({kalshi_url}))"
                            
            trades.append({
                "formatted_date": parts[0],
                "location_line": location_line,
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
        
    # Check if a mention (like @here, @everyone, or a user ID) is requested
    mention = os.getenv("DISCORD_MENTION")
    if mention:
        if mention.isdigit():
            payload["content"] = f"<@{mention}>"
        elif mention.lower() in ("everyone", "here"):
            payload["content"] = f"@{mention.lower()}"
        else:
            payload["content"] = mention
            
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
        
    # Dynamically populate city stations mapping from config
    for c in cities:
        CITY_STATIONS[c["name"]] = {
            "station": c["nws_station_id"],
            "timezone": c["timezone"]
        }
        
    # Configure production simulation
    config['kalshi']['environment'] = 'prod'
    config['kalshi']['simulation'] = True
    config['kalshi']['trading']['min_edge_threshold'] = 0.00  # Fetch any positive edge
    
    client = KalshiWeatherClient(config)
    model_processor = WeatherModelProcessor(config)
    edge_detector = EdgeDetector(config)
    risk_manager = RiskManager(config)
    bias_tracker = BiasTracker(config)
    
    import sys
    settle_only = "--settle-only" in sys.argv
    
    # Automatically update actuals and compute rolling MOS bias offsets daily
    if settle_only:
        logger.info("Skipping rolling MOS bias offset recalculation in SETTLE-ONLY mode.")
        bias_offsets = {}
    else:
        logger.info("Updating NWS historical actuals and recalculating rolling MOS bias offsets...")
        try:
            bias_offsets = await bias_tracker.update_actuals_and_bias(cities, lookback_days=14)
        except Exception as e:
            logger.error(f"Failed to update rolling MOS bias offsets: {e}. Falling back to cached offsets.")
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
    cached_pooled_temps = {}
    
    if settle_only:
        logger.info("Running in SETTLE-ONLY mode. Skipping forecast model downloads and new edge scanning.")
        cities_to_scan = []
    else:
        cities_to_scan = cities
        
    for city in cities_to_scan:
        if not city.get("active", True):
            continue
            
        city_name = city["name"]
        lat = city["lat"]
        lon = city["lon"]
        timezone_str = city["timezone"]
        
        tz = pytz.timezone(timezone_str)
        local_now = datetime.now(tz)
        
        target_dates = [
            local_now.strftime("%Y-%m-%d"),
            (local_now + timedelta(days=1)).strftime("%Y-%m-%d")
        ]
        
        for target_date in target_dates:
            try:
                dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
                date_ticker_str = dt_obj.strftime("%y%b%d").upper()
                date_formatted_str = dt_obj.strftime("%b %d, %Y")
            except Exception:
                continue
                
            # Download forecasts once per city using cache/mixture collection
            forecasts = await get_forecasts_for_date(lat, lon, target_date, timezone_str)
            gfs_forecast = forecasts["gfs"]
            ecmwf_forecast = forecasts["ecmwf"]
            hrrr_forecast = forecasts["hrrr"]
            icon_forecast = forecasts["icon"]
            gem_forecast = forecasts["gem"]
            
            try:
                dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
                date_ticker_str = dt_obj.strftime("%y%b%d").upper()
                date_formatted_str = dt_obj.strftime("%b %d, %Y")
                
                # Compute lead hours to target date
                target_dt = tz.localize(datetime.combine(dt_obj.date(), datetime.max.time()))
                hours_to_target = (target_dt - local_now).total_seconds() / 3600.0
            except Exception:
                continue
                
            if not any([gfs_forecast, ecmwf_forecast, icon_forecast, gem_forecast]):
                logger.warning(f"  Skipping city {city_name} on {target_date} because no forecasts were retrieved.")
                continue
                
            scans = [
                ("HIGH", city["kalshi_market_prefix"]),
                ("LOW", city["kalshi_market_prefix_low"])
            ]
            
            for temp_type, prefix in scans:
                # Skip already-determined same-day contracts
                today_str = local_now.strftime("%Y-%m-%d")
                if target_date == today_str:
                    local_hour = local_now.hour
                    if temp_type == "HIGH" and local_hour >= 15:
                        continue
                    if temp_type == "LOW" and local_hour >= 3:
                        continue
                        
                markets = await client.get_weather_markets(prefix)
                await asyncio.sleep(1.0)  # Pacing rate limit protection
                if not markets:
                    continue
                    
                date_markets = [m for m in markets if date_ticker_str in m["ticker"]]
                if not date_markets:
                    continue
                    
                bias_key = f"{city['code']}_{temp_type}"
                bias_offset = bias_offsets.get(bias_key, 0.0)
                if bias_offset != 0.0:
                    logger.info(f"  Applying MOS rolling bias offset for {bias_key}: {bias_offset:+.2f}°F")
                    
                pooled_temps = model_processor.process_ensembles(
                    gfs_data=gfs_forecast,
                    ecmwf_data=ecmwf_forecast,
                    temp_type=temp_type,
                    bias_offset=bias_offset,
                    hrrr_data=hrrr_forecast,
                    icon_data=icon_forecast,
                    gem_data=gem_forecast,
                    hours_to_target=hours_to_target
                )
                if len(pooled_temps) == 0:
                    continue
                    
                # Real-time NWS clipping is disabled to avoid sensor outlier/mismatch contamination.
                # Relying entirely on models (such as hourly HRRR updates) for active predictions.
                        
                cached_pooled_temps[(city["code"], target_date, temp_type)] = pooled_temps
                stats = model_processor.get_distribution_stats(pooled_temps)
                mean_val = stats["mean"]
                
                bias_tracker.log_forecast(city["code"], temp_type, target_date, mean_val)
                
                model_probabilities = {}
                for m in date_markets:
                    ticker = m["ticker"]
                    # Skip cross-contamination from substring matching in Kalshi API
                    ticker_type = "HIGH" if "HIGH" in ticker else "LOW"
                    if ticker_type != temp_type:
                        continue
                        
                    title = m["title"]
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
                    if edge["model_prob"] > 0.54 and edge["net_ev"] > 0.15:
                        edge["city"] = city_name
                        edge["temp_type"] = temp_type
                        edge["formatted_date"] = date_formatted_str
                        edge["target_date"] = target_date
                        size = risk_manager.calculate_position_size(edge, risk_manager.bankroll, 0.0)
                        edge["suggested_size"] = size if size > 0 else 1
                        new_edges.append(edge)
                    
    # Close client session as it is no longer needed
    await client.close()
    
    # 2.1 Update existing open weather trades with current live stats
    logger.info("Updating existing open weather trades with live stats...")
    updated_logged_trades = []
    for t in logged_trades:
        ticker = t["ticker"]
        if "Open" in t["status"]:
            if ticker in live_market_stats:
                stats = live_market_stats[ticker]
                side = "YES" if "YES" in t["play_desc"] else "NO"
                
                yes_bid = stats["yes_bid"]
                yes_ask = stats["yes_ask"]
                no_bid = stats["no_bid"]
                no_ask = stats["no_ask"]
                
                if side == "YES":
                    current_price = yes_bid + 0.01 if (yes_bid + 0.01) < yes_ask else yes_bid
                    if current_price <= 0:
                        current_price = 0.01
                else:
                    current_price = no_bid + 0.01 if (no_bid + 0.01) < no_ask else no_bid
                    if current_price <= 0:
                        current_price = 0.01
                        
                prob_play = stats["model_prob"] if side == "YES" else (1.0 - stats["model_prob"])
                
                fee_unit = calculate_maker_fee(current_price, 1)
                cost_unit = current_price + fee_unit
                current_ev = (prob_play / cost_unit) - 1.0 if cost_unit > 0 else 0.0
                    
                # Always keep existing open trades so they can be tracked, but update their live metrics
                size = t["qty"]
                cost = current_price * size
                fee = calculate_maker_fee(current_price, size)
                total = cost + fee
                payout = size * 1.00
                
                try:
                    t["play_desc"] = f"**Buy {side}** {stats['title'].split(' be ')[1].split(' on ')[0]} @ {int(current_price*100)}¢"
                except Exception:
                    pass
                t["total_cost_line"] = f"${cost:.2f} + ${fee:.2f} fee<br>**(${total:.2f} total)**"
                t["true_prob"] = f"{prob_play:.1%}"
                t["net_ev"] = f"{current_ev:>+6.1%}"
                t["est_payout"] = f"${payout:.2f}"
                updated_logged_trades.append(t)
                logger.info(f"Updated live open trade {ticker}: Prob {prob_play:.1%}, EV {current_ev:+.1%}")
            else:
                # If ticker is closed on Kalshi, evaluate using cached pooled forecast
                parts = ticker.split("-")
                if len(parts) >= 3:
                    prefix = parts[0]
                    trade_city = None
                    trade_temp_type = None
                    for c in cities:
                        if prefix == c["kalshi_market_prefix"]:
                            trade_city = c
                            trade_temp_type = "HIGH"
                            break
                        elif prefix == c["kalshi_market_prefix_low"]:
                            trade_city = c
                            trade_temp_type = "LOW"
                            break
                            
                    try:
                        dt = datetime.strptime(parts[1], "%y%b%d")
                        target_date_str = dt.strftime("%Y-%m-%d")
                    except Exception:
                        updated_logged_trades.append(t)
                        continue
                        
                    if trade_city and trade_temp_type:
                        key = (trade_city["code"], target_date_str, trade_temp_type)
                        pooled = cached_pooled_temps.get(key)
                        if pooled is not None and len(pooled) > 0:
                            play_desc = t["play_desc"]
                            side = "YES" if "Buy YES" in play_desc else "NO"
                            rtype, val1, val2 = parse_range(play_desc)
                            if rtype:
                                prob = calculate_market_probability(rtype, val1, val2, pooled)
                                prob_play = prob if side == "YES" else (1.0 - prob)
                                
                                price_match = re.search(r"@\s*(\d+)¢", play_desc)
                                if price_match:
                                    current_price = float(price_match.group(1)) / 100.0
                                else:
                                    current_price = 0.01
                                    
                                fee_unit = calculate_maker_fee(current_price, 1)
                                cost_unit = current_price + fee_unit
                                current_ev = (prob_play / cost_unit) - 1.0 if cost_unit > 0 else 0.0
                                
                                # Always keep existing closed open trades, but update their live metrics
                                t["true_prob"] = f"{prob_play:.1%}"
                                t["net_ev"] = f"{current_ev:>+6.1%}"
                                updated_logged_trades.append(t)
                                logger.info(f"Updated closed open trade {ticker}: Prob {prob_play:.1%}, EV {current_ev:+.1%}")
                                continue
                updated_logged_trades.append(t)
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
            
            parts = ticker.split("-")
            market_series_prefix = parts[0].lower()
            event_ticker_prefix = "-".join(parts[:2]).lower()
            kalshi_url = f"https://kalshi.com/markets/{market_series_prefix}/a/{event_ticker_prefix}"
            
            play_desc = f"**Buy {side}** {ne['title'].split(' be ')[1].split(' on ')[0]} @ {int(price*100)}¢"
            
            # Add correlation / mutual exclusivity warnings to action description
            if ne.get("overlapping_yes"):
                play_desc += "<br>⚠️ *Overlapping YES Play*"
            elif ne.get("group_no_count", 1) > 1:
                no_count = ne["group_no_count"]
                play_desc += f"<br>⚠️ *Correlated NO (Scaled 1/{no_count})*"
                
            location_line = f"**{city} {ttype.capitalize()}** ([NOAA Link]({nws_link}) • [Kalshi Link]({kalshi_url}))<br>`{ticker}`"
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
                
            # If target date < today, let's fetch outcomes
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
            
            # Skip settlement if target date is not in the past relative to local timezone
            tz = pytz.timezone(timezone_str)
            local_dt = datetime.now(tz)
            local_today = local_dt.strftime("%Y-%m-%d")
            
            # Allow settlement on the same day if it's after 9 PM (21:00) local time (high/low are already fully determined)
            is_past = trade_date_str < local_today
            is_same_day_late = (trade_date_str == local_today and local_dt.hour >= 21)
            
            if not (is_past or is_same_day_late):
                logger.info(f"Skipping auto-settlement for {t['ticker']}: Target date {trade_date_str} is today and it's before 9 PM local time (current: {local_dt.hour}:00).")
                continue
                
            # Fetch actual temp
            actual_temp = await fetch_nws_actual_high_low(station_id, trade_date_str, timezone_str, temp_type)
            if actual_temp is not None:
                # Settle contract
                result = evaluate_contract(t["ticker"], t["play_desc"], actual_temp)
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
                        
                    # Add exact Kalshi market link when settling if not already present
                    ticker = t["ticker"]
                    parts = ticker.split("-")
                    if len(parts) >= 2:
                        market_series_prefix = parts[0].lower()
                        event_ticker_prefix = "-".join(parts[:2]).lower()
                        kalshi_url = f"https://kalshi.com/markets/{market_series_prefix}/a/{event_ticker_prefix}"
                        if "Kalshi Link" not in t["location_line"]:
                            t["location_line"] = re.sub(
                                r"(\[NOAA Link\]\([^\)]+\))",
                                r"\1 | [Kalshi Link](" + kalshi_url + ")",
                                t["location_line"]
                            )
                            
                    logger.info(f"Auto-settled trade {t['ticker']} on {trade_date_str}: {t['status']}")

    # 4. Separate active (Open) and historical (Won/Lost)
    active_trades = []
    historical_trades = []
    
    for t in logged_trades:
        if "Open" in t["status"]:
            active_trades.append(t)
        else:
            historical_trades.append(t)
            
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
        
    # Group active trades by target date
    active_by_date = {}
    for t in active_trades:
        date = t["formatted_date"]
        if date not in active_by_date:
            active_by_date[date] = []
        active_by_date[date].append(t)
        
    # Sort dates chronologically descending (latest date/tomorrow first)
    sorted_active_dates = sorted(
        active_by_date.keys(),
        key=lambda x: datetime.strptime(x, "%b %d, %Y") if "%" not in x else datetime.now(),
        reverse=True
    )
    
    # We output a section for each date
    for date in sorted_active_dates:
        trades_for_date = active_by_date[date]
        # Sort trades for this date by Net EV descending
        trades_for_date.sort(
            key=lambda x: float(x["net_ev"].replace("%", "").replace("+", "").strip()) if "%" in x["net_ev"] else 0.0,
            reverse=True
        )
        
        markdown_lines.extend([
            "",
            "---",
            "",
            f"## 🔮 Active Weather Edges for {date}",
            f"*These represent active predictions for {date}. Spreads and EV are live as of generating.*",
            "",
            "| Target Date | Location & Ticker | Action / Play | Qty | Total Cost | True Prob | Net EV | Est. Payout | Status / Profit |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
        ])
        
        for t in trades_for_date:
            markdown_lines.append(
                f"| {t['formatted_date']} | {t['location_line']} | {t['play_desc']} | {t['qty']} | {t['total_cost_line']} | {t['true_prob']} | {t['net_ev']} | {t['est_payout']} | {t['status']} |"
            )
            
    if not active_trades:
        tomorrow_dt = datetime.now(pytz.timezone("America/New_York")) + timedelta(days=1)
        tomorrow_str = tomorrow_dt.strftime("%b %d, %Y")
        markdown_lines.extend([
            "",
            "---",
            "",
            f"## 🔮 Active Weather Edges for {tomorrow_str}",
            "*These represent tomorrow's predictions. Spreads and EV are live as of generating.*",
            "",
            "| Target Date | Location & Ticker | Action / Play | Qty | Total Cost | True Prob | Net EV | Est. Payout | Status / Profit |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
            "| - | *No active trades* | - | - | - | - | - | - | - |"
        ])
        
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
        # Check if there are staged changes to commit
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if staged.returncode == 1:
            subprocess.run(["git", "commit", "-m", "Add daily PnL breakdown to tracking dashboard"], check=True)
            subprocess.run(["git", "push"], check=True)
            logger.info("Successfully pushed updates to Git remote.")
        else:
            logger.info("No staged modifications detected. Git push skipped.")
    except Exception as git_err:
        logger.error(f"Git execution failed: {git_err}")

if __name__ == "__main__":
    asyncio.run(run_update())
