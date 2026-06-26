import requests
import sys

# Set stdout to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

EVENTS = {
    "KXHIGHTOKC-26JUN26": [
        "KXHIGHTOKC-26JUN26-T97", "KXHIGHTOKC-26JUN26-T90", "KXHIGHTOKC-26JUN26-B96.5",
        "KXHIGHTOKC-26JUN26-B94.5", "KXHIGHTOKC-26JUN26-B92.5", "KXHIGHTOKC-26JUN26-B90.5"
    ],
    "KXHIGHPHIL-26JUN26": [
        "KXHIGHPHIL-26JUN26-T92", "KXHIGHPHIL-26JUN26-T85", "KXHIGHPHIL-26JUN26-B91.5",
        "KXHIGHPHIL-26JUN26-B89.5", "KXHIGHPHIL-26JUN26-B87.5", "KXHIGHPHIL-26JUN26-B85.5"
    ],
    "KXHIGHDEN-26JUN26": [
        "KXHIGHDEN-26JUN26-T90", "KXHIGHDEN-26JUN26-T83", "KXHIGHDEN-26JUN26-B89.5",
        "KXHIGHDEN-26JUN26-B87.5", "KXHIGHDEN-26JUN26-B85.5", "KXHIGHDEN-26JUN26-B83.5"
    ],
    "KXHIGHTNOLA-26JUN26": [
        "KXHIGHTNOLA-26JUN26-T98", "KXHIGHTNOLA-26JUN26-T91", "KXHIGHTNOLA-26JUN26-B97.5",
        "KXHIGHTNOLA-26JUN26-B95.5", "KXHIGHTNOLA-26JUN26-B93.5", "KXHIGHTNOLA-26JUN26-B91.5"
    ],
    "KXHIGHAUS-26JUN26": [
        "KXHIGHAUS-26JUN26-T94", "KXHIGHAUS-26JUN26-T101", "KXHIGHAUS-26JUN26-B98.5",
        "KXHIGHAUS-26JUN26-B96.5", "KXHIGHAUS-26JUN26-B94.5", "KXHIGHAUS-26JUN26-B100.5"
    ]
}

def analyze_all_events():
    bankroll = 30.00
    print(f"Allocating a ${bankroll:.2f} bankroll across profitable weather arbitrages...\n")
    
    all_recommendations = []
    
    for event, tickers in EVENTS.items():
        print(f"Fetching orderbooks for {event}...")
        books = []
        for ticker in tickers:
            url = f"{BASE_URL}/markets/{ticker}/orderbook"
            try:
                res = requests.get(url)
                res.raise_for_status()
                data = res.json()
                
                # We need the full list of bids and asks
                # A YES Ask is equivalent to 1.00 - NO Bid
                no_bids = data.get("orderbook_fp", {}).get("no_dollars", [])
                
                # Format of no_bids: [[price, size], ...]
                # Each NO bid at price P is equivalent to a YES ask at 1 - P with same size
                yes_asks = []
                for p_str, sz_str in no_bids:
                    p = float(p_str)
                    sz = float(sz_str)
                    yes_asks.append((round(1.00 - p, 4), sz))
                
                # If there are no NO bids, then YES ask is 1.00 with infinite size (or we just don't list it)
                # Sort yes_asks by price ascending
                yes_asks = sorted(yes_asks, key=lambda x: x[0])
                books.append(yes_asks)
            except Exception as e:
                print(f"Error fetching {ticker}: {e}")
                books.append([])
                
        # Now let's calculate how many bundles we can execute
        # A bundle consists of 1 contract of each of the 6 tickers.
        # We want to buy bundles such that the sum of asks for the bundle is <= $0.99.
        # Let's write a simple simulator that fills bundles one by one (or fractionally).
        
        # We keep track of how many contracts have been filled for each ticker
        filled_size = 0.0
        total_cost = 0.0
        
        # Keep buying bundles as long as the cost of the next bundle is <= 0.99
        # And we have depth available
        while True:
            # Calculate the cost of the next small increment (say 0.01 contracts)
            increment = 0.01
            incr_cost = 0.0
            can_fill = True
            
            for i in range(6):
                # Look at the available asks in books[i]
                # We want to find the first ask level that still has size available
                needed = increment
                temp_cost = 0.0
                filled = 0.0
                
                for price, size in books[i]:
                    # How much is available at this price level?
                    # We need to subtract what we already consumed
                    # Let's say we consume it greedily
                    avail = size
                    if avail > 0:
                        take = min(needed, avail)
                        temp_cost += take * price
                        needed -= take
                        filled += take
                        if needed <= 0.0001:
                            break
                
                if needed > 0.0001:
                    # We ran out of asks for this contract
                    # Let's assume we can buy the rest at $1.00 (which means no arbitrage)
                    temp_cost += needed * 1.00
                    can_fill = False
                    
                incr_cost += temp_cost
                
            # The effective cost per bundle for this increment
            eff_cost_per_bundle = incr_cost / increment
            
            if eff_cost_per_bundle > 0.99 or not can_fill:
                break
                
            # Deduct the filled sizes from books
            for i in range(6):
                needed = increment
                for idx, (price, size) in enumerate(books[i]):
                    take = min(needed, size)
                    books[i][idx] = (price, size - take)
                    needed -= take
                    if needed <= 0.0001:
                        break
                        
            filled_size += increment
            total_cost += incr_cost
            
        if filled_size > 0.01:
            profit = filled_size - total_cost
            all_recommendations.append({
                "event": event,
                "size": round(filled_size, 2),
                "cost": round(total_cost, 2),
                "profit": round(profit, 2),
                "return_pct": round((profit / total_cost) * 100, 2)
            })
            
    print("\n================ RECOMMENDATIONS ================")
    if not all_recommendations:
        print("No arbitrage bundles could be executed under $0.99 cost.")
        return
        
    total_allocated = 0.0
    total_expected_profit = 0.0
    
    for rec in all_recommendations:
        # Check bankroll limit
        allowed_size = rec["size"]
        cost = rec["cost"]
        
        if total_allocated + cost > bankroll:
            # Scale down to fit remaining bankroll
            remaining = bankroll - total_allocated
            ratio = remaining / cost
            allowed_size = round(rec["size"] * ratio, 2)
            cost = round(rec["cost"] * ratio, 2)
            profit = round(rec["profit"] * ratio, 2)
        else:
            profit = rec["profit"]
            
        if allowed_size > 0:
            print(f"\nEvent: {rec['event']}")
            print(f"  Action: Buy YES on all 6 temperature bins")
            print(f"  Number of bundles: {allowed_size:.2f}")
            print(f"  Total Cost: ${cost:.2f}")
            print(f"  Guaranteed Payout: ${allowed_size:.2f}")
            print(f"  Guaranteed Profit: ${profit:.2f} ({rec['return_pct']}% ROI)")
            
            total_allocated += cost
            total_expected_profit += profit
            
    print(f"\nTotal Bankroll Allocated: ${total_allocated:.2f} / ${bankroll:.2f}")
    print(f"Total Guaranteed Profit: ${total_expected_profit:.2f}")
    print(f"Overall Return on Capital: {(total_expected_profit/total_allocated)*100:.2f}%")

if __name__ == "__main__":
    analyze_all_events()
