import requests
from collections import defaultdict
import json
import sys

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

# Keywords that indicate cumulative thresholds (not mutually exclusive or exhaustive)
THRESHOLD_KEYWORDS = ["above", "below", "over", "under", "at least", "or more", "+", "wins by over", "wins by more than"]

def is_threshold_market(market):
    # Check strike type
    strike_type = market.get("strike_type", "").lower()
    if strike_type in ["greater", "greater_or_equal", "less", "less_or_equal"]:
        return True
        
    # Check title and subtitles for threshold keywords
    title = market.get("title", "").lower()
    yes_sub = market.get("yes_sub_title", "").lower()
    
    for kw in THRESHOLD_KEYWORDS:
        if kw in title or kw in yes_sub:
            return True
            
    return False

def scan_arbitrage():
    markets_by_event = defaultdict(list)
    cursor = None
    total_markets = 0
    standard_markets = 0
    page = 0
    seen_cursors = set()
    
    print("Starting filtered arbitrage scan...", flush=True)
    while True:
        page += 1
        url = f"{BASE_URL}/markets?status=open&mve_filter=exclude&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
            
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Error fetching page {page}: {e}", flush=True)
            break
            
        markets = data.get("markets", [])
        if not markets:
            break
            
        for m in markets:
            total_markets += 1
            if is_threshold_market(m):
                continue
                
            standard_markets += 1
            event_ticker = m.get("event_ticker")
            markets_by_event[event_ticker].append(m)
            
        next_cursor = data.get("cursor")
        if not next_cursor:
            break
            
        if next_cursor in seen_cursors:
            break
            
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        
        if total_markets >= 4000:
            break
            
    print(f"\nScanned {total_markets} markets. Filtered down to {standard_markets} categorical markets across {len(markets_by_event)} events.", flush=True)
    
    opportunities = []
    
    for event_ticker, mkts in markets_by_event.items():
        # 1. Single Market Arb Check
        for m in mkts:
            yes_bid = float(m.get("yes_bid_dollars") or 0)
            yes_ask = float(m.get("yes_ask_dollars") or 0)
            no_bid = float(m.get("no_bid_dollars") or 0)
            no_ask = float(m.get("no_ask_dollars") or 0)
            
            # Check if YES Ask + NO Ask < 1.00
            if yes_ask > 0 and no_ask > 0 and (yes_ask + no_ask) < 0.999:
                profit = 1.00 - (yes_ask + no_ask)
                opportunities.append({
                    "type": "single_market_buy_both",
                    "event_ticker": event_ticker,
                    "market_ticker": m["ticker"],
                    "title": m["title"],
                    "yes_ask": yes_ask,
                    "no_ask": no_ask,
                    "profit_per_contract": profit,
                    "details": f"Buy YES at {yes_ask:.4f} and NO at {no_ask:.4f}. Profit: {profit:.4f}"
                })
                
            # Check if YES Bid + NO Bid > 1.00
            if yes_bid > 0 and no_bid > 0 and (yes_bid + no_bid) > 1.001:
                profit = (yes_bid + no_bid) - 1.00
                opportunities.append({
                    "type": "single_market_sell_both",
                    "event_ticker": event_ticker,
                    "market_ticker": m["ticker"],
                    "title": m["title"],
                    "yes_bid": yes_bid,
                    "no_bid": no_bid,
                    "profit_per_contract": profit,
                    "details": f"Sell YES at {yes_bid:.4f} and NO at {no_bid:.4f}. Profit: {profit:.4f}"
                })
        
        # 2. Multi-Market (Categorical) Arb Check
        if len(mkts) > 1:
            valid_yes_asks = []
            valid_yes_bids = []
            mkt_details = []
            
            for m in mkts:
                yes_bid = float(m.get("yes_bid_dollars") or 0)
                yes_ask = float(m.get("yes_ask_dollars") or 0)
                mkt_details.append({
                    "ticker": m["ticker"],
                    "title": m["title"],
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask
                })
                if yes_ask > 0:
                    valid_yes_asks.append(yes_ask)
                if yes_bid > 0:
                    valid_yes_bids.append(yes_bid)
                    
            # Check sum of YES asks (Exhaustive Arb: buy YES on all)
            if len(valid_yes_asks) == len(mkts):
                sum_asks = sum(valid_yes_asks)
                if sum_asks < 0.999:
                    profit = 1.00 - sum_asks
                    opportunities.append({
                        "type": "categorical_buy_all_yes",
                        "event_ticker": event_ticker,
                        "num_markets": len(mkts),
                        "sum_asks": sum_asks,
                        "profit_per_contract": profit,
                        "markets": mkt_details,
                        "details": f"Buy YES on all {len(mkts)} outcomes. Sum of asks: {sum_asks:.4f}. Profit if exhaustive: {profit:.4f}"
                    })
                    
            # Check sum of YES bids (Mutually Exclusive Arb: buy NO on all)
            if len(valid_yes_bids) == len(mkts):
                sum_bids = sum(valid_yes_bids)
                if sum_bids > 1.001:
                    profit = sum_bids - 1.00
                    opportunities.append({
                        "type": "categorical_buy_all_no",
                        "event_ticker": event_ticker,
                        "num_markets": len(mkts),
                        "sum_bids": sum_bids,
                        "profit_per_contract": profit,
                        "markets": mkt_details,
                        "details": f"Buy NO on all {len(mkts)} outcomes (sell YES). Sum of bids: {sum_bids:.4f}. Profit if mutually exclusive: {profit:.4f}"
                    })
                    
    print(f"\nScan complete. Found {len(opportunities)} potential arbitrage opportunities.", flush=True)
    
    if opportunities:
        print("\nOpportunities Details:", flush=True)
        for idx, opp in enumerate(opportunities):
            print(f"\n--- Opp #{idx+1} ({opp['type']}) ---", flush=True)
            print(f"Event: {opp['event_ticker']}", flush=True)
            if "market_ticker" in opp:
                print(f"Market Ticker: {opp['market_ticker']}", flush=True)
                print(f"Title: {opp['title']}", flush=True)
            print(opp['details'], flush=True)
            if opp['type'].startswith("categorical"):
                print("Constituent Markets:", flush=True)
                for m in opp['markets']:
                    print(f"  - Ticker: {m['ticker']}", flush=True)
                    print(f"    Title: {m['title']}", flush=True)
                    print(f"    Yes Bid/Ask: {m['yes_bid']:.4f}/{m['yes_ask']:.4f}", flush=True)
    else:
        print("No arbitrage opportunities found at this moment.", flush=True)

if __name__ == "__main__":
    scan_arbitrage()
