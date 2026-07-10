from decimal import Decimal

from kalshi_weather_lab.domain import OrderBook, PriceLevel, Side
from kalshi_weather_lab.orderbook import best_ask, quote_taker_buy


def test_binary_ask_is_complement_of_opposing_bid():
    book = OrderBook(
        "T",
        yes_bids=(PriceLevel(Decimal("0.35"), 4),),
        no_bids=(PriceLevel(Decimal("0.60"), 3),),
    )
    assert best_ask(book, Side.YES) == Decimal("0.40")
    assert best_ask(book, Side.NO) == Decimal("0.65")


def test_taker_quote_walks_depth_and_charges_each_level():
    book = OrderBook(
        "T",
        no_bids=(
            PriceLevel(Decimal("0.70"), 1),
            PriceLevel(Decimal("0.65"), 2),
        ),
    )
    quote = quote_taker_buy(book, Side.YES, 2)
    assert quote.levels == ((Decimal("0.30"), 1), (Decimal("0.35"), 1))
    assert quote.notional == Decimal("0.65")
    assert quote.fee == Decimal("0.0307")
    assert quote.total_cost == Decimal("0.6807")
