"""Export top TSI candidates from the NASDAQ-100 universe.

This script reuses the same data procedures as the backtest script:
- NASDAQ-100 constituents are loaded via FinHub.
- Historical prices are downloaded with yfinance.
- TSI is calculated with the same TA-Lib based implementation.

Output:
- An Excel file in reports/ with a date-stamped filename.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from backtest_tsi_rotation import (
    FINHUB_BASE_URL,
    FINHUB_TIMEOUT_S,
    build_tsi_series,
    download_frames,
    normalize_index_name,
)

DEFAULT_UNIVERSE_INDEX = "NASDAQ100"
DEFAULT_TOP_N: int | None = None
DEFAULT_BUY_TOP_N: int | None = None
DEFAULT_TSI_FAST = 13
DEFAULT_TSI_SLOW = 25
DEFAULT_LOOKBACK_DAYS = 3 * 365
DEFAULT_DOWNLOAD_CHUNK_SIZE = 20
DEFAULT_MIN_BARS = 60


def fetch_index_constituents_with_metadata(index_name: str) -> list[dict[str, str]]:
    normalized = normalize_index_name(index_name)
    base_url = FINHUB_BASE_URL.rstrip("/")
    timeout = FINHUB_TIMEOUT_S
    rows: list[dict[str, str]] = []

    with httpx.Client(base_url=base_url, timeout=timeout, follow_redirects=True) as client:
        try:
            members_resp = client.get(f"/v1/indices/{normalized}")
            members_resp.raise_for_status()
            members = members_resp.json()
        except Exception as exc:
            raise SystemExit(
                f"Failed to load {normalized} constituents from FinHub: {exc}"
            ) from exc

        for member in members:
            isin = str(member.get("isin") or "").strip()
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
            symbol = str(identifiers.get("symbol_yfinance") or "").strip()
            if not symbol:
                continue

            rows.append(
                {
                    "symbol": symbol,
                    "isin": isin,
                    "name": str(member.get("name") or symbol),
                }
            )

    if not rows:
        raise SystemExit(f"FinHub returned no usable constituents for {normalized}.")

    # Preserve the first occurrence per symbol if duplicates appear.
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        symbol = row["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)
        deduped.append(row)
    return deduped


def latest_tsi_and_price(frame: pd.DataFrame, fast: int, slow: int) -> tuple[float | None, float | None]:
    close = frame.get("Close")
    if close is None:
        return None, None

    tsi_series = build_tsi_series(close, fast=fast, slow=slow)
    tsi_non_null = tsi_series.dropna()
    close_non_null = close.dropna()

    if tsi_non_null.empty or close_non_null.empty:
        return None, None

    return float(tsi_non_null.iloc[-1]), float(close_non_null.iloc[-1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export top NASDAQ-100 TSI candidates to Excel.")
    parser.add_argument(
        "--universe-index",
        default=DEFAULT_UNIVERSE_INDEX,
        help="Universe index to fetch (default: NASDAQ100).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Number of top TSI rows to export (default: all scored rows).",
    )
    parser.add_argument(
        "--buy-top-n",
        type=int,
        default=DEFAULT_BUY_TOP_N,
        help="Mark top rows with BUY up to this rank (default: all selected rows).",
    )
    parser.add_argument("--tsi-fast", type=int, default=DEFAULT_TSI_FAST, help="TSI fast EMA period.")
    parser.add_argument("--tsi-slow", type=int, default=DEFAULT_TSI_SLOW, help="TSI slow EMA period.")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="Price history lookback in days used for TSI (default: 1095).",
    )
    parser.add_argument(
        "--download-chunk-size",
        type=int,
        default=DEFAULT_DOWNLOAD_CHUNK_SIZE,
        help="Batch size for yfinance downloads.",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=DEFAULT_MIN_BARS,
        help="Drop symbols with fewer than this many bars.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Output directory for the Excel file (default: reports).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.top_n is not None and args.top_n <= 0:
        raise SystemExit("--top-n must be > 0")
    if args.buy_top_n is not None and args.buy_top_n < 0:
        raise SystemExit("--buy-top-n must be >= 0")

    metadata = fetch_index_constituents_with_metadata(args.universe_index)
    symbol_to_meta = {row["symbol"]: row for row in metadata}
    tickers = list(symbol_to_meta.keys())

    end_dt = date.today()
    start_dt = end_dt - timedelta(days=max(args.lookback_days, 30))

    frames = download_frames(
        tickers=tickers,
        start=start_dt,
        end=end_dt,
        chunk_size=args.download_chunk_size,
    )
    if not frames:
        raise SystemExit("No price data downloaded for the requested tickers.")

    if args.min_bars > 1:
        frames = {symbol: frame for symbol, frame in frames.items() if len(frame) >= args.min_bars}
    if not frames:
        raise SystemExit("All tickers were filtered out by the minimum bar filter.")

    scored_rows: list[dict[str, object]] = []
    for symbol, frame in frames.items():
        tsi_value, price = latest_tsi_and_price(frame, fast=args.tsi_fast, slow=args.tsi_slow)
        if tsi_value is None or price is None:
            continue

        meta = symbol_to_meta.get(symbol, {})
        scored_rows.append(
            {
                "Symbol": symbol,
                "ISIN": str(meta.get("isin") or ""),
                "Name": str(meta.get("name") or symbol),
                "Current TSI": tsi_value,
                "Current Price (USD)": price,
            }
        )

    if not scored_rows:
        raise SystemExit("No symbols had a valid TSI and price value.")

    ranked = sorted(scored_rows, key=lambda row: float(row["Current TSI"]), reverse=True)
    if args.top_n is not None:
        ranked = ranked[: args.top_n]

    buy_top_n = len(ranked) if args.buy_top_n is None else args.buy_top_n

    output_rows: list[dict[str, object]] = []
    for rank, row in enumerate(ranked, start=1):
        output_rows.append(
            {
                "#": rank,
                "Symbol": row["Symbol"],
                "ISIN": row["ISIN"],
                "Name": row["Name"],
                "Current TSI": row["Current TSI"],
                "Current Price (USD)": row["Current Price (USD)"],
                "Transaction Type": "BUY" if rank <= buy_top_n else "",
            }
        )

    out_df = pd.DataFrame(output_rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = datetime.now().strftime("%Y-%m-%d")
    out_path = args.output_dir / f"top_tsi_candidates_{date_stamp}.xlsx"

    try:
        out_df.to_excel(out_path, index=False)
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = args.output_dir / f"top_tsi_candidates_{date_stamp}_{timestamp}.xlsx"
        out_df.to_excel(out_path, index=False)

    print(f"Universe size (metadata): {len(tickers)}")
    print(f"Scored symbols: {len(scored_rows)}")
    print(f"Exported top {len(out_df)} rows to {out_path}")


if __name__ == "__main__":
    main()
