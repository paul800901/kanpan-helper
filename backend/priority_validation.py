"""v12 排序驗證層：每日 priority 快照與歷史統計。"""

from __future__ import annotations

import json
import re
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from backend.config import get_taiwan_now, get_today_str
from backend.context_cards import generate_context_report_from_files
from backend.fetch_data import FinMindAPI
from backend.historical_reports import MARKET_INDEX_ID, ensure_historical_report_window


PRIORITY_REPORT_VERSION = "v12-priority-validation"
HISTORY_REPORT_VERSION = "v12-priority-history"
FACTOR_ANALYSIS_REPORT_VERSION = "v14-factor-analysis"
SORT_RULE_DESCRIPTION = "先比命中情境數，再比技術面狀態，最後比區間位置（試單區優先）；同分保留原出現順序。"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_EVALUATED_DAYS = 20

FINAL_ADVICE_PRIORITY = {
    "暫不考慮": 1,
    "暫不進場": 2,
    "先觀望": 3,
    "可留意": 4,
    "可偏多觀察": 5,
    "強勢續看": 6,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _reports_dir(base_dir: Optional[Path] = None) -> Path:
    root = base_dir or _repo_root()
    return root / "reports"


def _load_json(path: Path, required: bool = True) -> Optional[Dict[str, Any]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"找不到檔案：{path}")
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_json(path: Path, payload: Dict[str, Any]) -> Path:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_number(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    return round(value, digits)


def _mean(values: Iterable[float]) -> Optional[float]:
    items = [float(value) for value in values]
    if not items:
        return None
    return _round_number(sum(items) / len(items))


def _win_rate(values: Iterable[float]) -> Optional[float]:
    items = [float(value) for value in values]
    if not items:
        return None
    wins = sum(1 for value in items if value > 0)
    return _round_number((wins / len(items)) * 100)


def _std_dev(values: Iterable[float]) -> Optional[float]:
    items = [float(value) for value in values]
    if len(items) < 2:
        return 0.0 if items else None
    avg = sum(items) / len(items)
    variance = sum((value - avg) ** 2 for value in items) / len(items)
    return _round_number(variance ** 0.5)


def _safe_diff(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None or right is None:
        return None
    return _round_number(left - right)


def _comparison_win_rate(left_values: List[Optional[float]], right_values: List[Optional[float]]) -> Optional[float]:
    comparable = [1 for left, right in zip(left_values, right_values) if left is not None and right is not None and left > right]
    total = sum(1 for left, right in zip(left_values, right_values) if left is not None and right is not None)
    if total == 0:
        return None
    return _round_number((sum(comparable) / total) * 100)


def _factor_verdict(spread: Optional[float]) -> str:
    if spread is None:
        return "資料不足"
    if spread > 0:
        return "有效"
    if spread < 0:
        return "拖累"
    return "中性"


def _priority_report_path(date_str: str, base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / f"{date_str}-priority.json"


def _priority_history_path(base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / "priority-history.json"


def _factor_analysis_path(base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / "factor_analysis.json"


def _iter_daily_report_dates(reports_dir: Path) -> List[str]:
    dates = [path.stem for path in reports_dir.glob("*.json") if DATE_PATTERN.match(path.stem)]
    return sorted(dates)


def _available_priority_dates(reports_dir: Path) -> List[str]:
    dates: List[str] = []
    for date_str in _iter_daily_report_dates(reports_dir):
        if (reports_dir / f"{date_str}-universe.json").exists() and (reports_dir / f"{date_str}-context.json").exists():
            dates.append(date_str)
    return dates


def to_num(value: Any) -> Optional[float]:
    return _as_float(value)


def is_consecutive_institutional_buy(label: Any) -> bool:
    if not label:
        return False
    text = str(label)
    return "連" in text and "買" in text


def is_close_to_ma5(close: Optional[float], ma5: Optional[float]) -> bool:
    if close is None or ma5 is None or ma5 == 0:
        return False
    return abs(close - ma5) / abs(ma5) <= 0.01


def get_ma20_diff(close: Optional[float], ma20: Optional[float]) -> Optional[float]:
    if close is None or ma20 is None or ma20 == 0:
        return None
    return (close - ma20) / ma20


def downgrade_bullish_summary(summary: Dict[str, str]) -> Dict[str, str]:
    if summary.get("advice") == "強勢續看":
        return {
            "advice": "可偏多觀察",
            "reason": "結構仍偏多，但量能或過熱需要再確認",
            "risk": "縮量或高檔過熱時，續攻失敗容易回檔",
        }
    if summary.get("advice") == "可偏多觀察":
        return {
            "advice": "先觀望",
            "reason": "偏多條件存在，但量能或過熱需要先消化",
            "risk": "追價後若量縮或高檔反轉，容易回落",
        }
    return summary


def get_advice_priority(advice: Optional[str]) -> int:
    return FINAL_ADVICE_PRIORITY.get(str(advice or ""), 0)


def is_avoid_advice(advice: Optional[str]) -> bool:
    return advice in {"暫不考慮", "暫不進場"}


def get_decision_summary(stock: Dict[str, Any]) -> Dict[str, str]:
    indicators = stock.get("indicators") or {}
    signals = stock.get("signals") or {}

    score = to_num(stock.get("score"))
    close = to_num(indicators.get("close"))
    ma5 = to_num(indicators.get("ma5"))
    ma20 = to_num(indicators.get("ma20"))
    k_value = to_num(indicators.get("k"))
    volume_ratio = to_num(indicators.get("volume_ratio"))
    institutional = str(
        signals.get("institutional")
        or stock.get("institutional")
        or stock.get("institution_trend")
        or ""
    ).strip()

    ma20_diff = get_ma20_diff(close, ma20)
    is_weak_below_ma20 = score is not None and score < 60 and close is not None and ma20 is not None and close < ma20
    has_bullish_penalty = (volume_ratio is not None and volume_ratio < 1) or (k_value is not None and k_value >= 80)

    if score is not None and score < 50:
        return {
            "advice": "暫不考慮",
            "reason": "分數過低且結構偏弱",
            "risk": "下跌延續或反彈失敗",
        }

    matches: List[Dict[str, Any]] = []

    if score is not None and close is not None and ma20 is not None and score >= 80 and close > ma20:
        matches.append({
            "advice": "強勢續看",
            "reason": "評分高且結構偏強",
            "risk": "短線過熱時不宜追價",
            "priority": 5,
        })

    if close is not None and ma20 is not None and close > ma20 and is_consecutive_institutional_buy(institutional):
        matches.append({
            "advice": "可偏多觀察",
            "reason": "價格站上中期結構且法人偏多",
            "risk": "短線若爆量不續攻，容易追高回檔",
            "priority": 4,
        })

    if not is_weak_below_ma20 and close is not None and ma20 is not None and k_value is not None and close < ma20 and k_value < 30:
        matches.append({
            "advice": "可留意",
            "reason": "低檔區出現反彈訊號",
            "risk": "尚未站回中期結構，反彈可能失敗",
            "priority": 3,
        })

    if not is_weak_below_ma20 and (
        (ma20_diff is not None and ma20_diff < 0 and ma20_diff > -0.01)
        or (close is not None and ma5 is not None and volume_ratio is not None and is_close_to_ma5(close, ma5) and volume_ratio < 1)
    ):
        matches.append({
            "advice": "先觀望",
            "reason": "貼近中期結構，先觀察是否重新站穩"
            if ma20_diff is not None and ma20_diff < 0 and ma20_diff > -0.01
            else "短線位置不差，但量能不足",
            "risk": "若無法站回中期結構，容易再度轉弱"
            if ma20_diff is not None and ma20_diff < 0 and ma20_diff > -0.01
            else "缺乏續航，容易震盪",
            "priority": 2,
        })

    if is_weak_below_ma20 or (ma20_diff is not None and ma20_diff <= -0.01):
        matches.append({
            "advice": "暫不進場",
            "reason": "分數偏低且仍在中期壓力下方" if is_weak_below_ma20 else "仍在中期壓力下方",
            "risk": "弱勢延續時，反彈容易失敗" if is_weak_below_ma20 else "容易出現反彈後再回落",
            "priority": 1,
        })

    matches.sort(key=lambda item: item["priority"], reverse=True)

    summary = matches[0] if matches else {
        "advice": "先觀望",
        "reason": "條件不足，方向不明",
        "risk": "短線震盪或反覆",
    }

    if has_bullish_penalty and summary["advice"] in {"強勢續看", "可偏多觀察"}:
        summary = downgrade_bullish_summary(summary)

    return {
        "advice": str(summary["advice"]),
        "reason": str(summary["reason"]),
        "risk": str(summary["risk"]),
    }


def get_zone_flags(stock: Dict[str, Any], summary: Optional[Dict[str, str]] = None) -> Dict[str, bool]:
    indicators = stock.get("indicators") or {}
    score = to_num(stock.get("score"))
    close = to_num(indicators.get("close"))
    ma5 = to_num(indicators.get("ma5"))
    ma20 = to_num(indicators.get("ma20"))
    advice = (summary or get_decision_summary(stock)).get("advice") or "先觀望"
    is_weak_below_ma20 = score is not None and score < 60 and close is not None and ma20 is not None and close < ma20

    pilot_low = ma5 * 0.98 if ma5 is not None else None
    pilot_high = ma5 * 1.02 if ma5 is not None else None
    in_pilot_zone = close is not None and pilot_low is not None and pilot_high is not None and pilot_low <= close <= pilot_high

    in_observe_zone = False
    if not is_avoid_advice(advice) and close is not None and ma5 is not None and close < ma5:
        in_observe_zone = abs(close - ma5) / abs(ma5) <= 0.01

    return {
        "in_pilot_zone": in_pilot_zone,
        "in_observe_zone": in_observe_zone,
        "is_weak_blocked": is_weak_below_ma20,
    }


def get_zone_priority(zone_flags: Optional[Dict[str, bool]]) -> int:
    if zone_flags and zone_flags.get("in_pilot_zone"):
        return 2
    if zone_flags and zone_flags.get("in_observe_zone"):
        return 1
    return 0


def get_zone_priority_label(zone_flags: Optional[Dict[str, bool]]) -> str:
    if zone_flags and zone_flags.get("in_pilot_zone"):
        return "試單區優先"
    if zone_flags and zone_flags.get("in_observe_zone"):
        return "觀察區次優先"
    return "區間外"


def build_technical_map(report: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stocks = list((report or {}).get("stocks") or [])
    technical_map: Dict[str, Dict[str, Any]] = {}

    for stock in stocks:
        symbol = str(stock.get("symbol") or "").strip()
        if not symbol:
            continue
        summary = get_decision_summary(stock)
        technical_map[symbol] = {
            "symbol": symbol,
            "name": str(stock.get("name") or symbol),
            "stock": stock,
            "summary": summary,
            "zone_flags": get_zone_flags(stock, summary),
        }

    return technical_map


def compare_candidate_items(left: Dict[str, Any], right: Dict[str, Any], technical_map: Dict[str, Dict[str, Any]]) -> int:
    event_diff = int(right["hit_count"]) - int(left["hit_count"])
    if event_diff != 0:
        return event_diff

    left_technical = technical_map.get(left["symbol"])
    right_technical = technical_map.get(right["symbol"])

    advice_diff = get_advice_priority((right_technical or {}).get("summary", {}).get("advice")) - get_advice_priority((left_technical or {}).get("summary", {}).get("advice"))
    if advice_diff != 0:
        return advice_diff

    zone_diff = get_zone_priority((right_technical or {}).get("zone_flags")) - get_zone_priority((left_technical or {}).get("zone_flags"))
    if zone_diff != 0:
        return zone_diff

    return int(left["first_seen_order"]) - int(right["first_seen_order"])


def build_priority_explanation(item: Dict[str, Any], technical: Optional[Dict[str, Any]]) -> str:
    advice = ((technical or {}).get("summary") or {}).get("advice") or "技術資料不足"
    zone = get_zone_priority_label((technical or {}).get("zone_flags"))
    return f"{item['hit_count']} 情境 > {advice} > {zone}"


def _theme_label(context_report: Dict[str, Any], theme_id: str) -> str:
    taxonomy = ((context_report.get("trace_catalog") or {}).get("theme_taxonomy") or {})
    return ((taxonomy.get(theme_id) or {}).get("label")) or theme_id


def _event_label(event_map: Dict[str, str], event_id: str) -> str:
    return event_map.get(event_id, event_id)


def _build_candidate_entries(context_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    cards = list(context_report.get("cards") or [])
    event_map: Dict[str, str] = {}
    entries: Dict[str, Dict[str, Any]] = {}
    first_seen_order = 0

    for card in cards:
        trace = card.get("trace") or {}
        event_id = str(trace.get("event") or "")
        if event_id:
            event_map[event_id] = str(card.get("title") or event_id)

        for candidate in card.get("candidate_stocks") or []:
            symbol = str(candidate.get("symbol") or "").strip()
            if not symbol:
                continue

            theme_id = str(candidate.get("from_theme") or "").strip()
            trace_event = str(candidate.get("trace_event") or event_id).strip()
            reason = str(candidate.get("reason") or "").strip()
            existing = entries.get(symbol)

            if not existing:
                entries[symbol] = {
                    "symbol": symbol,
                    "primary_theme": theme_id,
                    "themes": [theme_id] if theme_id else [],
                    "events": [trace_event] if trace_event else [],
                    "reasons": [reason] if reason else [],
                    "first_seen_order": first_seen_order,
                }
                first_seen_order += 1
                continue

            if theme_id and theme_id not in existing["themes"]:
                existing["themes"].append(theme_id)
            if trace_event and trace_event not in existing["events"]:
                existing["events"].append(trace_event)
            if reason and reason not in existing["reasons"]:
                existing["reasons"].append(reason)

    for entry in entries.values():
        entry["hit_count"] = len(entry["events"])
        entry["event_labels"] = [_event_label(event_map, event_id) for event_id in entry["events"]]
        entry["theme_labels"] = [_theme_label(context_report, theme_id) for theme_id in entry["themes"]]
        entry["primary_theme_label"] = _theme_label(context_report, entry["primary_theme"]) if entry["primary_theme"] else ""

    return list(entries.values())


def _build_next_lookup(next_universe_report: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not next_universe_report:
        return {}
    lookup: Dict[str, Dict[str, Any]] = {}
    for stock in next_universe_report.get("stocks") or []:
        symbol = str(stock.get("symbol") or "").strip()
        if symbol:
            lookup[symbol] = stock
    return lookup


def _build_next_validation(
    symbol: str,
    current_close: Optional[float],
    next_lookup: Dict[str, Dict[str, Any]],
    next_date: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not next_date:
        return None

    next_stock = next_lookup.get(symbol)
    if not next_stock:
        return {
            "next_report_date": next_date,
            "found": False,
        }

    next_close = to_num((next_stock.get("indicators") or {}).get("close"))
    return_pct: Optional[float] = None
    if current_close is not None and current_close != 0 and next_close is not None:
        return_pct = _round_number(((next_close - current_close) / current_close) * 100)

    return {
        "next_report_date": next_date,
        "found": True,
        "current_close": current_close,
        "next_close": next_close,
        "return_pct": return_pct,
        "next_rank": next_stock.get("rank"),
        "next_score": next_stock.get("score"),
        "next_action_bias": next_stock.get("action_bias"),
    }


def _extract_return_pct(candidate: Dict[str, Any]) -> Optional[float]:
    validation = candidate.get("next_report_validation") or {}
    if not validation or not validation.get("found"):
        return None
    return _as_float(validation.get("return_pct"))


def _build_snapshot_evaluation(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    evaluated_returns = [value for value in (_extract_return_pct(candidate) for candidate in candidates) if value is not None]
    top1_returns = [value for value in (_extract_return_pct(candidate) for candidate in candidates if int(candidate.get("priority_rank") or 0) <= 1) if value is not None]
    top3_returns = [value for value in (_extract_return_pct(candidate) for candidate in candidates if int(candidate.get("priority_rank") or 0) <= 3) if value is not None]
    top5_returns = [value for value in (_extract_return_pct(candidate) for candidate in candidates if int(candidate.get("priority_rank") or 0) <= 5) if value is not None]

    return {
        "evaluated_candidate_count": len(evaluated_returns),
        "top1_evaluated_count": len(top1_returns),
        "top3_evaluated_count": len(top3_returns),
        "top5_evaluated_count": len(top5_returns),
        "all_avg_return_pct": _mean(evaluated_returns),
        "top1_avg_return_pct": _mean(top1_returns),
        "top3_avg_return_pct": _mean(top3_returns),
        "top5_avg_return_pct": _mean(top5_returns),
        "all_win_rate_pct": _win_rate(evaluated_returns),
        "top1_win_rate_pct": _win_rate(top1_returns),
        "top3_win_rate_pct": _win_rate(top3_returns),
        "top5_win_rate_pct": _win_rate(top5_returns),
    }


def generate_priority_snapshot(
    context_report: Dict[str, Any],
    universe_report: Dict[str, Any],
    next_universe_report: Optional[Dict[str, Any]] = None,
    next_date: Optional[str] = None,
) -> Dict[str, Any]:
    date_str = str(context_report.get("date") or universe_report.get("date") or get_today_str())
    generated_at = get_taiwan_now().isoformat()
    next_report_date = next_date or (str(next_universe_report.get("date")) if next_universe_report else None)

    technical_map = build_technical_map(universe_report)
    next_lookup = _build_next_lookup(next_universe_report)
    entries = sorted(
        _build_candidate_entries(context_report),
        key=cmp_to_key(lambda left, right: compare_candidate_items(left, right, technical_map)),
    )

    candidates: List[Dict[str, Any]] = []
    for index, item in enumerate(entries, start=1):
        technical = technical_map.get(item["symbol"])
        stock = (technical or {}).get("stock") or {}
        indicators = stock.get("indicators") or {}
        summary = (technical or {}).get("summary") or {
            "advice": "技術資料不足",
            "reason": "缺少主報表技術欄位，無法判讀。",
            "risk": "缺少技術資料時，不宜直接比較。",
        }
        zone_flags = (technical or {}).get("zone_flags") or {
            "in_pilot_zone": False,
            "in_observe_zone": False,
            "is_weak_blocked": False,
        }

        current_close = to_num(indicators.get("close"))
        advice = str(summary.get("advice") or "技術資料不足")
        technical_state = {
            "score": to_num(stock.get("score")),
            "close": current_close,
            "ma5": to_num(indicators.get("ma5")),
            "ma20": to_num(indicators.get("ma20")),
            "k": to_num(indicators.get("k")),
            "volume_ratio": to_num(indicators.get("volume_ratio")),
            "institutional": str(stock.get("institutional") or ((stock.get("signals") or {}).get("institutional") or "")).strip(),
            "advice": advice,
            "advice_priority": get_advice_priority(advice),
            "reason": str(summary.get("reason") or ""),
            "risk": str(summary.get("risk") or ""),
            "zone_label": get_zone_priority_label(zone_flags),
            "zone_priority": get_zone_priority(zone_flags),
            "in_pilot_zone": bool(zone_flags.get("in_pilot_zone")),
            "in_observe_zone": bool(zone_flags.get("in_observe_zone")),
            "is_weak_blocked": bool(zone_flags.get("is_weak_blocked")),
        }

        candidate = {
            "priority_rank": index,
            "symbol": item["symbol"],
            "name": (technical or {}).get("name") or item["symbol"],
            "primary_theme": item["primary_theme"],
            "primary_theme_label": item.get("primary_theme_label") or item["primary_theme"],
            "themes": item["themes"],
            "theme_labels": item.get("theme_labels") or item["themes"],
            "events": item["events"],
            "event_labels": item.get("event_labels") or item["events"],
            "hit_count": int(item["hit_count"]),
            "first_seen_order": int(item["first_seen_order"]),
            "reasons": item.get("reasons") or [],
            "technical_state": technical_state,
            "priority_explanation": build_priority_explanation(item, technical),
            "next_report_validation": _build_next_validation(item["symbol"], current_close, next_lookup, next_report_date),
        }
        candidates.append(candidate)

    evaluation = _build_snapshot_evaluation(candidates)

    return {
        "report_version": PRIORITY_REPORT_VERSION,
        "date": date_str,
        "generated_at": generated_at,
        "evaluation_horizon": "next_available_report",
        "next_report_date": next_report_date,
        "sort_rule": {
            "description": SORT_RULE_DESCRIPTION,
            "keys": [
                "hit_count desc",
                "advice_priority desc",
                "zone_priority desc",
                "first_seen_order asc",
            ],
        },
        "source_reports": {
            "context": f"{date_str}-context.json",
            "universe": f"{date_str}-universe.json",
            "next_universe": f"{next_report_date}-universe.json" if next_report_date else None,
        },
        "candidate_count": len(candidates),
        "top1_symbols": [candidate["symbol"] for candidate in candidates[:1]],
        "top3_symbols": [candidate["symbol"] for candidate in candidates[:3]],
        "top5_symbols": [candidate["symbol"] for candidate in candidates[:5]],
        "evaluation": evaluation,
        "candidates": candidates,
    }


def save_priority_snapshot(report: Dict[str, Any], date_str: Optional[str] = None, base_dir: Optional[Path] = None) -> Path:
    target_date = date_str or str(report.get("date") or get_today_str())
    return _save_json(_priority_report_path(target_date, base_dir), report)


def ensure_context_report(date_str: str, base_dir: Optional[Path] = None, refresh: bool = False) -> Path:
    path = _reports_dir(base_dir) / f"{date_str}-context.json"
    if refresh or not path.exists():
        return generate_context_report_from_files(date_str, base_dir=base_dir)
    return path


def generate_priority_snapshot_from_files(
    date_str: str,
    base_dir: Optional[Path] = None,
    next_date: Optional[str] = None,
    refresh_context: bool = False,
) -> Path:
    reports_dir = _reports_dir(base_dir)
    ensure_context_report(date_str, base_dir=base_dir, refresh=refresh_context)

    context_report = _load_json(reports_dir / f"{date_str}-context.json", required=True)
    universe_report = _load_json(reports_dir / f"{date_str}-universe.json", required=True)

    if next_date is None:
        dates = _available_priority_dates(reports_dir)
        if date_str in dates:
            current_index = dates.index(date_str)
            if current_index + 1 < len(dates):
                next_date = dates[current_index + 1]

    next_universe_report = None
    if next_date:
        next_universe_report = _load_json(reports_dir / f"{next_date}-universe.json", required=False)

    report = generate_priority_snapshot(
        context_report,
        universe_report,
        next_universe_report=next_universe_report,
        next_date=next_date,
    )
    return save_priority_snapshot(report, date_str=date_str, base_dir=base_dir)


def _build_bucket_stats(
    candidates: List[Dict[str, Any]],
    bucket_key: Callable[[Dict[str, Any]], Any],
    order_key: Optional[Callable[[Any], Any]] = None,
    reverse: bool = False,
    label_key: str = "bucket",
) -> List[Dict[str, Any]]:
    grouped: Dict[Any, List[float]] = {}
    for candidate in candidates:
        return_pct = _extract_return_pct(candidate)
        if return_pct is None:
            continue
        key = bucket_key(candidate)
        grouped.setdefault(key, []).append(return_pct)

    if order_key:
        ordered_keys = sorted(grouped.keys(), key=order_key, reverse=reverse)
    else:
        ordered_keys = sorted(grouped.keys(), reverse=reverse)

    stats: List[Dict[str, Any]] = []
    for key in ordered_keys:
        values = grouped[key]
        stats.append({
            label_key: key,
            "sample_count": len(values),
            "avg_return_pct": _mean(values),
            "win_rate_pct": _win_rate(values),
        })
    return stats


def _normalize_market_prices(market_prices: Optional[Any]) -> Dict[str, Optional[float]]:
    if market_prices is None:
        return {}
    if isinstance(market_prices, dict):
        return {str(date): _as_float(close) for date, close in market_prices.items()}

    lookup: Dict[str, Optional[float]] = {}
    for row in market_prices:
        if not isinstance(row, dict):
            continue
        date_str = str(row.get("date") or "").strip()
        if not date_str:
            continue
        lookup[date_str] = _as_float(row.get("close"))
    return lookup


def _fetch_market_price_lookup(priority_reports: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    if not priority_reports:
        return {}

    start_date = str(priority_reports[0].get("date") or "")
    end_date = str(priority_reports[-1].get("next_report_date") or priority_reports[-1].get("date") or "")
    if not start_date or not end_date:
        return {}

    api = FinMindAPI()
    return _normalize_market_prices(api.get_market_index_prices(start_date, end_date, data_id=MARKET_INDEX_ID))


def _market_return(date_str: Optional[str], next_date: Optional[str], market_lookup: Dict[str, Optional[float]]) -> Optional[float]:
    if not date_str or not next_date:
        return None
    current_close = market_lookup.get(date_str)
    next_close = market_lookup.get(next_date)
    if current_close in (None, 0) or next_close is None:
        return None
    return _round_number(((next_close - current_close) / current_close) * 100)


def _build_topn_day_summary(candidates: List[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    selected = [candidate for candidate in candidates if int(candidate.get("priority_rank") or 0) <= limit]
    returns = []
    for candidate in selected:
        return_pct = _extract_return_pct(candidate)
        returns.append({
            "priority_rank": candidate.get("priority_rank"),
            "symbol": candidate.get("symbol"),
            "return_pct": return_pct,
        })

    valid_returns = [item["return_pct"] for item in returns if item["return_pct"] is not None]
    return {
        "symbols": [candidate.get("symbol") for candidate in selected],
        "returns": returns,
        "avg_return_pct": _mean(valid_returns),
        "win_rate_pct": _win_rate(valid_returns),
        "evaluated_count": len(valid_returns),
    }


def _build_stability_summary(
    strategy_returns: List[Optional[float]],
    market_returns: List[Optional[float]],
    random_returns: List[Optional[float]],
) -> Dict[str, Any]:
    valid_strategy_returns = [value for value in strategy_returns if value is not None]
    return {
        "evaluated_days": len(valid_strategy_returns),
        "avg_return": _mean(valid_strategy_returns),
        "return_std_dev": _std_dev(valid_strategy_returns),
        "positive_day_ratio": _win_rate(valid_strategy_returns),
        "outperform_market_ratio": _comparison_win_rate(strategy_returns, market_returns),
        "outperform_random_ratio": _comparison_win_rate(strategy_returns, random_returns),
    }


def _collect_trading_interval_candidates(
    priority_reports: List[Dict[str, Any]],
    market_lookup: Dict[str, Optional[float]],
    universe_reports_by_date: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[List[Dict[str, Any]], int]:
    ordered_reports = sorted(priority_reports, key=lambda item: str(item.get("date") or ""))
    candidates: List[Dict[str, Any]] = []
    evaluated_days = 0

    for index, report in enumerate(ordered_reports):
        previous_date = str(ordered_reports[index - 1].get("date") or "") if index > 0 else None
        current_date = str(report.get("date") or "")
        current_universe = ((universe_reports_by_date or {}).get(current_date) or {}).get("stocks") or []
        previous_universe = ((universe_reports_by_date or {}).get(previous_date or "") or {}).get("stocks") or []
        current_universe_lookup = {str(stock.get("symbol") or ""): stock for stock in current_universe}
        previous_universe_lookup = {str(stock.get("symbol") or ""): stock for stock in previous_universe}
        market_return = _market_return(str(report.get("date") or ""), str(report.get("next_report_date") or ""), market_lookup)
        if market_return is None:
            continue

        evaluated_days += 1
        for candidate in report.get("candidates") or []:
            return_pct = _extract_return_pct(candidate)
            if return_pct is None:
                continue
            symbol = str(candidate.get("symbol") or "")
            candidates.append({
                "date": report.get("date"),
                "previous_date": previous_date,
                "next_report_date": report.get("next_report_date"),
                "return_pct": return_pct,
                "candidate": candidate,
                "current_universe_stock": current_universe_lookup.get(symbol),
                "previous_universe_stock": previous_universe_lookup.get(symbol),
            })

    return candidates, evaluated_days


def _build_factor_bucket_summary(
    label: str,
    factor_value: Any,
    values: List[float],
) -> Dict[str, Any]:
    return {
        "label": label,
        "factor_value": factor_value,
        "sample_count": len(values),
        "avg_return_pct": _mean(values),
        "win_rate_pct": _win_rate(values),
    }


def _build_factor_section(
    factor_name: str,
    factor_label: str,
    ordered_buckets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    high_bucket = ordered_buckets[0] if ordered_buckets else None
    low_bucket = ordered_buckets[-1] if ordered_buckets else None
    spread = _safe_diff(
        (high_bucket or {}).get("avg_return_pct"),
        (low_bucket or {}).get("avg_return_pct"),
    )

    return {
        "factor": factor_name,
        "label": factor_label,
        "bucket_count": len(ordered_buckets),
        "buckets": ordered_buckets,
        "high_group": high_bucket,
        "low_group": low_bucket,
        "spread_avg_return_pct": spread,
        "spread_win_rate_pct": _safe_diff(
            (high_bucket or {}).get("win_rate_pct"),
            (low_bucket or {}).get("win_rate_pct"),
        ),
        "verdict": _factor_verdict(spread),
    }


def _candidate_metric(sample: Dict[str, Any], metric: str) -> Optional[float]:
    technical_state = (sample.get("candidate") or {}).get("technical_state") or {}
    if metric in technical_state:
        return _as_float(technical_state.get(metric))

    current_indicators = ((sample.get("current_universe_stock") or {}).get("indicators") or {})
    return _as_float(current_indicators.get(metric))


def _previous_metric(sample: Dict[str, Any], metric: str) -> Optional[float]:
    previous_indicators = ((sample.get("previous_universe_stock") or {}).get("indicators") or {})
    return _as_float(previous_indicators.get(metric))


def _build_boolean_factor(
    samples: List[Dict[str, Any]],
    factor_name: str,
    factor_label: str,
    positive_label: str,
    negative_label: str,
    predicate: Callable[[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    positive_values = [sample["return_pct"] for sample in samples if predicate(sample)]
    negative_values = [sample["return_pct"] for sample in samples if not predicate(sample)]
    buckets = [
        _build_factor_bucket_summary(positive_label, True, positive_values),
        _build_factor_bucket_summary(negative_label, False, negative_values),
    ]
    return _build_factor_section(factor_name, factor_label, buckets)


def _build_low_position_ma20_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    valued_samples: List[tuple[Dict[str, Any], float]] = []
    for sample in samples:
        close = _candidate_metric(sample, "close")
        ma20 = _candidate_metric(sample, "ma20")
        if close is None or ma20 in (None, 0):
            continue
        gap_pct = (close - ma20) / ma20
        valued_samples.append((sample, gap_pct))

    if not valued_samples:
        return _build_factor_section("low_position_ma20", "低位因子", [])

    ordered_values = sorted(value for _, value in valued_samples)
    first_cut = ordered_values[len(ordered_values) // 3]
    second_cut = ordered_values[(len(ordered_values) * 2) // 3]

    low_values = [sample["return_pct"] for sample, value in valued_samples if value <= first_cut]
    mid_values = [sample["return_pct"] for sample, value in valued_samples if first_cut < value < second_cut]
    high_values = [sample["return_pct"] for sample, value in valued_samples if value >= second_cut]

    buckets = [
        _build_factor_bucket_summary("低位組", "lower_third", low_values),
        _build_factor_bucket_summary("中位組", "middle_third", mid_values),
        _build_factor_bucket_summary("高位組", "upper_third", high_values),
    ]
    return _build_factor_section("low_position_ma20", "低位因子", buckets)


def _build_break_ma20_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "just_break_ma20",
        "回檔因子：剛跌破 MA20",
        "剛跌破組",
        "非剛跌破組",
        lambda sample: (
            _previous_metric(sample, "close") is not None
            and _previous_metric(sample, "ma20") not in (None, 0)
            and _candidate_metric(sample, "close") is not None
            and _candidate_metric(sample, "ma20") not in (None, 0)
            and _previous_metric(sample, "close") >= _previous_metric(sample, "ma20")
            and _candidate_metric(sample, "close") < _candidate_metric(sample, "ma20")
        ),
    )


def _build_retest_ma20_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "retest_ma20",
        "回檔因子：剛回測 MA20",
        "剛回測組",
        "非剛回測組",
        lambda sample: (
            _previous_metric(sample, "close") is not None
            and _previous_metric(sample, "ma20") not in (None, 0)
            and _candidate_metric(sample, "close") is not None
            and _candidate_metric(sample, "ma20") not in (None, 0)
            and _previous_metric(sample, "close") > _previous_metric(sample, "ma20")
            and _candidate_metric(sample, "close") >= _candidate_metric(sample, "ma20")
            and abs((_candidate_metric(sample, "close") - _candidate_metric(sample, "ma20")) / _candidate_metric(sample, "ma20")) <= 0.01
        ),
    )


def _build_volume_expand_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "volume_expand_after_shrink",
        "量縮後放量",
        "量縮後放量組",
        "其他量能組",
        lambda sample: (
            _previous_metric(sample, "volume_ratio") is not None
            and _candidate_metric(sample, "volume_ratio") is not None
            and _previous_metric(sample, "volume_ratio") < 1
            and _candidate_metric(sample, "volume_ratio") >= 1.2
        ),
    )


def _build_low_k_turn_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "low_k_turn_up",
        "KD 低檔翻揚",
        "低檔翻揚組",
        "非低檔翻揚組",
        lambda sample: (
            _previous_metric(sample, "k") is not None
            and _candidate_metric(sample, "k") is not None
            and _candidate_metric(sample, "k") < 30
            and _candidate_metric(sample, "k") > _previous_metric(sample, "k")
        ),
    )


def _build_hit_count_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[int, List[float]] = {}
    for sample in samples:
        candidate = sample["candidate"]
        grouped.setdefault(int(candidate.get("hit_count") or 0), []).append(sample["return_pct"])

    buckets = [
        _build_factor_bucket_summary(str(hit_count), hit_count, grouped[hit_count])
        for hit_count in sorted(grouped.keys(), reverse=True)
    ]
    return _build_factor_section("hit_count", "情境命中數", buckets)


def _build_technical_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[int, Dict[str, Any]] = {}
    for sample in samples:
        technical_state = sample["candidate"].get("technical_state") or {}
        advice = str(technical_state.get("advice") or "技術資料不足")
        advice_priority = int(technical_state.get("advice_priority") or 0)
        bucket = grouped.setdefault(advice_priority, {"label": advice, "values": []})
        bucket["values"].append(sample["return_pct"])

    buckets = [
        _build_factor_bucket_summary(grouped[priority]["label"], priority, grouped[priority]["values"])
        for priority in sorted(grouped.keys(), reverse=True)
    ]
    return _build_factor_section("technical", "技術面", buckets)


def _build_zone_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[int, Dict[str, Any]] = {}
    for sample in samples:
        technical_state = sample["candidate"].get("technical_state") or {}
        zone_label = str(technical_state.get("zone_label") or "區間外")
        zone_priority = int(technical_state.get("zone_priority") or 0)
        bucket = grouped.setdefault(zone_priority, {"label": zone_label, "values": []})
        bucket["values"].append(sample["return_pct"])

    buckets = [
        _build_factor_bucket_summary(grouped[priority]["label"], priority, grouped[priority]["values"])
        for priority in sorted(grouped.keys(), reverse=True)
    ]
    return _build_factor_section("zone", "區間位置", buckets)


def generate_factor_analysis_report(
    priority_reports: List[Dict[str, Any]],
    market_prices: Optional[Any] = None,
    universe_reports_by_date: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    ordered_reports = sorted(priority_reports, key=lambda item: str(item.get("date") or ""))
    market_lookup = _normalize_market_prices(market_prices) if market_prices is not None else _fetch_market_price_lookup(ordered_reports)
    trading_samples, evaluated_days = _collect_trading_interval_candidates(
        ordered_reports,
        market_lookup,
        universe_reports_by_date=universe_reports_by_date,
    )

    hit_count_section = _build_hit_count_factor(trading_samples)
    technical_section = _build_technical_factor(trading_samples)
    zone_section = _build_zone_factor(trading_samples)
    low_position_section = _build_low_position_ma20_factor(trading_samples)
    break_ma20_section = _build_break_ma20_factor(trading_samples)
    retest_ma20_section = _build_retest_ma20_factor(trading_samples)
    volume_expand_section = _build_volume_expand_factor(trading_samples)
    low_k_turn_section = _build_low_k_turn_factor(trading_samples)

    legacy_factors = {
        "hit_count": hit_count_section,
        "technical": technical_section,
        "zone": zone_section,
    }
    test_factors = {
        "low_position_ma20": low_position_section,
        "just_break_ma20": break_ma20_section,
        "retest_ma20": retest_ma20_section,
        "volume_expand_after_shrink": volume_expand_section,
        "low_k_turn_up": low_k_turn_section,
    }
    all_factor_sections = list(legacy_factors.values()) + list(test_factors.values())

    factor_effect_ranking = sorted(
        all_factor_sections,
        key=lambda item: item.get("spread_avg_return_pct") if item.get("spread_avg_return_pct") is not None else float("-inf"),
        reverse=True,
    )

    positive_factors = [
        section for section in factor_effect_ranking
        if section.get("verdict") == "有效"
    ]
    drag_factors = [
        section for section in factor_effect_ranking
        if section.get("verdict") == "拖累"
    ]

    return {
        "report_version": FACTOR_ANALYSIS_REPORT_VERSION,
        "generated_at": get_taiwan_now().isoformat(),
        "evaluation_horizon": "next_available_report",
        "evaluated_days": evaluated_days,
        "candidate_samples": len(trading_samples),
        "legacy_factor_names": list(legacy_factors.keys()),
        "test_factor_names": list(test_factors.keys()),
        "factors": {
            **legacy_factors,
            **test_factors,
        },
        "factor_effect_ranking": [
            {
                "factor": section["factor"],
                "label": section["label"],
                "verdict": section["verdict"],
                "spread_avg_return_pct": section["spread_avg_return_pct"],
                "high_group_label": (section.get("high_group") or {}).get("label"),
                "low_group_label": (section.get("low_group") or {}).get("label"),
            }
            for section in factor_effect_ranking
        ],
        "positive_factors": [
            {
                "factor": section["factor"],
                "label": section["label"],
                "spread_avg_return_pct": section["spread_avg_return_pct"],
                "high_group_label": (section.get("high_group") or {}).get("label"),
                "low_group_label": (section.get("low_group") or {}).get("label"),
            }
            for section in positive_factors
        ],
        "drag_factors": [
            {
                "factor": section["factor"],
                "label": section["label"],
                "spread_avg_return_pct": section["spread_avg_return_pct"],
                "high_group_label": (section.get("high_group") or {}).get("label"),
                "low_group_label": (section.get("low_group") or {}).get("label"),
            }
            for section in drag_factors
        ],
    }


def generate_priority_history_report(
    priority_reports: List[Dict[str, Any]],
    market_prices: Optional[Any] = None,
) -> Dict[str, Any]:
    generated_at = get_taiwan_now().isoformat()
    ordered_reports = sorted(priority_reports, key=lambda item: str(item.get("date") or ""))
    market_lookup = _normalize_market_prices(market_prices) if market_prices is not None else _fetch_market_price_lookup(ordered_reports)
    replay_days: List[Dict[str, Any]] = []
    all_candidates: List[Dict[str, Any]] = []
    top1_day_returns: List[Optional[float]] = []
    top3_day_returns: List[Optional[float]] = []
    top5_day_returns: List[Optional[float]] = []
    market_day_returns: List[Optional[float]] = []
    random_day_returns: List[Optional[float]] = []

    for report in ordered_reports:
        candidates = list(report.get("candidates") or [])
        evaluation = report.get("evaluation") or {}
        valid_candidate_returns = [value for value in (_extract_return_pct(candidate) for candidate in candidates) if value is not None]
        top1_summary = _build_topn_day_summary(candidates, 1)
        top3_summary = _build_topn_day_summary(candidates, 3)
        top5_summary = _build_topn_day_summary(candidates, 5)
        market_return = _market_return(str(report.get("date") or ""), str(report.get("next_report_date") or ""), market_lookup)
        random_candidate_avg_return = _mean(valid_candidate_returns)
        is_trading_interval = market_return is not None

        replay_days.append({
            "date": report.get("date"),
            "priority_file": f"{report.get('date')}-priority.json",
            "candidate_count": report.get("candidate_count", len(candidates)),
            "top1_symbols": report.get("top1_symbols") or top1_summary["symbols"],
            "top3_symbols": report.get("top3_symbols") or [],
            "top5_symbols": report.get("top5_symbols") or top5_summary["symbols"],
            "next_report_date": report.get("next_report_date"),
            "top1_returns": top1_summary["returns"],
            "top3_returns": top3_summary["returns"],
            "top5_returns": top5_summary["returns"],
            "top1_avg_return": top1_summary["avg_return_pct"],
            "top3_avg_return": top3_summary["avg_return_pct"],
            "top5_avg_return": top5_summary["avg_return_pct"],
            "is_trading_interval": is_trading_interval,
            "benchmark_return": {
                "market_return": market_return,
                "random_selection_expected_return": random_candidate_avg_return,
            },
            "top1_avg_return_pct": top1_summary["avg_return_pct"],
            "top3_avg_return_pct": evaluation.get("top3_avg_return_pct"),
            "top5_avg_return_pct": top5_summary["avg_return_pct"],
            "all_avg_return_pct": evaluation.get("all_avg_return_pct"),
        })
        if is_trading_interval:
            all_candidates.extend(candidates)
            top1_day_returns.append(top1_summary["avg_return_pct"])
            top3_day_returns.append(top3_summary["avg_return_pct"])
            top5_day_returns.append(top5_summary["avg_return_pct"])
            market_day_returns.append(market_return)
            random_day_returns.append(random_candidate_avg_return)

    evaluated_candidates = [candidate for candidate in all_candidates if _extract_return_pct(candidate) is not None]
    top1_candidates = [candidate for candidate in evaluated_candidates if int(candidate.get("priority_rank") or 0) <= 1]
    top3_candidates = [candidate for candidate in evaluated_candidates if int(candidate.get("priority_rank") or 0) <= 3]
    top5_candidates = [candidate for candidate in evaluated_candidates if int(candidate.get("priority_rank") or 0) <= 5]
    all_returns = [_extract_return_pct(candidate) for candidate in evaluated_candidates]
    top1_returns = [_extract_return_pct(candidate) for candidate in top1_candidates]
    top3_returns = [_extract_return_pct(candidate) for candidate in top3_candidates]
    top5_returns = [_extract_return_pct(candidate) for candidate in top5_candidates]

    top1_avg_return = _mean([value for value in top1_returns if value is not None])
    top3_avg_return = _mean([value for value in top3_returns if value is not None])
    top5_avg_return = _mean([value for value in top5_returns if value is not None])
    market_avg_return = _mean([value for value in market_day_returns if value is not None])
    random_avg_return = _mean([value for value in random_day_returns if value is not None])

    advice_stats = _build_bucket_stats(
        evaluated_candidates,
        bucket_key=lambda candidate: (candidate.get("technical_state") or {}).get("advice") or "技術資料不足",
        order_key=lambda advice: get_advice_priority(str(advice)),
        reverse=True,
        label_key="advice",
    )

    pilot_zone_stats = _build_bucket_stats(
        evaluated_candidates,
        bucket_key=lambda candidate: "位於試單區" if (candidate.get("technical_state") or {}).get("in_pilot_zone") else "未在試單區",
        order_key=lambda label: 1 if label == "位於試單區" else 0,
        reverse=True,
    )

    weak_block_stats = _build_bucket_stats(
        evaluated_candidates,
        bucket_key=lambda candidate: "弱股封鎖" if (candidate.get("technical_state") or {}).get("is_weak_blocked") else "非弱股",
        order_key=lambda label: 1 if label == "非弱股" else 0,
        reverse=True,
    )

    hit_count_stats = _build_bucket_stats(
        evaluated_candidates,
        bucket_key=lambda candidate: int(candidate.get("hit_count") or 0),
        order_key=lambda value: int(value),
        reverse=True,
        label_key="hit_count",
    )

    return {
        "report_version": HISTORY_REPORT_VERSION,
        "generated_at": generated_at,
        "evaluation_horizon": "next_available_report",
        "available_dates": [report.get("date") for report in ordered_reports],
        "replay_days": replay_days,
        "stats": {
            "snapshot_count": len(ordered_reports),
            "evaluated_snapshot_count": sum(1 for day in replay_days if day.get("is_trading_interval")),
            "candidate_samples": len(all_candidates),
            "evaluated_candidate_samples": len(evaluated_candidates),
            "top1_avg_return": top1_avg_return,
            "top3_avg_return": top3_avg_return,
            "top5_avg_return": top5_avg_return,
            "benchmark_return": {
                "market_avg_return": market_avg_return,
                "random_selection_expected_return": random_avg_return,
                "market_index": MARKET_INDEX_ID,
            },
            "validation_readiness": {
                "minimum_evaluated_days_required": MIN_EVALUATED_DAYS,
                "evaluated_days": len(top1_day_returns),
                "is_sample_size_ready": len(top1_day_returns) >= MIN_EVALUATED_DAYS,
            },
            "topn_vs_benchmark": {
                "top1_minus_market": _safe_diff(top1_avg_return, market_avg_return),
                "top3_minus_market": _safe_diff(top3_avg_return, market_avg_return),
                "top5_minus_market": _safe_diff(top5_avg_return, market_avg_return),
                "top1_minus_random": _safe_diff(top1_avg_return, random_avg_return),
                "top3_minus_random": _safe_diff(top3_avg_return, random_avg_return),
                "top5_minus_random": _safe_diff(top5_avg_return, random_avg_return),
            },
            "stability": {
                "top1": _build_stability_summary(top1_day_returns, market_day_returns, random_day_returns),
                "top3": _build_stability_summary(top3_day_returns, market_day_returns, random_day_returns),
                "top5": _build_stability_summary(top5_day_returns, market_day_returns, random_day_returns),
            },
            "top3_vs_all": {
                "top1_sample_count": len(top1_candidates),
                "top3_sample_count": len(top3_candidates),
                "top5_sample_count": len(top5_candidates),
                "all_candidate_sample_count": len(evaluated_candidates),
                "top1_avg_return_pct": top1_avg_return,
                "top3_avg_return_pct": _mean([value for value in top3_returns if value is not None]),
                "top5_avg_return_pct": top5_avg_return,
                "all_candidates_avg_return_pct": _mean([value for value in all_returns if value is not None]),
                "top1_win_rate_pct": _win_rate([value for value in top1_returns if value is not None]),
                "top3_win_rate_pct": _win_rate([value for value in top3_returns if value is not None]),
                "top5_win_rate_pct": _win_rate([value for value in top5_returns if value is not None]),
                "all_candidates_win_rate_pct": _win_rate([value for value in all_returns if value is not None]),
            },
            "hit_count_effect": hit_count_stats,
            "advice_effect": advice_stats,
            "pilot_zone_effect": pilot_zone_stats,
            "weak_block_filter_effect": weak_block_stats,
        },
    }


def save_priority_history_report(report: Dict[str, Any], base_dir: Optional[Path] = None) -> Path:
    return _save_json(_priority_history_path(base_dir), report)


def save_factor_analysis_report(report: Dict[str, Any], base_dir: Optional[Path] = None) -> Path:
    return _save_json(_factor_analysis_path(base_dir), report)


def load_priority_reports(base_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    reports_dir = _reports_dir(base_dir)
    reports: List[Dict[str, Any]] = []
    for path in sorted(reports_dir.glob("*-priority.json")):
        stem = path.stem
        if not stem.endswith("-priority"):
            continue
        date_str = stem[:-9]
        if not DATE_PATTERN.match(date_str):
            continue
        reports.append(_load_json(path, required=True) or {})
    return reports


def load_universe_reports_by_date(base_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    reports_dir = _reports_dir(base_dir)
    universe_reports: Dict[str, Dict[str, Any]] = {}
    for path in sorted(reports_dir.glob("*-universe.json")):
        stem = path.stem
        if not stem.endswith("-universe"):
            continue
        date_str = stem[:-9]
        if not DATE_PATTERN.match(date_str):
            continue
        universe_reports[date_str] = _load_json(path, required=True) or {}
    return universe_reports


def generate_priority_history_from_reports(base_dir: Optional[Path] = None, market_prices: Optional[Any] = None) -> Path:
    report = generate_priority_history_report(load_priority_reports(base_dir=base_dir), market_prices=market_prices)
    return save_priority_history_report(report, base_dir=base_dir)


def generate_factor_analysis_from_reports(base_dir: Optional[Path] = None, market_prices: Optional[Any] = None) -> Path:
    report = generate_factor_analysis_report(
        load_priority_reports(base_dir=base_dir),
        market_prices=market_prices,
        universe_reports_by_date=load_universe_reports_by_date(base_dir=base_dir),
    )
    return save_factor_analysis_report(report, base_dir=base_dir)


def backfill_priority_validation_reports(
    base_dir: Optional[Path] = None,
    refresh_context: bool = False,
    target_date: Optional[str] = None,
    min_evaluated_days: int = MIN_EVALUATED_DAYS,
    auto_backfill_history: Optional[bool] = None,
    market_prices: Optional[Any] = None,
) -> Dict[str, Any]:
    reports_dir = _reports_dir(base_dir)
    ensured_context_paths: List[str] = []
    priority_paths: List[str] = []
    skipped: List[Dict[str, str]] = []
    history_window: Optional[Dict[str, Any]] = None

    if auto_backfill_history is None:
        auto_backfill_history = base_dir is None

    if auto_backfill_history:
        history_window = ensure_historical_report_window(
            min_available_dates=min_evaluated_days + 1,
            end_date=target_date,
            base_dir=base_dir,
        )

    for date_str in _iter_daily_report_dates(reports_dir):
        if not (reports_dir / f"{date_str}-universe.json").exists():
            skipped.append({
                "date": date_str,
                "reason": "缺少 universe 報告，無法回放完整排序。",
            })
            continue
        try:
            path = ensure_context_report(date_str, base_dir=base_dir, refresh=refresh_context)
            ensured_context_paths.append(str(path))
        except FileNotFoundError as exc:
            skipped.append({
                "date": date_str,
                "reason": str(exc),
            })

    available_dates = _available_priority_dates(reports_dir)
    for index, date_str in enumerate(available_dates):
        next_date = available_dates[index + 1] if index + 1 < len(available_dates) else None
        try:
            path = generate_priority_snapshot_from_files(
                date_str,
                base_dir=base_dir,
                next_date=next_date,
                refresh_context=False,
            )
            priority_paths.append(str(path))
        except FileNotFoundError as exc:
            skipped.append({
                "date": date_str,
                "reason": str(exc),
            })

    history_path = generate_priority_history_from_reports(base_dir=base_dir, market_prices=market_prices)
    factor_analysis_path = generate_factor_analysis_from_reports(base_dir=base_dir, market_prices=market_prices)
    history_report = _load_json(Path(history_path), required=True) or {}
    evaluated_days = (((history_report.get("stats") or {}).get("validation_readiness") or {}).get("evaluated_days"))
    current_date = target_date or (available_dates[-1] if available_dates else None)

    return {
        "available_dates": available_dates,
        "evaluated_days": evaluated_days,
        "ensured_context_paths": ensured_context_paths,
        "priority_paths": priority_paths,
        "history_path": str(history_path),
        "factor_analysis_path": str(factor_analysis_path),
        "current_context_path": str(reports_dir / f"{current_date}-context.json") if current_date else None,
        "current_priority_path": str(_priority_report_path(current_date, base_dir)) if current_date else None,
        "history_window": history_window,
        "skipped": skipped,
    }