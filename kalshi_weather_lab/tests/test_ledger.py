from decimal import Decimal

from kalshi_weather_lab.domain import FillQuote, LiquidityRole, Side
from kalshi_weather_lab.ledger import Ledger


def test_settlement_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    ledger.initialize(Decimal("15.00"))
    quote = FillQuote(
        ticker="T",
        side=Side.YES,
        quantity=1,
        average_price=Decimal("0.40"),
        notional=Decimal("0.40"),
        fee=Decimal("0.0175"),
        total_cost=Decimal("0.4175"),
        levels=((Decimal("0.40"), 1),),
        liquidity_role=LiquidityRole.TAKER,
    )
    ledger.execute_paper_fill("E", quote)
    assert ledger.cash_balance() == Decimal("14.5825")
    assert ledger.settle_position("T", Side.YES, True, source="test") is True
    assert ledger.cash_balance() == Decimal("15.5825")
    assert ledger.settle_position("T", Side.YES, True, source="test again") is False
    assert ledger.cash_balance() == Decimal("15.5825")
