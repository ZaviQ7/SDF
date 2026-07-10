from __future__ import annotations

from decimal import Decimal, ROUND_CEILING

from .domain import LiquidityRole, as_decimal

CENTICENT = Decimal("0.0001")  # one hundredth of one cent


def round_up_to_centicent(value: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0.0000")
    return value.quantize(CENTICENT, rounding=ROUND_CEILING)


def kalshi_fee(
    price: Decimal | float | str,
    contracts: int,
    role: LiquidityRole = LiquidityRole.TAKER,
    *,
    taker_rate: Decimal | float | str = Decimal("0.07"),
    maker_rate: Decimal | float | str = Decimal("0.0175"),
    taker_multiplier: Decimal | float | str = Decimal("1"),
    maker_multiplier: Decimal | float | str = Decimal("0"),
) -> Decimal:
    """General Kalshi fee formula, rounded up to the nearest centicent.

    A centicent is $0.0001. Published fee tables display fewer decimals, but the
    current official formula specifies centicent rounding.
    """
    if contracts <= 0:
        return Decimal("0.0000")
    p = as_decimal(price)
    if not Decimal("0") < p < Decimal("1"):
        raise ValueError("price must be strictly between 0 and 1")
    if role is LiquidityRole.TAKER:
        rate = as_decimal(taker_rate)
        multiplier = as_decimal(taker_multiplier)
    else:
        rate = as_decimal(maker_rate)
        multiplier = as_decimal(maker_multiplier)
    raw = multiplier * rate * Decimal(contracts) * p * (Decimal("1") - p)
    return round_up_to_centicent(raw)
