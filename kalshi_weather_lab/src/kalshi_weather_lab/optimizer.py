from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import log
from collections.abc import Sequence

from .domain import CandidateTrade, EventPlan, PlannedTrade, Side, ensure_probability_vector


@dataclass(frozen=True, slots=True)
class OptimizerLimits:
    max_event_loss: Decimal
    max_positions: int = 3
    max_contracts_per_market: int = 1


def candidate_from_quote(market, side: Side, side_probability: float, quote) -> CandidateTrade:
    payout_probability = max(0.0, min(1.0, side_probability))
    expected_payout = Decimal(str(payout_probability)) * quote.quantity
    dollar_ev = expected_payout - quote.total_cost
    roc = float(dollar_ev / quote.total_cost) if quote.total_cost > 0 else -1.0
    return CandidateTrade(market, side, payout_probability, quote, dollar_ev, roc)


def _terminal_wealth(
    bankroll: Decimal,
    candidates: Sequence[CandidateTrade],
    quantities: Sequence[int],
    outcome_count: int,
) -> tuple[float, ...]:
    total_cost = sum(
        (candidate.quote.total_cost * qty / candidate.quote.quantity for candidate, qty in zip(candidates, quantities, strict=True)),
        Decimal("0"),
    )
    cash_after = bankroll - total_cost
    wealth = []
    for outcome_idx in range(outcome_count):
        payout = Decimal("0")
        for candidate, qty in zip(candidates, quantities, strict=True):
            market_idx = getattr(candidate.market, "outcome_index")
            wins = outcome_idx == market_idx if candidate.side is Side.YES else outcome_idx != market_idx
            if wins:
                payout += Decimal(qty)
        wealth.append(float(cash_after + payout))
    return tuple(wealth)


def optimize_event(
    event_ticker: str,
    outcome_probabilities: Sequence[float],
    candidates: Sequence[CandidateTrade],
    bankroll: Decimal,
    limits: OptimizerLimits,
) -> EventPlan:
    """Greedy integer expected-log optimizer with exact scenario wealth checks.

    The bankroll is small and contracts are indivisible, so every proposed increment is
    evaluated against every mutually exclusive event outcome. A trade is accepted only
    when it improves expected log wealth and remains inside the worst-case loss cap.
    """
    probabilities = ensure_probability_vector(outcome_probabilities)
    usable = [c for c in candidates if c.dollar_ev > 0 and c.quote.quantity >= 1]
    quantities = [0] * len(usable)

    def score(qty: list[int]) -> tuple[float, tuple[float, ...], Decimal]:
        wealth = _terminal_wealth(bankroll, usable, qty, len(probabilities))
        if not wealth or min(wealth) <= 0:
            return float("-inf"), wealth, bankroll
        worst_loss = bankroll - Decimal(str(min(wealth)))
        if worst_loss > limits.max_event_loss:
            return float("-inf"), wealth, worst_loss
        expected_log = sum(p * log(w) for p, w in zip(probabilities, wealth, strict=True))
        return expected_log, wealth, worst_loss

    base_score, base_wealth, base_loss = score(quantities)
    while True:
        occupied = sum(1 for qty in quantities if qty > 0)
        best: tuple[float, int, tuple[float, ...], Decimal] | None = None
        for idx, candidate in enumerate(usable):
            if quantities[idx] >= limits.max_contracts_per_market:
                continue
            if quantities[idx] == 0 and occupied >= limits.max_positions:
                continue
            trial = quantities.copy()
            trial[idx] += 1
            trial_score, trial_wealth, trial_loss = score(trial)
            improvement = trial_score - base_score
            if improvement > 1e-12 and (best is None or improvement > best[0]):
                best = (improvement, idx, trial_wealth, trial_loss)
        if best is None:
            break
        _, idx, base_wealth, base_loss = best
        quantities[idx] += 1
        base_score, _, _ = score(quantities)

    trades = tuple(
        PlannedTrade(candidate, qty) for candidate, qty in zip(usable, quantities, strict=True) if qty > 0
    )
    expected_terminal = sum(p * w for p, w in zip(probabilities, base_wealth, strict=True))
    return EventPlan(
        event_ticker=event_ticker,
        trades=trades,
        expected_log_growth=base_score - log(float(bankroll)),
        expected_terminal_wealth=expected_terminal,
        worst_case_loss=base_loss,
        outcome_wealth=base_wealth,
    )
