import requests
import re
import sys
import json
from datetime import datetime, timedelta

# Set stdout to UTF-8 to prevent Windows terminal encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL_KALSHI = "https://external-api.kalshi.com/trade-api/v2"

# MLB and WNBA team mappings to resolve conflicts (e.g. ATL)
MAP_MLB = {
    "ARI": "Arizona Diamondbacks", "AZ": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CWS": "Chicago White Sox", "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC": "Kansas City Royals", "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "OAK": "Oakland Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD": "San Diego Padres",
    "SF": "San Francisco Giants",
    "SEA": "Seattle Mariners",
    "STL": "St. Louis Cardinals",
    "TB": "Tampa Bay Rays", "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals", "WAS": "Washington Nationals", "WSN": "Washington Nationals"
}

MAP_WNBA = {
    "ATL": "Atlanta Dream",
    "CHI": "Chicago Sky",
    "CON": "Connecticut Sun",
    "DAL": "Dallas Wings",
    "IND": "Indiana Fever",
    "LV": "Las Vegas Aces", "LVA": "Las Vegas Aces",
    "LA": "Los Angeles Sparks", "LAS": "Los Angeles Sparks",
    "MIN": "Minnesota Lynx",
    "NY": "New York Liberty", "NYL": "New York Liberty",
    "PHX": "Phoenix Mercury", "PHO": "Phoenix Mercury",
    "SEA": "Seattle Storm",
    "WAS": "Washington Mystics", "WSH": "Washington Mystics"
}

MAP_WORLD_CUP = {
    "URU": "Uruguay", "ESP": "Spain",
    "CPV": "Cape Verde", "KSA": "Saudi Arabia",
    "EGY": "Egypt", "IRI": "Iran",
    "NZL": "New Zealand", "BEL": "Belgium",
    "USA": "USA", "BIH": "Bosnia and Herzegovina",
    "NED": "Netherlands", "MAR": "Morocco",
    "BRA": "Brazil", "JPN": "Japan",
    "RSA": "South Africa", "CAN": "Canada",
    "COD": "DR Congo", "UZB": "Uzbekistan",
    "JOR": "Jordan", "ARG": "Argentina",
    "DZA": "Algeria", "AUT": "Austria",
    "CRO": "Croatia", "GHA": "Ghana",
    "COL": "Colombia", "POR": "Portugal",
    "PAN": "Panama", "ENG": "England"
}

def get_pinnacle_team_name(abbr, ticker):
    if ticker.startswith("KXWNBA"):
        return MAP_WNBA.get(abbr)
    elif ticker.startswith(("KXWC", "KXSOCCER")):
        return MAP_WORLD_CUP.get(abbr)
    return MAP_MLB.get(abbr)

def get_pinnacle_key():
    url = "https://www.pinnacle.com/config/app.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        key = data.get("api", {}).get("haywire", {}).get("apiKey")
        if key:
            return key
    except Exception as e:
        print(f"Error fetching Pinnacle API key: {e}")
    return None

def fetch_pinnacle_mlb_data(api_key):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-API-Key": api_key
    }
    # Fetch Matchups (MLB = League ID 246)
    matchups_url = "https://guest.api.arcadia.pinnacle.com/0.1/leagues/246/matchups?brandId=0"
    markets_url = "https://guest.api.arcadia.pinnacle.com/0.1/leagues/246/markets/straight"
    
    try:
        print("Fetching MLB matchups from Pinnacle...")
        m_resp = requests.get(matchups_url, headers=headers, timeout=10)
        m_resp.raise_for_status()
        matchups = m_resp.json()
        
        print("Fetching straight markets from Pinnacle...")
        mk_resp = requests.get(markets_url, headers=headers, timeout=10)
        mk_resp.raise_for_status()
        markets = mk_resp.json()
        
        return matchups, markets
    except Exception as e:
        print(f"Error fetching Pinnacle data: {e}")
        return [], []

