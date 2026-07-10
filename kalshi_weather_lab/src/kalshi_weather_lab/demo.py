from __future__ import annotations

from datetime import date
from decimal import Decimal

from .calibration import ResidualCalibrator
from .contracts import parse_contract_rule
from .domain import ForecastBundle, ModelForecast, OrderBook, PriceLevel, TemperatureType
from .market_types import IndexedMarket
from .optimizer import OptimizerLimits, optimize_event
from .orderbook import quote_taker_buy
from .probability import estimate_markets
from .selection import build_candidates


def run_demo(bankroll: Decimal = Decimal("15.00")) -> dict:
    titles = ["79 or below", "80 to 81", "82 to 83", "84 or above"]
    markets = [
        IndexedMarket(
            ticker=f"DEMO-{idx}",
            event_ticker="DEMO-WEATHER",
            title=title,
            rule=parse_contract_rule(title),
            outcome_index=idx,
        )
        for idx, title in enumerate(titles)
    ]
    bundle = ForecastBundle(
        city_code="DEMO",
        target_date=date.today(),
        temp_type=TemperatureType.HIGH,
        hours_to_target=8,
        forecasts=(
            ModelForecast("ecmwf", (81.4, 82.0, 82.3, 83.0, 81.8)),
            ModelForecast("gfs", (81.1, 81.8, 82.2, 82.8, 83.1)),
            ModelForecast("hrrr", (82.1,), deterministic=True),
        ),
        observed_extreme=78.0,
    )
    books = {
        "DEMO-0": OrderBook("DEMO-0", yes_bids=(PriceLevel(Decimal("0.12"), 10),), no_bids=(PriceLevel(Decimal("0.80"), 10),)),
        "DEMO-1": OrderBook("DEMO-1", yes_bids=(PriceLevel(Decimal("0.21"), 10),), no_bids=(PriceLevel(Decimal("0.70"), 10),)),
        "DEMO-2": OrderBook("DEMO-2", yes_bids=(PriceLevel(Decimal("0.30"), 10),), no_bids=(PriceLevel(Decimal("0.80"), 10),)),
        "DEMO-3": OrderBook("DEMO-3", yes_bids=(PriceLevel(Decimal("0.10"), 10),), no_bids=(PriceLevel(Decimal("0.83"), 10),)),
    }
    estimates = estimate_markets(
        [market.ticker for market in markets],
        [market.rule for market in markets],
        bundle,
        ResidualCalibrator(),
        calibration_error_floor=0.02,
        confidence_z=0.5,
    )
    candidates = build_candidates(
        markets,
        estimates,
        books,
        taker_rate=0.07,
        taker_multiplier=1.0,
        min_dollar_ev=0.01,
        min_return_on_cost=0.03,
	min_side_probability=0.10,
    )
    plan = optimize_event(
        "DEMO-WEATHER",
        [estimate.raw_yes for estimate in estimates],
        candidates,
        bankroll,
        OptimizerLimits(Decimal("0.75"), max_positions=2, max_contracts_per_market=1),
    )
    return {
        "probabilities": [
            {"ticker": estimate.ticker, "raw_yes": estimate.raw_yes, "conservative_yes": estimate.conservative_yes}
            for estimate in estimates
        ],
        "candidate_count": len(candidates),
        "selected": [
            {
                "ticker": trade.candidate.market.ticker,
                "side": trade.candidate.side.value,
                "cost": str(trade.candidate.quote.total_cost),
                "ev": str(trade.candidate.dollar_ev),
            }
            for trade in plan.trades
        ],
        "worst_case_loss": str(plan.worst_case_loss),
        "outcome_wealth": plan.outcome_wealth,
    }
