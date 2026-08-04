# tsi-rotation

Backtesting utilities for a weekly TSI rotation strategy over a NASDAQ-100 universe fetched via FinHub and priced with yfinance.

## Strategy Comparison

The repository includes a comparison runner that evaluates four methods over the same date range and fee assumptions:

- TSI Rotation
- Momentum 12-1
- Equal-Weight Weekly
- QQQ Buy & Hold

### Run the Comparison

```powershell
.\.venv\Scripts\python.exe scripts/compare_strategies.py --start 2016-08-04 --end 2026-08-04 --fee-bps-list 0,10
```

### Output Files

- CSV: `reports/comparison/strategy_comparison.csv`
- Markdown: `reports/comparison/strategy_comparison.md`

### Latest 10-Year Snapshot (2016-08-04 to 2026-08-04)

| Strategy | Fee (bps) | Final Capital | Return | CAGR | Volatility | Sharpe | Max Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TSI Rotation | 0 | 243,482.48 | 2,334.82% | 38.21% | 23.77% | 1.482 | -31.87% |
| TSI Rotation | 10 | 210,495.05 | 2,004.95% | 36.20% | 23.79% | 1.419 | -32.71% |
| Momentum 12-1 | 0 | 164,557.07 | 1,545.57% | 36.50% | 38.60% | 1.000 | -42.25% |
| Momentum 12-1 | 10 | 160,314.73 | 1,503.15% | 36.12% | 38.61% | 0.992 | -42.29% |
| Equal-Weight Weekly | 0 | 101,555.05 | 915.55% | 26.03% | 19.37% | 1.294 | -26.69% |
| Equal-Weight Weekly | 10 | 99,865.85 | 898.66% | 25.83% | 19.37% | 1.286 | -26.82% |
| QQQ Buy & Hold | 0 | 63,445.72 | 534.46% | 20.19% | 21.02% | 0.982 | -34.07% |
| QQQ Buy & Hold | 10 | 63,382.34 | 533.82% | 20.19% | 21.02% | 0.982 | -34.07% |

## Interpretation Notes

- These are historical backtest results, not forward-looking performance guarantees.
- Data-provider limitations (missing/delisted symbols) can affect realized universe composition.
- Results can be biased by universe construction and should be stress-tested with additional robustness checks.
- Fee modeling includes a notional transaction cost (bps), but not full market microstructure slippage.

## Reproducibility

Run the following commands from the repository root to reproduce the comparison artifacts end-to-end.

```powershell
# 1) Create/refresh local environment from pyproject + lockfile
uv sync

# 2) Activate the virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 3) Optional sanity check
pytest -q

# 4) Regenerate 10-year comparison outputs
python scripts/compare_strategies.py --start 2016-08-04 --end 2026-08-04 --fee-bps-list 0,10
```

Expected artifacts:

- `reports/comparison/strategy_comparison.csv`
- `reports/comparison/strategy_comparison.md`