def fetch_kalshi_sports_markets():
    print("Fetching active Kalshi sports markets by series...")
    series_tickers = [
        "KXMLBTOTAL", "KXMLBSPREAD", "KXMLBF5TOTAL", "KXMLBF5SPREAD", "KXMLBF5",
        "KXWNBATOTAL", "KXWNBASPREAD", "KXWNBA", "KXWCGAME"
    ]
    markets = []
    for series in series_tickers:
        url = f"{BASE_URL_KALSHI}/markets?series_ticker={series}&status=open&limit=1000"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            page_markets = data.get("markets", [])
            markets.extend(page_markets)
            print(f"  Series {series}: fetched {len(page_markets)} markets.")
        except Exception as e:
            print(f"  Error fetching series {series}: {e}")
            
    print(f"Found {len(markets)} active Kalshi sports contracts.")
    return markets

def american_to_implied(odds):
    if odds > 0:
        return 100.0 / (odds + 100.0)
    else:
        return -odds / (-odds + 100.0)

def de_vig_two_way(odds1, odds2):
    p1_raw = american_to_implied(odds1)
    p2_raw = american_to_implied(odds2)
    sum_p = p1_raw + p2_raw
    if sum_p == 0:
        return 0, 0
    return p1_raw / sum_p, p2_raw / sum_p

def de_vig_three_way(odds1, odds2, odds3):
    p1 = american_to_implied(odds1)
    p2 = american_to_implied(odds2)
    p3 = american_to_implied(odds3)
    sum_p = p1 + p2 + p3
    if sum_p == 0:
        return 0, 0, 0
    return p1 / sum_p, p2 / sum_p, p3 / sum_p

def parse_kalshi_date_team(ticker):
    # E.g. KXMLBTOTAL-26JUN271905WSHBAL-8 or KXWCGAME-26JUN26URUESP-URU
    # Pattern 1 (with 4-digit time)
    match_time = re.search(r'-(\d{2}[A-Z]{3}\d{2})(\d{4})([A-Z]{3})([A-Z]{3})', ticker)
    if match_time:
        date_str = match_time.group(1)
        time_str = match_time.group(2)
        team1 = match_time.group(3)
        team2 = match_time.group(4)
        try:
            dt = datetime.strptime(date_str, "%y%b%d")
            formatted_date = dt.strftime("%Y-%m-%d")
            return formatted_date, team1, team2, time_str
        except Exception:
            pass
            
    # Pattern 2 (without time)
    match_no_time = re.search(r'-(\d{2}[A-Z]{3}\d{2})([A-Z]{3})([A-Z]{3})', ticker)
    if match_no_time:
        date_str = match_no_time.group(1)
        team1 = match_no_time.group(2)
        team2 = match_no_time.group(3)
        try:
            dt = datetime.strptime(date_str, "%y%b%d")
            formatted_date = dt.strftime("%Y-%m-%d")
            return formatted_date, team1, team2, None
        except Exception:
            pass
            
    return None, None, None, None

def match_games(kalshi_markets, pinnacle_matchups):
    # Index pinnacle matchups by date and teams
    pinnacle_games = []
    for m in pinnacle_matchups:
        if m.get("type") != "matchup":
            continue
            
        participants = m.get("participants", [])
        if len(participants) < 2:
            continue
            
        home_team = next((p.get("name") for p in participants if p.get("alignment") == "home"), None)
        away_team = next((p.get("name") for p in participants if p.get("alignment") == "away"), None)
        
        if not home_team or not away_team:
            continue
            
        # Parse Pinnacle start time (e.g. 2026-06-27T02:15:00Z)
        start_time_str = m.get("startTime", "")
        if not start_time_str:
            continue
            
        try:
            # Convert to datetime and calculate Eastern Time date
            utc_dt = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%SZ")
            # Eastern Time is UTC - 4 hours (Daylight) or UTC - 5 hours (Standard). 
            # We subtract 4 hours as a simple approximation for June (EDT).
            et_dt = utc_dt - timedelta(hours=4)
            game_date = et_dt.strftime("%Y-%m-%d")
        except Exception:
            game_date = start_time_str.split("T")[0]
            
        pinnacle_games.append({
            "id": m.get("id"),
            "home_team": home_team,
            "away_team": away_team,
            "game_date": game_date,
            "start_time_utc": start_time_str,
            "raw": m
        })
        
    print(f"Indexed {len(pinnacle_games)} Pinnacle MLB games.")
    
    # Match Kalshi markets to Pinnacle games
    matched_markets = []
    failed_matches = set()
    
    for km in kalshi_markets:
        ticker = km.get("ticker", "")
        k_date, t1, t2, k_time = parse_kalshi_date_team(ticker)
        
        if not k_date or not t1 or not t2:
            continue
            
        # Map abbreviations to Pinnacle team names
        p_team1 = get_pinnacle_team_name(t1, ticker)
        p_team2 = get_pinnacle_team_name(t2, ticker)
        
        if not p_team1 or not p_team2:
            failed_matches.add(f"{t1}/{t2}")
            continue
            
        # Find matching game in pinnacle_games
        # We match on Date and both team names (independent of home/away)
        matching_game = None
        for pg in pinnacle_games:
            if pg["game_date"] == k_date:
                # Check if both teams are present in the matchup
                teams_in_game = [pg["home_team"], pg["away_team"]]
                if p_team1 in teams_in_game and p_team2 in teams_in_game:
                    matching_game = pg
                    break
                    

        if matching_game:
            matched_markets.append({
                "kalshi_market": km,
                "pinnacle_game": matching_game
            })
            
    if failed_matches:
        print(f"Note: Unmapped team pairs in Kalshi tickers: {failed_matches}")
        
    print(f"Successfully matched {len(matched_markets)} Kalshi contracts to Pinnacle matchups.")
    return matched_markets

