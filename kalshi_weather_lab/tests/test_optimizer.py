from decimal import Decimal

from kalshi_weather_lab.contracts import parse_contract_rule
from kalshi_weather_lab.domain import FillQuote, LiquidityRole, Side
from kalshi_weather_lab.market_types import IndexedMarket
from kalshi_weather_lab.optimizer import OptimizerLimits, candidate_from_quote, optimize_event


def quote(ticker: str, side: Side, cost: str) -> FillQuote:
    total = Decimal(cost)
    return FillQuote(
        ticker=ticker,
        side=side,
        quantity=1,
        average_price=total,
        notional=total,
        fee=Decimal("0"),
        total_cost=total,
        levels=((total, 1),),
        liquidity_role=LiquidityRole.TAKER,
    )


def test_optimizer_keeps_rejected_size_at_zero_and_respects_loss_cap():
    markets = [
        IndexedMarket("A", "E", "49 or below", parse_contract_rule("49 or below"), 0),
        IndexedMarket("B", "E", "50 or above", parse_contract_rule("50 or above"), 1),
    ]
    good = candidate_from_quote(markets[0], Side.YES, 0.80, quote("A", Side.YES, "0.50"))
    too_expensive = candidate_from_quote(markets[1], Side.YES, 0.95, quote("B", Side.YES, "0.90"))
    plan = optimize_event(
        "E",
        (0.80, 0.20),
        (good, too_expensive),
        Decimal("15.00"),
        OptimizerLimits(Decimal("0.60"), max_positions=2, max_contracts_per_market=1),
    )
    assert [(trade.candidate.market.ticker, trade.quantity) for trade in plan.trades] == [("A", 1)]
    assert plan.worst_case_loss <= Decimal("0.60")
