from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def load_backtest_module() -> Any:
    script_path = Path(__file__).resolve().parent / "backtest_tsi_rotation.py"
    spec = importlib.util.spec_from_file_location("tsi_rotation_backtest", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class StrategyResult:
    strategy: str
    fee_bps: float
    universe_size: int
    start: date
    end: date
    initial_capital: float
    final_capital: float
    total_return_pct: float
    cagr_pct: float
    volatility_pct: float
    sharpe: float
    max_drawdown_pct: float
    avg_turnover_pct: float
    trade_cycles: int
    transactions: int


def calc_metrics(
    btr: Any,
    equity_df: pd.DataFrame,
    initial_capital: float,
    avg_turnover_pct: float,
    transactions: int,
) -> tuple[float, float, float, float, float, int]:
    if equity_df.empty:
        raise RuntimeError("No equity points were produced.")

    equity_series = equity_df.set_index("trade_date")["equity"].astype(float)
    start_value = float(equity_series.iloc[0])
    end_value = float(equity_series.iloc[-1])
    periods = max(len(equity_series) - 1, 1)
    weekly_returns = equity_series.pct_change().dropna()

    total_return = end_value / initial_capital - 1.0
    annual_vol = float(weekly_returns.std(ddof=0) * np.sqrt(52.0)) if not weekly_returns.empty else 0.0
    sharpe = (
        float((weekly_returns.mean() / weekly_returns.std(ddof=0)) * np.sqrt(52.0))
        if len(weekly_returns) > 1 and weekly_returns.std(ddof=0) > 0
        else 0.0
    )
    max_dd = btr.max_drawdown(equity_series)
    cagr_value = btr.cagr(start_value, end_value, periods)
    trade_cycles = len(equity_df)

    return (
        end_value,
        total_return * 100.0,
        cagr_value * 100.0,
        annual_vol * 100.0,
        sharpe,
        max_dd * 100.0,
        trade_cycles,
    )


def run_tsi(
    btr: Any,
    frames: dict[str, pd.DataFrame],
    calendar: list[pd.Timestamp],
    symbol_names: dict[str, str],
    start: date,
    end: date,
    capital: float,
    fee_bps: float,
    top_n: int,
    exit_rank: int,
    signal_weekday: int,
    trade_weekday: int,
) -> StrategyResult:
    state = btr.PortfolioState(cash=capital, positions={})
    equity_rows: list[dict[str, object]] = []
    transaction_rows: list[dict[str, object]] = []

    trade_dates = pd.date_range(start=start, end=end, freq=f"W-{btr.weekday_code(trade_weekday)}")
    if trade_weekday <= signal_weekday:
        raise RuntimeError("trade weekday must be later in the week than signal weekday.")

    for trade_dt in trade_dates:
        signal_cutoff = (trade_dt - pd.Timedelta(days=1)).date()
        signal_candidates = [
            ts.date() for ts in calendar if ts.date() <= signal_cutoff and ts.weekday() == signal_weekday
        ]
        if not signal_candidates:
            signal_candidates = [ts.date() for ts in calendar if ts.date() <= signal_cutoff]
        if not signal_candidates:
            continue

        signal_date = signal_candidates[-1]
        rankings = btr.rank_universe(frames, signal_date, fast=13, slow=25)
        if not rankings:
            continue

        rank_map = {symbol: idx + 1 for idx, (symbol, _) in enumerate(rankings)}
        current_holdings = list(state.positions.keys())
        kept = [symbol for symbol in current_holdings if rank_map.get(symbol, 10**9) <= exit_rank]

        target = kept.copy()
        for symbol, _score in rankings:
            if len(target) >= top_n:
                break
            if symbol in target:
                continue
            target.append(symbol)

        exec_date = btr.next_trading_date(calendar, trade_dt.date())
        if exec_date is None:
            break

        state, exec_prices, traded_notional, fee, tx_rows = btr.rotate_portfolio(
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
        equity_rows.append(
            {
                "trade_date": exec_date.isoformat(),
                "equity": equity,
                "turnover_pct": traded_notional / equity if equity else 0.0,
                "fee": fee,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    transactions_df = pd.DataFrame(transaction_rows)

    avg_turnover_pct = float(equity_df["turnover_pct"].mean() * 100.0) if not equity_df.empty else 0.0
    transactions = len(transactions_df)
    end_value, total_return_pct, cagr_pct, vol_pct, sharpe, max_dd_pct, trade_cycles = calc_metrics(
        btr, equity_df, capital, avg_turnover_pct, transactions
    )

    return StrategyResult(
        strategy="TSI Rotation",
        fee_bps=fee_bps,
        universe_size=len(frames),
        start=start,
        end=end,
        initial_capital=capital,
        final_capital=end_value,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        volatility_pct=vol_pct,
        sharpe=sharpe,
        max_drawdown_pct=max_dd_pct,
        avg_turnover_pct=avg_turnover_pct,
        trade_cycles=trade_cycles,
        transactions=transactions,
    )


def run_qqq_buy_hold(
    btr: Any,
    qqq_frame: pd.DataFrame,
    start: date,
    end: date,
    capital: float,
    fee_bps: float,
) -> StrategyResult:
    frame = qqq_frame
    buy_ts, buy_price = btr.first_open_after(frame, start)
    if buy_ts is None or buy_price is None:
        raise RuntimeError("Unable to determine initial QQQ execution price.")

    fee_rate = fee_bps / 10_000.0
    buy_notional = capital / (1.0 + fee_rate)
    qty = buy_notional / buy_price

    trade_dates = pd.date_range(start=start, end=end, freq="W-THU")
    equity_rows: list[dict[str, object]] = []
    for trade_dt in trade_dates:
        exec_date = btr.next_trading_date(btr.build_calendar({"QQQ": frame}), trade_dt.date())
        if exec_date is None:
            break
        exec_ts, price = btr.first_open_after(frame, exec_date)
        if exec_ts is None or price is None:
            continue
        equity_rows.append(
            {
                "trade_date": exec_ts.date().isoformat(),
                "equity": qty * price,
                "turnover_pct": 0.0,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    avg_turnover_pct = 0.0
    transactions = 1
    end_value, total_return_pct, cagr_pct, vol_pct, sharpe, max_dd_pct, trade_cycles = calc_metrics(
        btr, equity_df, capital, avg_turnover_pct, transactions
    )

    return StrategyResult(
        strategy="QQQ Buy & Hold",
        fee_bps=fee_bps,
        universe_size=1,
        start=start,
        end=end,
        initial_capital=capital,
        final_capital=end_value,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        volatility_pct=vol_pct,
        sharpe=sharpe,
        max_drawdown_pct=max_dd_pct,
        avg_turnover_pct=avg_turnover_pct,
        trade_cycles=trade_cycles,
        transactions=transactions,
    )


def run_equal_weight(
    btr: Any,
    frames: dict[str, pd.DataFrame],
    calendar: list[pd.Timestamp],
    start: date,
    end: date,
    capital: float,
    fee_bps: float,
    trade_weekday: int,
) -> StrategyResult:
    if not frames:
        raise RuntimeError("No price data available for equal-weight strategy.")

    universe = sorted(frames.keys())
    state = btr.PortfolioState(cash=capital, positions={})
    fee_rate = fee_bps / 10_000.0

    equity_rows: list[dict[str, object]] = []
    total_notional = 0.0
    total_transactions = 0

    trade_dates = pd.date_range(start=start, end=end, freq=f"W-{btr.weekday_code(trade_weekday)}")
    for trade_dt in trade_dates:
        exec_date = btr.next_trading_date(calendar, trade_dt.date())
        if exec_date is None:
            break

        prices: dict[str, float] = {}
        for symbol in universe:
            exec_ts, px = btr.first_open_after(frames[symbol], exec_date)
            if exec_ts is not None and px is not None and px > 0:
                prices[symbol] = px
        if not prices:
            continue

        current_value = state.cash + sum(
            qty * prices[symbol] for symbol, qty in state.positions.items() if symbol in prices
        )
        target_value = current_value / len(prices)

        traded_notional = 0.0
        for symbol, price in prices.items():
            old_qty = state.positions.get(symbol, 0.0)
            new_qty = target_value / price
            delta_qty = new_qty - old_qty
            delta_notional = delta_qty * price

            if abs(delta_notional) > 1e-10:
                total_transactions += 1

            traded_notional += abs(delta_notional)
            state.cash -= delta_notional
            state.positions[symbol] = new_qty

        fee = traded_notional * fee_rate
        state.cash -= fee
        total_notional += traded_notional

        equity = state.cash + sum(
            qty * prices[symbol] for symbol, qty in state.positions.items() if symbol in prices
        )
        equity_rows.append(
            {
                "trade_date": exec_date.isoformat(),
                "equity": equity,
                "turnover_pct": traded_notional / equity if equity else 0.0,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    avg_turnover_pct = float(equity_df["turnover_pct"].mean() * 100.0) if not equity_df.empty else 0.0
    end_value, total_return_pct, cagr_pct, vol_pct, sharpe, max_dd_pct, trade_cycles = calc_metrics(
        btr, equity_df, capital, avg_turnover_pct, total_transactions
    )

    return StrategyResult(
        strategy="Equal-Weight Weekly",
        fee_bps=fee_bps,
        universe_size=len(universe),
        start=start,
        end=end,
        initial_capital=capital,
        final_capital=end_value,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        volatility_pct=vol_pct,
        sharpe=sharpe,
        max_drawdown_pct=max_dd_pct,
        avg_turnover_pct=avg_turnover_pct,
        trade_cycles=trade_cycles,
        transactions=total_transactions,
    )


def momentum_12_1_on_or_before(close: pd.Series, cutoff: date) -> float | None:
    cutoff_ts = pd.Timestamp(cutoff)
    eligible = close.loc[:cutoff_ts].dropna()
    if len(eligible) < 253:
        return None
    p_t_minus_21 = float(eligible.iloc[-22])
    p_t_minus_252 = float(eligible.iloc[-253])
    if p_t_minus_252 <= 0:
        return None
    return p_t_minus_21 / p_t_minus_252 - 1.0


def rank_momentum_12_1(frames: dict[str, pd.DataFrame], signal_date: date) -> list[tuple[str, float]]:
    rankings: list[tuple[str, float]] = []
    for symbol, frame in frames.items():
        mom = momentum_12_1_on_or_before(frame["Close"], signal_date)
        if mom is None:
            continue
        rankings.append((symbol, mom))
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings


def run_momentum_12_1(
    btr: Any,
    frames: dict[str, pd.DataFrame],
    calendar: list[pd.Timestamp],
    symbol_names: dict[str, str],
    start: date,
    end: date,
    capital: float,
    fee_bps: float,
    top_n: int,
    exit_rank: int,
    signal_weekday: int,
    trade_weekday: int,
) -> StrategyResult:
    if not frames:
        raise RuntimeError("No price data available for 12-1 momentum strategy.")
    state = btr.PortfolioState(cash=capital, positions={})
    equity_rows: list[dict[str, object]] = []
    transaction_rows: list[dict[str, object]] = []

    trade_dates = pd.date_range(start=start, end=end, freq=f"W-{btr.weekday_code(trade_weekday)}")
    if trade_weekday <= signal_weekday:
        raise RuntimeError("trade weekday must be later in the week than signal weekday.")

    for trade_dt in trade_dates:
        signal_cutoff = (trade_dt - pd.Timedelta(days=1)).date()
        signal_candidates = [
            ts.date() for ts in calendar if ts.date() <= signal_cutoff and ts.weekday() == signal_weekday
        ]
        if not signal_candidates:
            signal_candidates = [ts.date() for ts in calendar if ts.date() <= signal_cutoff]
        if not signal_candidates:
            continue

        signal_date = signal_candidates[-1]
        rankings = rank_momentum_12_1(frames, signal_date)
        if not rankings:
            continue

        rank_map = {symbol: idx + 1 for idx, (symbol, _) in enumerate(rankings)}
        current_holdings = list(state.positions.keys())
        kept = [symbol for symbol in current_holdings if rank_map.get(symbol, 10**9) <= exit_rank]

        target = kept.copy()
        for symbol, _score in rankings:
            if len(target) >= top_n:
                break
            if symbol in target:
                continue
            target.append(symbol)

        exec_date = btr.next_trading_date(calendar, trade_dt.date())
        if exec_date is None:
            break

        state, exec_prices, traded_notional, fee, tx_rows = btr.rotate_portfolio(
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
        equity_rows.append(
            {
                "trade_date": exec_date.isoformat(),
                "equity": equity,
                "turnover_pct": traded_notional / equity if equity else 0.0,
                "fee": fee,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    avg_turnover_pct = float(equity_df["turnover_pct"].mean() * 100.0) if not equity_df.empty else 0.0
    transactions = len(transaction_rows)
    end_value, total_return_pct, cagr_pct, vol_pct, sharpe, max_dd_pct, trade_cycles = calc_metrics(
        btr, equity_df, capital, avg_turnover_pct, transactions
    )

    return StrategyResult(
        strategy="Momentum 12-1",
        fee_bps=fee_bps,
        universe_size=len(frames),
        start=start,
        end=end,
        initial_capital=capital,
        final_capital=end_value,
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        volatility_pct=vol_pct,
        sharpe=sharpe,
        max_drawdown_pct=max_dd_pct,
        avg_turnover_pct=avg_turnover_pct,
        trade_cycles=trade_cycles,
        transactions=transactions,
    )


def to_dataframe(results: list[StrategyResult]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for r in results:
        rows.append(
            {
                "strategy": r.strategy,
                "fee_bps": r.fee_bps,
                "universe_size": r.universe_size,
                "start": r.start.isoformat(),
                "end": r.end.isoformat(),
                "initial_capital": round(r.initial_capital, 2),
                "final_capital": round(r.final_capital, 2),
                "total_return_pct": round(r.total_return_pct, 2),
                "cagr_pct": round(r.cagr_pct, 2),
                "volatility_pct": round(r.volatility_pct, 2),
                "sharpe": round(r.sharpe, 3),
                "max_drawdown_pct": round(r.max_drawdown_pct, 2),
                "avg_turnover_pct": round(r.avg_turnover_pct, 2),
                "trade_cycles": r.trade_cycles,
                "transactions": r.transactions,
            }
        )
    return pd.DataFrame(rows)


def write_markdown_summary(df: pd.DataFrame, path: Path) -> None:
    display = df.copy()
    display = display[
        [
            "strategy",
            "fee_bps",
            "final_capital",
            "total_return_pct",
            "cagr_pct",
            "volatility_pct",
            "sharpe",
            "max_drawdown_pct",
            "avg_turnover_pct",
            "trade_cycles",
            "transactions",
        ]
    ]
    headers = list(display.columns)
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in display.itertuples(index=False, name=None):
        values = [str(v) for v in row]
        lines.append("| " + " | ".join(values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare TSI rotation against benchmark strategies.")
    parser.add_argument("--start", default="2016-08-04", help="Backtest start date (YYYY-MM-DD).")
    parser.add_argument("--end", default="2026-08-04", help="Backtest end date (YYYY-MM-DD).")
    parser.add_argument("--capital", type=float, default=10_000.0, help="Starting capital.")
    parser.add_argument("--top-n", type=int, default=15, help="Top N holdings for ranked strategies.")
    parser.add_argument("--exit-rank", type=int, default=30, help="Exit rank threshold for ranked strategies.")
    parser.add_argument("--min-bars", type=int, default=180, help="Minimum bars per ticker.")
    parser.add_argument("--signal-weekday", default="wednesday", help="Signal weekday.")
    parser.add_argument("--trade-weekday", default="thursday", help="Trade weekday.")
    parser.add_argument(
        "--fee-bps-list",
        default="0,10",
        help="Comma-separated fee bps values to run (e.g. 0,10).",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("reports/comparison/strategy_comparison"),
        help="Output prefix for CSV/Markdown files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    btr = load_backtest_module()
    btr.logger.setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)

    start = btr.parse_date(args.start)
    end = btr.parse_date(args.end)
    signal_weekday = btr.parse_weekday(args.signal_weekday)
    trade_weekday = btr.parse_weekday(args.trade_weekday)
    fee_bps_list = [float(x.strip()) for x in args.fee_bps_list.split(",") if x.strip()]

    tickers, symbol_names = btr.fetch_index_constituents(btr.DEFAULT_UNIVERSE_INDEX)
    tickers = list(dict.fromkeys(tickers))

    frames = btr.download_frames(tickers, start, end, chunk_size=20)
    frames = {symbol: frame for symbol, frame in frames.items() if len(frame) >= args.min_bars}
    if not frames:
        raise RuntimeError("No universe price data available after filtering.")
    calendar = btr.build_calendar(frames)

    qqq_frames = btr.download_frames(["QQQ"], start, end, chunk_size=1)
    if "QQQ" not in qqq_frames:
        raise RuntimeError("Unable to download QQQ history.")
    qqq_frame = qqq_frames["QQQ"]

    symbol_names = {symbol: symbol_names.get(symbol, symbol) for symbol in frames.keys()}

    results: list[StrategyResult] = []
    for fee_bps in fee_bps_list:
        results.append(
            run_tsi(
                btr=btr,
                frames=frames,
                calendar=calendar,
                symbol_names=symbol_names,
                start=start,
                end=end,
                capital=args.capital,
                fee_bps=fee_bps,
                top_n=args.top_n,
                exit_rank=args.exit_rank,
                signal_weekday=signal_weekday,
                trade_weekday=trade_weekday,
            )
        )
        results.append(
            run_equal_weight(
                btr=btr,
                frames=frames,
                calendar=calendar,
                start=start,
                end=end,
                capital=args.capital,
                fee_bps=fee_bps,
                trade_weekday=trade_weekday,
            )
        )
        results.append(
            run_momentum_12_1(
                btr=btr,
                frames=frames,
                calendar=calendar,
                symbol_names=symbol_names,
                start=start,
                end=end,
                capital=args.capital,
                fee_bps=fee_bps,
                top_n=args.top_n,
                exit_rank=args.exit_rank,
                signal_weekday=signal_weekday,
                trade_weekday=trade_weekday,
            )
        )
        results.append(
            run_qqq_buy_hold(
                btr=btr,
                qqq_frame=qqq_frame,
                start=start,
                end=end,
                capital=args.capital,
                fee_bps=fee_bps,
            )
        )

    df = to_dataframe(results).sort_values(["fee_bps", "strategy"]).reset_index(drop=True)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_prefix.with_suffix(".csv")
    md_path = args.output_prefix.with_suffix(".md")
    df.to_csv(csv_path, index=False)
    write_markdown_summary(df, md_path)

    print(f"Wrote comparison CSV to {csv_path}")
    print(f"Wrote comparison Markdown to {md_path}")
    print()
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
