# Kalshi Trading Strategies Guide

This guide details how to identify and execute profitable opportunities on Kalshi prediction markets using either **Guaranteed Arbitrage** or **Expected Value (+EV) / Mispricing** strategies, specifically tailored for a **$30.00 bankroll** and accounting for Kalshi's transaction fee structure.

---

## 1. The Critical Role of Transaction Fees on Kalshi

Before trading, we must factor in Kalshi's transaction fee model. If we do not, a mathematically perfect "arbitrage" on paper will actually result in a net loss.

### The Fee Formulas
Kalshi charges fees based on whether your order is a **Taker** (matches immediately against a resting order in the book) or a **Maker** (sits in the book as a limit order and waits to be filled):

*   **Taker Fee:**  
    $$\text{Fee} = \text{round\_up}(0.07 \times C \times P \times (1 - P))$$
*   **Maker Fee:**  
    $$\text{Fee} = \text{round\_up}(0.0175 \times C \times P \times (1 - P))$$

*Where:*
*   $C$ = Number of contracts.
*   $P$ = Price of the contract in dollars (e.g., 40 cents is $0.40$).
*   **Rounding:** Fees are rounded up **to the nearest cent per position** traded. This means there is a **minimum fee of $0.01 (1 cent)** for any position that gets executed.

---

### The Round-Up Drag (Why Arbitrage Fails for Small Budgets)
If you buy a 6-contract weather bundle, you are opening 6 separate positions. Because of the rounding rule, each position will incur a minimum fee of at least **$0.01**. 
*   **Minimum fee per bundle:** $0.01 \times 6 = \$0.06$ (6 cents).
*   **Arbitrage profit margin:** Typical weather arbitrages have a gross profit of only **$0.01 to $0.02** per bundle (buying the bundle for $0.98 or $0.99 and settling for $1.00).
*   **Net Profit/Loss:** 
    $$\text{Net} = \text{Gross Profit} - \text{Minimum Fee} = \$0.02 - \$0.06 = -\$0.04 \text{ (Loss of 4 cents per bundle!)}$$

> [!WARNING]
> Because of the $0.01 minimum fee per contract position, **low-margin arbitrage is mathematically impossible on small bankrolls**. The transaction fees will always exceed your gross profit.

#### Example: Denver Weather Event (`KXHIGHDEN-26JUN26`) at $C = 25$ Bundles
If you try to execute the Denver weather arbitrage with a $30 bankroll (buying 25 contract bundles):
*   **Gross Cost:** $25 \times \$0.98 = \$24.74$
*   **Gross Payout:** $25 \times \$1.00 = \$25.00$
*   **Gross Profit:** **+$0.26**
*   **Taker Fees:** 
    *   `>90` ($P=0.04$): $\text{round\_up}(0.07 \times 25 \times 0.04 \times 0.96) = \text{round\_up}(\$0.0672) = \$0.07$
    *   `89-90` ($P=0.20$): $\text{round\_up}(0.07 \times 25 \times 0.20 \times 0.80) = \text{round\_up}(\$0.28) = \$0.28$
    *   `87-88` ($P=0.41$): $\text{round\_up}(0.07 \times 25 \times 0.41 \times 0.59) = \text{round\_up}(\$0.423) = \$0.43$
    *   `85-86` ($P=0.20$): $\text{round\_up}(0.07 \times 25 \times 0.20 \times 0.80) = \text{round\_up}(\$0.28) = \$0.28$
    *   `83-84` ($P=0.10$): $\text{round\_up}(0.07 \times 25 \times 0.10 \times 0.90) = \text{round\_up}(\$0.1575) = \$0.16$
    *   `<83` ($P=0.03$): $\text{round\_up}(0.07 \times 25 \times 0.03 \times 0.97) = \text{round\_up}(\$0.0509) = \$0.06$
    *   **Total Taker Fees:** $0.07 + 0.28 + 0.43 + 0.28 + 0.16 + 0.06 = \mathbf{\$1.28}$
*   **Net Result (Taker):** $+\$0.26 - \$1.28 = \mathbf{-\$1.02}$ (Net Loss)
*   **Net Result (Maker):** If you execute all 6 as limit orders, the Maker fees total **$0.33**, which still results in a **-$0.07** net loss.

#### When does Arbitrage become profitable?
Arbitrage only becomes profitable at **large contract volumes** where the rounding fee no longer dominates, and only when executed as **Maker orders** (resting limits):
*   At $C = 1000$ bundles (capital of $980):
    *   Gross Profit: **+$20.00**
    *   Maker Fees: **$12.61** (no longer dominated by rounding)
    *   Net Profit: **+$7.39** (0.75% net risk-free return in 1 day)

---

## 2. Guaranteed Arbitrage (Multi-Outcome Bins)

Guaranteed arbitrage (or "arb") is a risk-free strategy that exploits price discrepancies in markets with mutually exclusive and exhaustive outcomes. 

### The Math
In a set of $N$ mutually exclusive outcomes where **exactly one** outcome must happen (e.g., the high temperature in a city must fall into one of several temperature ranges, or a sports team must win, lose, or tie):
* Let $P_i$ be the price (in dollars) of the `YES` contract for outcome $i$.
* If you buy exactly 1 `YES` contract for every possible outcome, your total cost is:
  $$\text{Total Cost} = \sum_{i=1}^N P_i$$
