from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


def _load_backtest_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "backtest_tsi_rotation.py"
    spec = importlib.util.spec_from_file_location("tsi_rotation_backtest", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    index = pd.to_datetime([row[0] for row in rows])
    opens = [row[1] for row in rows]
    return pd.DataFrame(
        {
            "Open": opens,
            "High": opens,
            "Low": opens,
            "Close": opens,
            "Volume": [1_000_000] * len(rows),
        },
        index=index,
    )


def test_normalize_index_name_accepts_nasdaq100_variants():
    module = _load_backtest_module()

    assert module.normalize_index_name("NASDAQ100") == "NASDAQ100"
    assert module.normalize_index_name("NASDAQ-100") == "NASDAQ100"
    assert module.normalize_index_name("Nasdaq 100") == "NASDAQ100"


def test_normalize_index_name_rejects_unsupported_index():
    module = _load_backtest_module()

    with pytest.raises(SystemExit, match="Unsupported universe index"):
        module.normalize_index_name("DAX40")


def test_run_backtest_does_not_resize_kept_holdings(monkeypatch):
    module = _load_backtest_module()

    frames = {
        "A": _frame(
            [
                ("2025-01-01", 100.0),
                ("2025-01-03", 100.0),
                ("2025-01-06", 100.0),
                ("2025-01-08", 110.0),
                ("2025-01-10", 110.0),
                ("2025-01-13", 110.0),
            ]
        ),
        "B": _frame(
            [
                ("2025-01-01", 100.0),
                ("2025-01-03", 100.0),
                ("2025-01-06", 100.0),
                ("2025-01-08", 80.0),
                ("2025-01-10", 80.0),
                ("2025-01-13", 80.0),
            ]
        ),
        "C": _frame(
            [
                ("2025-01-01", 50.0),
                ("2025-01-03", 50.0),
                ("2025-01-06", 50.0),
                ("2025-01-08", 50.0),
                ("2025-01-10", 50.0),
                ("2025-01-13", 50.0),
            ]
        ),
    }

    rankings_by_date = {
        date(2025, 1, 1): [("A", 90.0), ("B", 80.0), ("C", 70.0)],
        date(2025, 1, 8): [("A", 95.0), ("C", 85.0), ("B", 60.0)],
    }

    monkeypatch.setattr(module, "download_frames", lambda *args, **kwargs: frames)
    monkeypatch.setattr(
        module,
        "rank_universe",
        lambda _frames, signal_date, fast, slow: rankings_by_date[signal_date],
    )

    _equity_df, _trades_df, transactions_df, _final_holdings = module.run_backtest(
        tickers=["A", "B", "C"],
        symbol_names={"A": "A", "B": "B", "C": "C"},
        start=date(2025, 1, 1),
        end=date(2025, 1, 9),
        capital=1_000.0,
        top_n=2,
        exit_rank=2,
        signal_weekday=module.parse_weekday("wednesday"),
        trade_weekday=module.parse_weekday("thursday"),
        fee_bps=0.0,
        tsi_fast=13,
        tsi_slow=25,
        download_chunk_size=20,
        min_bars=1,
    )

    a_transactions = transactions_df[transactions_df["symbol"] == "A"]
    assert len(a_transactions) == 1
    assert a_transactions.iloc[0]["transaction_type"] == "BUY"
    assert a_transactions.iloc[0]["amount_of_stocks"] == 5.0

    jan_13_transactions = transactions_df[transactions_df["date"] == "2025-01-13"]
    assert jan_13_transactions["symbol"].tolist() == ["B", "C"]
    assert jan_13_transactions["transaction_type"].tolist() == ["SELL", "BUY"]
    assert jan_13_transactions.iloc[0]["amount_of_stocks"] == 5.0
    assert jan_13_transactions.iloc[1]["amount_of_stocks"] == 8.0