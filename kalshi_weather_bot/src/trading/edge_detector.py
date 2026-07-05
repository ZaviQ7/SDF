import logging
from datetime import datetime
from typing import Dict, List, Any
from src.utils.helpers import parse_range, calculate_maker_fee

logger = logging.getLogger(__name__)

class EdgeDetector:
    """Find positive EV trading edges in Kalshi weather markets."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.min_edge = float(config['kalshi']['trading'].get('min_edge_threshold', 0.05))
        self.max_spread = float(config['kalshi']['trading'].get('max_spread_cents', 5.0)) / 100.0

    def find_edges(
        self,
        market_data: List[Dict[str, Any]],
        model_probabilities: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """
        Scan open weather markets and compute edges.
        
        Args:
            market_data: List of market dictionaries from Kalshi
            model_probabilities: Dict mapping market ticker to model probability
            
        Returns:
            List of edge dictionaries sorted by EV magnitude
        """
        edges = []
        
        for m in market_data:
            ticker = m["ticker"]
            if ticker not in model_probabilities:
                continue
                
            model_prob = model_probabilities[ticker]
            yes_ask = m["yes_ask"]
            yes_bid = m["yes_bid"]
            no_ask = m["no_ask"]
            no_bid = m["no_bid"]
            
            # Skip if market is crossed or spread is too wide
            if yes_ask <= 0 or no_ask <= 0:
                continue
                
            spread = yes_ask - yes_bid
            if spread > self.max_spread:
                logger.debug(f"Skipping {ticker}: spread {spread*100:.1f}¢ exceeds limit {self.max_spread*100:.1f}¢")
                continue
                
            # Determine target resting entry prices (join the bid or join the bid + 0.01)
            yes_entry = yes_bid + 0.01 if (yes_bid + 0.01) < yes_ask else yes_bid
            if yes_entry <= 0:
                yes_entry = 0.01
                
            no_entry = no_bid + 0.01 if (no_bid + 0.01) < no_ask else no_bid
            if no_entry <= 0:
                no_entry = 0.01
                
            # Calculate EV at the resting entry price
            fee_yes = calculate_maker_fee(yes_entry, 1)
            cost_yes = yes_entry + fee_yes
            yes_ev = model_prob - cost_yes
            yes_ev_pct = yes_ev / cost_yes if cost_yes > 0 else 0.0
            
            fee_no = calculate_maker_fee(no_entry, 1)
            cost_no = no_entry + fee_no
            no_ev = (1.0 - model_prob) - cost_no
            no_ev_pct = no_ev / cost_no if cost_no > 0 else 0.0
            
            # Only emit the BEST side for this ticker (prevents contradictory signals)
            best_side = None
            best_ev = 0.0
            
            if yes_ev_pct >= self.min_edge and yes_ev_pct >= no_ev_pct:
                best_side = "yes"
                best_ev = yes_ev_pct
            elif no_ev_pct >= self.min_edge and no_ev_pct > yes_ev_pct:
                best_side = "no"
                best_ev = no_ev_pct
                
            if best_side == "yes":
                edges.append({
                    "ticker": ticker,
                    "title": m["title"],
                    "side": "yes",
                    "entry_price": yes_entry,
                    "market_ask": yes_ask,
                    "market_bid": yes_bid,
                    "model_prob": model_prob,
                    "market_prob": yes_ask,
                    "net_ev": yes_ev_pct,
                    "spread": spread,
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "timestamp": datetime.utcnow().isoformat()
                })
                logger.info(f"🎯 Edge detected: {ticker} YES | Entry: {yes_entry:.2f} | Model: {model_prob:.1%} | EV: {yes_ev_pct:+.1%}")
                
            elif best_side == "no":
                edges.append({
                    "ticker": ticker,
                    "title": m["title"],
                    "side": "no",
                    "entry_price": no_entry,
                    "market_ask": no_ask,
                    "market_bid": no_bid,
                    "model_prob": 1.0 - model_prob,
                    "market_prob": no_ask,
                    "net_ev": no_ev_pct,
                    "spread": spread,
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "timestamp": datetime.utcnow().isoformat()
                })
                logger.info(f"🎯 Edge detected: {ticker} NO | Entry: {no_entry:.2f} | Model: {1.0 - model_prob:.1%} | EV: {no_ev_pct:+.1%}")
                
        # Sort by EV magnitude (descending)
        edges.sort(key=lambda x: x["net_ev"], reverse=True)
        return edges
