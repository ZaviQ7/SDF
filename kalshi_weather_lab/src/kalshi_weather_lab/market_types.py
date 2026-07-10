from __future__ import annotations

from dataclasses import dataclass
from .domain import ContractRule


@dataclass(frozen=True, slots=True)
class IndexedMarket:
    ticker: str
    event_ticker: str
    title: str
    rule: ContractRule
    outcome_index: int
    yes_bid: object = None
    yes_ask: object = None
    no_bid: object = None
    no_ask: object = None
    result: str | None = None
