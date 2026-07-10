# Kalshi Weather Lab

A **dry-run-first**, auditable weather-market research and paper-trading engine designed for a very small bankroll. It is a clean replacement for the previous Markdown-ledger bot.

> This repository does not submit live orders. It deliberately stops at market-data retrieval, decision generation, realistic taker-fill simulation, paper execution, and official settlement. Do not enable real-money execution until the strategy has passed a substantial out-of-sample shadow test.

## What is materially better

1. **SQLite is the only source of truth.** Cash, fills, positions, decisions, settlements, calibration residuals, and NAV snapshots are transactional. Markdown is generated output only.
2. **Settlement is idempotent.** A ticker/side can be settled only once, so duplicate dashboard rows cannot create duplicate payouts.
3. **No forced one-contract trades.** A zero size remains zero.
4. **Portfolio decisions are made at the event level.** Every possible temperature-bracket outcome is evaluated before a combination of trades is accepted.
5. **Exact order-book direction is respected.** Kalshi order books expose YES bids and NO bids. A YES ask is inferred from the opposing NO bid, and vice versa.
6. **Depth and slippage are modeled.** Taker simulation walks price levels and rejects quantities that cannot actually be filled.
7. **Current fees are calculated at centicent precision.** The general July 7, 2026 formula is configurable and applied by price level.
8. **Probabilities are deterministic.** The engine no longer creates 10,000 random resamples and treats them as new information.
9. **Model uncertainty is explicit.** Each forecast member is convolved with a historical or conservative fallback error distribution. Correlated model members receive a capped effective sample size.
10. **All bracket probabilities are normalized together.** A mutually exclusive and exhaustive event must sum to exactly 100%.
11. **Observed station temperatures impose hard constraints.** A final high cannot finish below the high already recorded; a final low cannot finish above the low already recorded.
12. **Settlement waits for the final NWS Daily Climate Report.** Preliminary hourly observations are never used to close paper positions.
13. **Structural arbitrage is checked separately.** Complete YES and NO strips are evaluated after fees and available depth.
14. **Every decision is logged, including rejections.** This makes calibration and out-of-sample testing possible.
15. **Scheduling is city-local.** A frequent systemd timer can run the program, while local windows decide which HIGH or LOW event is eligible.

## Architecture

```text
Kalshi public markets + order books       Open-Meteo ensembles + HRRR
                  |                                  |
                  v                                  v
        contract partition parser          calibrated predictive mixture
                  |                                  |
                  +-------------> event probability vector
                                      |
NWS observed extreme ---------------------+
                                      |
                       conservative edge calculation
                                      |
                  structural-arbitrage scanner
                                      |
              integer expected-log event optimizer
                                      |
                  realistic paper fill simulator
                                      |
                         SQLite ledger
                         /           \
             final NWS CLI settlement  Markdown report
```

## Quick start on Raspberry Pi

```bash
cd ~/SDF
unzip kalshi_weather_lab.zip
cd kalshi_weather_lab
bash scripts/install_pi.sh
```

The installer creates a virtual environment, installs the package, initializes a $15 paper ledger, and runs the test suite. This avoids modifying Raspberry Pi OS's externally managed Python environment.

Edit `config/cities.yaml` and copy the HIGH/LOW series tickers from your existing city configuration. The loader accepts both the new names and your legacy keys:

```yaml
series_high: KXHIGHNY
series_low: YOUR_LOW_SERIES
```

or:

```yaml
kalshi_market_prefix: KXHIGHNY
kalshi_market_prefix_low: YOUR_LOW_SERIES
```

## Core commands

```bash
# Deterministic offline demonstration
.venv/bin/kalshi-weather demo

# Initialize or open the paper ledger
.venv/bin/kalshi-weather init --bankroll 15.00

# Scan one event without entering a paper position
.venv/bin/kalshi-weather scan --city NY --type HIGH --date 2026-07-10

# Scan and execute only the optimizer-selected paper fills
.venv/bin/kalshi-weather scan --city NY --type HIGH --date 2026-07-10 --paper-execute

# Run all currently eligible city-local scan windows
.venv/bin/kalshi-weather run-once

# Attempt settlement; positions remain open until a final NWS CLI exists
.venv/bin/kalshi-weather settle-open

# Rebuild the dashboard from SQLite
.venv/bin/kalshi-weather report

# Inspect duplicate rows in the old Markdown ledger without importing them
.venv/bin/kalshi-weather audit-legacy ../theoretical_edges.md
```

## Recommended test sequence

### Phase 1 — clean shadow data

Run `run-once` without `--paper-execute` every 30 minutes. Keep all decisions, even rejected ones. Accumulate at least several hundred settled event snapshots across cities, forecast horizons, and weather regimes.

Evaluate:

- Brier score and log loss.
- Reliability by 5% or 10% probability bucket.
- Calibration slope/intercept.
- Realized EV after exact entry fees.
- Price movement after the decision timestamp.
- Performance by city, station, HIGH/LOW, lead bucket, and model availability.

