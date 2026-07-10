# Official API and market-rule notes

Last checked: 2026-07-09.

## Market data

Kalshi documents unauthenticated public market data under:

`https://external-api.kalshi.com/trade-api/v2`

The client uses:

- `GET /markets?series_ticker=...&status=open`
- `GET /markets/{ticker}`
- `GET /markets/{ticker}/orderbook`

The order-book response contains bid levels for YES and NO. It does not need separate asks because a YES bid at `x` is a NO ask at `1-x`, and vice versa.

## Fees

The fee engine follows the schedule effective July 7, 2026:

- general taker: `round_up(M × 0.07 × C × P × (1-P))`
- maker: `round_up(M × 0.0175 × C × P × (1-P))`
- round-up precision: centicent (`$0.0001`)
- no settlement fee

The general maker multiplier is zero unless a series appears in the schedule with another multiplier. This is configurable rather than assumed permanent.

## Weather settlement

Weather contracts use the final NWS Daily Climate Report, typically released the following morning. The code therefore does not settle from hourly observations. During daylight saving time, the climate report's local-standard-time convention can extend the high-temperature reporting window into the following daylight-time calendar date.

## Revalidation requirement

Before enabling any future live executor, re-check:

- API base URL and schemas,
- fee formula and series-specific multipliers,
- exact event settlement source and rule text,
- authentication/signing requirements,
- rate limits and WebSocket behavior.
