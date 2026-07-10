from decimal import Decimal

from kalshi_weather_lab.domain import LiquidityRole
from kalshi_weather_lab.fees import kalshi_fee


def test_general_taker_fee_uses_official_centicent_rounding():
    assert kalshi_fee(Decimal("0.01"), 1) == Decimal("0.0007")
    assert kalshi_fee(Decimal("0.50"), 1) == Decimal("0.0175")
    assert kalshi_fee(Decimal("0.50"), 100) == Decimal("1.7500")
    assert kalshi_fee(Decimal("0.99"), 100) == Decimal("0.0693")


def test_default_general_maker_multiplier_is_zero():
    assert kalshi_fee(Decimal("0.50"), 10, LiquidityRole.MAKER) == Decimal("0.0000")
