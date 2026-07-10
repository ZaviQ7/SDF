from decimal import Decimal

from kalshi_weather_lab.arbitrage import find_strip_arbitrage
from kalshi_weather_lab.contracts import parse_contract_rule
from kalshi_weather_lab.domain import OrderBook, PriceLevel
from kalshi_weather_lab.market_types import IndexedMarket


def test_yes_strip_arbitrage_detected_after_fees():
    markets = [
        IndexedMarket("A", "E", "49 or below", parse_contract_rule("49 or below"), 0),
        IndexedMarket("B", "E", "50 or above", parse_contract_rule("50 or above"), 1),
    ]
    # YES asks are 0.30 each, total notional .60 plus .0294 fees = .6294, payout 1.00.
    books = {
        "A": OrderBook("A", no_bids=(PriceLevel(Decimal("0.70"), 1),)),
        "B": OrderBook("B", no_bids=(PriceLevel(Decimal("0.70"), 1),)),
    }
    opportunities = find_strip_arbitrage(markets, books)
    yes = next(opportunity for opportunity in opportunities if opportunity.side.value == "yes")
    assert yes.guaranteed_profit == Decimal("0.3706")
