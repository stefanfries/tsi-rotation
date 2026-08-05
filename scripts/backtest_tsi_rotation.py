"""Backtest a simple weekly TSI rotation strategy.

Strategy idea:
- compute TSI for the whole universe once per week from historical closes
- on the weekly signal day, rank the universe by TSI
- on the trade day, hold the top N names
- sell any holding whose TSI rank falls below the exit threshold
- replace sold names with the highest-ranked names not already held
- keep surviving holdings at their current size instead of rebalancing them

The script is intentionally standalone and uses yfinance only. It assumes a
single dominant trading calendar and uses the first available open after the
trade date for execution.

Usage examples:
    uv run python scripts/backtest_tsi_rotation.py
    uv run python scripts/backtest_tsi_rotation.py --universe-index NASDAQ100
    uv run python scripts/backtest_tsi_rotation.py --tickers-file universe.txt --start 2022-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import calendar
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import talib
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE_INDEX = "NASDAQ100"
FINHUB_BASE_URL = "https://ca-fastapi.yellowwater-786ec0d0.germanywestcentral.azurecontainerapps.io"
FINHUB_TIMEOUT_S = 65


@dataclass
class PortfolioState:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    avg_costs: dict[str, float] = field(default_factory=dict)


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "-").replace(".", "-").strip()


def read_tickers_file(path: Path) -> list[str]:
    tickers: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line)
    return tickers


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def normalize_index_name(index_name: str) -> str:
    canonical = "".join(ch for ch in index_name.strip().upper() if ch.isalnum())
    if canonical == "NASDAQ100":
        return "NASDAQ100"
    raise SystemExit(f"Unsupported universe index: {index_name}")


def weekday_code(weekday: int) -> str:
    return calendar.day_abbr[weekday].upper()


def fetch_index_constituents(index_name: str) -> tuple[list[str], dict[str, str]]:
    normalized = normalize_index_name(index_name)
    return fetch_index_constituents_finhub(normalized)


def fetch_index_constituents_finhub(index_name: str) -> tuple[list[str], dict[str, str]]:
    base_url = FINHUB_BASE_URL.rstrip("/")
    timeout = FINHUB_TIMEOUT_S
    symbols: list[str] = []
    names: dict[str, str] = {}

    with httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=True) as client:
        try:
            members_resp = client.get(f"/v1/indices/{index_name}")
            members_resp.raise_for_status()
            members = members_resp.json()
        except Exception as exc:
            raise SystemExit(
                f"Failed to load {index_name} constituents from FinHub: {exc}"
            ) from exc

        for member in members:
            isin = member.get("isin")
            if not isin:
                continue
            try:
                instrument_resp = client.get(f"/v1/instruments/{isin}")
                if instrument_resp.status_code == 404:
                    continue
                instrument_resp.raise_for_status()
                instrument = instrument_resp.json()
            except Exception:
                continue

            identifiers = instrument.get("global_identifiers") or {}
            symbol = identifiers.get("symbol_yfinance")
            if not symbol:
                continue

            symbols.append(symbol)
            names[symbol] = str(member.get("name") or symbol)

    if not symbols:
        raise SystemExit(f"FinHub returned no usable constituents for {index_name}.")

    logger.info("Loaded %d constituents for %s via FinHub", len(symbols), index_name)
    return symbols, names


def parse_weekday(value: str) -> int:
    normalized = value.strip().lower()
    mapping = {
        "mon": 0,
        "monday": 0,
        "tue": 1,
        "tues": 1,
        "tuesday": 1,
        "wed": 2,
        "wednesday": 2,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "thursday": 3,
        "fri": 4,
        "friday": 4,
    }
    if normalized not in mapping:
        raise argparse.ArgumentTypeError(f"Unsupported weekday: {value}")
    return mapping[normalized]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def download_frames(
    tickers: list[str], start: date, end: date, chunk_size: int
) -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}

    frames: dict[str, pd.DataFrame] = {}
    end_str = (end + timedelta(days=1)).isoformat()

    for batch in chunked(tickers, chunk_size):
        yf_symbols = [normalize_symbol(symbol) for symbol in batch]
        try:
            raw = yf.download(
                yf_symbols,
                start=start.isoformat(),
                end=end_str,
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as exc:
            logger.warning("Download failed for batch of %d tickers: %s", len(batch), exc)
            continue

        if raw.empty:
            logger.warning("Empty price download for batch of %d tickers", len(batch))
            continue

        if isinstance(raw.columns, pd.MultiIndex):
            available = set(raw.columns.get_level_values(0))
            for symbol, yf_symbol in zip(batch, yf_symbols, strict=False):
                if yf_symbol not in available:
                    logger.warning("Missing price history for %s", symbol)
                    continue
                frame = raw[yf_symbol].copy()
                frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
                if frame.empty:
                    logger.warning("Empty OHLCV frame after cleanup for %s", symbol)
                    continue
                frames[symbol] = frame
            continue

        if len(batch) == 1:
            frame = raw.copy().dropna(subset=["Open", "High", "Low", "Close"])
            if not frame.empty:
                frames[batch[0]] = frame
            else:
                logger.warning("Empty OHLCV frame after cleanup for %s", batch[0])

    return frames


def build_tsi_series(close: pd.Series, fast: int, slow: int) -> pd.Series:
    prices = close.astype(float).to_numpy()
    changes = np.diff(prices).astype(float)
    numerator = talib.EMA(talib.EMA(changes, timeperiod=fast), timeperiod=slow)
    denominator = talib.EMA(talib.EMA(np.abs(changes), timeperiod=fast), timeperiod=slow)

    tsi = np.full(prices.shape, np.nan, dtype=float)
    if len(tsi) > 0:
        tsi[1:] = np.where(
            np.isnan(denominator) | (denominator == 0.0) | np.isnan(numerator),
            np.nan,
            100.0 * numerator / denominator,
        )
    return pd.Series(tsi, index=close.index, name="TSI")


def ensure_tsi_column(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    if "TSI" not in frame.columns:
        frame["TSI"] = build_tsi_series(frame["Close"], fast=fast, slow=slow)
    return frame["TSI"]


def latest_value_on_or_before(series: pd.Series, cutoff: date) -> float | None:
    cutoff_ts = pd.Timestamp(cutoff)
    eligible = series.loc[:cutoff_ts].dropna()
    if eligible.empty:
        return None
    return float(eligible.iloc[-1])


def first_open_after(frame: pd.DataFrame, cutoff: date) -> tuple[pd.Timestamp | None, float | None]:
    cutoff_ts = pd.Timestamp(cutoff)
    eligible = frame.loc[frame.index > cutoff_ts]
    if eligible.empty:
        return None, None
    row = eligible.iloc[0]
    return eligible.index[0], float(row["Open"])


def next_trading_date(calendar: list[pd.Timestamp], cutoff: date) -> date | None:
    for ts in calendar:
        if ts.date() > cutoff:
            return ts.date()
    return None


def build_calendar(frames: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for frame in frames.values():
        dates.update(pd.to_datetime(frame.index).normalize())
    return sorted(dates)


def rank_universe(
    frames: dict[str, pd.DataFrame],
    signal_date: date,
    fast: int,
    slow: int,
) -> list[tuple[str, float]]:
    rankings: list[tuple[str, float]] = []
    for symbol, frame in frames.items():
        tsi_series = ensure_tsi_column(frame, fast=fast, slow=slow)
        tsi_value = latest_value_on_or_before(tsi_series, signal_date)
        if tsi_value is None:
            continue
        rankings.append((symbol, tsi_value))
    rankings.sort(key=lambda item: item[1], reverse=True)
    return rankings


def rotate_portfolio(
    state: PortfolioState,
    target_symbols: list[str],
    frames: dict[str, pd.DataFrame],
    symbol_names: dict[str, str],
    execution_date: date,
    fee_bps: float,
) -> tuple[PortfolioState, dict[str, float], float, float, list[dict[str, object]]]:
    current_values: dict[str, float] = {}
    execution_prices: dict[str, float] = {}
    execution_timestamps: dict[str, pd.Timestamp] = {}

    union_symbols = set(state.positions) | set(target_symbols)
    for symbol in union_symbols:
        frame = frames[symbol]
        exec_ts, open_price = first_open_after(frame, execution_date)
        if open_price is None or exec_ts is None:
            continue
        execution_timestamps[symbol] = exec_ts
        execution_prices[symbol] = open_price
        current_values[symbol] = state.positions.get(symbol, 0.0) * open_price

    transaction_rows: list[dict[str, object]] = []
    new_positions = {
        symbol: qty for symbol, qty in state.positions.items() if symbol in target_symbols
    }
    new_avg_costs = {
        symbol: avg_cost for symbol, avg_cost in state.avg_costs.items() if symbol in target_symbols
    }
    eps = 1e-10

    sold_symbols = [symbol for symbol in state.positions if symbol not in target_symbols]
    new_symbols = [symbol for symbol in target_symbols if symbol not in state.positions]

    sell_notional = sum(current_values.get(symbol, 0.0) for symbol in sold_symbols)
    executable_new_symbols = [
        symbol
        for symbol in new_symbols
        if (price := execution_prices.get(symbol)) is not None and price > 0
    ]

    fee_rate = fee_bps / 10_000.0
    available_cash = state.cash + sell_notional
    buy_notional = 0.0

    if executable_new_symbols:
        buy_notional = max((available_cash - fee_rate * sell_notional) / (1.0 + fee_rate), 0.0)
        buy_value_per_symbol = buy_notional / len(executable_new_symbols)
        for symbol in executable_new_symbols:
            price = execution_prices[symbol]
            new_positions[symbol] = buy_value_per_symbol / price
            new_avg_costs[symbol] = price

    traded_notional = sell_notional + buy_notional
    fee = traded_notional * fee_rate

    for symbol in sorted(sold_symbols):
        price = execution_prices.get(symbol)
        exec_ts = execution_timestamps.get(symbol)
        if price is None or exec_ts is None:
            continue
        old_qty = state.positions.get(symbol, 0.0)
        if abs(old_qty) <= eps:
            continue

        symbol_name = symbol_names.get(symbol) or symbol
        old_avg = state.avg_costs.get(symbol, price)
        realized_pct = 0.0
        if old_avg > 0:
            realized_pct = (price / old_avg - 1.0) * 100.0
        transaction_rows.append(
            {
                "date": exec_ts.date().isoformat(),
                "transaction_type": "SELL",
                "symbol": symbol,
                "name": symbol_name,
                "amount_of_stocks": old_qty,
                "price": price,
                "realized_pnl_pct": realized_pct,
            }
        )
        new_avg_costs.pop(symbol, None)

    for symbol in executable_new_symbols:
        price = execution_prices[symbol]
        exec_ts = execution_timestamps[symbol]
        buy_qty = new_positions.get(symbol, 0.0)
        if buy_qty <= eps:
            continue
        transaction_rows.append(
            {
                "date": exec_ts.date().isoformat(),
                "transaction_type": "BUY",
                "symbol": symbol,
                "name": symbol_names.get(symbol) or symbol,
                "amount_of_stocks": buy_qty,
                "price": price,
                "realized_pnl_pct": np.nan,
            }
        )

    cash_after = available_cash - buy_notional - fee
    if cash_after < 0 and abs(cash_after) < 1e-8:
        cash_after = 0.0

    return (
        PortfolioState(cash=cash_after, positions=new_positions, avg_costs=new_avg_costs),
        execution_prices,
        traded_notional,
        fee,
        transaction_rows,
    )


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def cagr(
    start_value: float, end_value: float, periods: int, periods_per_year: float = 52.0
) -> float:
    if periods <= 0 or start_value <= 0 or end_value <= 0:
        return 0.0
    return float((end_value / start_value) ** (periods_per_year / periods) - 1.0)


def summarize_holdings(
    state: PortfolioState, frames: dict[str, pd.DataFrame], as_of: date
) -> list[tuple[str, float, float]]:
    rows: list[tuple[str, float, float]] = []
    for symbol, qty in sorted(state.positions.items()):
        frame = frames[symbol]
        _, price = first_open_after(frame, as_of)
        if price is None:
            continue
        rows.append((symbol, qty, price))
    rows.sort(key=lambda item: item[1] * item[2], reverse=True)
    return rows


def run_backtest(
    tickers: list[str],
    symbol_names: dict[str, str],
    start: date,
    end: date,
    capital: float,
    top_n: int,
    exit_rank: int,
    signal_weekday: int,
    trade_weekday: int,
    fee_bps: float,
    tsi_fast: int,
    tsi_slow: int,
    download_chunk_size: int,
    min_bars: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[tuple[str, float, float]]]:
    frames = download_frames(tickers, start, end, chunk_size=download_chunk_size)
    if not frames:
        raise SystemExit("No price data downloaded for the requested tickers.")

    if min_bars > 1:
        before = len(frames)
        frames = {symbol: frame for symbol, frame in frames.items() if len(frame) >= min_bars}
        dropped = before - len(frames)
        if dropped:
            logger.info("Dropped %d tickers with fewer than %d bars", dropped, min_bars)
        if not frames:
            raise SystemExit("All tickers were filtered out by the minimum bar filter.")

    calendar = build_calendar(frames)
    if not calendar:
        raise SystemExit("No trading calendar available.")

    state = PortfolioState(cash=capital, positions={})
    equity_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    transaction_rows: list[dict[str, object]] = []

    trade_dates = pd.date_range(start=start, end=end, freq=f"W-{weekday_code(trade_weekday)}")
    if trade_weekday <= signal_weekday:
        raise SystemExit(
            "trade weekday must be later in the week than signal weekday for this script."
        )

    for trade_dt in trade_dates:
        signal_cutoff = (trade_dt - pd.Timedelta(days=1)).date()
        signal_candidates = [
            ts.date()
            for ts in calendar
            if ts.date() <= signal_cutoff and ts.weekday() == signal_weekday
        ]
        if not signal_candidates:
            signal_candidates = [ts.date() for ts in calendar if ts.date() <= signal_cutoff]
        if not signal_candidates:
            continue
        signal_date = signal_candidates[-1]
        rankings = rank_universe(frames, signal_date, fast=tsi_fast, slow=tsi_slow)
        if not rankings:
            continue

        rank_map = {symbol: idx + 1 for idx, (symbol, _) in enumerate(rankings)}
        current_holdings = list(state.positions.keys())
        kept = [symbol for symbol in current_holdings if rank_map.get(symbol, 10**9) <= exit_rank]

        target: list[str] = kept.copy()
        for symbol, _tsi in rankings:
            if len(target) >= top_n:
                break
            if symbol in target:
                continue
            target.append(symbol)

        exec_date = next_trading_date(calendar, trade_dt.date())
        if exec_date is None:
            break

        state, exec_prices, traded_notional, fee, tx_rows = rotate_portfolio(
            state=state,
            target_symbols=target,
            frames=frames,
            symbol_names=symbol_names,
            execution_date=exec_date,
            fee_bps=fee_bps,
        )
        transaction_rows.extend(tx_rows)

        equity = state.cash + sum(
            qty * exec_prices[symbol]
            for symbol, qty in state.positions.items()
            if symbol in exec_prices
        )
        top_snapshot = ", ".join(
            f"{symbol}:{rank_map.get(symbol, 999)}({rankings[rank_map[symbol] - 1][1]:.1f})"
            for symbol in target[: min(len(target), 5)]
            if symbol in rank_map
        )

        equity_rows.append(
            {
                "signal_date": signal_date,
                "trade_date": exec_date,
                "equity": equity,
                "cash": state.cash,
                "positions": len(state.positions),
                "turnover_pct": traded_notional / equity if equity else 0.0,
                "fee": fee,
                "top_snapshot": top_snapshot,
            }
        )
        trade_rows.append(
            {
                "signal_date": signal_date,
                "trade_date": exec_date,
                "target_symbols": ",".join(target),
                "kept_symbols": ",".join(kept),
                "sold_symbols": ",".join(sorted(set(current_holdings) - set(kept))),
                "fee": fee,
                "turnover_pct": traded_notional / equity if equity else 0.0,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(trade_rows)
    transactions_df = pd.DataFrame(transaction_rows)
    final_holdings = summarize_holdings(state, frames, end)
    return equity_df, trades_df, transactions_df, final_holdings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest a weekly TSI rotation strategy.")
    parser.add_argument(
        "--tickers", nargs="*", default=[], help="Ticker symbols to include in the universe."
    )
    parser.add_argument("--tickers-file", type=Path, help="Optional file with one ticker per line.")
    parser.add_argument(
        "--universe-index",
        default=DEFAULT_UNIVERSE_INDEX,
        help="Universe index to fetch when no tickers are supplied (default: NASDAQ100).",
    )
    parser.add_argument(
        "--start",
        type=parse_date,
        default=date.today() - timedelta(days=3 * 365),
        help="Backtest start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end", type=parse_date, default=date.today(), help="Backtest end date (YYYY-MM-DD)."
    )
    parser.add_argument("--capital", type=float, default=10_000.0, help="Starting capital.")
    parser.add_argument("--top-n", type=int, default=15, help="Number of holdings to keep.")
    parser.add_argument(
        "--exit-rank",
        type=int,
        default=30,
        help="Sell a holding when its rank falls below this threshold.",
    )
    parser.add_argument(
        "--signal-weekday",
        type=parse_weekday,
        default=parse_weekday("wednesday"),
        help="Weekday to compute the TSI ranking.",
    )
    parser.add_argument(
        "--trade-weekday",
        type=parse_weekday,
        default=parse_weekday("thursday"),
        help="Weekday to place the trade after the signal.",
    )
    parser.add_argument(
        "--fee-bps",
        type=float,
        default=0.0,
        help="Transaction cost in basis points on traded notional.",
    )
    parser.add_argument("--tsi-fast", type=int, default=13, help="TSI fast EMA period.")
    parser.add_argument("--tsi-slow", type=int, default=25, help="TSI slow EMA period.")
    parser.add_argument(
        "--download-chunk-size", type=int, default=20, help="Batch size for yfinance downloads."
    )
    parser.add_argument(
        "--min-bars", type=int, default=180, help="Drop tickers with fewer than this many bars."
    )
    parser.add_argument(
        "--output-equity", type=Path, help="Optional CSV path for the equity curve."
    )
    parser.add_argument("--output-trades", type=Path, help="Optional CSV path for the trade log.")
    parser.add_argument(
        "--output-transactions",
        type=Path,
        default=Path("reports/tsi_transactions.xlsx"),
        help="Excel output path for all BUY/SELL transactions.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = list(dict.fromkeys(args.tickers or []))
    symbol_names: dict[str, str] = {}
    if args.tickers_file:
        tickers.extend(read_tickers_file(args.tickers_file))
    if not tickers:
        tickers, symbol_names = fetch_index_constituents(args.universe_index)
        print(
            f"No tickers supplied; using {args.universe_index} constituents ({len(tickers)} names)."
        )

    tickers = list(dict.fromkeys(tickers))
    if not symbol_names:
        symbol_names = {symbol: symbol for symbol in tickers}

    equity_df, trades_df, transactions_df, final_holdings = run_backtest(
        tickers=tickers,
        symbol_names=symbol_names,
        start=args.start,
        end=args.end,
        capital=args.capital,
        top_n=args.top_n,
        exit_rank=args.exit_rank,
        signal_weekday=args.signal_weekday,
        trade_weekday=args.trade_weekday,
        fee_bps=args.fee_bps,
        tsi_fast=args.tsi_fast,
        tsi_slow=args.tsi_slow,
        download_chunk_size=args.download_chunk_size,
        min_bars=args.min_bars,
    )

    if equity_df.empty:
        raise SystemExit(
            "Backtest produced no equity points. Try a longer date range or a different universe."
        )

    equity_series = equity_df.set_index("trade_date")["equity"]
    start_value = float(equity_series.iloc[0])
    end_value = float(equity_series.iloc[-1])
    periods = max(len(equity_series) - 1, 1)
    weekly_returns = equity_series.pct_change().dropna()

    total_return = end_value / start_value - 1.0
    annual_vol = (
        float(weekly_returns.std(ddof=0) * np.sqrt(52.0)) if not weekly_returns.empty else 0.0
    )
    sharpe = (
        float((weekly_returns.mean() / weekly_returns.std(ddof=0)) * np.sqrt(52.0))
        if len(weekly_returns) > 1 and weekly_returns.std(ddof=0) > 0
        else 0.0
    )
    max_dd = max_drawdown(equity_series)
    cagr_value = cagr(start_value, end_value, periods)
    avg_turnover = float(equity_df["turnover_pct"].mean()) if not equity_df.empty else 0.0

    sells_df = (
        transactions_df[transactions_df["transaction_type"] == "SELL"].copy()
        if not transactions_df.empty
        else pd.DataFrame()
    )
    total_transactions = int(len(transactions_df))
    total_sells = int(len(sells_df))
    profitable_sells = (
        sells_df[sells_df["realized_pnl_pct"] > 0] if not sells_df.empty else pd.DataFrame()
    )
    losing_sells = (
        sells_df[sells_df["realized_pnl_pct"] < 0] if not sells_df.empty else pd.DataFrame()
    )
    profitable_sells_count = int(len(profitable_sells))
    losing_sells_count = int(len(losing_sells))
    profitable_sells_pct = (profitable_sells_count / total_sells * 100.0) if total_sells else 0.0
    losing_sells_pct = (losing_sells_count / total_sells * 100.0) if total_sells else 0.0
    avg_profit_sell_pct = (
        float(profitable_sells["realized_pnl_pct"].mean()) if profitable_sells_count else 0.0
    )
    avg_loss_sell_pct = (
        float(losing_sells["realized_pnl_pct"].mean()) if losing_sells_count else 0.0
    )

    print()
    print(f"Universe size: {len(tickers)}")
    print(f"Backtest range: {args.start} -> {args.end}")
    print(
        f"Signal weekday: {weekday_code(args.signal_weekday)} | Trade weekday: {weekday_code(args.trade_weekday)}"
    )
    print(f"Top N: {args.top_n} | Exit rank: {args.exit_rank} | Fee: {args.fee_bps:.2f} bps")
    print(f"Initial capital: {args.capital:,.2f}")
    print(f"Final capital:   {end_value:,.2f}")
    print(f"Total return:    {total_return * 100:,.2f}%")
    print(f"CAGR:            {cagr_value * 100:,.2f}%")
    print(f"Volatility:      {annual_vol * 100:,.2f}%")
    print(f"Sharpe:          {sharpe:,.2f}")
    print(f"Max drawdown:    {max_dd * 100:,.2f}%")
    print(f"Avg turnover:    {avg_turnover * 100:,.2f}%")
    print(f"Trade cycles:    {len(equity_df)}")
    print(f"Transactions:    {total_transactions}")
    print(f"Sells profit:    {profitable_sells_count} ({profitable_sells_pct:,.2f}%)")
    print(f"Avg profit/sell: {avg_profit_sell_pct:,.2f}%")
    print(f"Sells loss:      {losing_sells_count} ({losing_sells_pct:,.2f}%)")
    print(f"Avg loss/sell:   {avg_loss_sell_pct:,.2f}%")
    if final_holdings:
        print()
        print("Final holdings:")
        for symbol, qty, price in final_holdings:
            print(
                f"  {symbol:<12} qty={qty:>10.4f} price={price:>10.2f} value={qty * price:>12.2f}"
            )

    if args.output_equity:
        args.output_equity.parent.mkdir(parents=True, exist_ok=True)
        equity_df.to_csv(args.output_equity, index=False)
        print(f"\nWrote equity curve to {args.output_equity}")

    if args.output_trades:
        args.output_trades.parent.mkdir(parents=True, exist_ok=True)
        trades_df.to_csv(args.output_trades, index=False)
        print(f"Wrote trade log to {args.output_trades}")

    if args.output_transactions:
        args.output_transactions.parent.mkdir(parents=True, exist_ok=True)
        tx_export = transactions_df.copy()
        if not tx_export.empty:
            tx_export = tx_export[
                [
                    "date",
                    "transaction_type",
                    "symbol",
                    "name",
                    "amount_of_stocks",
                    "price",
                ]
            ]
        try:
            tx_export.to_excel(args.output_transactions, index=False)
            print(f"Wrote transactions to {args.output_transactions}")
        except PermissionError:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fallback_path = args.output_transactions.with_name(
                f"{args.output_transactions.stem}_{timestamp}{args.output_transactions.suffix}"
            )
            tx_export.to_excel(fallback_path, index=False)
            print(
                "Could not write transactions to "
                f"{args.output_transactions} (file may be open). "
                f"Wrote transactions to {fallback_path} instead."
            )


if __name__ == "__main__":
    main()