### Phase 2 — paper fills

Enable `--paper-execute`. Do not reset the database after losses. Review:

- worst drawdown,
- fraction of signals rejected by the optimizer,
- whether estimated edges survive fees and displayed depth,
- whether results remain positive under a one-tick adverse-price stress,
- whether the uncertainty penalty is large enough.

### Phase 3 — micro-live, only after validation

The code intentionally has no live-order endpoint. A future authenticated execution adapter should require:

- an explicit config flag,
- a second manual confirmation flag,
- a hard dollar-loss circuit breaker,
- order and fill reconciliation from Kalshi,
- a kill switch,
- maker orders modeled separately from taker orders,
- API-key storage outside the repository.

## $15 bankroll defaults

Defaults are intentionally restrictive:

- maximum event loss: 5% of the original bankroll,
- maximum daily loss budget: 10%,
- one contract per market,
- at most three positions in one event,
- minimum conservative dollar EV: 3 cents,
- minimum return on all-in cost: 8%.

An indivisible contract that exceeds the event-loss budget receives a position size of zero. This is correct behavior, even when the raw EV is positive.

## Probability model

The engine does not randomly duplicate forecast members. For each model:

1. Daily maximum or minimum is extracted for each real ensemble member.
2. A residual error distribution is selected by city, HIGH/LOW, model, and lead-time bucket.
3. When history is insufficient, a conservative fallback standard deviation is used.
4. Each member contributes a continuous normal probability to every integer settlement bracket.
5. Model weights are normalized only across models actually available.
6. Same-day station observations remove physically impossible outcomes.
7. The event vector is normalized to 100%.
8. A calibration and effective-sample-size penalty produces a conservative tradable probability.

Historical residuals are stored in the same SQLite database. The minimum sample count is deliberately high enough to avoid treating a few recent days as stable model skill.

## Event-level optimizer

The optimizer evaluates terminal wealth under every mutually exclusive bracket. It adds an integer contract only when all of these remain true:

- expected log wealth improves,
- worst-case event loss remains under the cap,
- cash stays positive in every outcome,
- maximum contracts per market is respected,
- maximum simultaneous positions is respected.

This is superior to independently applying Kelly to adjacent YES/NO contracts because adjacent temperature contracts share the same settlement outcome.

## Accounting definitions

- **Cash:** uncommitted simulated dollars.
- **Cost basis:** entry notional plus paid entry fees.
- **Liquidation NAV:** cash plus proceeds available from current executable bids after exit fees.
- **Model value:** cash plus expected position value using calibrated probabilities.
- **Realized P/L:** settlement credits minus settled cost basis.

The generated basic report shows cash, open cost basis, and realized P/L. It intentionally does not label cost basis as NAV. A live market-data reporting pass can add liquidation and model values.

## Automation

A systemd service and timer are included in `systemd/`. The timer runs every 30 minutes; the application checks each city's local HIGH/LOW window before scanning.

```bash
sudo cp systemd/kalshi-weather-run.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kalshi-weather-run.timer
systemctl list-timers | grep kalshi-weather
```

Adjust `/home/pi/SDF/kalshi_weather_lab` in the service file if your installation path differs.

## Important limitations

- Open-Meteo is a convenient model-data transport, not the official settlement source.
- Forecast-model issue time should eventually be persisted and validated more rigorously.
- The fallback error distributions are conservative placeholders until enough residuals exist.
- The public client currently requests one order book per ticker for compatibility. A batch endpoint or authenticated WebSocket can reduce latency later.
- Maker-fill simulation is deliberately not enabled. A resting order cannot be assumed filled merely because the market touches its price.
- Series tickers must be copied from your current configuration because they can change and were not included in the uploaded files.
- The parser refuses a market set that is overlapping, gapped, or not open-ended at both tails.

## Official assumptions used by this version

Checked July 9, 2026:

- Public market data base URL: `https://external-api.kalshi.com/trade-api/v2`
- Order books contain YES bids and NO bids; opposite-side asks are complements.
- General taker formula: `M × 0.07 × C × P × (1-P)` with centicent rounding.
- General maker formula: `M × 0.0175 × C × P × (1-P)`; the default maker multiplier is zero unless a listed series overrides it.
- There is no settlement fee.
- Weather contracts resolve from the final NWS Daily Climate Report, typically the following morning.

Sources:

- https://docs.kalshi.com/getting_started/quick_start_market_data
- https://docs.kalshi.com/api-reference/market/get-market-orderbook
- https://kalshi.com/docs/kalshi-fee-schedule.pdf
- https://help.kalshi.com/en/articles/13823837-weather-markets

## Tests

```bash
.venv/bin/pytest
```

The included tests cover fee precision, binary order-book complements, depth walking, contract parsing, exhaustive partitions, deterministic probabilities, observed-temperature constraints, risk caps, settlement idempotency, structural arbitrage, and the offline demo.
