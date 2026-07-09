import asyncio
import logging
import time
import base64
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import aiohttp
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logger = logging.getLogger(__name__)

class RateLimiter:
    """Token bucket rate limiter for Kalshi API."""
    def __init__(self, limits: Dict[str, Any]):
        self.read_budget = limits.get('read_budget', 100)
        self.write_budget = limits.get('write_budget', 50)
        self.burst_capacity = limits.get('burst_capacity', 200)
        
        self.read_tokens = float(self.burst_capacity)
        self.write_tokens = float(self.burst_capacity)
        
        self.last_read_refill = time.time()
        self.last_write_refill = time.time()
        self.lock = asyncio.Lock()
        
    async def acquire(self, bucket: str):
        async with self.lock:
            now = time.time()
            if bucket == 'read':
                elapsed = now - self.last_read_refill
                self.read_tokens = min(self.burst_capacity, self.read_tokens + elapsed * self.read_budget)
                self.last_read_refill = now
                
                # Check if we have at least 1 token
                if self.read_tokens < 1.0:
                    wait_time = (1.0 - self.read_tokens) / self.read_budget
                    await asyncio.sleep(wait_time)
                    self.read_tokens = 0.0
                else:
                    self.read_tokens -= 1.0
            elif bucket == 'write':
                elapsed = now - self.last_write_refill
                self.write_tokens = min(self.burst_capacity, self.write_tokens + elapsed * self.write_budget)
                self.last_write_refill = now
                
                if self.write_tokens < 1.0:
                    wait_time = (1.0 - self.write_tokens) / self.write_budget
                    await asyncio.sleep(wait_time)
                    self.write_tokens = 0.0
                else:
                    self.write_tokens -= 1.0

