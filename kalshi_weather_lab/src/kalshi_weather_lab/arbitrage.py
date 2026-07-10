from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Sequence

from .contracts import validate_partition
from .domain import FillQuote, Market, Side
from .orderbook import InsufficientDepthError, quote_taker_buy


@dataclass(frozen=True, slots=True)
class StripArbitrage:
    side: Side
    quotes: tuple[FillQuote, ...]
    guaranteed_payout: Decimal
    total_cost: Decimal
    guaranteed_profit: Decimal


def find_strip_arbitrage(
    markets: Sequence[Market],
    books: dict[str, object],
    *,
    quantity: int = 1,
    taker_rate: float = 0.07,
    taker_multiplier: float = 1.0,
    minimum_profit: Decimal = Decimal("0.01"),
) -> tuple[StripArbitrage, ...]:
    ok, _ = validate_partition([market.rule for market in markets])
    if not ok or len(markets) < 2:
        return ()
    opportunities: list[StripArbitrage] = []
    for side in (Side.YES, Side.NO):
        quotes: list[FillQuote] = []
        try:
            for market in markets:
                quotes.append(
                    quote_taker_buy(
                        books[market.ticker],
                        side,
                        quantity,
                        taker_rate=taker_rate,
                        taker_multiplier=taker_multiplier,
                    )
                )
        except (KeyError, InsufficientDepthError):
            continue
        total_cost = sum((quote.total_cost for quote in quotes), Decimal("0"))
        payout_per_strip = Decimal("1") if side is Side.YES else Decimal(len(markets) - 1)
        payout = payout_per_strip * quantity
        profit = payout - total_cost
        if profit >= minimum_profit:
            opportunities.append(
                StripArbitrage(side, tuple(quotes), payout, total_cost, profit)
            )
    return tuple(opportunities)
