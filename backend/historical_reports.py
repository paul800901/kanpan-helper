"""v12 歷史報告回補：補齊最近 20+ 個可回放交易日的基礎 reports。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.calc_indicators import calculate_all_indicators
from backend.config import DEFAULT_STOCKS, REPORTS_DIR, get_taiwan_now
from backend.fetch_data import FinMindAPI
from backend.generate_report import (
    generate_lite_report,
    generate_report_v2,
    generate_universe_report,
    save_report,
    save_universe_report,
    validate_report_consistency,
)
from backend.ranking import rank_stocks
from backend.report_index import atomic_update_index


MARKET_INDEX_ID = "TAIEX"
CALENDAR_BUFFER_DAYS = 140
PRICE_LOOKBACK_DAYS = 40
INSTITUTIONAL_LOOKBACK_ROWS = 10


def _reports_dir(base_dir: Optional[Path] = None) -> Path:
    return Path(base_dir) / "reports" if base_dir else Path(REPORTS_DIR)


def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def _complete_base_reports_exist(reports_dir: Path, date_str: str) -> bool:
    return all(
        (reports_dir / f"{date_str}{suffix}.json").exists()
        for suffix in ["", "-lite", "-universe"]
    )


def recent_trading_dates(min_dates: int, end_date: Optional[str] = None, api: Optional[FinMindAPI] = None) -> List[str]:
    client = api or FinMindAPI()
    target_end = end_date or get_taiwan_now().strftime("%Y-%m-%d")
    calendar_lookback_days = max(CALENDAR_BUFFER_DAYS, int(min_dates * 2.5))
    start_date = (_parse_date(target_end) - timedelta(days=calendar_lookback_days)).strftime("%Y-%m-%d")
    market_rows = client.get_market_index_prices(start_date, target_end, data_id=MARKET_INDEX_ID)
    dates = [str(row.get("date") or "").strip() for row in market_rows if row.get("date")]
    unique_dates = sorted({value for value in dates if value})

    if len(unique_dates) < min_dates:
        raise RuntimeError(f"大盤交易日資料不足，預期至少 {min_dates} 天，實際只有 {len(unique_dates)} 天")

    return unique_dates[-min_dates:]


def _build_history_range(target_dates: List[str]) -> tuple[str, str]:
    earliest = _parse_date(target_dates[0]) - timedelta(days=CALENDAR_BUFFER_DAYS)
    latest = _parse_date(target_dates[-1])
    return earliest.strftime("%Y-%m-%d"), latest.strftime("%Y-%m-%d")


def fetch_history_bundle(
    target_dates: List[str],
    symbols: Optional[List[str]] = None,
    api: Optional[FinMindAPI] = None,
) -> Dict[str, Dict[str, Any]]:
    client = api or FinMindAPI()
    stock_symbols = symbols or DEFAULT_STOCKS
    start_date, end_date = _build_history_range(target_dates)
    history: Dict[str, Dict[str, Any]] = {}

    print(f"[v12] 歷史回補抓取區間: {start_date} ~ {end_date}")
    for index, symbol in enumerate(stock_symbols, start=1):
        print(f"[v12] [{index}/{len(stock_symbols)}] 抓取 {symbol} 歷史資料...")
        candles = client.get_stock_candles_in_range(symbol, start_date, end_date)
        institutional = client.get_institutional_data_in_range(symbol, start_date, end_date)
        if not candles:
            continue
        history[symbol] = {
            "symbol": symbol,
            "candles": candles,
            "institutional": institutional,
        }

    return history


def build_snapshot_for_date(history_bundle: Dict[str, Dict[str, Any]], date_str: str) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for symbol, payload in history_bundle.items():
        candles = [row for row in payload.get("candles", []) if str(row.get("date") or "") <= date_str]
        if len(candles) < 20:
            continue

        institutional_rows = [row for row in payload.get("institutional", []) if str(row.get("date") or "") <= date_str]
        snapshot[symbol] = {
            "symbol": symbol,
            "candles": candles[-PRICE_LOOKBACK_DAYS:],
            "institutional": institutional_rows[-INSTITUTIONAL_LOOKBACK_ROWS:],
            "last_update": date_str,
        }

    return snapshot


def generate_reports_for_date(snapshot: Dict[str, Dict[str, Any]], date_str: str) -> Dict[str, str]:
    indicators = calculate_all_indicators(snapshot)
    if not indicators:
        raise RuntimeError(f"{date_str} 沒有足夠的指標資料可計算")

    all_stocks = rank_stocks(indicators, top_n=len(indicators))
    top_stocks = all_stocks[:5]
    bundle_id = f"{date_str}-{get_taiwan_now().strftime('%Y%m%dT%H%M%S%f')}-historical"

    full_report = generate_report_v2(
        top_stocks=top_stocks,
        date_str=date_str,
        total_stocks_requested=len(snapshot),
        total_stocks_analyzed=len(indicators),
        bundle_id=bundle_id,
    )
    universe_report = generate_universe_report(all_stocks, date_str, bundle_id=bundle_id)
    lite_report = generate_lite_report(full_report, universe_report)

    validate_report_consistency(full_report, lite_report, universe_report)

    full_path = save_report(full_report, date_str, suffix="")
    lite_path = save_report(lite_report, date_str, suffix="-lite")
    universe_path = save_universe_report(universe_report, date_str)
    atomic_update_index(date_str, has_lite=True, has_full=True, has_universe=True)

    return {
        "full_path": full_path,
        "lite_path": lite_path,
        "universe_path": universe_path,
    }


def ensure_historical_report_window(
    min_available_dates: int,
    end_date: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    force: bool = False,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    api = FinMindAPI()
    target_dates = recent_trading_dates(min_available_dates, end_date=end_date, api=api)
    reports_dir = _reports_dir(base_dir)
    missing_dates = [date_str for date_str in target_dates if force or not _complete_base_reports_exist(reports_dir, date_str)]

    generated: List[Dict[str, str]] = []
    if missing_dates:
        history_bundle = fetch_history_bundle(target_dates, symbols=symbols, api=api)
        for date_str in missing_dates:
            print(f"[v12] 生成歷史報告: {date_str}")
            snapshot = build_snapshot_for_date(history_bundle, date_str)
            generated.append({"date": date_str, **generate_reports_for_date(snapshot, date_str)})

    return {
        "target_dates": target_dates,
        "missing_dates": missing_dates,
        "generated": generated,
    }