class KalshiWeatherClient:
    """Wrapper around Kalshi API v2 for weather trading."""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.env = config['kalshi'].get('environment', 'demo')
        self.api_key = config['kalshi'].get('api_key') or os.getenv('KALSHI_API_KEY')
        self.private_key_path = config['kalshi'].get('private_key_path') or os.getenv('KALSHI_PRIVATE_KEY_PATH')
        
        # Determine URLs
        if self.env == 'prod':
            self.base_url = "https://external-api.kalshi.com"
        else:
            self.base_url = "https://external-api.demo.kalshi.co"
            
        self.rate_limiter = RateLimiter(config['kalshi'].get('rate_limits', {}))
        self.session: Optional[aiohttp.ClientSession] = None
        self.private_key = None
        
        # Dry-run Simulation state
        self.dry_run = True
        self.simulated_balance = float(config['risk'].get('bankroll', 15.00))
        self.simulated_positions: Dict[str, Dict[str, Any]] = {}
        self.simulated_orders: Dict[str, Dict[str, Any]] = {}
        
    def _load_simulated_balance(self):
        portfolio_path = os.path.join("data", "historical", "simulated_portfolio.json")
        if os.path.exists(portfolio_path):
            try:
                with open(portfolio_path, "r") as f:
                    data = json.load(f)
                self.simulated_balance = float(data.get("bankroll", 15.00))
                logger.info(f"Loaded persistent simulated balance: ${self.simulated_balance:.2f}")
            except Exception as e:
                logger.warning(f"Error loading simulated portfolio file: {e}. Using default.")
        else:
            logger.info(f"Simulated portfolio file not found at {portfolio_path}. Using config bankroll.")

    def _save_simulated_balance(self):
        portfolio_path = os.path.join("data", "historical", "simulated_portfolio.json")
        os.makedirs(os.path.dirname(portfolio_path), exist_ok=True)
        try:
            if os.path.exists(portfolio_path):
                with open(portfolio_path, "r") as f:
                    data = json.load(f)
            else:
                data = {}
            data["bankroll"] = self.simulated_balance
            data["last_updated"] = datetime.utcnow().isoformat() + "Z"
            with open(portfolio_path, "w") as f:
                json.dump(data, f, indent=4)
            logger.info(f"Saved persistent simulated balance: ${self.simulated_balance:.2f}")
        except Exception as e:
            logger.error(f"Error saving simulated portfolio file: {e}")

    async def initialize(self) -> bool:
        """Initialize HTTP session, load key, and authenticate."""
        logger.info("Initializing Kalshi API v2 client...")
        self.session = aiohttp.ClientSession(
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=15)
        )
        
        # Load Private Key if available and not forcing simulation
        force_simulation = self.config['kalshi'].get('simulation', True)
        
        if force_simulation:
            logger.info("Simulation mode is explicitly enabled in config. Running in DRY RUN mode.")
            self.dry_run = True
        elif self.private_key_path and os.path.exists(self.private_key_path):
            try:
                with open(self.private_key_path, "rb") as f:
                    key_data = f.read()
                self.private_key = load_pem_private_key(key_data, password=None)
                self.dry_run = False
                logger.info("✅ RSA Private key loaded successfully. Running in LIVE mode.")
            except Exception as e:
                logger.error(f"Failed to parse private key at {self.private_key_path}: {e}")
                logger.warning("Falling back to SIMULATION / DRY RUN mode.")
        else:
            logger.warning("No valid private key file path found in config or environment. Running in SIMULATION / DRY RUN mode.")
            
        if not self.dry_run:
            try:
                # Test connectivity by querying balance
                balance = await self.get_balance()
                logger.info(f"✅ Connected to Kalshi API. Real Balance: ${balance:.2f}")
                return True
            except Exception as e:
                logger.error(f"❌ Real Kalshi authentication failed: {e}. Falling back to simulation mode.")
                self.dry_run = True
                
        if self.dry_run:
            self._load_simulated_balance()
        logger.info(f"✅ Simulation mode active. Bankroll: ${self.simulated_balance:.2f}")
        return True

    async def close(self):
        if self.session:
            await self.session.close()

    def _sign_request(self, timestamp: str, method: str, path: str) -> str:
        if not self.private_key:
            return ""
        # Strip query parameters for signing
        clean_path = path.split('?')[0]
        message = f"{timestamp}{method}{clean_path}".encode('utf-8')
        
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')

    def _get_headers(self, method: str, path: str) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.dry_run or not self.api_key or not self.private_key:
            return headers
            
        timestamp = str(int(time.time() * 1000))
        signature = self._sign_request(timestamp, method, path)
        
        headers.update({
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature
        })
        return headers

    async def get_balance(self) -> float:
        """Get current balance."""
        if self.dry_run:
            return self.simulated_balance
            
        await self.rate_limiter.acquire('read')
        path = "/trade-api/v2/portfolio/balance"
        headers = self._get_headers("GET", path)
        
        async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data.get("balance", 0)) / 100.0  # Kalshi returns cents
            else:
                text = await resp.text()
                raise Exception(f"Failed to fetch balance ({resp.status}): {text}")

    async def get_weather_markets(self, city_prefix: str) -> List[Dict[str, Any]]:
        """Fetch all active weather markets matching the city prefix (public endpoint)."""
        await self.rate_limiter.acquire('read')
        # Markets endpoint is public, no authentication required
        path = f"/trade-api/v2/markets?series_ticker={city_prefix}&status=open&limit=1000"
        
        async with self.session.get(f"{self.base_url}{path}") as resp:
            if resp.status == 200:
                data = await resp.json()
                markets = data.get("markets", [])
                
                # Format to a standardized weather market structure
                formatted_markets = []
                for m in markets:
                    formatted_markets.append({
                        "ticker": m.get("ticker"),
                        "title": m.get("title"),
                        "subtitle": m.get("subtitle", ""),
                        "yes_ask": float(m.get("yes_ask_dollars") or 0),
                        "yes_bid": float(m.get("yes_bid_dollars") or 0),
                        "no_ask": float(m.get("no_ask_dollars") or 0),
                        "no_bid": float(m.get("no_bid_dollars") or 0),
                        "volume": m.get("volume", 0),
                        "open_interest": m.get("open_interest", 0),
                        "close_time": m.get("close_time"),
                        "status": m.get("status")
                    })
                return formatted_markets
            else:
                text = await resp.text()
                logger.error(f"Failed to fetch markets for prefix {city_prefix} ({resp.status}): {text}")
                return []

    async def get_market_orderbook(self, ticker: str) -> Dict[str, Any]:
        """Fetch depth/orderbook for a specific market (public)."""
        await self.rate_limiter.acquire('read')
        path = f"/trade-api/v2/markets/{ticker}/orderbook"
        
        async with self.session.get(f"{self.base_url}{path}") as resp:
            if resp.status == 200:
                data = await resp.json()
                ob = data.get("orderbook", {})
                
                # Standardize bids & asks (Kalshi prices are in cents)
                yes_bids = [{"price": float(b[0])/100.0, "size": int(b[1])} for b in ob.get("yes", [])]
                no_bids = [{"price": float(b[0])/100.0, "size": int(b[1])} for b in ob.get("no", [])]
                
                return {
                    "ticker": ticker,
                    "yes": yes_bids,
                    "no": no_bids
                }
            else:
                return {"ticker": ticker, "yes": [], "no": []}

    async def place_limit_order(
        self,
        ticker: str,
        side: str,
        price: float,
        size: int,
        post_only: bool = True
    ) -> Dict[str, Any]:
        """Place a limit order."""
        price_cents = int(round(price * 100))
        if not 1 <= price_cents <= 99:
            raise ValueError(f"Price must be between 0.01 and 0.99, got {price}")
            
        if self.dry_run:
            # Simulate placing order
            order_id = f"sim_ord_{int(time.time()*1000)}"
            order = {
                "order_id": order_id,
                "status": "resting",
                "ticker": ticker,
                "side": side,
                "price": price,
                "size": size,
                "filled_size": 0,
                "timestamp": datetime.utcnow().isoformat()
            }
            self.simulated_orders[order_id] = order
            logger.info(f"Simulated resting order Rested: {order_id} | {ticker} {side.upper()} {size} @ {price:.2f}")
            return order
            
        await self.rate_limiter.acquire('write')
        path = "/trade-api/v2/portfolio/orders"
        
        payload = {
            "ticker": ticker,
            "side": side.lower(),
            "price": price_cents,
            "action": "buy",
            "type": "limit",
            "count": size,
            "post_only": post_only,
            "client_order_id": f"bot_{int(time.time()*1000)}"
        }
        
        headers = self._get_headers("POST", path)
        async with self.session.post(f"{self.base_url}{path}", json=payload, headers=headers) as resp:
            if resp.status == 201 or resp.status == 200:
                data = await resp.json()
                order_info = data.get("order", {})
                return {
                    "order_id": order_info.get("order_id"),
                    "status": order_info.get("status", "resting"),
                    "ticker": ticker,
                    "side": side,
                    "price": float(order_info.get("price", 0)) / 100.0,
                    "size": int(order_info.get("count", 0)),
                    "filled_size": int(order_info.get("filled_count", 0)),
                    "timestamp": order_info.get("created_time")
                }
            else:
                text = await resp.text()
                raise Exception(f"Failed to place order ({resp.status}): {text}")

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get details/status of a specific order from Kalshi."""
        if self.dry_run:
            return self.simulated_orders.get(order_id)
            
        await self.rate_limiter.acquire('read')
        path = f"/trade-api/v2/portfolio/orders/{order_id}"
        headers = self._get_headers("GET", path)
        
        try:
            async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    order_info = data.get("order", {})
                    return {
                        "order_id": order_info.get("order_id"),
                        "status": order_info.get("status"),
                        "ticker": order_info.get("ticker"),
                        "side": order_info.get("side"),
                        "price": float(order_info.get("price", 0)) / 100.0,
                        "size": int(order_info.get("count", 0)),
                        "filled_size": int(order_info.get("filled_count", 0))
                    }
                else:
                    text = await resp.text()
                    logger.error(f"Failed to fetch order {order_id} ({resp.status}): {text}")
                    return None
        except Exception as e:
            logger.error(f"Exception fetching order {order_id}: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if self.dry_run:
            if order_id in self.simulated_orders:
                del self.simulated_orders[order_id]
                logger.info(f"Simulated order cancelled: {order_id}")
                return True
            return False
            
        await self.rate_limiter.acquire('write')
        path = f"/trade-api/v2/portfolio/orders/{order_id}"
        headers = self._get_headers("DELETE", path)
        
        async with self.session.delete(f"{self.base_url}{path}", headers=headers) as resp:
            if resp.status == 200:
                return True
            else:
                text = await resp.text()
                logger.error(f"Failed to cancel order {order_id} ({resp.status}): {text}")
                return False

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        if self.dry_run:
            return list(self.simulated_positions.values())
            
        await self.rate_limiter.acquire('read')
        path = "/trade-api/v2/portfolio/positions"
        headers = self._get_headers("GET", path)
        
        async with self.session.get(f"{self.base_url}{path}", headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                raw_positions = data.get("positions", [])
                
                positions = []
                for p in raw_positions:
                    side = p.get("position_direction", "long") # or short
                    count = int(p.get("position", 0))
                    if count == 0:
                        continue
                    ticker = p.get("ticker")
                    
                    positions.append({
                        "ticker": ticker,
                        "side": "yes" if side == "long" else "no",
                        "size": count,
                        "avg_price": float(p.get("avg_cost_basis", 0)) / 100.0,
                        "current_value": float(p.get("market_price", 0)) / 100.0,
                        "pnl": float(p.get("realized_pnl", 0)) / 100.0
                    })
                return positions
            else:
                text = await resp.text()
                logger.error(f"Failed to fetch positions ({resp.status}): {text}")
                return []

    # Simulation matching engine for Dry Run
    def update_simulation(self, markets_by_ticker: Dict[str, Dict[str, Any]]):
        """Simulate order matching against live market book prices in dry-run mode."""
        if not self.dry_run:
            return
            
        for oid, order in list(self.simulated_orders.items()):
            ticker = order["ticker"]
            if ticker not in markets_by_ticker:
                continue
                
            m = markets_by_ticker[ticker]
            side = order["side"]
            price = order["price"]
            size = order["size"]
            
            # Match condition:
            # If we placed YES buy order at price P:
            # It fills if YES ask is <= P
            # If we placed NO buy order at price P:
            # It fills if NO ask is <= P
            market_ask = m["yes_ask"] if side == "yes" else m["no_ask"]
            
            if market_ask <= price and market_ask > 0:
                # Fill order
                del self.simulated_orders[oid]
                
                # Check balance
                cost = price * size
                maker_fee = 0.0175 * price * (1.0 - price) * size
                total_cost = cost + maker_fee
                
                if self.simulated_balance >= total_cost:
                    self.simulated_balance -= total_cost
                    self._save_simulated_balance()
                    
                    # Update position
                    if ticker in self.simulated_positions:
                        pos = self.simulated_positions[ticker]
                        old_size = pos["size"]
                        old_price = pos["avg_price"]
                        new_size = old_size + size
                        new_price = (old_size * old_price + size * price) / new_size
                        
                        pos["size"] = new_size
                        pos["avg_price"] = new_price
                        pos["current_value"] = market_ask
                        pos["pnl"] = (market_ask - new_price) * new_size
                    else:
                        self.simulated_positions[ticker] = {
                            "ticker": ticker,
                            "side": side,
                            "size": size,
                            "avg_price": price,
                            "current_value": market_ask,
                            "pnl": 0.0
                        }
                    logger.info(f"🔔 Simulation: RESTING ORDER FILLED: {oid} | {ticker} {side.upper()} {size} @ {price:.2f} (Total Cost: ${total_cost:.2f})")
                else:
                    logger.warning(f"🔔 Simulation: ORDER EXPIRED / CANCELLED (Insufficient funds): {oid}")
