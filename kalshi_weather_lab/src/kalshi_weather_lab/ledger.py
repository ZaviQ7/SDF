from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .domain import FillQuote, Side


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    starting_cash_cc INTEGER NOT NULL,
    cash_cc INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    event_ticker TEXT NOT NULL,
    ticker TEXT NOT NULL,
    city_code TEXT,
    target_date TEXT,
    temp_type TEXT,
    side TEXT NOT NULL,
    raw_probability REAL NOT NULL,
    conservative_probability REAL NOT NULL,
    price_cc INTEGER,
    fee_cc INTEGER,
    dollar_ev_cc INTEGER,
    accepted INTEGER NOT NULL,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_event ON decisions(event_ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker, created_at);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    external_fill_id TEXT UNIQUE,
    created_at TEXT NOT NULL,
    event_ticker TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    average_price_cc INTEGER NOT NULL,
    notional_cc INTEGER NOT NULL,
    fee_cc INTEGER NOT NULL,
    total_cost_cc INTEGER NOT NULL,
    liquidity_role TEXT NOT NULL,
    levels_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    event_ticker TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity >= 0),
    total_cost_cc INTEGER NOT NULL CHECK(total_cost_cc >= 0),
    status TEXT NOT NULL CHECK(status IN ('open', 'settled')),
    settlement_result TEXT,
    settlement_credit_cc INTEGER NOT NULL DEFAULT 0,
    opened_at TEXT NOT NULL,
    settled_at TEXT,
    PRIMARY KEY (ticker, side)
);

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    official_result TEXT NOT NULL,
    credit_cc INTEGER NOT NULL,
    settled_at TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(ticker, side)
);

CREATE TABLE IF NOT EXISTS forecast_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_code TEXT NOT NULL,
    temp_type TEXT NOT NULL,
    model TEXT NOT NULL,
    lead_bucket TEXT NOT NULL,
    target_date TEXT NOT NULL,
    forecast_f REAL NOT NULL,
    deterministic INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    residual_recorded INTEGER NOT NULL DEFAULT 0,
    UNIQUE(
        city_code,
        temp_type,
        model,
        lead_bucket,
        target_date
    )
);

CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_target
ON forecast_snapshots(city_code, temp_type, target_date, residual_recorded);

CREATE TABLE IF NOT EXISTS forecast_residuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_code TEXT NOT NULL,
    temp_type TEXT NOT NULL,
    model TEXT NOT NULL,
    lead_bucket TEXT NOT NULL,
    target_date TEXT NOT NULL,
    forecast_f REAL NOT NULL,
    actual_f REAL NOT NULL,
    residual_f REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(city_code, temp_type, model, lead_bucket, target_date)
);

CREATE TABLE IF NOT EXISTS nav_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TEXT NOT NULL,
    cash_cc INTEGER NOT NULL,
    liquidation_value_cc INTEGER NOT NULL,
    model_value_cc INTEGER NOT NULL,
    note TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def units(value: Decimal | float | str) -> int:
    return int((Decimal(str(value)) * 10000).quantize(Decimal("1")))


