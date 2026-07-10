# Build report

Build date: 2026-07-09/10 UTC

## Completed

- Rebuilt the project around a transactional SQLite ledger.
- Added deterministic calibrated probability generation.
- Added event-partition validation and normalization.
- Added NWS observed-extreme constraints.
- Added Kalshi binary order-book depth simulation.
- Added current centicent fee calculation.
- Added structural YES/NO strip arbitrage checks.
- Added integer expected-log event optimization.
- Added city-local automated scan windows.
- Added final-NWS-CLI-only idempotent settlement.
- Added a generated Markdown dashboard.
- Added legacy Markdown duplicate auditing.
- Added Raspberry Pi virtual-environment installer and systemd units.
- Preserved the four uploaded files under `legacy_reference/`.

## Validation performed

- Python source compiled successfully with `compileall`.
- Editable package installation succeeded with `pip install -e . --no-deps`.
- CLI help, demo, initialization, scheduled no-op, settlement no-op, and report generation were exercised.
- Automated tests: **12 passed**.

Test coverage includes:

- official fee formula precision,
- order-book complement mechanics,
- depth walking and fees,
- contract parsing,
- exhaustive partition checks,
- deterministic probabilities,
- same-day observed-temperature constraints,
- risk-cap enforcement,
- idempotent settlements,
- structural arbitrage,
- end-to-end offline demo.

## Not validated inside this build environment

The container did not have outbound DNS/network access, so live integration calls to NWS, Open-Meteo, and Kalshi could not be executed here. The public endpoint shapes and current fee/settlement assumptions were checked against official documentation, and the network adapters have retries and explicit errors, but the first Raspberry Pi shadow run should be treated as an integration test.

The full list of city-specific HIGH/LOW Kalshi series tickers was not present in the uploaded files. The new loader accepts the old YAML key names, so your existing `cities.yaml` can be copied over directly or its tickers can be pasted into `config/cities.yaml`.

## Live trading status

Live order submission is intentionally absent. This package is suitable for research, shadow decisions, and paper fills. An authenticated live executor should be a later, separately reviewed component after out-of-sample calibration and execution testing.
