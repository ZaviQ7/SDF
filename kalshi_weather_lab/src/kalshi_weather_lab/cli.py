from __future__ import annotations

import argparse
from dataclasses import asdict
import asyncio
import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

from .automation import run_scheduled_scans
from .config import load_config
from .demo import run_demo
from .domain import TemperatureType
from .ledger import Ledger
from .legacy_migration import parse_legacy_markdown
from .pipeline import Scanner
from .reporting import write_report
from .settlement import settle_all_open


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kalshi-weather",
        description="Dry-run-first Kalshi weather market research and paper-trading engine",
    )
    parser.add_argument("--settings", default="config/settings.yaml")
    parser.add_argument("--cities", default="config/cities.yaml")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize the SQLite paper ledger")
    init.add_argument("--bankroll", type=Decimal, default=Decimal("15.00"))

    sub.add_parser("demo", help="Run a deterministic synthetic event demonstration")

    scan = sub.add_parser("scan", help="Scan one configured city/date event")
    scan.add_argument("--city", required=True, help="City name or code from cities.yaml")
    scan.add_argument("--type", choices=["HIGH", "LOW"], required=True)
    scan.add_argument("--date", type=date.fromisoformat, required=True)
    scan.add_argument("--paper-execute", action="store_true")

    run_once = sub.add_parser("run-once", help="Scan all active city events whose local scan window is open")
    run_once.add_argument("--paper-execute", action="store_true")

    sub.add_parser("settle-open", help="Settle open paper positions only from final NWS CLI reports")
    sub.add_parser("report", help="Regenerate the Markdown dashboard from SQLite")

    migrate = sub.add_parser("audit-legacy", help="Detect duplicate rows in the old Markdown ledger")
    migrate.add_argument("markdown", type=Path)
    return parser


async def _scan(args, config, ledger):
    city = next(
        (
            city for city in config.cities
            if city.name.lower() == args.city.lower() or city.code.lower() == args.city.lower()
        ),
        None,
    )
    if city is None:
        raise SystemExit(f"Unknown city {args.city!r}")
    result = await Scanner(config, ledger).scan_city_event(
        city,
        TemperatureType(args.type),
        args.date,
        paper_execute=args.paper_execute,
    )
    print(json.dumps(result, indent=2))


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.command == "demo":
        print(json.dumps(run_demo(), indent=2))
        return
    if args.command == "audit-legacy":
        rows, duplicates = parse_legacy_markdown(args.markdown)
        print(json.dumps({"unique_rows": len(rows), "duplicates": len(duplicates), "duplicate_rows": [asdict(row) for row in duplicates]}, indent=2))
        return

    config = load_config(args.settings, args.cities)
    ledger = Ledger(config.database_path)
    if args.command == "init":
        ledger.initialize(args.bankroll)
        print(f"Initialized {config.database_path} with ${args.bankroll:.2f}")
    elif args.command == "report":
        ledger.initialize(config.risk.starting_bankroll)
        output = write_report(ledger, config.report_path)
        print(output)
    elif args.command == "scan":
        ledger.initialize(config.risk.starting_bankroll)
        asyncio.run(_scan(args, config, ledger))
    elif args.command == "run-once":
        ledger.initialize(config.risk.starting_bankroll)
        print(json.dumps(asyncio.run(run_scheduled_scans(config, ledger, paper_execute=args.paper_execute)), indent=2))
    elif args.command == "settle-open":
        ledger.initialize(config.risk.starting_bankroll)
        print(json.dumps(asyncio.run(settle_all_open(config, ledger)), indent=2))
        write_report(ledger, config.report_path)


if __name__ == "__main__":
    main()
