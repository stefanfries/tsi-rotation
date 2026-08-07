# German Tax Impact Evaluation (Matched Runs)

## Setup

- Script: `scripts/backtest_tsi_rotation.py`
- Strategy: `top_n=15`, `exit_rank=30`, `fee_bps=10`
- Window: `2023-08-04` to `2026-08-04`
- Initial capital: `10,000 EUR`
- Rebalance cadence: weekly (unchanged)

Two runs were executed with identical parameters except tax settings:

1. Tax OFF
2. Tax ON (`allowance=1,000 EUR`, `Abgeltungsteuer=25%`, `Solidarity=5.5%`, `Church=0%`, effective rate `26.375%`)

## Results

| Metric | Tax OFF | Tax ON | Delta (ON - OFF) |
| ------ | ------- | ------ | ---------------- |
| Final capital (EUR) | 46,944.98 | 35,677.04 | -11,267.94 (-24.00%) |
| Total return | 369.92% | 257.13% | -112.79 pp |
| CAGR | 72.23% | 56.40% | -15.83 pp |
| Volatility | 27.99% | 28.81% | +0.82 pp |
| Sharpe | 2.09 | 1.70 | -0.39 |
| Max drawdown | -19.73% | -23.57% | -3.84 pp |
| Avg turnover | 28.97% | 28.93% | -0.04 pp |
| Trade cycles | 149 | 149 | 0 |
| Transactions | 691 | 691 | 0 |
| Tax paid total (EUR) | 0.00 | 7,478.58 | +7,478.58 |

## Interpretation

- The tax model materially reduces terminal wealth in this high-turnover strategy: about `-24.0%` final capital versus tax OFF.
- Risk-adjusted performance declines (`Sharpe 2.09 -> 1.70`) while volatility changes only modestly (`+0.82 pp`).
- Drawdowns deepen under tax ON (`-19.73% -> -23.57%`) due to reduced compounding base after taxable realizations.
- Turnover and trade count are effectively unchanged, confirming performance drag is tax cash outflow, not changed signal behavior.

## Tax Burden Context

- Total tax paid (`7,478.58 EUR`) equals:
  - `74.79%` of initial capital,
  - `15.93%` of tax-OFF final capital,
  - `20.96%` of tax-ON final capital.

## Conclusion

For this rotation profile, German capital gains taxation is a first-order effect. Any forward-looking performance expectation should use the tax-ON path (or a similarly realistic tax/friction model), not gross-tax simulations.

## 10-Year Matched Run (2016-08-04 to 2026-08-04)

### Setup

- Script: `scripts/backtest_tsi_rotation.py`
- Strategy: `top_n=15`, `exit_rank=30`, `fee_bps=10`
- Window: `2016-08-04` to `2026-08-04`
- Initial capital: `10,000 EUR`
- Tax ON config: allowance `1,000 EUR`, effective rate `26.375%`

### Results

| Metric | Tax OFF | Tax ON | Delta (ON - OFF) |
| ------ | ------- | ------ | ---------------- |
| Final capital (EUR) | 210,496.72 | 111,905.82 | -98,590.91 (-46.84%) |
| Total return | 2,007.07% | 1,020.18% | -986.89 pp |
| CAGR | 36.20% | 27.75% | -8.45 pp |
| Volatility | 23.79% | 24.20% | +0.42 pp |
| Sharpe | 1.42 | 1.13 | -0.29 |
| Max drawdown | -32.71% | -35.09% | -2.38 pp |
| Avg turnover | 28.46% | 28.44% | -0.02 pp |
| Trade cycles | 514 | 514 | 0 |
| Transactions | 2,323 | 2,323 | 0 |
| Tax paid total (EUR) | 0.00 | 33,300.80 | +33,300.80 |

### Interpretation

- Over a longer horizon, tax drag compounds strongly: terminal wealth is `46.84%` lower in tax ON versus tax OFF.
- Risk-adjusted return declines (`Sharpe 1.42 -> 1.13`) with only a small volatility increase (`+0.42 pp`).
- Drawdowns are deeper under tax ON (`-32.71% -> -35.09%`) as periodic tax payments reduce reinvestable capital.
- Turnover and transaction count are unchanged, confirming the difference is driven by taxation, not strategy behavior changes.

### Tax Burden Context

- Total tax paid: `33,300.80 EUR`
- Tax paid as share of initial capital: `333.01%`
- Tax paid as share of tax-OFF final capital: `15.82%`
- Tax paid as share of tax-ON final capital: `29.76%`
