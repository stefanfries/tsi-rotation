# TSI Strategy Improvement Ideas (2026-08-07)

## Context

Current baseline strategy:

- Buy when a stock enters Top 15, only if portfolio has fewer than 15 holdings.
- Sell when a holding leaves Top 30.
- Weekly rotation schedule from existing backtest implementation.

This note documents concrete ideas to improve performance robustness, drawdown behavior, and live-trading realism.

## Prioritized Improvement Ideas

### 1) Add regime-aware exposure control

Idea:

- Reduce or pause risk-on allocation during weak market regimes.
- Example gates: QQQ below 200-day moving average, or weak breadth signals.

Why:

- Can materially reduce deep drawdowns in bear/sideways conditions.

### 2) Use dynamic exit rank instead of fixed rank

Idea:

- Adjust exit_rank based on volatility or trend regime.
- Example: tighter exits in high volatility, looser exits in strong trend.

Why:

- Balances whipsaw risk vs trend persistence better than one fixed threshold.

### 3) Add minimum holding period

Idea:

- Keep newly entered positions for at least 1-2 rebalance cycles unless hard risk rules trigger.

Why:

- Reduces turnover and noise-driven churn.

### 4) Add quality and liquidity pre-filters

Idea:

- Pre-filter candidate universe before TSI ranking.
- Example filters: minimum dollar volume, earnings quality proxy, exclusion of unstable names.

Why:

- Improves tradability and reduces tail-risk names entering portfolio.

### 5) Move from equal-cash buys to risk-scaled sizing

Idea:

- Size positions by inverse volatility or risk budget rather than equal notional.

Why:

- Better concentration control and typically smoother equity curve.

### 6) Add entry confirmation gate

Idea:

- Require more than rank entry alone.
- Example: top-15 plus positive/rising TSI slope or absolute TSI threshold.

Why:

- Avoids marginal entries caused by short-term noise around cutoff ranks.

### 7) Replace binary exit with partial de-risking

Idea:

- Scale out progressively as rank deteriorates.
- Example: rank 31-40 reduce 50%; rank > 40 fully exit.

Why:

- Smoother transitions and potentially improved risk-adjusted outcomes.

### 8) Improve execution realism

Idea:

- Model spread/slippage and stress execution assumptions.
- Compare next-open execution with alternative realistic execution models.

Why:

- Reduces risk of optimistic backtest bias.

### 9) Reduce survivorship bias

Idea:

- Use point-in-time historical index membership instead of only current constituents.

Why:

- This is a high-impact realism improvement for long-horizon tests.

### 10) Add walk-forward optimization

Idea:

- Optimize parameters on training windows and validate on subsequent out-of-sample windows.

Why:

- Improves confidence that gains are not overfit to one historical period.

### 11) Add portfolio-level risk constraints

Idea:

- Cap single-name weight, sector weight, and max weekly turnover.

Why:

- Prevents concentration blowups and improves implementation stability.

### 12) Build ensemble signals

Idea:

- Blend TSI with one or two orthogonal signals (for example 12-1 momentum or trend stability score).

Why:

- Reduces dependence on a single indicator regime.

## Suggested Experiment Roadmap

### Phase 1: Fast, high-impact tests

1. Dynamic exit rank (around 30-35 baseline)
2. Minimum holding period (1-2 cycles)
3. Entry confirmation gate

Acceptance targets:

- Keep or improve Sharpe
- Reduce Avg Turnover %
- No significant Max Drawdown deterioration

### Phase 2: Risk and realism upgrades

1. Regime filter
2. Risk-scaled sizing
3. Partial de-risking exits

Acceptance targets:

- Lower Max Drawdown
- Sharpe improvement at 10-25 bps fee assumptions

### Phase 3: Robustness and production readiness

1. Survivorship-bias mitigation
2. Walk-forward validation
3. Execution/slippage stress tests

Acceptance targets:

- Stable ranking of preferred parameter sets across out-of-sample windows
- Acceptable degradation under higher friction assumptions

## KPI Set For Comparing Variants

Track the following for every variant:

- Final capital
- CAGR %
- Sharpe
- Max Drawdown %
- Avg Turnover %
- Transactions
- Performance at multiple fee levels (at least 0, 10, 25 bps)

## Notes

- Prioritize variants that remain strong after costs.
- Prefer simpler rules if performance is similar, to reduce implementation risk.
- Keep all tests reproducible with saved parameter/config metadata.