def find_edges(matched_markets, pinnacle_markets):
    # Group pinnacle markets by matchupId
    p_markets_by_matchup = {}
    for pm in pinnacle_markets:
        mid = pm.get("matchupId")
        if mid not in p_markets_by_matchup:
            p_markets_by_matchup[mid] = []
        p_markets_by_matchup[mid].append(pm)
        
    edges = []
    
    for item in matched_markets:
        start_idx = len(edges)
        km = item["kalshi_market"]
        pg = item["pinnacle_game"]
        mid = pg["id"]
        
        # Get Pinnacle markets for this game
        game_p_markets = p_markets_by_matchup.get(mid, [])
        if not game_p_markets:
            continue
            
        ticker = km["ticker"]
        k_date, t1, t2, k_time = parse_kalshi_date_team(ticker)
        if not t1 or not t2:
            continue
        title = km["title"]
        yes_ask = float(km.get("yes_ask_dollars") or 0)
        no_ask = float(km.get("no_ask_dollars") or 0)
        
        if yes_ask <= 0 or no_ask <= 0:
            continue
            
        # Parse market types and lines
        # 1. TOTALS (KXMLBTOTAL)
        if ticker.startswith("KXMLBTOTAL"):
            # Extract total line from ticker (e.g. KXMLBTOTAL-...-8)
            suffix = ticker.split("-")[-1]
            try:
                line_val = float(suffix) - 0.5 # Suffix 8 means Over 7.5
            except Exception:
                continue
                
            # Find matching Pinnacle market
            # type: total, period: 0, points: line_val
            matched_p = None
            for pm in game_p_markets:
                if pm.get("type") == "total" and pm.get("period") == 0:
                    prices = pm.get("prices", [])
                    if prices and prices[0].get("points") == line_val:
                        matched_p = pm
                        break
                        
            if matched_p:
                prices = matched_p.get("prices", [])
                over_odds = next((p.get("price") for p in prices if p.get("designation") == "over"), None)
                under_odds = next((p.get("price") for p in prices if p.get("designation") == "under"), None)
                
                if over_odds is not None and under_odds is not None:
                    p_over, p_under = de_vig_two_way(over_odds, under_odds)
                    
                    # Compare YES (Over)
                    yes_fee = 0.0175 * yes_ask * (1.0 - yes_ask)
                    yes_cost = yes_ask + yes_fee
                    yes_ev = (p_over * 1.0) - yes_cost
                    yes_ev_pct = (yes_ev / yes_cost) * 100.0
                    
                    # Compare NO (Under)
                    no_fee = 0.0175 * no_ask * (1.0 - no_ask)
                    no_cost = no_ask + no_fee
                    no_ev = (p_under * 1.0) - no_cost
                    no_ev_pct = (no_ev / no_cost) * 100.0
                    
                    # Record YES edge
                    if yes_ev_pct > 0:
                        b = (1.0 - yes_cost) / yes_cost
                        kelly = 0.25 * ((p_over * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "Total Runs",
                            "line": f"Over {line_val}",
                            "pinnacle_odds": f"Over {over_odds} / Under {under_odds}",
                            "play": "YES (Over)",
                            "kalshi_price": f"{int(yes_ask*100)}¢",
                            "pinn_prob": f"{p_over*100:.1f}%",
                            "ev": yes_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })
                        
                    # Record NO edge
                    if no_ev_pct > 0:
                        b = (1.0 - no_cost) / no_cost
                        kelly = 0.25 * ((p_under * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "Total Runs",
                            "line": f"Under {line_val}",
                            "pinnacle_odds": f"Over {over_odds} / Under {under_odds}",
                            "play": "NO (Under)",
                            "kalshi_price": f"{int(no_ask*100)}¢",
                            "pinn_prob": f"{p_under*100:.1f}%",
                            "ev": no_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })
                        
        # 2. SPREADS (KXMLBSPREAD)
        elif ticker.startswith("KXMLBSPREAD"):
            # Extract team and line from ticker (e.g. KXMLBSPREAD-...-WSH2)
            suffix = ticker.split("-")[-1]
            match_suffix = re.match(r'([A-Z]+)(\d+)', suffix)
            if not match_suffix:
                continue
                
            k_team_abbr = match_suffix.group(1)
            line_suffix = float(match_suffix.group(2))
            spread_line = line_suffix - 0.5 # WSH2 means wins by over 1.5 runs (-1.5)
            
            p_target_team = get_pinnacle_team_name(k_team_abbr, ticker)
            if not p_target_team:
                continue
                
            # Find matching spread market in Pinnacle
            matched_p = None
            for pm in game_p_markets:
                if pm.get("type") == "spread" and pm.get("period") == 0:
                    prices = pm.get("prices", [])
                    home_points = next((p.get("points") for p in prices if p.get("designation") == "home"), None)
                    away_points = next((p.get("points") for p in prices if p.get("designation") == "away"), None)
                    
                    if home_points is not None and away_points is not None:
                        is_home_target = (p_target_team == pg["home_team"])
                        target_points = -spread_line if is_home_target else spread_line
                        if abs(home_points - target_points) < 0.01:
                            matched_p = pm
                            break
                            
            if matched_p:
                prices = matched_p.get("prices", [])
                is_home_target = (p_target_team == pg["home_team"])
                
                target_designation = "home" if is_home_target else "away"
                opp_designation = "away" if is_home_target else "home"
                
                target_odds = next((p.get("price") for p in prices if p.get("designation") == target_designation), None)
                opp_odds = next((p.get("price") for p in prices if p.get("designation") == opp_designation), None)
                
                if target_odds is not None and opp_odds is not None:
                    p_target, p_opp = de_vig_two_way(target_odds, opp_odds)
                    
                    # Compare YES
                    yes_fee = 0.0175 * yes_ask * (1.0 - yes_ask)
                    yes_cost = yes_ask + yes_fee
                    yes_ev = (p_target * 1.0) - yes_cost
                    yes_ev_pct = (yes_ev / yes_cost) * 100.0
                    
                    # Compare NO
                    no_fee = 0.0175 * no_ask * (1.0 - no_ask)
                    no_cost = no_ask + no_fee
                    no_ev = (p_opp * 1.0) - no_cost
                    no_ev_pct = (no_ev / no_cost) * 100.0
                    
                    if yes_ev_pct > 0:
                        b = (1.0 - yes_cost) / yes_cost
                        kelly = 0.25 * ((p_target * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "Run Line",
                            "line": f"{p_target_team} -{spread_line}",
                            "pinnacle_odds": f"{p_target_team} -{spread_line} ({target_odds}) / Opponent +{spread_line} ({opp_odds})",
                            "play": "YES (Fav -Spread)",
                            "kalshi_price": f"{int(yes_ask*100)}¢",
                            "pinn_prob": f"{p_target*100:.1f}%",
                            "ev": yes_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })
                        
                    if no_ev_pct > 0:
                        b = (1.0 - no_cost) / no_cost
                        kelly = 0.25 * ((p_opp * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "Run Line",
                            "line": f"{p_target_team} +{spread_line}",
                            "pinnacle_odds": f"{p_target_team} -{spread_line} ({target_odds}) / Opponent +{spread_line} ({opp_odds})",
                            "play": "NO (Dog +Spread)",
                            "kalshi_price": f"{int(no_ask*100)}¢",
                            "pinn_prob": f"{p_opp*100:.1f}%",
                            "ev": no_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })
                        
        # 3. FIRST 5 TOTALS (KXMLBF5TOTAL)
        elif ticker.startswith("KXMLBF5TOTAL"):
            suffix = ticker.split("-")[-1]
            try:
                line_val = float(suffix) - 0.5
            except Exception:
                continue
                
            matched_p = None
            for pm in game_p_markets:
                if pm.get("type") == "total" and pm.get("period") == 1:
                    prices = pm.get("prices", [])
                    if prices and prices[0].get("points") == line_val:
                        matched_p = pm
                        break
                        
            if matched_p:
                prices = matched_p.get("prices", [])
                over_odds = next((p.get("price") for p in prices if p.get("designation") == "over"), None)
                under_odds = next((p.get("price") for p in prices if p.get("designation") == "under"), None)
                
                if over_odds is not None and under_odds is not None:
                    p_over, p_under = de_vig_two_way(over_odds, under_odds)
                    
                    yes_fee = 0.0175 * yes_ask * (1.0 - yes_ask)
                    yes_cost = yes_ask + yes_fee
                    yes_ev = (p_over * 1.0) - yes_cost
                    yes_ev_pct = (yes_ev / yes_cost) * 100.0
                    
                    no_fee = 0.0175 * no_ask * (1.0 - no_ask)
                    no_cost = no_ask + no_fee
                    no_ev = (p_under * 1.0) - no_cost
                    no_ev_pct = (no_ev / no_cost) * 100.0
                    
                    if yes_ev_pct > 0:
                        b = (1.0 - yes_cost) / yes_cost
                        kelly = 0.25 * ((p_over * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "First 5 Runs",
                            "line": f"Over {line_val} (F5)",
                            "pinnacle_odds": f"Over {over_odds} / Under {under_odds} (F5)",
                            "play": "YES (Over)",
                            "kalshi_price": f"{int(yes_ask*100)}¢",
                            "pinn_prob": f"{p_over*100:.1f}%",
                            "ev": yes_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })
                        
                    if no_ev_pct > 0:
                        b = (1.0 - no_cost) / no_cost
                        kelly = 0.25 * ((p_under * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "First 5 Runs",
                            "line": f"Under {line_val} (F5)",
                            "pinnacle_odds": f"Over {over_odds} / Under {under_odds} (F5)",
                            "play": "NO (Under)",
                            "kalshi_price": f"{int(no_ask*100)}¢",
                            "pinn_prob": f"{p_under*100:.1f}%",
                            "ev": no_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })

        # 4. FIRST 5 SPREADS (KXMLBF5SPREAD)
        elif ticker.startswith("KXMLBF5SPREAD"):
            suffix = ticker.split("-")[-1]
            match_suffix = re.match(r'([A-Z]+)(\d+)', suffix)
            if not match_suffix:
                continue
                
            k_team_abbr = match_suffix.group(1)
            line_suffix = float(match_suffix.group(2))
            spread_line = line_suffix - 0.5
            
            p_target_team = get_pinnacle_team_name(k_team_abbr, ticker)
            if not p_target_team:
                continue
                
            matched_p = None
            for pm in game_p_markets:
                if pm.get("type") == "spread" and pm.get("period") == 1:
                    prices = pm.get("prices", [])
                    home_points = next((p.get("points") for p in prices if p.get("designation") == "home"), None)
                    away_points = next((p.get("points") for p in prices if p.get("designation") == "away"), None)
                    
                    if home_points is not None and away_points is not None:
                        is_home_target = (p_target_team == pg["home_team"])
                        target_points = -spread_line if is_home_target else spread_line
                        if abs(home_points - target_points) < 0.01:
                            matched_p = pm
                            break
                            
            if matched_p:
                prices = matched_p.get("prices", [])
                is_home_target = (p_target_team == pg["home_team"])
                target_designation = "home" if is_home_target else "away"
                opp_designation = "away" if is_home_target else "home"
                
                target_odds = next((p.get("price") for p in prices if p.get("designation") == target_designation), None)
                opp_odds = next((p.get("price") for p in prices if p.get("designation") == opp_designation), None)
                
                if target_odds is not None and opp_odds is not None:
                    p_target, p_opp = de_vig_two_way(target_odds, opp_odds)
                    
                    yes_fee = 0.0175 * yes_ask * (1.0 - yes_ask)
                    yes_cost = yes_ask + yes_fee
                    yes_ev = (p_target * 1.0) - yes_cost
                    yes_ev_pct = (yes_ev / yes_cost) * 100.0
                    
                    no_fee = 0.0175 * no_ask * (1.0 - no_ask)
                    no_cost = no_ask + no_fee
                    no_ev = (p_opp * 1.0) - no_cost
                    no_ev_pct = (no_ev / no_cost) * 100.0
                    
                    if yes_ev_pct > 0:
                        b = (1.0 - yes_cost) / yes_cost
                        kelly = 0.25 * ((p_target * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "First 5 Run Line",
                            "line": f"{p_target_team} -{spread_line} (F5)",
                            "pinnacle_odds": f"{p_target_team} -{spread_line} ({target_odds}) / Opponent +{spread_line} ({opp_odds}) (F5)",
                            "play": "YES (Fav -Spread)",
                            "kalshi_price": f"{int(yes_ask*100)}¢",
                            "pinn_prob": f"{p_target*100:.1f}%",
                            "ev": yes_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })
                        
                    if no_ev_pct > 0:
                        b = (1.0 - no_cost) / no_cost
                        kelly = 0.25 * ((p_opp * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "First 5 Run Line",
                            "line": f"{p_target_team} +{spread_line} (F5)",
                            "pinnacle_odds": f"{p_target_team} -{spread_line} ({target_odds}) / Opponent +{spread_line} ({opp_odds}) (F5)",
                            "play": "NO (Dog +Spread)",
                            "kalshi_price": f"{int(no_ask*100)}¢",
                            "pinn_prob": f"{p_opp*100:.1f}%",
                            "ev": no_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })

        # 5. FIRST 5 WINNERS (KXMLBF5)
        elif ticker.startswith("KXMLBF5"):
            suffix = ticker.split("-")[-1]
            if suffix == "TIE":
                continue
                
            p_target_team = get_pinnacle_team_name(suffix, ticker)
            if not p_target_team:
                continue
                
            matched_p = None
            for pm in game_p_markets:
                if pm.get("type") == "moneyline" and pm.get("period") == 1:
                    matched_p = pm
                    break
                    
            if matched_p:
                prices = matched_p.get("prices", [])
                is_home_target = (p_target_team == pg["home_team"])
                target_designation = "home" if is_home_target else "away"
                opp_designation = "away" if is_home_target else "home"
                
                target_odds = next((p.get("price") for p in prices if p.get("designation") == target_designation), None)
                opp_odds = next((p.get("price") for p in prices if p.get("designation") == opp_designation), None)
                draw_odds = next((p.get("price") for p in prices if p.get("designation") == "draw"), None)
                
                if target_odds is not None and opp_odds is not None:
                    if draw_odds is not None:
                        p_t = american_to_implied(target_odds)
                        p_o = american_to_implied(opp_odds)
                        p_d = american_to_implied(draw_odds)
                        sum_p = p_t + p_o + p_d
                        p_target = p_t / sum_p
                        p_opp = p_o / sum_p
                    else:
                        p_target, p_opp = de_vig_two_way(target_odds, opp_odds)
                        
                    yes_fee = 0.0175 * yes_ask * (1.0 - yes_ask)
                    yes_cost = yes_ask + yes_fee
                    yes_ev = (p_target * 1.0) - yes_cost
                    yes_ev_pct = (yes_ev / yes_cost) * 100.0
                    
                    if yes_ev_pct > 0:
                        b = (1.0 - yes_cost) / yes_cost
                        kelly = 0.25 * ((p_target * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "First 5 Winner",
                            "line": f"{p_target_team} ML (F5)",
                            "pinnacle_odds": f"{p_target_team} ({target_odds}) / Opponent ({opp_odds}) / Tie ({draw_odds}) (F5)",
                            "play": "YES (Winner)",
                            "kalshi_price": f"{int(yes_ask*100)}¢",
                            "pinn_prob": f"{p_target*100:.1f}%",
                            "ev": yes_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })

        # 6. WORLD CUP GAMES (KXWCGAME)
        elif ticker.startswith("KXWCGAME"):
            suffix = ticker.split("-")[-1]
            matched_p = None
            for pm in game_p_markets:
                if pm.get("type") == "moneyline" and pm.get("period") == 0:
                    matched_p = pm
                    break
                    
            if matched_p:
                prices = matched_p.get("prices", [])
                home_odds = next((p.get("price") for p in prices if p.get("designation") == "home"), None)
                away_odds = next((p.get("price") for p in prices if p.get("designation") == "away"), None)
                draw_odds = next((p.get("price") for p in prices if p.get("designation") == "draw"), None)
                
                if home_odds is not None and away_odds is not None and draw_odds is not None:
                    p_home, p_away, p_draw = de_vig_three_way(home_odds, away_odds, draw_odds)
                    
                    is_home = (suffix == t1)
                    is_away = (suffix == t2)
                    is_tie = (suffix == "TIE")
                    
                    if is_home:
                        prob = p_home
                    elif is_away:
                        prob = p_away
                    elif is_tie:
                        prob = p_draw
                    else:
                        continue
                        
                    yes_fee = 0.0175 * yes_ask * (1.0 - yes_ask)
                    yes_cost = yes_ask + yes_fee
                    yes_ev = (prob * 1.0) - yes_cost
                    yes_ev_pct = (yes_ev / yes_cost) * 100.0
                    
                    if yes_ev_pct > 0:
                        b = (1.0 - yes_cost) / yes_cost
                        kelly = 0.25 * ((prob * (b + 1.0) - 1.0) / b)
                        edges.append({
                            "game": f"{pg['away_team']} @ {pg['home_team']}",
                            "market": "Match Winner",
                            "line": suffix,
                            "pinnacle_odds": f"Home {home_odds} / Away {away_odds} / Draw {draw_odds}",
                            "play": f"YES ({suffix})",
                            "kalshi_price": f"{int(yes_ask*100)}¢",
                            "pinn_prob": f"{prob*100:.1f}%",
                            "ev": yes_ev_pct,
                            "kelly": max(0.0, kelly * 100.0),
                            "ticker": ticker
                        })

        # Post-process to add date to all edges found for this matchup
        for idx in range(start_idx, len(edges)):
            edges[idx]["date"] = pg["game_date"]

    return sorted(edges, key=lambda x: x["ev"], reverse=True)

