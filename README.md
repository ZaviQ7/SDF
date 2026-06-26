# Steak Dinner Fund (SDF)

**Steak Dinner Fund (SDF)** is an algorithmic trading, market analysis, and scraping toolkit designed to systematically identify, calculate, and exploit mathematical edges across prediction markets, sportsbooks, and financial platforms. 

The ultimate goal of SDF is to grow a modest trading bankroll into a "steak dinner" (and beyond) by strictly trading positive Expected Value (+EV) and risk-free arbitrage (arb) opportunities.

---

## 🎯 Project Overview

Rather than betting on gut feelings or sentiment, SDF treats markets as mathematical puzzles. The codebase contains scanners and calculators that cross-reference real-world data feeds (e.g., weather forecasts, economic nowcasts, sports statistics) with market prices to find discrepancies and mispricings.

### Target Platforms
- **Prediction Markets**: Kalshi, Polymarket, PredictIt
- **Sportsbooks**: Major sportsbooks offering player props, game totals, and derivatives
- **Economic Futures**: Event contracts on inflation, employment, and interest rates

---

## 🛠 Current Tooling

The current suite of tools in the workspace focuses on weather market inefficiencies:

1. **[weather_ev_scanner.py](file:///c:/Users/zavie/Downloads/Kalshi/weather_ev_scanner.py)**
   - Queries real-time National Weather Service (NWS) forecasts using latitude/longitude.
   - Models temperature outcome distributions using a normal probability density function ($T \sim \mathcal{N}(\mu, \sigma^2)$) with continuity corrections.
   - Identifies contracts on Kalshi with $>5\%$ Net Expected Value (+EV) after accounting for Maker fees.

2. **[weather_arb_calculator.py](file:///c:/Users/zavie/Downloads/Kalshi/weather_arb_calculator.py)**
   - Scans Kalshi order books to evaluate liquidity and depth for multi-outcome arbitrage opportunities.

3. **[arbitrage_scanner.py](file:///c:/Users/zavie/Downloads/Kalshi/scratch/arbitrage_scanner.py)**
   - Generates candidate arbitrage groups across standard Kalshi markets by checking if the sum of contract prices is $< 1.00$.

---

## 📐 Core Trading Principles

SDF operates under strict mathematical constraints to protect capital and maximize growth:

### 1. The Expected Value (+EV) Formula
We only take positions where the estimated win probability ($P_{\text{win}}$) multiplied by the payout exceeds the entry price ($P_{\text{ask}}$):
$$\text{Net EV} = (P_{\text{win}} \times \$1.00) - P_{\text{ask}} - \text{Fees}$$

### 2. Bankroll Management
We use a conservative **Quarter Kelly Criterion** to size directional trades. This manages variance and prevents ruin while compounding edge:
$$f^* = \frac{p(b + 1) - 1}{b}$$
*Where $p$ is the true probability, $b$ is the net decimal odds, and we allocate $0.25 \times f^*$ of the bankroll.*

### 3. Fee Awareness
Kalshi Maker fees (1.75%) and contract rounding structures are hardcoded into our scanners to prevent trading "ghost edges" where fees eat up the entire margin.
