from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from decimal import Decimal
from statistics import median

from .arbitrage import find_strip_arbitrage
from .calibration import ResidualCalibrator, load_residual_rows
from .config import AppConfig
from .contracts import validate_partition
from .domain import CityConfig, Market, Side, TemperatureType
from .kalshi_client import KalshiPublicClient, market_from_payload
from .ledger import Ledger
from .market_types import IndexedMarket
from .nws import NWSClient
from .optimizer import OptimizerLimits, optimize_event
from .probability import estimate_markets
from .reporting import write_report
from .selection import build_candidates
from .weather_client import OpenMeteoClient

logger = logging.getLogger(__name__)


class Scanner:
    def __init__(self, config: AppConfig, ledger: Ledger):
        self.config = config
        self.ledger = ledger

    async def scan_city_event(
        self,
        city: CityConfig,
        temp_type: TemperatureType,
        target_date: date,
        *,
        paper_execute: bool = False,
    ) -> dict:
        series = city.series_for(temp_type)
        if not series:
            raise ValueError(f"No series configured for {city.name} {temp_type.value}")
        nws = NWSClient(self.config.open_meteo_timeout_seconds)
        try:
            observed = await nws.observed_extreme_so_far(
                city.station_id, target_date, city.timezone, temp_type
            )
        except Exception as exc:
            logger.warning("NWS running observation unavailable for %s: %s", city.name, exc)
            observed = None
        weather = OpenMeteoClient(self.config.open_meteo_timeout_seconds)
        bundle = await weather.fetch_bundle(
            city, target_date, temp_type, observed_extreme=observed
        )
        if not bundle.forecasts:
            raise RuntimeError("No weather forecasts were retrieved")

        lead_bucket = ResidualCalibrator.lead_bucket(
            bundle.hours_to_target
        )

        for forecast in bundle.forecasts:
            if not forecast.values:
                continue

            # Store one representative value per model/date/lead bucket.
            # Ensemble members are correlated and must not each count as
            # independent calibration samples.
            representative_value = float(median(forecast.values))

            self.ledger.record_forecast_snapshot(
                city_code=city.code,
                temp_type=temp_type.value,
                model=forecast.model,
                lead_bucket=lead_bucket,
                target_date=target_date.isoformat(),
                forecast_f=representative_value,
                deterministic=forecast.deterministic,
            )

        async with KalshiPublicClient(self.config.api_base_url) as kalshi:
            payloads = await kalshi.list_markets(series_ticker=series, status="open")
            # occurrence_datetime is the most reliable date field when present; ticker fallback remains useful.
            target_iso = target_date.isoformat()
            compact = target_date.strftime("%y%b%d").upper()
            matching = [
                payload for payload in payloads
                if str(payload.get("occurrence_datetime", "")).startswith(target_iso)
                or compact in payload.get("ticker", "").upper()
            ]
            if not matching:
                raise RuntimeError(f"No open {series} markets found for {target_date}")
            by_event: dict[str, list[dict]] = {}
            for payload in matching:
                by_event.setdefault(payload["event_ticker"], []).append(payload)
            # There should normally be one event for one city/type/date. Pick the largest complete set.
            event_ticker, selected_payloads = max(by_event.items(), key=lambda item: len(item[1]))
            base_markets = [market_from_payload(payload) for payload in selected_payloads]
            base_markets.sort(key=lambda m: float("-inf") if m.rule.lower is None else m.rule.lower)
            valid, reason = validate_partition([market.rule for market in base_markets])
            if not valid:
                raise RuntimeError(f"Market set is not an exhaustive partition: {reason}")
            markets = [
                IndexedMarket(
                    ticker=market.ticker,
                    event_ticker=market.event_ticker,
                    title=market.title,
                    rule=market.rule,
                    outcome_index=index,
                    yes_bid=market.yes_bid,
                    yes_ask=market.yes_ask,
                    no_bid=market.no_bid,
                    no_ask=market.no_ask,
                    result=market.result,
                )
                for index, market in enumerate(base_markets)
            ]
            books = await kalshi.get_orderbooks([market.ticker for market in markets])

        calibrator = ResidualCalibrator(load_residual_rows(self.ledger.residual_rows()))
        estimates = estimate_markets(
            [market.ticker for market in markets],
            [market.rule for market in markets],
            bundle,
            calibrator,
            calibration_error_floor=self.config.risk.calibration_error_floor,
            confidence_z=self.config.risk.confidence_z,
        )
        raw_probabilities = tuple(estimate.raw_yes for estimate in estimates)
        all_candidates = build_candidates(
            markets,
            estimates,
            books,
            taker_rate=self.config.fees.taker_rate,
            taker_multiplier=self.config.fees.taker_multiplier,
            min_dollar_ev=self.config.risk.min_dollar_ev,
            min_return_on_cost=self.config.risk.min_return_on_cost,
	    min_side_probability=self.config.risk.min_side_probability,
                min_contract_price=self.config.risk.min_contract_price,
        )
        open_positions = self.ledger.open_positions()
        open_tickers = {position["ticker"] for position in open_positions}
        candidates = tuple(candidate for candidate in all_candidates if candidate.market.ticker not in open_tickers)

        cash = self.ledger.cash_balance()
        event_risk_used = self.ledger.open_cost_for_event(event_ticker)
        daily_risk_used = self.ledger.open_cost_for_target_date(target_date.isoformat())
        event_budget = max(
            Decimal("0"),
            cash * Decimal(str(self.config.risk.max_event_loss_fraction)) - event_risk_used,
        )
        daily_budget = max(
            Decimal("0"),
            cash * Decimal(str(self.config.risk.max_daily_loss_fraction)) - daily_risk_used,
        )
        max_incremental_loss = min(cash, event_budget, daily_budget)
        plan = optimize_event(
            event_ticker,
            raw_probabilities,
            candidates,
            cash,
            OptimizerLimits(
                max_event_loss=max_incremental_loss,
                max_positions=self.config.risk.max_positions_per_event,
                max_contracts_per_market=self.config.risk.max_contracts_per_market,
            ),
        )

        accepted_keys = {(trade.candidate.market.ticker, trade.candidate.side) for trade in plan.trades}
        estimate_map = {estimate.ticker: estimate for estimate in estimates}
        for candidate in all_candidates:
            estimate = estimate_map[candidate.market.ticker]
            accepted = (candidate.market.ticker, candidate.side) in accepted_keys
            already_open = candidate.market.ticker in open_tickers
            self.ledger.record_decision(
                event_ticker=event_ticker,
                ticker=candidate.market.ticker,
                side=candidate.side,
                raw_probability=estimate.raw_yes if candidate.side is Side.YES else 1.0 - estimate.raw_yes,
                conservative_probability=candidate.probability,
                accepted=accepted,
                reason=(
                    "selected by event expected-log optimizer"
                    if accepted
                    else "market already has an open position"
                    if already_open
                    else "positive edge, not selected under portfolio constraints"
                ),
                city_code=city.code,
                target_date=target_date.isoformat(),
                temp_type=temp_type.value,
                price=candidate.quote.average_price,
                fee=candidate.quote.fee,
                dollar_ev=candidate.dollar_ev,
                payload={"outcome_wealth": plan.outcome_wealth},
            )

        if paper_execute:
            for trade in plan.trades:
                quote = trade.candidate.quote
                if trade.quantity != quote.quantity:
                    raise RuntimeError("Current paper executor expects one-contract quotes")
                self.ledger.execute_paper_fill(event_ticker, quote)

        strip_arbs = find_strip_arbitrage(
            markets,
            books,
            taker_rate=self.config.fees.taker_rate,
            taker_multiplier=self.config.fees.taker_multiplier,
        )
        write_report(self.ledger, self.config.report_path)
        return {
            "event_ticker": event_ticker,
            "city": city.name,
            "temp_type": temp_type.value,
            "target_date": target_date.isoformat(),
            "observed_extreme": observed,
            "probabilities": [
                {
                    "ticker": estimate.ticker,
                    "raw_yes": estimate.raw_yes,
                    "conservative_yes": estimate.conservative_yes,
                    "penalty": estimate.uncertainty_penalty,
                }
                for estimate in estimates
            ],
            "candidates": len(all_candidates),
            "eligible_new_candidates": len(candidates),
            "event_risk_budget_remaining": str(event_budget),
            "daily_risk_budget_remaining": str(daily_budget),
            "selected": [
                {
                    "ticker": trade.candidate.market.ticker,
                    "side": trade.candidate.side.value,
                    "quantity": trade.quantity,
                    "cost": str(trade.candidate.quote.total_cost),
                    "dollar_ev": str(trade.candidate.dollar_ev),
                }
                for trade in plan.trades
            ],
            "worst_case_loss": str(plan.worst_case_loss),
            "structural_arbitrage": [
                {
                    "side": arb.side.value,
                    "cost": str(arb.total_cost),
                    "payout": str(arb.guaranteed_payout),
                    "profit": str(arb.guaranteed_profit),
                }
                for arb in strip_arbs
            ],
        }
