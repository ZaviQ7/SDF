# Technical Workflow & Forecasting Architecture: Kalshi Weather Bot

This document provides a comprehensive technical breakdown of the end-to-end forecasting, risk-sizing, and execution workflow of the Kalshi Weather Bot.

---

## 1. Model Data Ingestion & API Integration
To build a reliable probability distribution, the bot ingests meteorological forecast data from multiple physical weather models via a high-availability, rate-limit-friendly Open-Meteo API gateway. 

### Why These Specific Models?
No single weather model is perfect. By combining global synoptic ensembles with short-range high-resolution convective models, the bot captures both large-scale air mass movement and localized thermodynamic boundary layer changes.

| Model | Grid Spacing | Setup Type | Best Used For |
| :--- | :--- | :--- | :--- |
| **ECMWF Ensemble (Euro)** | 9 km | 50 members + control | Medium-range baseline. The gold standard for global pressure systems and air mass transitions. |
| **GFS Ensemble (US)** | 22 km | 30 members + control | Medium-range physics. High variance in temperature predictions, making it excellent for tail-risk analysis. |
| **ICON Ensemble (Germany)** | 40 km | 40 members | Alternative global physics model using non-hydrostatic equations on an icosahedral grid. |
| **GEM Ensemble (Canada)** | 25 km | 20 members | Polar air mass physics. Prevents GFS/Euro duopoly bias. |
| **HRRR (US - Deterministic)** | 3 km | Hourly single-run | Short-range convective-allowing. Ingests active radar and satellite data. Crucial for detecting afternoon storm cooling. |

---

## 2. Dynamic Mixture Weighting & Lead-Time Scaling
As a target date approaches, the predictability of local weather shifts. The bot handles this dynamically by running a weighted mixture model.

### Base Weights (Long-Range)
When lead time is long ($> 48\text{ hours}$), the bot relies entirely on the global ensembles:
*   **ECMWF Weight:** $40\%$
*   **GFS Weight:** $35\%$
*   **ICON Weight:** $15\%$
*   **GEM Weight:** $10\%$

### HRRR Short-Range Injection
The HRRR model is highly accurate but only runs out to 48 hours. The bot dynamically scales the HRRR weight based on the parameter `hours_to_target`:

```python
if has_hrrr and hours_to_target > 0:
    if hours_to_target <= 12:    hrrr_w = 0.45
    elif hours_to_target <= 24:  hrrr_w = 0.30
    elif hours_to_target <= 36:  hrrr_w = 0.15
    elif hours_to_target <= 48:  hrrr_w = 0.05
    else:                        hrrr_w = 0.0
```

When the HRRR weight ($w_{\text{hrrr}}$) is active ($> 0$), the global models' weights are scaled down proportionally:
$$\text{Weight}_{\text{model, adjusted}} = \text{Weight}_{\text{model, base}} \times (1.0 - w_{\text{hrrr}})$$

### Why Scale to 11:59:59 PM Local Time?
The `hours_to_target` calculation measures time remaining until **11:59:59 PM local time** of the target date, rather than the typical 3:00 PM–4:00 PM afternoon high temperature peak.
*   **Contract Rules:** Kalshi daily high/low contracts settle strictly on the maximum/minimum temperature recorded during the entire calendar day (from 12:00 AM to 11:59 PM).
*   **Risk Mitigation:** Late-day storm fronts or warm air advection can push the daily high/low outside the typical afternoon window. Aligning the calculation with the midnight cutoff matches the true legal settlement span of the contracts.

---

## 3. MOS (Model Output Statistics) Rolling Bias Correction
Physical models suffer from systematic localized biases due to station altitude discrepancies, urban heat island effects, or grid-resolution limitations. The bot implements a rolling Model Output Statistics (MOS) window to correct these.

```
                  ┌──────────────────────────────┐
                  │   NWS Station Observations   │
                  └──────────────┬───────────────┘
                                 │ (CLI Report / Hourly)
                                 ▼
┌──────────────────┐      ┌──────────────┐      ┌─────────────────────────┐
│ forecasts_log    ├─────►│ Bias Tracker ├─────►│ data/bias_offsets.json │
│ (14-day history) │      └──────────────┘      └────────────┬────────────┘
└──────────────────┘                                         │
                                                             │ (Adjusted offset)
                                                             ▼
                                                ┌─────────────────────────┐
                                                │   process_ensembles()   │
                                                └─────────────────────────┘
```

