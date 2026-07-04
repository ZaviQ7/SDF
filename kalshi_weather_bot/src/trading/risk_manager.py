import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class RiskManager:
    """Position sizing, daily loss limits, and cash reserve allocation."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Use $30 bankroll as requested by commitments
        self.bankroll = float(config['risk'].get('bankroll', 30.00))
        self.cash_reserve_pct = 0.35  # Keep at least 35% in cash at all times
        self.kelly_fraction = float(config['risk'].get('kelly_fraction', 0.25))
        self.max_open_positions = int(config['risk'].get('max_open_positions', 5))
        self.daily_loss_limit_pct = float(config['risk'].get('daily_loss_limit', 0.20))
        self.max_pos_per_market = int(config['kalshi']['trading'].get('max_position_per_market', 10))
        
        self.daily_pnl = 0.0
        self.daily_loss_limit = self.bankroll * self.daily_loss_limit_pct
        self.max_exposure = self.bankroll * (1.0 - self.cash_reserve_pct)
        
    def calculate_position_size(
        self,
        edge: Dict[str, Any],
        current_balance: float,
        current_exposure: float
    ) -> int:
        """
        Calculate sizing using Quarter-Kelly subject to 35% cash reserves and exposure caps.
        
        Args:
            edge: Edge dict from EdgeDetector
            current_balance: Real/Simulated account balance
            current_exposure: Dollar amount currently locked in resting orders + active positions
            
        Returns:
            Number of contracts to purchase (integer >= 0)
        """
        # 1. Check daily loss threshold
        if self.daily_pnl <= -self.daily_loss_limit:
            logger.warning(f"Risk Block: Daily P&L (${self.daily_pnl:+.2f}) hit daily loss limit (-${self.daily_loss_limit:.2f})")
            return 0
            
        # 2. Check total exposure cap (65% of bankroll max)
        allowed_new_exposure = self.max_exposure - current_exposure
        if allowed_new_exposure <= 0:
            logger.warning(f"Risk Block: Maximum exposure (${self.max_exposure:.2f}) reached. Current exposure: ${current_exposure:.2f}")
            return 0
            
        # 3. Kelly Sizing math
        # f* = (b*p - q) / b
        # where b = (1-price)/price, p = model_prob, q = 1-p
        price = edge["entry_price"]
        prob = edge["model_prob"]
        
        if price <= 0 or price >= 1.0:
            return 0
            
        b = (1.0 - price) / price
        p = prob
        q = 1.0 - p
        
        if b <= 0:
            return 0
            
        full_kelly = (b * p - q) / b
        adjusted_kelly = full_kelly * self.kelly_fraction
        
        if adjusted_kelly <= 0:
            logger.debug(f"Risk Info: Non-positive Kelly sizing for {edge['ticker']} ({adjusted_kelly:.2%})")
            return 0
            
        # Suggested capital risk in dollars
        suggested_capital_risk = adjusted_kelly * self.bankroll
        
        # Suggested size in contracts (floor)
        suggested_size = int(suggested_capital_risk / price)
        
        # 4. Apply caps:
        # Cap 1: allowed new exposure limit
        cap_by_exposure = int(allowed_new_exposure / price)
        suggested_size = min(suggested_size, cap_by_exposure)
        
        # Cap 2: maximum position per market limit
        suggested_size = min(suggested_size, self.max_pos_per_market)
        
        logger.info(
            f"Risk Sizing for {edge['ticker']}: Full Kelly={full_kelly:.1%}, "
            f"Adj Kelly={adjusted_kelly:.1%}, Cash Allowed Exposure: ${allowed_new_exposure:.2f}, "
            f"Final Suggested Contracts: {suggested_size}"
        )
        return max(0, suggested_size)

    def can_trade(self, current_balance: float, current_exposure: float) -> bool:
        """Check if trading is allowed under global risk parameters."""
        if self.daily_pnl <= -self.daily_loss_limit:
            return False
        if current_exposure >= self.max_exposure:
            return False
        return True

    def reset_daily(self):
        self.daily_pnl = 0.0
        logger.info("Daily risk manager limits reset.")
