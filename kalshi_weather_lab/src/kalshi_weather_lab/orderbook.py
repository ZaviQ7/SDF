from __future__ import annotations

from decimal import Decimal

from .domain import FillQuote, LiquidityRole, OrderBook, PriceLevel, Side
from .fees import kalshi_fee


class InsufficientDepthError(RuntimeError):
    pass


def normalize_levels(levels: list[list[str]] | tuple[tuple[str, str], ...]) -> tuple[PriceLevel, ...]:
    parsed = [PriceLevel(Decimal(str(price)), int(float(quantity))) for price, quantity in levels]
    return tuple(sorted((x for x in parsed if x.quantity > 0), key=lambda x: x.price, reverse=True))


def parse_orderbook(ticker: str, payload: dict) -> OrderBook:
    body = payload.get("orderbook_fp", payload.get("orderbook", payload))
    yes = body.get("yes_dollars", body.get("yes", [])) or []
    no = body.get("no_dollars", body.get("no", [])) or []
    return OrderBook(ticker=ticker, yes_bids=normalize_levels(yes), no_bids=normalize_levels(no))


def ask_levels(book: OrderBook, side: Side) -> tuple[PriceLevel, ...]:
    # Buying YES consumes resting NO bids, because NO at x is YES at 1-x.
    opposing = book.no_bids if side is Side.YES else book.yes_bids
    asks = [PriceLevel(Decimal("1") - level.price, level.quantity) for level in opposing]
    return tuple(sorted(asks, key=lambda x: x.price))


def bid_levels(book: OrderBook, side: Side) -> tuple[PriceLevel, ...]:
    return book.yes_bids if side is Side.YES else book.no_bids


def best_bid(book: OrderBook, side: Side) -> Decimal | None:
    levels = bid_levels(book, side)
    return levels[0].price if levels else None


def best_ask(book: OrderBook, side: Side) -> Decimal | None:
    levels = ask_levels(book, side)
    return levels[0].price if levels else None


def quote_taker_buy(
    book: OrderBook,
    side: Side,
    quantity: int,
    *,
    taker_rate: float = 0.07,
    taker_multiplier: float = 1.0,
) -> FillQuote:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    remaining = quantity
    fills: list[tuple[Decimal, int]] = []
    notional = Decimal("0")
    fee = Decimal("0")
    for level in ask_levels(book, side):
        if remaining <= 0:
            break
        take = min(remaining, level.quantity)
        fills.append((level.price, take))
        notional += level.price * take
        fee += kalshi_fee(
            level.price,
            take,
            LiquidityRole.TAKER,
            taker_rate=taker_rate,
            taker_multiplier=taker_multiplier,
        )
        remaining -= take
    if remaining:
        raise InsufficientDepthError(
            f"Only {quantity - remaining} of {quantity} contracts available for {book.ticker} {side}"
        )
    average = notional / Decimal(quantity)
    return FillQuote(
        ticker=book.ticker,
        side=side,
        quantity=quantity,
        average_price=average,
        notional=notional,
        fee=fee,
        total_cost=notional + fee,
        levels=tuple(fills),
        liquidity_role=LiquidityRole.TAKER,
    )
