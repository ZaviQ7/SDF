# Steak Dinner Fund (SDF)

**Steak Dinner Fund (SDF)** is an algorithmic weather trading framework designed to systematically identify, calculate, and exploit mathematical edges in prediction markets.

The core of the repository is a Kalshi weather trading bot that pools meteorological ensemble runs, applies bias correction, shifts the distributions using real-time NWS/HRRR forecasts, and logs optimal (+EV) trading opportunities.

---

## 📂 Repository Structure

The workspace is organized as follows:

*   **[.github/workflows/weather_bot.yml](file:///.github/workflows/weather_bot.yml)**: The GitHub Actions automation script that runs the bot on a schedule (10:00 AM & 11:00 PM EDT) and commits updates back to Git.
*   **[theoretical_edges.md](file:///theoretical_edges.md)**: The tracking log and dashboard displaying the live running performance summary, daily PnL history, active weather trades targeting tomorrow, and settled outcomes.
*   **[kalshi_weather_bot/](file:///kalshi_weather_bot)**: The core weather bot package containing:
    *   **[update_edges.py](file:///kalshi_weather_bot/update_edges.py)**: The main automation script that runs the forecast model, updates open trades, queries actual observations to auto-settle expired trades, and posts a report to Discord.
    *   **[scan_once.py](file:///kalshi_weather_bot/scan_once.py)**: A terminal-only tool to run a quick live scan and output a clean table of current +EV plays.
    *   **[main.py](file:///kalshi_weather_bot/main.py)**: Ingests forecasts and starts the dashboard server.
    *   **[config/](file:///kalshi_weather_bot/config)**: YAML configuration files for settings (bet sizing, API endpoints) and active cities.
    *   **[data/historical/](file:///kalshi_weather_bot/data/historical)**: Local JSON database tracking historical forecast distributions (`forecasts_log.json`) and calculated rolling bias offsets (`bias_offsets.json`).
    *   **[src/](file:///kalshi_weather_bot/src)**: Source package containing data downloaders (GFS, ECMWF, HRRR), probability calculators, risk management (Quarter-Kelly position sizing), and utilities.

---

## 📐 Core Trading Principles

SDF operates under strict mathematical constraints to protect capital and maximize growth:

### 1. Expected Value (+EV) & Fee Awareness
We only take positions where the estimated win probability ($P_{\text{win}}$) multiplied by the payout exceeds the entry price ($P_{\text{ask}}$), after incorporating Maker transaction fees (1.75%):
$$\text{Net EV} = (P_{\text{win}} \times \$1.00) - P_{\text{ask}} - \text{Maker Fees}$$

We apply a strict **$>53\%$ true probability** threshold on all logged trades to avoid high-variance tail events on a small bankroll.

### 2. Distribution Shift Modeling
We pool **82 ensemble runs** (31 GFS + 51 ECMWF) to establish a baseline distribution, apply a 14-day rolling MOS bias-correction, and shift the mean by **40%** of the delta between the latest high-resolution HRRR hourly grids and the ensemble average:
$$\text{Shifted Temp} = T_{\text{ensemble}} + \text{MOS Bias} + 0.4 \times (T_{\text{HRRR}} - T_{\text{mean}})$$

### 3. Bankroll Sizing
We size all suggested trades using a conservative **Quarter-Kelly Criterion** to control variance and protect the $30.00 bankroll while ensuring steady compounding.

---

## 🚀 How to Run the Bot

### Run a Local Live Scan
To scan the books right now and output a live terminal report of all +EV opportunities:
```bash
cd kalshi_weather_bot
py scan_once.py
```

### Run the Main Sync & Settle Script
To settle yesterday's trades, refresh active edges, and push updates:
```bash
cd kalshi_weather_bot
py update_edges.py
```
*(Optional: Set the `DISCORD_WEBHOOK_URL` environment variable to automatically post the report to your Discord server.)*