1.  **Ingestion:** For each active station, the tracker pulls yesterday's actual observed temperatures (first attempting to parse the NWS Climate CLI Report, falling back to hourly observations if CLI is delayed).
2.  **Tracking:** Settled forecast means are compared against NWS actual values in `forecasts_log.json`.
3.  **Rolling Bias Window:** For each station and temperature type (High/Low), the tracker extracts the last **14 days** of forecasts. It requires a **minimum of 3 days** of matching historical data to avoid reacting to one-off anomalies.
4.  **Offset Calculation:**
    $$\text{Bias Offset} = \frac{1}{N} \sum_{i=1}^{N} \left( \text{Actual Temp}_{i} - \text{Forecast Mean}_{i} \right)$$
    This offset (e.g. $+3.75^\circ\text{F}$ for Miami High) is added to all raw ensemble member predictions during the next run, dynamically adjusting the forecast distribution.

---

## 4. Bootstrapping & Monte Carlo Mixture Simulation
Once the weights are normalized and the bias offsets applied, the bot runs a Monte Carlo mixture simulation to build the probability distribution:

1.  For each ensemble member of GFS, ECMWF, GEM, and ICON, the daily high/low is extracted and adjusted:
    $$T_{\text{adjusted}} = T_{\text{raw}} + \text{Bias Offset}$$
2.  The bot resamples **10,000 simulated values** with replacement from the active models, drawn according to their active normalized mixture weights.
3.  The model probability of a contract landing in any range $[T_{\text{min}}, T_{\text{max}}]$ (e.g., $91^\circ\text{F}$ to $92^\circ\text{F}$ matches a Kalshi range of $[90.5^\circ\text{F}, 92.5^\circ\text{F}]$ due to rounding) is calculated as:
    $$P_{\text{model}} = \frac{\text{Count of simulated values inside } [T_{\text{min}}, T_{\text{max}}]}{10,000}$$

---

## 5. Kalshi Integration, Edge Math, & Risk Sizing

### Retrieving Kalshi Data
The bot calls `/v2/markets/{ticker}/orderbook` to fetch the live bid-ask spreads for the target contracts.

### PnL Math & Fee Inclusion
Kalshi implements a Maker fee of $1.75\%$ of the contract premium multiplied by the remaining premium:
$$\text{Maker Fee} = 0.0175 \times \text{Price} \times (1.0 - \text{Price})$$
$$\text{Cost of Entry} = \text{Price} + \text{Maker Fee}$$

Expected Value (EV) is then calculated as:
$$\text{Net EV} = \frac{P_{\text{model}}}{\text{Cost of Entry}} - 1.0$$

### Edge Filtering & Capital Allocation
A contract is flagged as an active trade opportunity if it meets the following conservative thresholds:
1.  **True Probability ($P_{\text{model}}$):** $> 54\%$
2.  **Net EV:** $> +15\%$

Position sizing is determined using a **Fractional Kelly Criterion** ($1/4$ Kelly sizing) to prevent over-leverage:
$$\text{Full Kelly} = \frac{P_{\text{model}} - \text{Cost of Entry}}{1.0 - \text{Cost of Entry}}$$
$$\text{Suggested Size} = \max\left(0, \frac{\text{Full Kelly}}{4.0}\right)$$

This suggested size is multiplied by your account bankroll and capped at a maximum cash allowed exposure per trade (default: $\$9.75$, translating to $10$ to $25$ contracts depending on price) to maintain strict risk parameters.

---

## 6. Same-Day Settle & Pruning Execution Flow
The bot operates in two distinct execution modes:

```
                  ┌──────────────────────────────┐
                  │    Trigger update_edges.py   │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                    Query NWS CLI / Actuals
                                 │
                                 ▼
                     Are there "Open" trades?
                                 │
                   ┌─────────────┴─────────────┐
                   ▼ (Yes)                     ▼ (No)
        Target Date < Today?             Skip Settlement
        OR Same-Day Late-Hour?
        (After 9:00 PM local time)
                   │
         ┌─────────┴─────────┐
         ▼ (Yes)             ▼ (No)
    Verify & Settle      Skip Settlement
         │
         ▼
    Prune Active Trades
    (Remove if Prob <= 53% or EV <= 0%
    due to live model changes)
         │
         ▼
    Scan New Edges for Tomorrow
```
*   **Active Pruning:** As new weather observations and model cycles update throughout the morning, if a logged active play's probability drops below $53\%$ or its EV becomes negative, it is immediately pruned from [theoretical_edges.md](file:///C:/Users/zavie/Downloads/Kalshi/theoretical_edges.md) to ensure only high-conviction plays remain live.
