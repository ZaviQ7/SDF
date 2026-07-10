# Detailed comparison with the uploaded version

This document explains exactly what changed and why the replacement is safer and more statistically honest.

## 1. Markdown portfolio state → transactional SQLite ledger

### Current behavior

The uploaded updater parses `theoretical_edges.md` to discover positions and uses a separate JSON file for cash. Open exposure is reconstructed from formatted text.

### Replacement

The database stores:

- account cash,
- every decision,
- every fill,
- aggregate open positions,
- official settlements,
- model residuals,
- NAV snapshots.

A fill, cash debit, and position update happen in one SQLite transaction. Settlement has a unique `(ticker, side)` constraint and returns without changing cash when called twice.

### Why better

There is no split-brain portfolio state, Markdown formatting cannot alter balances, and duplicated rows cannot generate duplicate payouts.

## 2. Forced minimum trade → hard zero

### Current behavior

`size if size > 0 else 1` converts every rejected size into one contract.

### Replacement

Only trades explicitly returned by the optimizer are paper-filled. No selected trade means no fill.

### Why better

Risk rules are enforceable. An expensive contract can correctly be positive EV but untradeable for a $15 account.

## 3. Independent candidate sizing → event scenario optimization

### Current behavior

Each edge is sized with current exposure passed as zero. Adjacent NO and YES positions are tagged as correlated after selection, but they are not jointly optimized over the actual temperature outcomes.

### Replacement

Markets are first verified as one exhaustive, non-overlapping partition. The optimizer computes terminal wealth for every bracket outcome and greedily adds only integer contracts that improve expected log wealth while respecting a worst-case event loss.

### Why better

Temperature brackets are mutually exclusive, not independent. The new method sees offsetting and compounding payouts exactly rather than applying an approximate correlation discount.

## 4. Synthetic resampling → deterministic probability integration

### Current behavior

Forecast members are randomly sampled with replacement until 10,000 values exist. HRRR is converted into 50 random normal draws. Repeated runs can produce different probabilities.

### Replacement

Each real member contributes its weight directly. Uncertainty is integrated analytically through a normal CDF. No random seed is necessary because no Monte Carlo sampling is performed.

### Why better

The output is reproducible, and duplicating a member no longer pretends to add information.

## 5. Raw member frequency → calibrated forecast-error model

### Current behavior

The empirical fraction of rounded pooled samples is treated as the outcome probability, with a 1%/99% clamp.

### Replacement

Residual distributions are keyed by city, HIGH/LOW, model, and lead bucket. Robust median bias and median-absolute-deviation scale are used after enough samples exist. Conservative fallback errors apply before that point. Effective sample size is capped to acknowledge within-model dependence.

### Why better

Forecast spread and forecast skill are not the same thing. Historical out-of-sample errors are the proper source of probability calibration.

## 6. Independent bracket calculations → one normalized event vector

### Current behavior

Each market probability is calculated separately. There is no validation that all contracts cover every integer outcome exactly once.

### Replacement

Rules are parsed into inclusive integer intervals. The scanner rejects gaps, overlaps, or missing tail brackets, then normalizes the full event probability vector to exactly one.

### Why better

The same temperature cannot accidentally carry probability in two brackets, and probability cannot disappear between brackets.

## 7. Forecast-only same-day model → observed-extreme constraints

### Current behavior

Same-day HIGH/LOW probabilities can remain on outcomes already made impossible by station observations.

### Replacement

The NWS station's running extreme is fetched before modeling. Outcomes below an already observed high, or above an already observed low, are assigned zero probability.

### Why better

This incorporates the strongest same-day information as a physical constraint rather than another weak model feature.

## 8. Price summary assumptions → bid-derived depth simulation

### Current behavior

The updater appears to use a market-level entry price and maker-fee helper without proving whether the simulated order crossed the spread or rested.

### Replacement

The order-book module uses Kalshi's binary complement relationship:

- buy YES asks come from NO bids,
- buy NO asks come from YES bids.

It walks every required price level and rejects insufficient depth.

### Why better

The simulated fill is executable at the captured book, not merely available somewhere in the market summary.

## 9. Approximate fee handling → configurable centicent fee engine

### Current behavior

The fee helper was not included, so its exact treatment could not be verified. The calling code labels entries as maker-fee calculations even when using ask-like prices.

### Replacement

Taker and maker roles are distinct. The current general formulas are implemented at $0.0001 precision and fees are calculated at each consumed level. Maker multiplier defaults to zero unless configured otherwise.

### Why better

Small-account edge is highly fee-sensitive. A few tenths of a cent can change whether a one-contract trade is positive EV.

## 10. 9 PM and hourly fallback settlement → final-CLI-only settlement

### Current behavior

Positions may settle after 9 PM local time, and hourly observations can be used when a final climate report is unavailable.

### Replacement

The settlement job does nothing until the matching final NWS CLI report exists. It then obtains the market's current rule text, evaluates the rounded official temperature, and settles once.

### Why better

The paper ledger follows the same official source hierarchy as the contract rather than closing on preliminary data.

## 11. Eastern-time global gating → city-local windows

### Current behavior

Global `current_hour_edt` and `today_str` variables govern cities in every time zone.

### Replacement

A frequent scheduler checks every city in its own IANA timezone. HIGH and LOW windows are configurable.

### Why better

Seattle and Phoenix are no longer treated as though their weather day is in New York.

## 12. Hidden rejected opportunities → full decision log

### Current behavior

The dashboard primarily contains trades that were opened.

### Replacement

Every qualifying edge is recorded with raw and conservative probabilities, price, fee, EV, acceptance status, reason, and optimizer outcome wealth.

### Why better

You can evaluate selection bias, missed opportunities, calibration, and whether the risk manager improves or harms results.

## 13. Cost-basis NAV → explicit accounting labels

### Current behavior

Cash plus original open cost is displayed as NAV.

### Replacement

The base report calls it open cost basis. The database supports separate liquidation and model-value snapshots.

### Why better

A 40-cent contract that can currently be sold for 10 cents is not worth 40 cents merely because that was its purchase price.

## 14. One blended strategy → separate structural and statistical engines

### Current behavior

All opportunities are forecast edges.

### Replacement

Complete YES and NO strips are evaluated independently for guaranteed payout after fees and available depth. Statistical positions go through calibrated probability and expected-log selection.

### Why better

A genuine price inconsistency is conceptually different from taking model risk and should be monitored, sized, and reported separately.

## 15. PEP 668 system installs → isolated virtual environment

### Current behavior

Packages are installed system-wide with `--break-system-packages`.

### Replacement

`scripts/install_pi.sh` creates `.venv` and installs the project there.

### Why better

It avoids corrupting the Raspberry Pi OS Python installation and makes dependency versions reproducible.

## What was preserved

- Raspberry Pi deployment.
- Dry-run-first workflow.
- Open-Meteo ensemble and HRRR retrieval.
- NWS station observations.
- City-level model weighting with higher near-term HRRR influence.
- Bias correction as a concept, upgraded to a robust residual-calibration system.
- Markdown dashboard output, but only as a view.
- Compatibility with your old city YAML key names.

## What still needs your existing repository

The uploaded subset did not include:

- actual city series tickers,
- your Kalshi client implementation,
- NBM text-card client,
- current residual/bias history,
- existing simulated ledger and dashboard,
- `risk_manager.py`, `edge_detector.py`, or fee helper.

The replacement does not depend on those missing modules, but you should copy your real series tickers into `config/cities.yaml`. NBM can later be added as another calibrated forecast component rather than being given unverified weight.
