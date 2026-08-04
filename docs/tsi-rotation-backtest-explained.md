# TSI Rotation Backtest: Detailed Explanation

## Purpose

This document explains exactly what scripts/backtest_tsi_rotation.py does, step by step, so results can be reviewed and challenged in a later session.

The script backtests a weekly momentum-rotation strategy based on TSI (True Strength Index):

- rank the universe by TSI once per week
- keep a fixed number of holdings (default 15)
- use an exit threshold rank (default 30)
- keep surviving holdings unchanged and only rotate exits into new entries
- track transactions and summary performance statistics

## High-level strategy logic

At each weekly trade cycle:

1. Compute/lookup each symbol's latest TSI value on or before the signal day.
2. Rank all available symbols by TSI descending.
3. Keep currently-held symbols only if their rank is less than or equal to the exit rank threshold.
4. Fill remaining slots up to top_n with the highest-ranked symbols not already kept.
5. Sell dropped holdings and use available cash to buy only the new entrants.
6. Record BUY/SELL transactions and realized SELL PnL percentages.

This creates hysteresis:

- enter from the top list (top_n)
- do not exit immediately unless a held name drops below exit_rank

## Data sources and universe construction

## Universe source order

When no explicit ticker list is supplied, the script resolves the index universe like this:

1. Wikipedia table parse (Nasdaq-100 page)
2. Fallback to FinHub API if Wikipedia fetch/parse fails

For the current setup, FinHub fallback is often used in practice due Wikipedia table changes or access restrictions.

## Symbol names

The script also keeps a symbol-to-company-name mapping for transaction export:

- from Wikipedia row labels when available
- from FinHub index member names when using fallback

## Price data

Price history is fetched via yfinance in chunks (default chunk size: 20 symbols), with adjusted prices enabled:

- auto_adjust=True
- OHLCV rows requiring Open/High/Low/Close are kept
- symbols with missing or empty history are skipped
- symbols with fewer than min_bars (default 180) are dropped

## Important symbol normalization

Before yfinance download:

- slash and dot are replaced by dash
- example: BRK.B -> BRK-B

This improves yfinance compatibility for class-share symbols.

## Trading calendar and weekly timing

The script builds a combined trading calendar from all downloaded symbol dates.

Default schedule settings:

- signal weekday: Wednesday
- trade weekday: Thursday

For each scheduled trade week:

- signal cutoff is trade weekday minus one calendar day
- preferred signal date is the latest date in the calendar matching signal weekday and <= cutoff
- if none exists, fallback is latest available date <= cutoff

Then execution date is selected by taking the next trading date strictly greater than the scheduled trade weekday.

Important audit note:

- because the execution date is chosen as strictly greater than the trade weekday, a Thursday schedule usually executes on Friday open (or next available open after Thursday), not Thursday open.

## TSI computation details

TSI is computed from close prices with TA-Lib:

- price change series: diff(close)
- numerator: EMA(EMA(diff, fast), slow)
- denominator: EMA(EMA(abs(diff), fast), slow)
- TSI = 100 * numerator / denominator

Defaults:

- fast = 13
- slow = 25

If denominator is zero/NaN or insufficient history, the value is NaN and skipped from ranking for that date.

## Portfolio rotation mechanics

## Portfolio state

PortfolioState tracks:

- cash
- positions as symbol -> quantity
- avg_costs as symbol -> average acquisition price (used for SELL realized PnL %)

## Target portfolio construction

At each cycle:

1. Start with kept holdings (rank <= exit_rank).
2. Append highest-ranked symbols until top_n is reached.
3. Leave kept holdings at their existing quantity.
4. Sell holdings that fell out of the target set.
5. Split available cash across only the newly-added symbols and buy them at the execution open.

## Fee model

Fee is optional (default 0 bps):

- traded_notional = total sell notional + total buy notional for newly entered symbols
- fee = traded_notional * fee_bps / 10000

Buying power is reduced by fees; kept holdings are not resized.

## Transaction logging

Each trade cycle emits BUY rows for new entrants and SELL rows for dropped holdings.

Recorded fields:

- date
- transaction_type (BUY or SELL)
- symbol
- name
- amount_of_stocks
- price
- realized_pnl_pct (SELL only; NaN for BUY)

SELL realized_pnl_pct is computed against the tracked average cost for that symbol.

## Output artifacts

## Console summary

The script prints:

- final capital
- total return
- CAGR
- annualized volatility
- Sharpe ratio
- max drawdown
- average turnover
- number of trade cycles
- transaction count
- SELL win/loss stats and averages

## Files

Optional/available exports:

- equity CSV via --output-equity
- trade-cycle CSV via --output-trades
- transaction Excel via --output-transactions (default: reports/tsi_transactions.xlsx)

## Metric definitions used in the script

- Final capital: last portfolio equity point
- Total return: final / first - 1
- CAGR: annualized growth from first to last equity point using weekly period count
- Transaction count: count of BUY + SELL rows
- Sells with profit: SELL rows with realized_pnl_pct > 0
- Average profit per sell: mean realized_pnl_pct over profitable SELL rows
- Sells with loss: SELL rows with realized_pnl_pct < 0
- Average loss per sell: mean realized_pnl_pct over losing SELL rows

## Key assumptions and limitations

1. Survivorship bias risk

- When using current index constituents to backtest past years, delisted/removed names may be absent.
- This can materially overstate historical performance.

2. Execution timing simplification

- Uses first open after scheduled trade day, not exact intraday execution.

3. No slippage model beyond optional basis-point fee

- Liquidity, spread, and market impact are not modeled.

4. Adjusted prices

- yfinance adjusted history is used; behavior around corporate actions depends on provider adjustments.

5. Partial universe data loss

- Symbols with missing history are skipped or dropped by min_bars.

6. Single-currency simplification

- Reported portfolio values are treated as one currency unit without FX conversion handling.

## Suggested validation checklist for the next session

1. Verify timing semantics

- decide whether Thursday trades should execute Thursday close, Thursday open, or Friday open
- adjust execution date logic accordingly

2. Verify universe point-in-time correctness

- replace static/current constituency with historical membership snapshots if possible

3. Sanity-check transactions

- pick several SELL rows from reports/tsi_transactions.xlsx and manually recompute realized_pnl_pct

4. Confirm equal-weight mechanics

- inspect weekly target quantities and ensure no unintended drift from sizing logic

5. Run sensitivity tests

- vary top_n (for example 10, 15, 20)
- vary exit_rank (for example 25, 30, 50)
- add realistic fee/slippage assumptions

6. Compare against benchmark

- evaluate strategy against QQQ or NASDAQ100 baseline over the same period

## Typical run command

uv run python scripts/backtest_tsi_rotation.py --start 2021-08-03 --end 2026-08-03 --capital 100000
