from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .domain import CandidateTrade, Market, ProbabilityEstimate, Side
from .optimizer import candidate_from_quote
from .orderbook import InsufficientDepthError, quote_taker_buy


def build_candidates(
    markets: Sequence[Market],
    estimates: Sequence[ProbabilityEstimate],
    books: dict[str, object],
    *,
    taker_rate: float,
    taker_multiplier: float,
    min_dollar_ev: float,
    min_return_on_cost: float,
    min_side_probability: float,
    min_contract_price: float,
) -> tuple[CandidateTrade, ...]:
    estimate_map = {estimate.ticker: estimate for estimate in estimates}
    candidates: list[CandidateTrade] = []

    for market in markets:
        estimate = estimate_map[market.ticker]

        for side in (Side.YES, Side.NO):
            probability = (
                estimate.conservative_yes
                if side is Side.YES
                else max(
                    0.0,
                    1.0 - estimate.raw_yes - estimate.uncertainty_penalty,
                )
            )

            if probability < min_side_probability:
                continue

            try:
                quote = quote_taker_buy(
                    books[market.ticker],
                    side,
                    1,
                    taker_rate=taker_rate,
                    taker_multiplier=taker_multiplier,
                )
            except (KeyError, InsufficientDepthError):
                continue

            if quote.average_price < Decimal(str(min_contract_price)):
                continue

            candidate = candidate_from_quote(
                market,
                side,
                probability,
                quote,
            )

            if candidate.dollar_ev < Decimal(str(min_dollar_ev)):
                continue

            if candidate.return_on_cost < min_return_on_cost:
                continue

            candidates.append(candidate)

    return tuple(
        sorted(
            candidates,
            key=lambda candidate: candidate.dollar_ev,
            reverse=True,
        )
    )
