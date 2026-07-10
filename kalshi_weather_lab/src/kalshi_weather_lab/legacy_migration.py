from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LegacyRow:
    target_date: str
    ticker: str
    side: str
    quantity: int
    total_cost: float
    status: str

    @property
    def dedupe_key(self) -> tuple:
        return (self.target_date, self.ticker, self.side, self.quantity, round(self.total_cost, 2))


def parse_legacy_markdown(path: str | Path) -> tuple[list[LegacyRow], list[LegacyRow]]:
    """Return unique rows and duplicates. This does not mutate the new ledger."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    rows: list[LegacyRow] = []
    duplicates: list[LegacyRow] = []
    seen: set[tuple] = set()
    for line in text.splitlines():
        if not line.strip().startswith("|") or "Target Date" in line or ":---" in line:
            continue
        parts = [part.strip() for part in line.split("|")][1:-1]
        if len(parts) < 9:
            continue
        ticker_match = re.search(r"`([^`]+)`", parts[1])
        qty_match = re.search(r"\d+", parts[3])
        cost_match = re.search(r"\(\$([\d.]+)\s+total\)", parts[4])
        if not (ticker_match and qty_match and cost_match):
            continue
        side = "yes" if "Buy YES" in parts[2] else "no"
        row = LegacyRow(
            target_date=parts[0],
            ticker=ticker_match.group(1),
            side=side,
            quantity=int(qty_match.group(0)),
            total_cost=float(cost_match.group(1)),
            status=parts[8],
        )
        if row.dedupe_key in seen:
            duplicates.append(row)
        else:
            seen.add(row.dedupe_key)
            rows.append(row)
    return rows, duplicates