def print_edge_table(edges):
    if not edges:
        print("\nNo positive EV edges found.")
        return
        
    # Group edges by date
    edges_by_date = {}
    for e in edges:
        d = e.get("date", "Unknown Date")
        if d not in edges_by_date:
            edges_by_date[d] = []
        edges_by_date[d].append(e)
        
    print(f"\nFound {len(edges)} positive EV edges:")
    
    for d in sorted(edges_by_date.keys()):
        date_edges = edges_by_date[d]
        print(f"\nTarget Date: {d} (Found {len(date_edges)} edges)")
        
        # Calculate column widths
        w_game = max(len(e["game"]) for e in date_edges)
        w_market = max(len(e["market"]) for e in date_edges)
        w_line = max(len(e["line"]) for e in date_edges)
        w_play = max(len(e["play"]) for e in date_edges)
        w_price = 8
        w_prob = 10
        w_ev = 8
        w_kelly = 10
        
        w_game = max(w_game, 15)
        w_market = max(w_market, 12)
        w_line = max(w_line, 10)
        w_play = max(w_play, 10)
        
        header = f"{'Game'.ljust(w_game)} | {'Market'.ljust(w_market)} | {'Line'.ljust(w_line)} | {'Play'.ljust(w_play)} | {'Price'.ljust(w_price)} | {'Pinn Prob'.ljust(w_prob)} | {'Net EV'.ljust(w_ev)} | {'Q-Kelly'.ljust(w_kelly)}"
        print(header)
        print("-" * len(header))
        
        for e in date_edges[:40]: # Print top 40 edges per date
            game = e["game"].ljust(w_game)
            market = e["market"].ljust(w_market)
            line = e["line"].ljust(w_line)
            play = e["play"].ljust(w_play)
            price = e["kalshi_price"].ljust(w_price)
            prob = e["pinn_prob"].ljust(w_prob)
            ev = f"{e['ev']:.1f}%".ljust(w_ev)
            kelly = f"{e['kelly']:.1f}%".ljust(w_kelly)
            
            print(f"{game} | {market} | {line} | {play} | {price} | {prob} | {ev} | {kelly}")

