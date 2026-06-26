import requests
import re
import math
import sys
from collections import defaultdict

# Set stdout to UTF-8 to prevent Windows terminal encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

# Dictionary of Kalshi weather events, their coordinates, and their station names
CITIES = {
    "PHIL": {"name": "Philadelphia (KPHL)", "lat": 39.8722, "lon": -75.2408},
    "DEN": {"name": "Denver (KDEN)", "lat": 39.8561, "lon": -104.6737},
    "OKC": {"name": "Oklahoma City (KOKC)", "lat": 35.3931, "lon": -97.6008},
    "NOLA": {"name": "New Orleans (KMSY)", "lat": 29.9911, "lon": -90.2589},
    "AUS": {"name": "Austin (KAUS)", "lat": 30.1944, "lon": -97.6700},
    "CHI": {"name": "Chicago (KORD)", "lat": 41.9742, "lon": -87.9073},
    "BOS": {"name": "Boston (KBOS)", "lat": 42.3643, "lon": -71.0051},
    "DC": {"name": "Washington DC (KDCA)", "lat": 38.8512, "lon": -77.0377},
    "SFO": {"name": "San Francisco (KSFO)", "lat": 37.6213, "lon": -122.3790},
    "LV": {"name": "Las Vegas (KLAS)", "lat": 36.0840, "lon": -115.1537},
    "MIA": {"name": "Miami (KMIA)", "lat": 25.7959, "lon": -80.2870},
    "SEA": {"name": "Seattle (KSEA)", "lat": 47.4502, "lon": -122.3088},
    "SATX": {"name": "San Antonio (KSAT)", "lat": 29.5337, "lon": -98.4697}
}

# Standard normal cumulative distribution function (CDF) using math.erf
def normal_cdf(x, mu, sigma):
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))

# Probability calculations with continuity corrections for NWS integer rounding
def prob_between(A, B, mu, sigma):
    return normal_cdf(B + 0.5, mu, sigma) - normal_cdf(A - 0.5, mu, sigma)

def prob_greater(X, mu, sigma):
    return 1.0 - normal_cdf(X + 0.5, mu, sigma)

def prob_less(X, mu, sigma):
    return normal_cdf(X - 0.5, mu, sigma)

def parse_range(title):
    # Matches "89-90" or "89-90°"
    m_between = re.search(r'(\d+)-(\d+)', title)
    if m_between:
        return "between", int(m_between.group(1)), int(m_between.group(2))
        
    # Matches ">90" or "above 90" or "over 90"
    m_greater = re.search(r'>(\d+)', title)
    if m_greater:
        return "greater", int(m_greater.group(1)), None
        
    # Matches "<83" or "below 83" or "under 83"
    m_less = re.search(r'<(\d+)', title)
    if m_less:
        return "less", int(m_less.group(1)), None
        
    return None, None, None

def get_nws_forecast(lat, lon, is_high_temp):
    headers = {"User-Agent": "KalshiEdgeBot/1.0 (contact@kalshiedgebot.com)"}
    try:
        # Step 1: Resolve lat/lon to NWS gridpoint
        res = requests.get(f"https://api.weather.gov/points/{lat},{lon}", headers=headers)
        res.raise_for_status()
        properties = res.json().get("properties", {})
        forecast_url = properties.get("forecast")
        
        # Step 2: Fetch forecast
        res_f = requests.get(forecast_url, headers=headers)
        res_f.raise_for_status()
        periods = res_f.json().get("properties", {}).get("periods", [])
        
        # Tomorrow is June 26, 2026
        target_date = "2026-06-26"
        
        for p in periods:
            start_time = p.get("startTime", "")
            is_daytime = p.get("isDaytime", True)
            
            if target_date in start_time:
                if is_high_temp and is_daytime:
                    return float(p.get("temperature"))
                elif not is_high_temp and not is_daytime:
                    return float(p.get("temperature"))
                    
        # Fallback to first available period if target date date-match fails
        for p in periods:
            is_daytime = p.get("isDaytime", True)
            if is_high_temp == is_daytime:
                return float(p.get("temperature"))
                
    except Exception as e:
        print(f"  Error fetching NWS forecast: {e}")
    return None

def calculate_maker_fee(contracts, price):
    # Maker fee: round_up(0.0175 * C * P * (1 - P))
    raw_fee = 0.0175 * contracts * price * (1.0 - price)
    return math.ceil(raw_fee * 100) / 100.0

