import logging
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class OrderExecutor:
    """Manages limit order execution, resting order tracking, and timeout cancellations."""
    
    def __init__(self, kalshi_client, config: Dict[str, Any]):
        self.kalshi = kalshi_client
        self.config = config
        self.order_expiry_minutes = int(config['kalshi']['trading'].get('order_expiry_minutes', 30))
        self.open_orders: Dict[str, Dict[str, Any]] = {}
        
    async def place_order(self, edge: Dict[str, Any], size: int) -> Optional[Dict[str, Any]]:
        """
        Place a limit order resting on the book.
        """
        ticker = edge["ticker"]
        side = edge["side"]
        price = edge["entry_price"]
        
        try:
            order = await self.kalshi.place_limit_order(
                ticker=ticker,
                side=side,
                price=price,
                size=size,
                post_only=self.config['kalshi']['trading'].get('post_only', True)
            )
            
            if order and order.get("order_id"):
                order_id = order["order_id"]
                # Store local timestamp and edge details
                self.open_orders[order_id] = {
                    **order,
                    "placed_time": time.time(),
                    "edge": edge
                }
                return order
        except Exception as e:
            logger.error(f"Failed to place order for {ticker}: {e}")
        return None
        
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an active order."""
        try:
            success = await self.kalshi.cancel_order(order_id)
            if success:
                if order_id in self.open_orders:
                    del self.open_orders[order_id]
                return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
        return False
        
    async def manage_resting_orders(self):
        """Monitor resting orders, check if they are filled or expired, and cancel timed-out orders."""
        now = time.time()
        expiry_seconds = self.order_expiry_minutes * 60
        
        # 1. Check for expired resting orders
        for order_id, order in list(self.open_orders.items()):
            placed_time = order["placed_time"]
            if now - placed_time > expiry_seconds:
                logger.info(f"Resting order {order_id} expired ({self.order_expiry_minutes}m timeout). Cancelling.")
                await self.cancel_order(order_id)
                
        # 2. In live mode, we query the orders endpoint or positions to see if orders were filled
        # In simulation mode, the client's update_simulation is called to perform the fills
        if not self.kalshi.dry_run:
            # Live tracking: check current open orders on the exchange
            try:
                # We can query all open orders or compare resting orders against current position counts
                # For simplicity, we query active positions. If a position is found for a ticker that we
                # placed a resting order on, the resting order is filled (or partially filled).
                positions = await self.kalshi.get_positions()
                pos_by_ticker = {p["ticker"]: p for p in positions}
                
                for order_id, order in list(self.open_orders.items()):
                    ticker = order["ticker"]
                    side = order["side"]
                    size = order["size"]
                    
                    if ticker in pos_by_ticker:
                        pos = pos_by_ticker[ticker]
                        # If we have an active position matching the side, we assume fill occurred
                        if pos["side"] == side and pos["size"] >= size:
                            logger.info(f"🔔 Resting order {order_id} filled on exchange! Position: {pos['size']} contracts.")
                            del self.open_orders[order_id]
            except Exception as e:
                logger.error(f"Error checking resting orders on exchange: {e}")

    def get_resting_orders_exposure(self) -> float:
        """Calculate the total dollar value of all active resting orders."""
        exposure = 0.0
        for order in self.open_orders.values():
            price = order["price"]
            size = order["size"]
            maker_fee = 0.0175 * price * (1.0 - price) * size
            exposure += (price * size) + maker_fee
        return exposure
