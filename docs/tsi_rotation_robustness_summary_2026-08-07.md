# TSI Rotation Robustness Summary (2026-08-07)

## Strategy Rule Evaluated

- Buy when a stock enters Top 15, only if portfolio has fewer than 15 holdings.
- Sell as soon as a holding leaves Top 30.
- Weekly signal/trade schedule as implemented in the backtest scripts.

## Test Setup

- Date range: 2016-08-04 to 2026-08-04
- Initial capital: 10,000
- Universe: NASDAQ-100 constituents resolved by current project data pipeline
- Parameter grid:
  - top_n in {10, 15, 20}
  - exit_rank in {25, 30, 35}
  - fee_bps in {0, 10, 25}

## Source Artifacts

- [tsi_grid_t10_e25.csv](../reports/comparison/tsi_grid_t10_e25.csv)
- [tsi_grid_t10_e30.csv](../reports/comparison/tsi_grid_t10_e30.csv)
- [tsi_grid_t10_e35.csv](../reports/comparison/tsi_grid_t10_e35.csv)
- [tsi_grid_t15_e25.csv](../reports/comparison/tsi_grid_t15_e25.csv)
- [tsi_grid_t15_e30.csv](../reports/comparison/tsi_grid_t15_e30.csv)
- [tsi_grid_t15_e35.csv](../reports/comparison/tsi_grid_t15_e35.csv)
- [tsi_grid_t20_e25.csv](../reports/comparison/tsi_grid_t20_e25.csv)
- [tsi_grid_t20_e30.csv](../reports/comparison/tsi_grid_t20_e30.csv)
- [tsi_grid_t20_e35.csv](../reports/comparison/tsi_grid_t20_e35.csv)

## Full TSI Grid Results

| top_n | exit_rank | fee_bps | final_capital | CAGR % | Sharpe | MaxDD % | Avg Turnover % | Transactions |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 25 | 0 | 260,539.13 | 39.16 | 1.441 | -31.27 | 31.02 | 1684 |
| 10 | 30 | 0 | 287,016.21 | 40.53 | 1.451 | -27.66 | 27.30 | 1480 |
| 10 | 35 | 0 | 304,294.53 | 41.37 | 1.439 | -30.35 | 24.42 | 1324 |
| 15 | 25 | 0 | 223,074.25 | 36.99 | 1.463 | -30.82 | 32.54 | 2633 |
| 15 | 30 | 0 | 243,484.47 | 38.21 | 1.482 | -31.87 | 28.47 | 2323 |
| 15 | 35 | 0 | 261,773.94 | 39.23 | 1.485 | -30.05 | 24.88 | 2035 |
| 20 | 25 | 0 | 185,586.86 | 34.46 | 1.457 | -30.60 | 35.35 | 3822 |
| 20 | 30 | 0 | 206,923.21 | 35.95 | 1.482 | -29.70 | 29.42 | 3208 |
| 20 | 35 | 0 | 229,651.22 | 37.39 | 1.495 | -29.42 | 25.53 | 2788 |
| 10 | 25 | 10 | 222,368.42 | 36.96 | 1.376 | -31.83 | 31.01 | 1684 |
| 10 | 30 | 10 | 249,619.32 | 38.57 | 1.396 | -28.19 | 27.30 | 1480 |
| 10 | 35 | 10 | 268,539.62 | 39.60 | 1.391 | -31.12 | 24.42 | 1324 |
| 15 | 25 | 10 | 188,730.26 | 34.70 | 1.390 | -31.64 | 32.54 | 2633 |
| 15 | 30 | 10 | 210,496.77 | 36.20 | 1.419 | -32.71 | 28.46 | 2323 |
| 15 | 35 | 10 | 230,424.44 | 37.45 | 1.431 | -30.79 | 24.87 | 2035 |
| 20 | 25 | 10 | 154,907.90 | 32.03 | 1.374 | -31.51 | 35.34 | 3822 |
| 20 | 30 | 10 | 178,045.60 | 33.91 | 1.413 | -30.49 | 29.41 | 3208 |
| 20 | 35 | 10 | 201,524.66 | 35.60 | 1.437 | -30.14 | 25.52 | 2788 |
| 10 | 25 | 25 | 175,381.76 | 33.72 | 1.279 | -32.67 | 31.01 | 1684 |
| 10 | 30 | 25 | 202,503.38 | 35.69 | 1.312 | -30.43 | 27.29 | 1480 |
| 10 | 35 | 25 | 222,666.95 | 37.00 | 1.318 | -32.24 | 24.41 | 1324 |
| 15 | 25 | 25 | 146,909.57 | 31.34 | 1.281 | -32.86 | 32.53 | 2633 |
| 15 | 30 | 25 | 169,248.13 | 33.24 | 1.325 | -33.94 | 28.45 | 2323 |
| 15 | 35 | 25 | 190,336.24 | 34.84 | 1.351 | -31.89 | 24.86 | 2035 |
| 20 | 25 | 25 | 118,179.16 | 28.48 | 1.249 | -32.86 | 35.32 | 3822 |
| 20 | 30 | 25 | 142,152.30 | 30.91 | 1.311 | -31.66 | 29.40 | 3208 |
| 20 | 35 | 25 | 165,701.79 | 32.96 | 1.351 | -31.20 | 25.51 | 2788 |

## Best Configurations

### Highest Final Capital

1. top_n=10, exit_rank=35, fee_bps=0 -> 304,294.53
2. top_n=10, exit_rank=30, fee_bps=0 -> 287,016.21
3. top_n=10, exit_rank=35, fee_bps=10 -> 268,539.62

### Highest Sharpe

1. top_n=20, exit_rank=35, fee_bps=0 -> 1.495
2. top_n=15, exit_rank=35, fee_bps=0 -> 1.485
3. top_n=15, exit_rank=30, fee_bps=0 and top_n=20, exit_rank=30, fee_bps=0 -> 1.482

## Practical Frontier Recommendations

1. Growth-focused: top_n=10, exit_rank=35
2. Balanced: top_n=15, exit_rank=35
3. Risk-adjusted: top_n=20, exit_rank=35
4. Lower drawdown alternative: top_n=10, exit_rank=30

## Notes

- Results are historical backtest outputs and not forward performance guarantees.
- Delisted/unavailable symbols were observed during data download and can influence long-horizon outcomes.
- For production decision-making, consider a second-stage local search around exit_rank 32-36 and fee stress above 25 bps.
