from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import aiohttp

from .contracts import parse_contract_rule
from .domain import Market
from .orderbook import parse_orderbook


class KalshiPublicClient:
    """Read-only client. This project deliberately does not submit live orders."""

    def __init__(self, base_url: str, timeout_seconds: int = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "KalshiPublicClient":
        self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Use KalshiPublicClient as an async context manager")
        return self._session

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        backoff = 1.0
        for attempt in range(4):
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status in {429, 500, 502, 503, 504} and attempt < 3:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    response.raise_for_status()
                    return await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == 3:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
        raise RuntimeError("unreachable")

    async def list_markets(
        self,
        *,
        series_ticker: str | None = None,
        event_ticker: str | None = None,
        status: str = "open",
        limit: int = 1000,
    ) -> list[dict]:
        params: dict[str, Any] = {"status": status, "limit": limit, "mve_filter": "exclude"}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        result: list[dict] = []
        cursor = None
        while True:
            if cursor:
                params["cursor"] = cursor
            payload = await self._get("markets", params=params)
            result.extend(payload.get("markets", []))
            cursor = payload.get("cursor")
            if not cursor:
                break
        return result

    async def get_orderbook(self, ticker: str):
        payload = await self._get(f"markets/{ticker}/orderbook")
        return parse_orderbook(ticker, payload)

    async def get_orderbooks(self, tickers: list[str], concurrency: int = 4) -> dict[str, object]:
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch(ticker: str):
            async with semaphore:
                return ticker, await self.get_orderbook(ticker)

        pairs = await asyncio.gather(*(fetch(ticker) for ticker in tickers))
        return dict(pairs)

    async def get_market(self, ticker: str) -> dict:
        try:
            return (await self._get(f"markets/{ticker}"))["market"]
        except aiohttp.ClientResponseError as exc:
            if exc.status != 404:
                raise
            return (await self._get(f"historical/markets/{ticker}"))["market"]


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def market_from_payload(payload: dict) -> Market:
    title = payload.get("subtitle") or payload.get("title") or payload.get("yes_sub_title") or ""
    rule = parse_contract_rule(title)
    return Market(
        ticker=payload["ticker"],
        event_ticker=payload["event_ticker"],
        title=title,
        rule=rule,
        yes_bid=decimal_or_none(payload.get("yes_bid_dollars")),
        yes_ask=decimal_or_none(payload.get("yes_ask_dollars")),
        no_bid=decimal_or_none(payload.get("no_bid_dollars")),
        no_ask=decimal_or_none(payload.get("no_ask_dollars")),
        result=payload.get("result"),
    )