def run_ev_scan():
    print("=========================================================")
    print("              KALSHI WEATHER +EV SCANNER                 ")
    print("=========================================================")
    print("This scanner fetches NWS forecasts, models tomorrow's high/low")
    print("as a normal distribution (std error = 2.0°F), and finds mispriced")
    print("contracts with > 5% Net EV edge (accounting for Maker fees).")
    print("=========================================================\n")
    
    # Fetch all open standard markets
    print("Fetching open standard markets from Kalshi...")
    cursor = None
    markets = []
    seen_cursors = set()
    while True:
        url = f"{BASE_URL}/markets?status=open&mve_filter=exclude&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            res = requests.get(url)
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            print(f"Error: {e}")
            break
        
        page_markets = data.get("markets", [])
        if not page_markets:
            break
        markets.extend(page_markets)
        
        cursor = data.get("cursor")
        if not cursor or cursor in seen_cursors or len(markets) >= 4000:
            break
        seen_cursors.add(cursor)
        
    print(f"Scanned {len(markets)} markets. Filtering for weather events...")
    
    # Group markets by event ticker
    event_markets = defaultdict(list)
    for m in markets:
        ticker = m.get("ticker", "")
        event_ticker = m.get("event_ticker", "")
        # Weather event tickers start with KXHIGH or KXLOW
        if event_ticker.startswith("KXHIGH") or event_ticker.startswith("KXLOW"):
            # Check if this event belongs to our monitored cities
            city_code = None
            for code in CITIES:
                if f"HIGH{code}" in event_ticker or f"LOW{code}" in event_ticker:
                    city_code = code
                    break
            if city_code:
                # We only want tomorrow's contracts (resolving around June 26, 2026)
                if "26JUN26" in event_ticker:
                    event_markets[event_ticker].append((city_code, m))
                    
    print(f"Found {len(event_markets)} active weather events for tomorrow.\n")
    
    # For each event, retrieve forecast, calculate probabilities, and output EV
    sigma = 2.0  # Standard forecast error in Fahrenheit for 1-day ahead
    opportunities = []
    
    for event_ticker, m_list in event_markets.items():
        city_code = m_list[0][0]
        city_info = CITIES[city_code]
        is_high_temp = "HIGH" in event_ticker
        temp_type = "HIGH" if is_high_temp else "LOW"
        
        print(f"Analyzing {city_info['name']} {temp_type} Temperature (Event: {event_ticker})...")
        
        # Get forecast mean (mu)
        mu = get_nws_forecast(city_info["lat"], city_info["lon"], is_high_temp)
        if mu is None:
            print(f"  Failed to get NWS forecast for {city_info['name']}. Skipping.")
            continue
            
        print(f"  NWS Forecast Mean: {mu}°F | Modeling Std Error: {sigma}°F")
        
        for _, m in m_list:
            ticker = m["ticker"]
            title = m["title"]
            yes_bid = float(m.get("yes_bid_dollars") or 0)
            yes_ask = float(m.get("yes_ask_dollars") or 0)
            
            # Parse the target range from the title
            rtype, val1, val2 = parse_range(title)
            if not rtype:
                continue
                
            # Calculate true probability p of this range
            p = 0.0
            if rtype == "between":
                p = prob_between(val1, val2, mu, sigma)
            elif rtype == "greater":
                p = prob_greater(val1, mu, sigma)
            elif rtype == "less":
                p = prob_less(val1, mu, sigma)
                
            # Trade 1: Buy YES (Limit Order at Yes Ask)
            if yes_ask > 0 and yes_ask < 1.00:
                # EV = Payout_p * (100 - Ask) - (1 - p) * Ask = p - Ask
                # Subtract maker fee (maker fee is on risk capital: P * (1-P))
                fee = calculate_maker_fee(1, yes_ask)
                net_ev_yes = p * 1.00 - yes_ask - fee
                
                if net_ev_yes > 0.05: # Edge > 5 cents
                    opportunities.append({
                        "ticker": ticker,
                        "title": title,
                        "action": "Buy YES",
                        "true_prob": p,
                        "market_price": yes_ask,
                        "fee": fee,
                        "net_ev": net_ev_yes,
                        "roi": (net_ev_yes / yes_ask) * 100
                    })
                    
            # Trade 2: Sell YES / Buy NO (Limit Order at Yes Bid)
            if yes_bid > 0 and yes_bid < 1.00:
                # If we sell YES to the bidder at yes_bid, we are taking a NO position
                # We receive yes_bid upfront. Payout is 0 if YES, and we owe 1.00 if YES.
                # So we pay out 1.00 if YES. 
                # EV = (1 - p) * yes_bid - p * (1.00 - yes_bid) = yes_bid - p
                fee = calculate_maker_fee(1, yes_bid)
                net_ev_no = yes_bid - p - fee
                
                if net_ev_no > 0.05: # Edge > 5 cents
                    opportunities.append({
                        "ticker": ticker,
                        "title": title,
                        "action": "Buy NO (Sell YES at Bid)",
                        "true_prob": 1.0 - p,
                        "market_price": 1.0 - yes_bid,
                        "fee": fee,
                        "net_ev": net_ev_no,
                        "roi": (net_ev_no / (1.0 - yes_bid)) * 100
                    })
        print()
        
    print("=========================================================")
    print("                 DETECTOR RESULTS                        ")
    print("=========================================================")
    if not opportunities:
        print("No +EV opportunities with > 5% net edge found at this moment.")
        return
        
    # Sort opportunities by highest Net EV
    opportunities = sorted(opportunities, key=lambda x: x["net_ev"], reverse=True)
    
    for idx, opp in enumerate(opportunities):
        print(f"\n[{idx+1}] Ticker: {opp['ticker']}")
        print(f"    Title: {opp['title']}")
        print(f"    Recommended Action: {opp['action']}")
        print(f"    True Probability: {opp['true_prob']*100:.1f}%")
        print(f"    Market Entry Price: ${opp['market_price']:.2f}")
        print(f"    Maker Transaction Fee: ${opp['fee']:.2f}")
        print(f"    Net Expected Value (Edge): +${opp['net_ev']:.2f} per contract")
        print(f"    Expected ROI: {opp['roi']:.1f}%")

if __name__ == "__main__":
    run_ev_scan()