* Since exactly one outcome is guaranteed to happen, one of your contracts will resolve to `$1.00` and the remaining $N-1$ contracts will resolve to `$0.00`.
* Your payout is guaranteed to be exactly `$1.00`.
* If $\text{Total Cost} < \$1.00$, you lock in a guaranteed profit of:
  $$\text{Guaranteed Profit} = \$1.00 - \sum_{i=1}^N P_i$$

### Raw Weather Arbitrage Data (Pre-Fee Prices)
Here is the raw data we retrieved from Kalshi's order books. **Note that this does not factor in the minimum transaction fees which make small positions unprofitable**:

| Event & Tickers | Action | Bundles | Ask Prices (per contract) | Total Cost | Payout | Profit (ROI) |
| :--- | :--- | :---: | :--- | :---: | :---: | :---: |
| **Oklahoma City High Temp**<br>`KXHIGHTOKC-26JUN26` | Buy YES on all 6 bins | **4.01** | `>97`: $0.03<br>`96-97`: $0.07<br>`94-95`: $0.15<br>`92-93`: $0.27<br>`90-91`: $0.33<br>`<90`: $0.13 | **$3.93** | **$4.01** | **$0.08**<br>(2.04%) |
| **Denver High Temp**<br>`KXHIGHDEN-26JUN26` | Buy YES on all 6 bins | **25.00** | `>90`: $0.04<br>`89-90`: $0.20<br>`87-88`: $0.41<br>`85-86`: $0.20<br>`83-84`: $0.10<br>`<83`: $0.03 | **$24.74** | **$25.00** | **$0.26**<br>(1.05%) |
| **New Orleans High Temp**<br>`KXHIGHTNOLA-26JUN26` | Buy YES on all 6 bins | **1.34** | `>98`: $0.02<br>`97-98`: $0.03<br>`95-96`: $0.09<br>`93-94`: $0.51<br>`91-92`: $0.30<br>`<91`: $0.04 | **$1.33** | **$1.34** | **$0.01**<br>(1.01%) |

---

## 3. Expected Value (+EV) / Mispricing Strategies

Because transaction fees eat up low-margin arbitrages on small budgets, **the best way to make money on Kalshi with a $30 bankroll is directional +EV trading**.

### The EV Formula
$$\text{Expected Value (EV)} = (\text{True Probability} \times \text{Profit if YES wins}) - (\text{False Probability} \times \text{Cost of YES})$$

If the contract trades at price $P$ (cents) and your model indicates the true probability of occurrence is $p$:
* Cost of contract: $P$
* Payout if YES: $100$ (net profit $100 - P$)
* Payout if NO: $0$ (loss of $P$)
* $$\text{EV} = 100p - P$$

### How to Find +EV Opportunities with $30

#### A. Weather Ensemble Forecasting
Since weather contracts settle to integer values based on NWS Climatological Reports:
1. **The Edge:** Mainstream forecasts give a single number (e.g. 90°F). However, Meteorologists use **ensemble runs** (like the GFS or European ECMWF ensembles) which output 30+ scenarios.
2. **The Calculation:** If 75% of GFS ensemble runs show Denver's high temp will be $\ge 88^{\circ}\text{F}$, the true probability of that contract resolving YES is $0.75$.
3. **Buying the Edge:** If the Denver $\ge 88^{\circ}\text{F}$ contract is priced at **55 cents** on Kalshi:
   * **Gross EV:** $100 \times 0.75 - 55 = +20\text{ cents}$
   * **Fee (Taker):** $\text{round\_up}(0.07 \times 1 \times 0.55 \times 0.45) = \text{round\_up}(0.017) = \$0.02$
   * **Net EV:** $+18\text{ cents per contract}$
   With a $30 bankroll, you can buy 5 contracts of this single directional bet. If you win, you get $5.00. If you lose, you lose $2.75. Over 100 such bets, you will make substantial profits.

#### B. Economic Nowcasting
1. **The Edge:** The Cleveland Fed publishes a daily updated **Inflation Nowcasting model** for CPI.
2. **Execution:** If the nowcast shows a high probability of a certain inflation rate bin, and Kalshi's market price is lagging or mispricing it, you buy that bin. Because you are buying a single bin (rather than a 6-bin bundle), your transaction fees are minimal ($0.01 - $0.02), making it highly profitable.

---

## 4. Bankroll Management & Execution Tips

1. **Maximize Capital Velocity:** Avoid buying contracts that resolve in months. Prioritize **daily weather contracts** or **weekly economic events** so you can recycle your $30 bankroll frequently.
2. **Avoid Market Orders (Use Limits):** To avoid Taker fees (7%), always place **limit orders** (which carry a 1.75% Maker fee rate). This significantly increases your net EV.
3. **Use the Kelly Criterion for EV Bets:** Never put your entire $30 bankroll on a single +EV trade. For a typical 60/40 edge, a safe bet size is 5% to 10% of your bankroll ($1.50 to $3.00 per trade).
