from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Iterable


class Side(StrEnum):
    YES = "yes"
    NO = "no"


class TemperatureType(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


class LiquidityRole(StrEnum):
    TAKER = "taker"
    MAKER = "maker"


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price: Decimal
    quantity: int

    def __post_init__(self) -> None:
        if not Decimal("0") < self.price < Decimal("1"):
            raise ValueError(f"Price must be between 0 and 1: {self.price}")
        if self.quantity < 0:
            raise ValueError("Quantity cannot be negative")


@dataclass(frozen=True, slots=True)
class OrderBook:
    ticker: str
    yes_bids: tuple[PriceLevel, ...] = ()
    no_bids: tuple[PriceLevel, ...] = ()
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class ContractRule:
    """Inclusive integer-temperature interval. None represents an open end."""

    lower: int | None
    upper: int | None
    label: str

    def contains(self, rounded_temperature: int) -> bool:
        if self.lower is not None and rounded_temperature < self.lower:
            return False
        if self.upper is not None and rounded_temperature > self.upper:
            return False
        return True

    def overlaps(self, other: "ContractRule") -> bool:
        lo = max(x for x in (self.lower, other.lower) if x is not None) if any(
            x is not None for x in (self.lower, other.lower)
        ) else None
        hi = min(x for x in (self.upper, other.upper) if x is not None) if any(
            x is not None for x in (self.upper, other.upper)
        ) else None
        return not (lo is not None and hi is not None and lo > hi)


@dataclass(frozen=True, slots=True)
class Market:
    ticker: str
    event_ticker: str
    title: str
    rule: ContractRule
    yes_bid: Decimal | None = None
    yes_ask: Decimal | None = None
    no_bid: Decimal | None = None
    no_ask: Decimal | None = None
    result: str | None = None


@dataclass(frozen=True, slots=True)
class CityConfig:
    name: str
    code: str
    latitude: float
    longitude: float
    timezone: str
    station_id: str
    series_high: str | None = None
    series_low: str | None = None
    active: bool = True

    def series_for(self, temp_type: TemperatureType) -> str | None:
        return self.series_high if temp_type is TemperatureType.HIGH else self.series_low


@dataclass(frozen=True, slots=True)
class ModelForecast:
    model: str
    values: tuple[float, ...]
    deterministic: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class ForecastBundle:
    city_code: str
    target_date: date
    temp_type: TemperatureType
    hours_to_target: float
    forecasts: tuple[ModelForecast, ...]
    observed_extreme: float | None = None


@dataclass(frozen=True, slots=True)
class ProbabilityEstimate:
    ticker: str
    raw_yes: float
    conservative_yes: float
    effective_sample_size: float
    uncertainty_penalty: float


@dataclass(frozen=True, slots=True)
class FillQuote:
    ticker: str
    side: Side
    quantity: int
    average_price: Decimal
    notional: Decimal
    fee: Decimal
    total_cost: Decimal
    levels: tuple[tuple[Decimal, int], ...]
    liquidity_role: LiquidityRole


@dataclass(frozen=True, slots=True)
class CandidateTrade:
    market: Market
    side: Side
    probability: float
    quote: FillQuote
    dollar_ev: Decimal
    return_on_cost: float


@dataclass(frozen=True, slots=True)
class PlannedTrade:
    candidate: CandidateTrade
    quantity: int


@dataclass(frozen=True, slots=True)
class EventPlan:
    event_ticker: str
    trades: tuple[PlannedTrade, ...]
    expected_log_growth: float
    expected_terminal_wealth: float
    worst_case_loss: Decimal
    outcome_wealth: tuple[float, ...]


def as_decimal(value: str | float | int | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def ensure_probability_vector(values: Iterable[float]) -> tuple[float, ...]:
    vals = tuple(max(0.0, float(v)) for v in values)
    total = sum(vals)
    if total <= 0:
        raise ValueError("Probability vector has no positive mass")
    return tuple(v / total for v in vals)