def dollars(value_cc: int) -> Decimal:
    return Decimal(value_cc) / Decimal(10000)


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self, starting_cash: Decimal | float | str = Decimal("15.00")) -> None:
        now = _now()
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                """INSERT OR IGNORE INTO account
                   (id, starting_cash_cc, cash_cc, created_at, updated_at)
                   VALUES (1, ?, ?, ?, ?)""",
                (units(starting_cash), units(starting_cash), now, now),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def cash_balance(self) -> Decimal:
        with self.connect() as conn:
            row = conn.execute("SELECT cash_cc FROM account WHERE id=1").fetchone()
        if row is None:
            raise RuntimeError("Ledger is not initialized")
        return dollars(row["cash_cc"])

    def starting_cash(self) -> Decimal:
        with self.connect() as conn:
            row = conn.execute("SELECT starting_cash_cc FROM account WHERE id=1").fetchone()
        if row is None:
            raise RuntimeError("Ledger is not initialized")
        return dollars(row["starting_cash_cc"])

    def record_decision(
        self,
        *,
        event_ticker: str,
        ticker: str,
        side: Side,
        raw_probability: float,
        conservative_probability: float,
        accepted: bool,
        reason: str,
        city_code: str | None = None,
        target_date: str | None = None,
        temp_type: str | None = None,
        price: Decimal | None = None,
        fee: Decimal | None = None,
        dollar_ev: Decimal | None = None,
        payload: dict | None = None,
    ) -> str:
        decision_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO decisions VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision_id,
                    _now(),
                    event_ticker,
                    ticker,
                    city_code,
                    target_date,
                    temp_type,
                    side.value,
                    raw_probability,
                    conservative_probability,
                    units(price) if price is not None else None,
                    units(fee) if fee is not None else None,
                    units(dollar_ev) if dollar_ev is not None else None,
                    int(accepted),
                    reason,
                    json.dumps(payload or {}, sort_keys=True, default=str),
                ),
            )
        return decision_id

    def execute_paper_fill(
        self,
        event_ticker: str,
        quote: FillQuote,
        *,
        external_fill_id: str | None = None,
    ) -> str:
        fill_id = str(uuid.uuid4())
        total_cost_cc = units(quote.total_cost)
        with self.transaction() as conn:
            account = conn.execute("SELECT cash_cc FROM account WHERE id=1").fetchone()
            if account is None:
                raise RuntimeError("Ledger is not initialized")
            if account["cash_cc"] < total_cost_cc:
                raise RuntimeError("Insufficient simulated cash")
            existing = conn.execute(
                "SELECT status FROM positions WHERE ticker=? AND side=?",
                (quote.ticker, quote.side.value),
            ).fetchone()
            if existing and existing["status"] == "settled":
                raise RuntimeError("Cannot reopen a settled ticker/side in the same ledger")

            conn.execute(
                """INSERT INTO fills
                   (fill_id, external_fill_id, created_at, event_ticker, ticker, side,
                    quantity, average_price_cc, notional_cc, fee_cc,
                    total_cost_cc, liquidity_role, levels_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fill_id,
                    external_fill_id,
                    _now(),
                    event_ticker,
                    quote.ticker,
                    quote.side.value,
                    quote.quantity,
                    units(quote.average_price),
                    units(quote.notional),
                    units(quote.fee),
                    total_cost_cc,
                    quote.liquidity_role.value,
                    json.dumps([(str(price), qty) for price, qty in quote.levels]),
                ),
            )
            conn.execute(
                "UPDATE account SET cash_cc=cash_cc-?, updated_at=? WHERE id=1",
                (total_cost_cc, _now()),
            )
            conn.execute(
                """INSERT INTO positions
                   (ticker, side, event_ticker, quantity, total_cost_cc, status,
                    settlement_result, settlement_credit_cc, opened_at, settled_at)
                   VALUES (?, ?, ?, ?, ?, 'open', NULL, 0, ?, NULL)
                   ON CONFLICT(ticker, side) DO UPDATE SET
                     quantity=positions.quantity + excluded.quantity,
                     total_cost_cc=positions.total_cost_cc + excluded.total_cost_cc""",
                (
                    quote.ticker,
                    quote.side.value,
                    event_ticker,
                    quote.quantity,
                    total_cost_cc,
                    _now(),
                ),
            )
        return fill_id

    def settle_position(
        self,
        ticker: str,
        side: Side,
        official_yes_result: bool,
        *,
        source: str,
    ) -> bool:
        """Settle exactly once. Returns False when already settled or absent."""
        with self.transaction() as conn:
            position = conn.execute(
                "SELECT * FROM positions WHERE ticker=? AND side=?",
                (ticker, side.value),
            ).fetchone()
            if position is None or position["status"] != "open":
                return False
            won = official_yes_result if side is Side.YES else not official_yes_result
            credit_cc = position["quantity"] * 10000 if won else 0
            settlement_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO settlements
                   (settlement_id, ticker, side, official_result, credit_cc, settled_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    settlement_id,
                    ticker,
                    side.value,
                    "yes" if official_yes_result else "no",
                    credit_cc,
                    _now(),
                    source,
                ),
            )
            conn.execute(
                """UPDATE positions SET status='settled', settlement_result=?,
                   settlement_credit_cc=?, settled_at=? WHERE ticker=? AND side=?""",
                (
                    "win" if won else "loss",
                    credit_cc,
                    _now(),
                    ticker,
                    side.value,
                ),
            )
            conn.execute(
                "UPDATE account SET cash_cc=cash_cc+?, updated_at=? WHERE id=1",
                (credit_cc, _now()),
            )
        return True

    def open_positions(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status='open' ORDER BY opened_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def all_positions(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM positions ORDER BY opened_at DESC").fetchall()
        return [dict(row) for row in rows]

    def recent_decisions(self, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def record_forecast_snapshot(
        self,
        *,
        city_code: str,
        temp_type: str,
        model: str,
        lead_bucket: str,
        target_date: str,
        forecast_f: float,
        deterministic: bool,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO forecast_snapshots
                   (city_code, temp_type, model, lead_bucket, target_date,
                    forecast_f, deterministic, captured_at, residual_recorded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                   ON CONFLICT(
                       city_code,
                       temp_type,
                       model,
                       lead_bucket,
                       target_date
                   )
                   DO UPDATE SET
                       forecast_f=excluded.forecast_f,
                       deterministic=excluded.deterministic,
                       captured_at=excluded.captured_at
                   WHERE forecast_snapshots.residual_recorded=0""",
                (
                    city_code,
                    temp_type,
                    model.lower(),
                    lead_bucket,
                    target_date,
                    float(forecast_f),
                    int(deterministic),
                    _now(),
                ),
            )

    def unresolved_forecast_snapshots(
        self,
        *,
        city_code: str,
        temp_type: str,
        target_date: str,
    ) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT *
                   FROM forecast_snapshots
                   WHERE city_code=?
                     AND temp_type=?
                     AND target_date=?
                     AND residual_recorded=0
                   ORDER BY captured_at""",
                (city_code, temp_type, target_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def finalize_forecast_snapshot(
        self,
        *,
        snapshot_id: int,
        actual_f: float,
    ) -> None:
        with self.transaction() as conn:
            row = conn.execute(
                """SELECT *
                   FROM forecast_snapshots
                   WHERE id=? AND residual_recorded=0""",
                (snapshot_id,),
            ).fetchone()

            if row is None:
                return

            conn.execute(
                """INSERT OR REPLACE INTO forecast_residuals
                   (city_code, temp_type, model, lead_bucket, target_date,
                    forecast_f, actual_f, residual_f, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["city_code"],
                    row["temp_type"],
                    row["model"],
                    row["lead_bucket"],
                    row["target_date"],
                    float(row["forecast_f"]),
                    float(actual_f),
                    float(actual_f) - float(row["forecast_f"]),
                    _now(),
                ),
            )

            conn.execute(
                """UPDATE forecast_snapshots
                   SET residual_recorded=1
                   WHERE id=?""",
                (snapshot_id,),
            )

    def residual_rows(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM forecast_residuals").fetchall()
        return [dict(row) for row in rows]

    def record_residual(
        self,
        *,
        city_code: str,
        temp_type: str,
        model: str,
        lead_bucket: str,
        target_date: str,
        forecast_f: float,
        actual_f: float,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO forecast_residuals
                   (city_code, temp_type, model, lead_bucket, target_date, forecast_f,
                    actual_f, residual_f, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    city_code,
                    temp_type,
                    model.lower(),
                    lead_bucket,
                    target_date,
                    forecast_f,
                    actual_f,
                    actual_f - forecast_f,
                    _now(),
                ),
            )

    def snapshot_nav(
        self,
        *,
        liquidation_value: Decimal,
        model_value: Decimal,
        note: str = "",
    ) -> None:
        cash = self.cash_balance()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO nav_snapshots
                   (captured_at, cash_cc, liquidation_value_cc, model_value_cc, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (_now(), units(cash), units(liquidation_value), units(model_value), note),
            )

    def open_positions_with_metadata(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT p.*,
                          (SELECT d.city_code FROM decisions d
                           WHERE d.ticker=p.ticker AND d.accepted=1
                           ORDER BY d.created_at DESC LIMIT 1) AS city_code,
                          (SELECT d.target_date FROM decisions d
                           WHERE d.ticker=p.ticker AND d.accepted=1
                           ORDER BY d.created_at DESC LIMIT 1) AS target_date,
                          (SELECT d.temp_type FROM decisions d
                           WHERE d.ticker=p.ticker AND d.accepted=1
                           ORDER BY d.created_at DESC LIMIT 1) AS temp_type
                   FROM positions p WHERE p.status='open' ORDER BY p.opened_at"""
            ).fetchall()
        return [dict(row) for row in rows]

    def open_cost_for_event(self, event_ticker: str) -> Decimal:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(total_cost_cc), 0) AS total FROM positions WHERE status='open' AND event_ticker=?",
                (event_ticker,),
            ).fetchone()
        return dollars(row["total"])

    def open_cost_for_target_date(self, target_date: str) -> Decimal:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(p.total_cost_cc), 0) AS total
                   FROM positions p
                   WHERE p.status='open'
                     AND (SELECT d.target_date FROM decisions d
                          WHERE d.ticker=p.ticker AND d.accepted=1
                          ORDER BY d.created_at DESC LIMIT 1)=?""",
                (target_date,),
            ).fetchone()
        return dollars(row["total"])
