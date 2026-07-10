from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .ledger import Ledger, dollars


def build_markdown_report(ledger: Ledger) -> str:
    cash = ledger.cash_balance()
    starting = ledger.starting_cash()
    positions = ledger.all_positions()
    decisions = ledger.recent_decisions(50)
    open_cost = sum((dollars(row["total_cost_cc"]) for row in positions if row["status"] == "open"), Decimal("0"))
    settled_credit = sum((dollars(row["settlement_credit_cc"]) for row in positions if row["status"] == "settled"), Decimal("0"))
    realized_cost = sum((dollars(row["total_cost_cc"]) for row in positions if row["status"] == "settled"), Decimal("0"))
    realized_pnl = settled_credit - realized_cost

    lines = [
        "# Kalshi Weather Lab — Paper Portfolio",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- **Starting bankroll:** ${starting:.2f}",
        f"- **Cash:** ${cash:.2f}",
        f"- **Open cost basis (not NAV):** ${open_cost:.2f}",
        f"- **Realized P/L:** {realized_pnl:+.2f}",
        "",
        "> This report intentionally does not call cost basis ‘NAV’. Liquidation NAV requires current executable bids and exit fees.",
        "",
        "## Positions",
        "",
        "| Ticker | Side | Qty | Cost | Status | Result | Credit |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in positions:
        lines.append(
            f"| `{row['ticker']}` | {row['side'].upper()} | {row['quantity']} | "
            f"${dollars(row['total_cost_cc']):.2f} | {row['status']} | "
            f"{row['settlement_result'] or '-'} | ${dollars(row['settlement_credit_cc']):.2f} |"
        )
    if not positions:
        lines.append("| — | — | — | — | — | — | — |")

    lines.extend([
        "",
        "## Recent Decisions",
        "",
        "| Time | Ticker | Side | Conservative p | Price | EV | Accepted | Reason |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for row in decisions:
        price = "—" if row["price_cc"] is None else f"${dollars(row['price_cc']):.4f}"
        ev = "—" if row["dollar_ev_cc"] is None else f"{dollars(row['dollar_ev_cc']):+.4f}"
        lines.append(
            f"| {row['created_at']} | `{row['ticker']}` | {row['side'].upper()} | "
            f"{row['conservative_probability']:.1%} | {price} | {ev} | "
            f"{'yes' if row['accepted'] else 'no'} | {row['reason']} |"
        )
    if not decisions:
        lines.append("| — | — | — | — | — | — | — | — |")
    lines.append("")
    return "\n".join(lines)


def write_report(ledger: Ledger, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_markdown_report(ledger), encoding="utf-8")
    return output