def run_sports_edge_finder():
    api_key = get_pinnacle_key()
    if not api_key:
        print("Could not obtain Pinnacle API key. Exiting.")
        return
        
    print(f"Acquired Pinnacle Guest API Key: {api_key}")
    
    # 1. Fetch Pinnacle MLB
    pinn_matchups_mlb, pinn_markets_mlb = fetch_pinnacle_mlb_data(api_key)
    
    # 2. Fetch Pinnacle WNBA
    print("Fetching WNBA matchups from Pinnacle...")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-API-Key": api_key
    }
    wnba_matchups_url = "https://guest.api.arcadia.pinnacle.com/0.1/leagues/578/matchups?brandId=0"
    wnba_markets_url = "https://guest.api.arcadia.pinnacle.com/0.1/leagues/578/markets/straight"
    
    pinn_matchups_wnba, pinn_markets_wnba = [], []
    try:
        w_m_resp = requests.get(wnba_matchups_url, headers=headers, timeout=10)
        if w_m_resp.status_code == 200:
            pinn_matchups_wnba = w_m_resp.json()
            print(f"Fetched {len(pinn_matchups_wnba)} WNBA matchups.")
            w_mk_resp = requests.get(wnba_markets_url, headers=headers, timeout=10)
            if w_mk_resp.status_code == 200:
                pinn_markets_wnba = w_mk_resp.json()
                print(f"Fetched {len(pinn_markets_wnba)} WNBA straight markets.")
    except Exception as e:
        print(f"Error fetching WNBA: {e}")
        
    # 2b. Fetch Pinnacle World Cup (League 2686)
    print("Fetching World Cup matchups from Pinnacle...")
    wc_matchups_url = "https://guest.api.arcadia.pinnacle.com/0.1/leagues/2686/matchups?brandId=0"
    wc_markets_url = "https://guest.api.arcadia.pinnacle.com/0.1/leagues/2686/markets/straight"
    
    pinn_matchups_wc, pinn_markets_wc = [], []
    try:
        wc_m_resp = requests.get(wc_matchups_url, headers=headers, timeout=10)
        if wc_m_resp.status_code == 200:
            pinn_matchups_wc = wc_m_resp.json()
            print(f"Fetched {len(pinn_matchups_wc)} World Cup matchups.")
            wc_mk_resp = requests.get(wc_markets_url, headers=headers, timeout=10)
            if wc_mk_resp.status_code == 200:
                pinn_markets_wc = wc_mk_resp.json()
                print(f"Fetched {len(pinn_markets_wc)} World Cup straight markets.")
    except Exception as e:
        print(f"Error fetching World Cup: {e}")
        
    # Combine Pinnacle matchups and markets
    all_pinn_matchups = pinn_matchups_mlb + pinn_matchups_wnba + pinn_matchups_wc
    all_pinn_markets = pinn_markets_mlb + pinn_markets_wnba + pinn_markets_wc
    
    # 3. Fetch Kalshi
    kalshi_markets = fetch_kalshi_sports_markets()
    
    if not kalshi_markets or not all_pinn_matchups:
        print("Data fetch incomplete. Exiting.")
        return
        
    # 4. Match games
    matched = match_games(kalshi_markets, all_pinn_matchups)
    
    # 5. Compute edges
    edges = find_edges(matched, all_pinn_markets)
    
    # 6. Print result
    print_edge_table(edges)

if __name__ == "__main__":
    run_sports_edge_finder()
