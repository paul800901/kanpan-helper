"""v21 排序驗證層：每日 priority 快照、單因子、組合、策略與訊號密度分析。"""

from __future__ import annotations

from datetime import datetime
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
FACTOR_ANALYSIS_REPORT_VERSION = "v18-factor-analysis"
FACTOR_COMBINATION_ANALYSIS_REPORT_VERSION = "v15-factor-combination-analysis"
STRATEGY_ANALYSIS_REPORT_VERSION = "v19-strategy-analysis"
SIGNAL_DENSITY_REPORT_VERSION = "v17-signal-density-analysis"
STEADY_V2_BLOCKER_REPORT_VERSION = "v20-steady-v2-blockers"
TIMING_ALIGNMENT_REPORT_VERSION = "v21-timing-alignment"
SORT_RULE_DESCRIPTION = "先比命中情境數，再比技術面狀態，最後比區間位置（試單區優先）；同分保留原出現順序。"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_EVALUATED_DAYS = 20
MA20_V2_BAND_PCT = 0.02
MA20_V2_RECENT_BREAK_LOOKBACK = 3
TIMING_ALIGNMENT_LOOKAHEAD_DAYS = [1, 2, 3]

CONDITION_DEFINITIONS = {
    "ma20_break": {
        "label": "MA20 條件",
        "description": "剛跌破 MA20",
    },
    "kd_low_turn_up": {
        "label": "KD 條件",
        "description": "KD 低檔翻揚",
    },
    "low_position": {
        "label": "低位條件",
        "description": "低位因子",
    },
}
CONDITION_ORDER = {name: index for index, name in enumerate(CONDITION_DEFINITIONS.keys())}

STEADY_V2_BLOCKER_CONDITION_DEFINITIONS = {
    "ma20_v2": {
        "label": "MA20_v2 條件",
        "description": "接近 MA20 區間 / 最近 3 日內跌破",
    },
    "kd_low_turn_up": CONDITION_DEFINITIONS["kd_low_turn_up"],
    "low_position": CONDITION_DEFINITIONS["low_position"],
}
STEADY_V2_BLOCKER_CONDITION_ORDER = {
    name: index for index, name in enumerate(STEADY_V2_BLOCKER_CONDITION_DEFINITIONS.keys())
}

STRATEGY_DEFINITIONS = {
    "sniper": {
        "label": "狙擊型",
        "style_focus": "高報酬",
        "description": "剛跌破 MA20 + 低位因子",
        "selection_hint": "偏攻擊，樣本較少，但成立時平均報酬較高。",
        "combination_source": "just_break_ma20_plus_low_position_ma20",
        "condition_names": ["ma20_break", "low_position"],
        "factor_names": ["just_break_ma20", "low_position_ma20"],
        "family": "sniper",
        "generation": "v1",
    },
    "steady": {
        "label": "穩定型",
        "style_focus": "穩定",
        "description": "KD 低檔翻揚 + 低位因子",
        "selection_hint": "偏穩健，平均報酬較平，但勝率通常較高。",
        "combination_source": "low_k_turn_up_plus_low_position_ma20",
        "condition_names": ["kd_low_turn_up", "low_position"],
        "factor_names": ["low_k_turn_up", "low_position_ma20"],
        "family": "steady",
        "generation": "v1",
    },
}

STRATEGY_V2_DEFINITIONS = {
    "sniper_v2": {
        "label": "狙擊型 v2",
        "style_focus": "高報酬",
        "description": "MA20_v2 + 低位因子",
        "selection_hint": "把 MA20 擴成區間條件，提高命中密度，但平均報酬通常會比舊狙擊型更平。",
        "factor_names": ["ma20_v2", "low_position_ma20"],
        "family": "sniper",
        "generation": "v2",
    },
    "steady_v2": {
        "label": "穩定型 v2",
        "style_focus": "穩定",
        "description": "MA20_v2 + KD 低檔翻揚",
        "selection_hint": "保留 KD 低檔翻揚，但把 MA20 改成區間條件，優先提升可用樣本。",
        "factor_names": ["ma20_v2", "low_k_turn_up"],
        "family": "steady",
        "generation": "v2",
    },
}

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


def _factor_combination_analysis_path(base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / "factor_combination_analysis.json"


def _strategy_analysis_path(base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / "strategy_analysis.json"


def _signal_density_path(base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / "signal_density.json"


def _steady_v2_blockers_path(base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / "steady_v2_blockers.json"


def _timing_alignment_path(base_dir: Optional[Path] = None) -> Path:
    return _reports_dir(base_dir) / "timing_alignment.json"


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
    universe_lookup_by_date = {
        str(report.get("date") or ""): {
            str(stock.get("symbol") or ""): stock
            for stock in ((((universe_reports_by_date or {}).get(str(report.get("date") or "")) or {}).get("stocks") or []))
        }
        for report in ordered_reports
        if str(report.get("date") or "")
    }

    for index, report in enumerate(ordered_reports):
        previous_date = str(ordered_reports[index - 1].get("date") or "") if index > 0 else None
        current_date = str(report.get("date") or "")
        current_universe_lookup = universe_lookup_by_date.get(current_date, {})
        previous_universe_lookup = universe_lookup_by_date.get(previous_date or "", {})
        recent_dates = [
            str(ordered_reports[lookback_index].get("date") or "")
            for lookback_index in range(max(0, index - (MA20_V2_RECENT_BREAK_LOOKBACK - 1)), index + 1)
            if str(ordered_reports[lookback_index].get("date") or "")
        ]
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
                "recent_universe_history": [
                    {
                        "date": history_date,
                        "stock": (universe_lookup_by_date.get(history_date) or {}).get(symbol),
                    }
                    for history_date in recent_dates
                ],
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


def _ma20_gap_pct(sample: Dict[str, Any]) -> Optional[float]:
    close = _candidate_metric(sample, "close")
    ma20 = _candidate_metric(sample, "ma20")
    if close is None or ma20 in (None, 0):
        return None
    return (close - ma20) / ma20


def _collect_ma20_gap_samples(samples: List[Dict[str, Any]]) -> List[tuple[Dict[str, Any], float]]:
    valued_samples: List[tuple[Dict[str, Any], float]] = []
    for sample in samples:
        gap_pct = _ma20_gap_pct(sample)
        if gap_pct is None:
            continue
        valued_samples.append((sample, gap_pct))
    return valued_samples


def _low_position_cutoffs(samples: List[Dict[str, Any]]) -> tuple[List[tuple[Dict[str, Any], float]], Optional[float], Optional[float]]:
    valued_samples = _collect_ma20_gap_samples(samples)
    if not valued_samples:
        return valued_samples, None, None

    ordered_values = sorted(value for _, value in valued_samples)
    first_cut = ordered_values[len(ordered_values) // 3]
    second_cut = ordered_values[(len(ordered_values) * 2) // 3]
    return valued_samples, first_cut, second_cut


def _is_low_position_sample(sample: Dict[str, Any], lower_third_cutoff: Optional[float]) -> bool:
    gap_pct = _ma20_gap_pct(sample)
    if gap_pct is None or lower_third_cutoff is None:
        return False
    return gap_pct <= lower_third_cutoff


def _is_just_break_ma20(sample: Dict[str, Any]) -> bool:
    previous_close = _previous_metric(sample, "close")
    previous_ma20 = _previous_metric(sample, "ma20")
    current_close = _candidate_metric(sample, "close")
    current_ma20 = _candidate_metric(sample, "ma20")
    return (
        previous_close is not None
        and previous_ma20 not in (None, 0)
        and current_close is not None
        and current_ma20 not in (None, 0)
        and previous_close >= previous_ma20
        and current_close < current_ma20
    )


def _recent_ma20_history(sample: Dict[str, Any]) -> List[Dict[str, float]]:
    history_entries = list(sample.get("recent_universe_history") or [])
    if not history_entries:
        history_entries = [
            {
                "date": sample.get("previous_date"),
                "stock": sample.get("previous_universe_stock"),
            },
            {
                "date": sample.get("date"),
                "stock": sample.get("current_universe_stock"),
            },
        ]

    history: List[Dict[str, float]] = []
    for entry in history_entries:
        indicators = ((entry.get("stock") or {}).get("indicators") or {})
        close = _as_float(indicators.get("close"))
        ma20 = _as_float(indicators.get("ma20"))
        if close is None or ma20 in (None, 0):
            continue
        history.append({
            "close": close,
            "ma20": ma20,
        })
    return history


def _is_near_ma20_band(sample: Dict[str, Any]) -> bool:
    gap_pct = _ma20_gap_pct(sample)
    if gap_pct is None:
        return False
    return abs(gap_pct) <= MA20_V2_BAND_PCT


def _has_recent_ma20_break(sample: Dict[str, Any]) -> bool:
    history = _recent_ma20_history(sample)
    if len(history) < 2:
        return False

    recent_history = history[-MA20_V2_RECENT_BREAK_LOOKBACK:]
    return any(
        previous_state["close"] >= previous_state["ma20"] and current_state["close"] < current_state["ma20"]
        for previous_state, current_state in zip(recent_history, recent_history[1:])
    )


def _is_ma20_v2(sample: Dict[str, Any]) -> bool:
    return _is_near_ma20_band(sample) or _has_recent_ma20_break(sample)


def _is_retest_ma20(sample: Dict[str, Any]) -> bool:
    previous_close = _previous_metric(sample, "close")
    previous_ma20 = _previous_metric(sample, "ma20")
    current_close = _candidate_metric(sample, "close")
    current_ma20 = _candidate_metric(sample, "ma20")
    return (
        previous_close is not None
        and previous_ma20 not in (None, 0)
        and current_close is not None
        and current_ma20 not in (None, 0)
        and previous_close > previous_ma20
        and current_close >= current_ma20
        and abs((current_close - current_ma20) / current_ma20) <= 0.01
    )


def _is_volume_expand_after_shrink(sample: Dict[str, Any]) -> bool:
    previous_volume_ratio = _previous_metric(sample, "volume_ratio")
    current_volume_ratio = _candidate_metric(sample, "volume_ratio")
    return (
        previous_volume_ratio is not None
        and current_volume_ratio is not None
        and previous_volume_ratio < 1
        and current_volume_ratio >= 1.2
    )


def _is_low_k_turn_up(sample: Dict[str, Any]) -> bool:
    previous_k = _previous_metric(sample, "k")
    current_k = _candidate_metric(sample, "k")
    return (
        previous_k is not None
        and current_k is not None
        and current_k < 30
        and current_k > previous_k
    )


def _build_low_position_ma20_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    valued_samples, first_cut, second_cut = _low_position_cutoffs(samples)

    if not valued_samples:
        return _build_factor_section("low_position_ma20", "低位因子", [])

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
        _is_just_break_ma20,
    )


def _build_ma20_v2_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "ma20_v2",
        "回檔因子：接近 MA20 區間",
        "接近 MA20 / 3 日內跌破組",
        "非 MA20_v2 組",
        _is_ma20_v2,
    )


def _build_retest_ma20_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "retest_ma20",
        "回檔因子：剛回測 MA20",
        "剛回測組",
        "非剛回測組",
        _is_retest_ma20,
    )


def _build_volume_expand_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "volume_expand_after_shrink",
        "量縮後放量",
        "量縮後放量組",
        "其他量能組",
        _is_volume_expand_after_shrink,
    )


def _build_low_k_turn_factor(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_boolean_factor(
        samples,
        "low_k_turn_up",
        "KD 低檔翻揚",
        "低檔翻揚組",
        "非低檔翻揚組",
        _is_low_k_turn_up,
    )


def _build_positive_factor_baseline(
    factor_name: str,
    factor_label: str,
    positive_group_label: str,
    samples: List[Dict[str, Any]],
    predicate: Callable[[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    values = [sample["return_pct"] for sample in samples if predicate(sample)]
    return {
        "factor": factor_name,
        "label": factor_label,
        "positive_group_label": positive_group_label,
        "sample_count": len(values),
        "avg_return_pct": _mean(values),
        "win_rate_pct": _win_rate(values),
    }


def _build_factor_variant_summary(
    factor_name: str,
    factor_label: str,
    positive_group_label: str,
    samples: List[Dict[str, Any]],
    predicate: Callable[[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    values = [sample["return_pct"] for sample in samples if predicate(sample)]
    total_samples = len(samples)
    sample_count = len(values)
    return {
        "factor": factor_name,
        "label": factor_label,
        "positive_group_label": positive_group_label,
        "sample_count": sample_count,
        "total_sample_count": total_samples,
        "pass_rate_pct": _round_number((sample_count / total_samples) * 100) if total_samples else None,
        "avg_return_pct": _mean(values),
        "win_rate_pct": _win_rate(values),
    }


def _build_ma20_variant_comparison(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    old_ma20 = _build_factor_variant_summary(
        "just_break_ma20",
        "舊 MA20：剛跌破 MA20",
        "剛跌破組",
        samples,
        _is_just_break_ma20,
    )
    ma20_v2 = _build_factor_variant_summary(
        "ma20_v2",
        "新 MA20：接近 MA20 區間",
        "接近 MA20 / 3 日內跌破組",
        samples,
        _is_ma20_v2,
    )

    pass_rate_over_10 = bool((ma20_v2.get("pass_rate_pct") or 0) > 10)
    positive_avg_return = bool((ma20_v2.get("avg_return_pct") or 0) > 0)
    if pass_rate_over_10 and positive_avg_return:
        verdict = "達標"
    elif pass_rate_over_10:
        verdict = "通過率達標，但報酬未維持正向"
    elif positive_avg_return:
        verdict = "報酬維持正向，但通過率未達標"
    else:
        verdict = "未達標"

    return {
        "definition": {
            "metric": "close 相對 MA20 的距離",
            "band_pct": _round_number(MA20_V2_BAND_PCT * 100, digits=2),
            "recent_break_lookback_days": MA20_V2_RECENT_BREAK_LOOKBACK,
            "logic": "close 在 MA20 ±2% 內，或最近 3 個交易日內出現由上往下跌破 MA20。",
        },
        "variants": {
            "just_break_ma20": old_ma20,
            "ma20_v2": ma20_v2,
        },
        "pass_rate_lift_pct": _safe_diff(ma20_v2.get("pass_rate_pct"), old_ma20.get("pass_rate_pct")),
        "avg_return_lift_pct": _safe_diff(ma20_v2.get("avg_return_pct"), old_ma20.get("avg_return_pct")),
        "win_rate_lift_pct": _safe_diff(ma20_v2.get("win_rate_pct"), old_ma20.get("win_rate_pct")),
        "requirements": {
            "pass_rate_over_10_pct": pass_rate_over_10,
            "positive_avg_return": positive_avg_return,
        },
        "verdict": verdict,
    }


def _build_factor_combination_summary(
    combination_name: str,
    combination_label: str,
    samples: List[Dict[str, Any]],
    predicate: Callable[[Dict[str, Any]], bool],
    constituent_factor_names: List[str],
    single_factor_baselines: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    values = [sample["return_pct"] for sample in samples if predicate(sample)]
    avg_return = _mean(values)
    constituent_baselines = [single_factor_baselines[name] for name in constituent_factor_names if name in single_factor_baselines]
    valid_baselines = [item for item in constituent_baselines if item.get("avg_return_pct") is not None]
    best_single_factor = max(valid_baselines, key=lambda item: item["avg_return_pct"]) if valid_baselines else None

    beats_constituent_single_factors: Optional[bool] = None
    avg_return_edge_vs_best_single_factor: Optional[float] = None
    if avg_return is not None and valid_baselines:
        beats_constituent_single_factors = all(avg_return > float(item["avg_return_pct"]) for item in valid_baselines)
        avg_return_edge_vs_best_single_factor = _safe_diff(avg_return, best_single_factor.get("avg_return_pct") if best_single_factor else None)

    verdict = "資料不足"
    if avg_return is not None:
        verdict = "優於單因子" if beats_constituent_single_factors else "未優於單因子"

    return {
        "combination": combination_name,
        "label": combination_label,
        "factor_names": constituent_factor_names,
        "sample_count": len(values),
        "avg_return_pct": avg_return,
        "win_rate_pct": _win_rate(values),
        "constituent_single_factors": constituent_baselines,
        "best_single_factor": best_single_factor,
        "avg_return_edge_vs_best_single_factor": avg_return_edge_vs_best_single_factor,
        "beats_constituent_single_factors": beats_constituent_single_factors,
        "verdict": verdict,
    }


def _summarize_factor_combination(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not item:
        return None
    return {
        "combination": item["combination"],
        "label": item["label"],
        "factor_names": item["factor_names"],
        "sample_count": item["sample_count"],
        "avg_return_pct": item["avg_return_pct"],
        "win_rate_pct": item["win_rate_pct"],
        "avg_return_edge_vs_best_single_factor": item["avg_return_edge_vs_best_single_factor"],
        "beats_constituent_single_factors": item["beats_constituent_single_factors"],
        "best_single_factor": item["best_single_factor"],
        "verdict": item["verdict"],
    }


def _build_strategy_summary(
    strategy_name: str,
    definition: Dict[str, str],
    source_summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = source_summary or {}
    hit_count = int(summary.get("sample_count") or 0)
    return {
        "strategy": strategy_name,
        "label": definition["label"],
        "style_focus": definition["style_focus"],
        "description": definition["description"],
        "selection_hint": definition["selection_hint"],
        "family": definition.get("family") or strategy_name,
        "generation": definition.get("generation") or "v1",
        "combination_source": definition.get("combination_source"),
        "factor_names": list(summary.get("factor_names") or definition.get("factor_names") or []),
        "sample_count": hit_count,
        "hit_count": hit_count,
        "avg_return_pct": summary.get("avg_return_pct"),
        "win_rate_pct": summary.get("win_rate_pct"),
        "avg_return_edge_vs_best_single_factor": summary.get("avg_return_edge_vs_best_single_factor"),
        "beats_constituent_single_factors": summary.get("beats_constituent_single_factors"),
        "best_single_factor": summary.get("best_single_factor"),
        "verdict": summary.get("verdict") or "資料不足",
    }


def _summarize_strategy(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not item:
        return None
    return {
        "strategy": item["strategy"],
        "label": item["label"],
        "style_focus": item["style_focus"],
        "description": item["description"],
        "selection_hint": item["selection_hint"],
        "family": item.get("family"),
        "generation": item.get("generation"),
        "factor_names": list(item.get("factor_names") or []),
        "hit_count": item.get("hit_count"),
        "sample_count": item["sample_count"],
        "avg_return_pct": item["avg_return_pct"],
        "win_rate_pct": item["win_rate_pct"],
        "avg_return_edge_vs_best_single_factor": item["avg_return_edge_vs_best_single_factor"],
        "beats_constituent_single_factors": item["beats_constituent_single_factors"],
        "best_single_factor": item["best_single_factor"],
        "verdict": item["verdict"],
    }


def _sample_matches_factor(
    sample: Dict[str, Any],
    factor_name: str,
    lower_third_cutoff: Optional[float],
) -> bool:
    if factor_name == "just_break_ma20":
        return _is_just_break_ma20(sample)
    if factor_name == "ma20_v2":
        return _is_ma20_v2(sample)
    if factor_name == "low_position_ma20":
        return _is_low_position_sample(sample, lower_third_cutoff)
    if factor_name == "low_k_turn_up":
        return _is_low_k_turn_up(sample)
    raise KeyError(f"未支援的策略因子：{factor_name}")


def _build_strategy_variant_summary(
    strategy_name: str,
    definition: Dict[str, Any],
    samples: List[Dict[str, Any]],
    single_factor_baselines: Dict[str, Dict[str, Any]],
    lower_third_cutoff: Optional[float],
) -> Dict[str, Any]:
    factor_names = list(definition.get("factor_names") or [])
    source_summary = _build_factor_combination_summary(
        strategy_name,
        definition["description"],
        samples,
        lambda sample: all(
            _sample_matches_factor(sample, factor_name, lower_third_cutoff)
            for factor_name in factor_names
        ),
        factor_names,
        single_factor_baselines,
    )
    return _build_strategy_summary(strategy_name, definition, source_summary)


def _build_strategy_variant_comparison(
    family_name: str,
    family_label: str,
    v1_strategy: Optional[Dict[str, Any]],
    v2_strategy: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    v1_hit_count = int((v1_strategy or {}).get("hit_count") or 0)
    v2_hit_count = int((v2_strategy or {}).get("hit_count") or 0)
    v2_avg_return_positive = ((v2_strategy or {}).get("avg_return_pct") or 0) > 0
    v2_hit_count_increase = v2_hit_count > v1_hit_count

    return {
        "family": family_name,
        "label": family_label,
        "v1": _summarize_strategy(v1_strategy),
        "v2": _summarize_strategy(v2_strategy),
        "hit_count_delta": v2_hit_count - v1_hit_count,
        "hit_count_ratio": _round_number(v2_hit_count / v1_hit_count) if v1_hit_count else None,
        "avg_return_delta_pct": _safe_diff(
            (v2_strategy or {}).get("avg_return_pct"),
            (v1_strategy or {}).get("avg_return_pct"),
        ),
        "win_rate_delta_pct": _safe_diff(
            (v2_strategy or {}).get("win_rate_pct"),
            (v1_strategy or {}).get("win_rate_pct"),
        ),
        "v2_hit_count_increase": v2_hit_count_increase,
        "v2_avg_return_positive": v2_avg_return_positive,
        "meets_v19_goal": v2_hit_count_increase and v2_avg_return_positive,
    }


def _iso_week_key(date_str: str) -> str:
    iso = datetime.strptime(date_str, "%Y-%m-%d").isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _build_signal_sample_days(
    priority_reports: List[Dict[str, Any]],
    universe_reports_by_date: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    ordered_reports = sorted(priority_reports, key=lambda item: str(item.get("date") or ""))
    sample_days: List[Dict[str, Any]] = []

    for index, report in enumerate(ordered_reports):
        previous_date = str(ordered_reports[index - 1].get("date") or "") if index > 0 else None
        current_date = str(report.get("date") or "")
        current_universe = ((universe_reports_by_date or {}).get(current_date) or {}).get("stocks") or []
        previous_universe = ((universe_reports_by_date or {}).get(previous_date or "") or {}).get("stocks") or []
        current_universe_lookup = {str(stock.get("symbol") or ""): stock for stock in current_universe}
        previous_universe_lookup = {str(stock.get("symbol") or ""): stock for stock in previous_universe}

        samples: List[Dict[str, Any]] = []
        for candidate in report.get("candidates") or []:
            symbol = str(candidate.get("symbol") or "")
            samples.append({
                "date": current_date,
                "previous_date": previous_date,
                "candidate": candidate,
                "current_universe_stock": current_universe_lookup.get(symbol),
                "previous_universe_stock": previous_universe_lookup.get(symbol),
            })

        sample_days.append({
            "date": current_date,
            "previous_date": previous_date,
            "candidate_count": len(samples),
            "previous_universe_available": bool(previous_universe_lookup),
            "samples": samples,
        })

    return sample_days


def _build_signal_condition_flags(sample: Dict[str, Any], lower_third_cutoff: Optional[float]) -> Dict[str, bool]:
    return {
        "ma20_break": _is_just_break_ma20(sample),
        "kd_low_turn_up": _is_low_k_turn_up(sample),
        "low_position": _is_low_position_sample(sample, lower_third_cutoff),
    }


def _build_signal_condition_summary(condition_name: str, pass_count: int, candidate_count: int) -> Dict[str, Any]:
    definition = CONDITION_DEFINITIONS.get(condition_name) or {}
    fail_count = max(candidate_count - int(pass_count), 0)
    pass_rate = _round_number((pass_count / candidate_count) * 100) if candidate_count else None
    return {
        "condition": condition_name,
        "label": definition.get("label") or condition_name,
        "description": definition.get("description") or condition_name,
        "candidate_count": candidate_count,
        "pass_count": int(pass_count),
        "fail_count": fail_count,
        "pass_rate_pct": pass_rate,
    }


def _build_named_condition_summary(
    condition_name: str,
    pass_count: int,
    candidate_count: int,
    definitions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    definition = definitions.get(condition_name) or {}
    fail_count = max(candidate_count - int(pass_count), 0)
    pass_rate = _round_number((pass_count / candidate_count) * 100) if candidate_count else None
    fail_rate = _round_number((fail_count / candidate_count) * 100) if candidate_count else None
    return {
        "condition": condition_name,
        "label": definition.get("label") or condition_name,
        "description": definition.get("description") or condition_name,
        "candidate_count": candidate_count,
        "pass_count": int(pass_count),
        "fail_count": fail_count,
        "pass_rate_pct": pass_rate,
        "block_rate_pct": fail_rate,
    }


def _rank_signal_condition_summaries(
    items: Iterable[Dict[str, Any]],
    order_lookup: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    order_map = order_lookup or CONDITION_ORDER
    return sorted(
        list(items),
        key=lambda item: (
            item.get("pass_rate_pct") if item.get("pass_rate_pct") is not None else float("inf"),
            item.get("pass_count") if item.get("pass_count") is not None else float("inf"),
            order_map.get(str(item.get("condition") or ""), 999),
        ),
    )


def _build_condition_intersection_summary(
    condition_names: List[str],
    flags_by_sample: List[Dict[str, bool]],
    condition_summaries: Dict[str, Dict[str, Any]],
    definitions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    candidate_count = len(flags_by_sample)
    pass_count = sum(
        1 for flags in flags_by_sample
        if all(flags.get(condition_name) for condition_name in condition_names)
    )
    fail_count = max(candidate_count - pass_count, 0)
    within_condition_pass_rates = {}
    for condition_name in condition_names:
        base_pass_count = int((condition_summaries.get(condition_name) or {}).get("pass_count") or 0)
        within_condition_pass_rates[condition_name] = (
            _round_number((pass_count / base_pass_count) * 100)
            if base_pass_count else None
        )

    return {
        "intersection": "__".join(condition_names),
        "condition_names": list(condition_names),
        "labels": [definitions.get(name, {}).get("label") or name for name in condition_names],
        "candidate_count": candidate_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "overall_pass_rate_pct": _round_number((pass_count / candidate_count) * 100) if candidate_count else None,
        "block_rate_pct": _round_number((fail_count / candidate_count) * 100) if candidate_count else None,
        "within_condition_pass_rates": within_condition_pass_rates,
    }


def _build_steady_v2_condition_flags(sample: Dict[str, Any], lower_third_cutoff: Optional[float]) -> Dict[str, bool]:
    return {
        "ma20_v2": _is_ma20_v2(sample),
        "kd_low_turn_up": _is_low_k_turn_up(sample),
        "low_position": _is_low_position_sample(sample, lower_third_cutoff),
    }


def generate_steady_v2_blockers_report(
    priority_reports: List[Dict[str, Any]],
    market_prices: Optional[Any] = None,
    universe_reports_by_date: Optional[Dict[str, Dict[str, Any]]] = None,
    strategy_analysis_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ordered_reports = sorted(priority_reports, key=lambda item: str(item.get("date") or ""))
    strategy_report = strategy_analysis_report or generate_strategy_analysis_report(
        ordered_reports,
        market_prices=market_prices,
        universe_reports_by_date=universe_reports_by_date,
    )
    market_lookup = _normalize_market_prices(market_prices) if market_prices is not None else _fetch_market_price_lookup(ordered_reports)
    trading_samples, evaluated_days = _collect_trading_interval_candidates(
        ordered_reports,
        market_lookup,
        universe_reports_by_date=universe_reports_by_date,
    )

    low_position_definition = strategy_report.get("low_position_definition") or {}
    lower_third_cutoff = _as_float(low_position_definition.get("lower_third_cutoff"))
    flags_by_sample = [
        _build_steady_v2_condition_flags(sample, lower_third_cutoff)
        for sample in trading_samples
    ]
    pass_counts = {
        condition_name: sum(1 for flags in flags_by_sample if flags.get(condition_name))
        for condition_name in STEADY_V2_BLOCKER_CONDITION_DEFINITIONS.keys()
    }
    condition_summaries = {
        condition_name: _build_named_condition_summary(
            condition_name,
            pass_count,
            len(trading_samples),
            STEADY_V2_BLOCKER_CONDITION_DEFINITIONS,
        )
        for condition_name, pass_count in pass_counts.items()
    }
    ranked_conditions = _rank_signal_condition_summaries(
        condition_summaries.values(),
        order_lookup=STEADY_V2_BLOCKER_CONDITION_ORDER,
    )
    strictest_conditions = _co_strictest_conditions(ranked_conditions)
    overall_strictest_condition = strictest_conditions[0] if strictest_conditions else (ranked_conditions[0] if ranked_conditions else None)

    pairwise_intersections = {
        "ma20_v2__kd_low_turn_up": _build_condition_intersection_summary(
            ["ma20_v2", "kd_low_turn_up"],
            flags_by_sample,
            condition_summaries,
            STEADY_V2_BLOCKER_CONDITION_DEFINITIONS,
        ),
        "ma20_v2__low_position": _build_condition_intersection_summary(
            ["ma20_v2", "low_position"],
            flags_by_sample,
            condition_summaries,
            STEADY_V2_BLOCKER_CONDITION_DEFINITIONS,
        ),
        "kd_low_turn_up__low_position": _build_condition_intersection_summary(
            ["kd_low_turn_up", "low_position"],
            flags_by_sample,
            condition_summaries,
            STEADY_V2_BLOCKER_CONDITION_DEFINITIONS,
        ),
    }
    all_three_intersection = _build_condition_intersection_summary(
        ["ma20_v2", "kd_low_turn_up", "low_position"],
        flags_by_sample,
        condition_summaries,
        STEADY_V2_BLOCKER_CONDITION_DEFINITIONS,
    )

    condition_breakdown = {
        condition_name: {
            **summary,
            "intersections": {
                other_condition: pairwise_intersections["__".join(sorted([condition_name, other_condition], key=lambda item: STEADY_V2_BLOCKER_CONDITION_ORDER[item]))]
                for other_condition in STEADY_V2_BLOCKER_CONDITION_DEFINITIONS.keys()
                if other_condition != condition_name
            },
            "all_conditions": all_three_intersection,
        }
        for condition_name, summary in condition_summaries.items()
    }

    strategy_snapshot = ((strategy_report.get("strategy_variant_comparison") or {}).get("steady") or {})
    kd_base_count = int((condition_summaries.get("kd_low_turn_up") or {}).get("pass_count") or 0)
    old_steady_hit_count = int((((strategy_snapshot.get("v1") or {}).get("hit_count")) or 0))
    new_steady_hit_count = int((((strategy_snapshot.get("v2") or {}).get("hit_count")) or 0))
    low_position_on_kd = int((pairwise_intersections["kd_low_turn_up__low_position"].get("pass_count") or 0))
    ma20_v2_on_kd = int((pairwise_intersections["ma20_v2__kd_low_turn_up"].get("pass_count") or 0))
    lost_from_v1 = max(old_steady_hit_count - new_steady_hit_count, 0)
    transition_bottleneck_condition = (
        condition_summaries.get("ma20_v2")
        if ma20_v2_on_kd <= low_position_on_kd
        else condition_summaries.get("low_position")
    )

    summary = (
        f"steady_v2 的主要 bottleneck 是 {transition_bottleneck_condition['label']}："
        f"在 KD 條件通過的 {kd_base_count} 個樣本裡，"
        f"低位條件可保留 {low_position_on_kd} 個，但 MA20_v2 只保留 {ma20_v2_on_kd} 個，"
        f"因此 steady 從 {old_steady_hit_count} 檔降到 {new_steady_hit_count} 檔。"
    ) if transition_bottleneck_condition and kd_base_count else "資料不足，無法判定 steady_v2 bottleneck。"

    return {
        "report_version": STEADY_V2_BLOCKER_REPORT_VERSION,
        "generated_at": get_taiwan_now().isoformat(),
        "evaluation_horizon": strategy_report.get("evaluation_horizon"),
        "evaluated_days": evaluated_days,
        "candidate_samples": len(trading_samples),
        "strategy_target": {
            "family": "steady",
            "v1_strategy": "steady",
            "v2_strategy": "steady_v2",
            "v2_condition_names": ["ma20_v2", "kd_low_turn_up"],
            "comparison_condition_names": ["ma20_v2", "kd_low_turn_up", "low_position"],
        },
        "low_position_definition": low_position_definition,
        "condition_names": list(STEADY_V2_BLOCKER_CONDITION_DEFINITIONS.keys()),
        "condition_definitions": STEADY_V2_BLOCKER_CONDITION_DEFINITIONS,
        "conditions": condition_summaries,
        "condition_breakdown": condition_breakdown,
        "ranking_by_strictness": ranked_conditions,
        "pairwise_intersections": pairwise_intersections,
        "all_three_intersection": all_three_intersection,
        "strategy_variant_snapshot": strategy_snapshot,
        "bottleneck_summary": {
            "overall_strictest_condition": overall_strictest_condition,
            "overall_strictest_conditions": strictest_conditions,
            "steady_v2_required_condition_intersection": pairwise_intersections["ma20_v2__kd_low_turn_up"],
            "transition_from_v1_to_v2": {
                "shared_base_condition": condition_summaries.get("kd_low_turn_up"),
                "old_secondary_condition_on_shared_base": {
                    "condition": "low_position",
                    "label": STEADY_V2_BLOCKER_CONDITION_DEFINITIONS["low_position"]["label"],
                    "pass_count": low_position_on_kd,
                    "pass_rate_within_shared_base_pct": _round_number((low_position_on_kd / kd_base_count) * 100) if kd_base_count else None,
                },
                "new_secondary_condition_on_shared_base": {
                    "condition": "ma20_v2",
                    "label": STEADY_V2_BLOCKER_CONDITION_DEFINITIONS["ma20_v2"]["label"],
                    "pass_count": ma20_v2_on_kd,
                    "pass_rate_within_shared_base_pct": _round_number((ma20_v2_on_kd / kd_base_count) * 100) if kd_base_count else None,
                },
                "lost_hit_count_vs_v1": lost_from_v1,
                "lost_share_vs_v1_pct": _round_number((lost_from_v1 / old_steady_hit_count) * 100) if old_steady_hit_count else None,
                "blocked_share_on_shared_base_pct": _round_number((lost_from_v1 / kd_base_count) * 100) if kd_base_count else None,
                "bottleneck_condition": transition_bottleneck_condition,
            },
            "summary": summary,
        },
    }


def _sorted_universe_dates(universe_reports_by_date: Optional[Dict[str, Dict[str, Any]]]) -> List[str]:
    return sorted(
        str(date_str)
        for date_str in (universe_reports_by_date or {}).keys()
        if DATE_PATTERN.match(str(date_str))
    )


def _build_universe_stock_lookup_by_date(
    universe_reports_by_date: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {
        str(date_str): {
            str(stock.get("symbol") or ""): stock
            for stock in ((report or {}).get("stocks") or [])
        }
        for date_str, report in (universe_reports_by_date or {}).items()
        if DATE_PATTERN.match(str(date_str))
    }


def _stock_indicator_metric(stock: Optional[Dict[str, Any]], metric: str) -> Optional[float]:
    return _as_float((((stock or {}).get("indicators") or {}).get(metric)))


def _stock_close_return_pct(
    current_stock: Optional[Dict[str, Any]],
    next_stock: Optional[Dict[str, Any]],
) -> Optional[float]:
    current_close = _stock_indicator_metric(current_stock, "close")
    next_close = _stock_indicator_metric(next_stock, "close")
    if current_close in (None, 0) or next_close is None:
        return None
    return _round_number(((next_close - current_close) / current_close) * 100)


def _build_universe_alignment_sample(
    symbol: str,
    ordered_dates: List[str],
    universe_lookup_by_date: Dict[str, Dict[str, Dict[str, Any]]],
    date_index: int,
) -> Dict[str, Any]:
    target_date = ordered_dates[date_index]
    previous_date = ordered_dates[date_index - 1] if date_index > 0 else None
    recent_dates = ordered_dates[max(0, date_index - (MA20_V2_RECENT_BREAK_LOOKBACK - 1)):date_index + 1]

    return {
        "date": target_date,
        "previous_date": previous_date,
        "current_universe_stock": (universe_lookup_by_date.get(target_date) or {}).get(symbol),
        "previous_universe_stock": (universe_lookup_by_date.get(previous_date or "") or {}).get(symbol),
        "recent_universe_history": [
            {
                "date": history_date,
                "stock": (universe_lookup_by_date.get(history_date) or {}).get(symbol),
            }
            for history_date in recent_dates
        ],
    }


def generate_timing_alignment_report(
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

    kd_samples = [sample for sample in trading_samples if _is_low_k_turn_up(sample)]
    universe_dates = _sorted_universe_dates(universe_reports_by_date)
    universe_lookup_by_date = _build_universe_stock_lookup_by_date(universe_reports_by_date)
    universe_date_to_index = {date_str: index for index, date_str in enumerate(universe_dates)}

    delay_stats = {
        delay: {
            "available_count": 0,
            "aligned_count": 0,
            "first_alignment_count": 0,
            "aligned_gaps": [],
            "first_alignment_returns": [],
        }
        for delay in TIMING_ALIGNMENT_LOOKAHEAD_DAYS
    }
    first_alignment_counts: Dict[Optional[int], int] = {
        0: 0,
        1: 0,
        2: 0,
        3: 0,
        None: 0,
    }
    event_returns: List[float] = []
    event_closes: List[float] = []
    event_gaps: List[float] = []
    event_samples: List[Dict[str, Any]] = []
    already_in_ma20_v2_count = 0

    for sample in kd_samples:
        current_date = str(sample.get("date") or "")
        symbol = str((sample.get("candidate") or {}).get("symbol") or "")
        current_index = universe_date_to_index.get(current_date)
        if not symbol or current_index is None:
            continue

        event_return = _as_float(sample.get("return_pct"))
        if event_return is not None:
            event_returns.append(event_return)

        event_close = _candidate_metric(sample, "close")
        if event_close is not None:
            event_closes.append(event_close)

        event_gap = _ma20_gap_pct(sample)
        if event_gap is not None:
            event_gaps.append(event_gap)

        event_in_ma20_v2 = _is_ma20_v2(sample)
        if event_in_ma20_v2:
            already_in_ma20_v2_count += 1

        first_alignment_delay: Optional[int] = 0 if event_in_ma20_v2 else None
        lookahead: Dict[str, Dict[str, Any]] = {}

        for delay in TIMING_ALIGNMENT_LOOKAHEAD_DAYS:
            delay_key = f"day_{delay}"
            target_index = current_index + delay
            if target_index >= len(universe_dates):
                lookahead[delay_key] = {
                    "available": False,
                    "date": None,
                    "close": None,
                    "ma20_gap_pct": None,
                    "in_ma20_v2": False,
                    "first_alignment": False,
                    "entry_return_pct": None,
                }
                continue

            target_date = universe_dates[target_index]
            alignment_sample = _build_universe_alignment_sample(symbol, universe_dates, universe_lookup_by_date, target_index)
            target_stock = alignment_sample.get("current_universe_stock")
            available = target_stock is not None
            if available:
                delay_stats[delay]["available_count"] += 1

            in_ma20_v2 = _is_ma20_v2(alignment_sample) if available else False
            target_gap = _ma20_gap_pct(alignment_sample) if available else None
            if in_ma20_v2:
                delay_stats[delay]["aligned_count"] += 1
                if target_gap is not None:
                    delay_stats[delay]["aligned_gaps"].append(target_gap)

            next_stock = None
            if target_index + 1 < len(universe_dates):
                next_stock = (universe_lookup_by_date.get(universe_dates[target_index + 1]) or {}).get(symbol)
            entry_return = _stock_close_return_pct(target_stock, next_stock) if in_ma20_v2 else None

            if first_alignment_delay is None and in_ma20_v2:
                first_alignment_delay = delay
                delay_stats[delay]["first_alignment_count"] += 1
                if entry_return is not None:
                    delay_stats[delay]["first_alignment_returns"].append(entry_return)

            lookahead[delay_key] = {
                "available": available,
                "date": target_date,
                "close": _stock_indicator_metric(target_stock, "close"),
                "ma20_gap_pct": target_gap,
                "in_ma20_v2": in_ma20_v2,
                "first_alignment": False,
                "entry_return_pct": entry_return,
            }

        first_alignment_counts[first_alignment_delay] = first_alignment_counts.get(first_alignment_delay, 0) + 1
        if first_alignment_delay in TIMING_ALIGNMENT_LOOKAHEAD_DAYS:
            lookahead[f"day_{first_alignment_delay}"]["first_alignment"] = True

        event_samples.append({
            "symbol": symbol,
            "date": current_date,
            "event_day": {
                "close": event_close,
                "ma20_gap_pct": event_gap,
                "return_pct": event_return,
                "in_ma20_v2": event_in_ma20_v2,
            },
            "first_alignment_delay_days": first_alignment_delay,
            "lookahead": lookahead,
        })

    kd_event_sample_count = len(event_samples)
    delay_alignment = {
        f"day_{delay}": {
            "delay_days": delay,
            "available_sample_count": stats["available_count"],
            "aligned_count": stats["aligned_count"],
            "aligned_rate_pct": _round_number((stats["aligned_count"] / stats["available_count"]) * 100) if stats["available_count"] else None,
            "first_alignment_count": stats["first_alignment_count"],
            "first_alignment_rate_pct": _round_number((stats["first_alignment_count"] / kd_event_sample_count) * 100) if kd_event_sample_count else None,
            "avg_ma20_gap_pct_when_aligned": _mean(stats["aligned_gaps"]),
            "first_alignment_avg_return_pct": _mean(stats["first_alignment_returns"]),
            "first_alignment_win_rate_pct": _win_rate(stats["first_alignment_returns"]),
            "first_alignment_evaluated_count": len(stats["first_alignment_returns"]),
        }
        for delay, stats in delay_stats.items()
    }

    first_alignment_distribution = {
        "day_0": {
            "delay_days": 0,
            "sample_count": first_alignment_counts.get(0, 0),
            "sample_rate_pct": _round_number((first_alignment_counts.get(0, 0) / kd_event_sample_count) * 100) if kd_event_sample_count else None,
        },
        "day_1": {
            "delay_days": 1,
            "sample_count": first_alignment_counts.get(1, 0),
            "sample_rate_pct": _round_number((first_alignment_counts.get(1, 0) / kd_event_sample_count) * 100) if kd_event_sample_count else None,
        },
        "day_2": {
            "delay_days": 2,
            "sample_count": first_alignment_counts.get(2, 0),
            "sample_rate_pct": _round_number((first_alignment_counts.get(2, 0) / kd_event_sample_count) * 100) if kd_event_sample_count else None,
        },
        "day_3": {
            "delay_days": 3,
            "sample_count": first_alignment_counts.get(3, 0),
            "sample_rate_pct": _round_number((first_alignment_counts.get(3, 0) / kd_event_sample_count) * 100) if kd_event_sample_count else None,
        },
        "no_alignment_within_3d": {
            "delay_days": None,
            "sample_count": first_alignment_counts.get(None, 0),
            "sample_rate_pct": _round_number((first_alignment_counts.get(None, 0) / kd_event_sample_count) * 100) if kd_event_sample_count else None,
        },
    }

    best_alignment_candidates = [
        summary for summary in delay_alignment.values()
        if int(summary.get("first_alignment_count") or 0) > 0
    ]
    best_alignment_delay = None
    if best_alignment_candidates:
        best_alignment_delay = max(
            best_alignment_candidates,
            key=lambda item: (
                int(item.get("first_alignment_count") or 0),
                item.get("first_alignment_rate_pct") if item.get("first_alignment_rate_pct") is not None else float("-inf"),
                -int(item.get("delay_days") or 0),
            ),
        )

    best_delayed_entry_candidates = [
        summary for summary in delay_alignment.values()
        if summary.get("first_alignment_avg_return_pct") is not None
    ]
    best_delayed_entry_timing = None
    if best_delayed_entry_candidates:
        best_delayed_entry_timing = max(
            best_delayed_entry_candidates,
            key=lambda item: (
                item.get("first_alignment_avg_return_pct") if item.get("first_alignment_avg_return_pct") is not None else float("-inf"),
                int(item.get("first_alignment_count") or 0),
                -int(item.get("delay_days") or 0),
            ),
        )

    baseline_avg_return = _mean(event_returns)
    if best_delayed_entry_timing is not None:
        best_delayed_entry_timing = {
            **best_delayed_entry_timing,
            "beats_kd_event_baseline": (
                baseline_avg_return is not None
                and best_delayed_entry_timing.get("first_alignment_avg_return_pct") is not None
                and best_delayed_entry_timing["first_alignment_avg_return_pct"] > baseline_avg_return
            ),
        }

    recommendation_summary = "資料不足，無法判定最佳延遲進場時間。"
    recommended_delay_days = None
    beats_baseline = False
    if best_delayed_entry_timing is not None:
        beats_baseline = bool(best_delayed_entry_timing.get("beats_kd_event_baseline"))
        if beats_baseline:
            recommended_delay_days = int(best_delayed_entry_timing.get("delay_days") or 0)
            recommendation_summary = (
                f"KD 後 {recommended_delay_days} 天的首次 MA20_v2 對齊，"
                f"平均報酬 {best_delayed_entry_timing['first_alignment_avg_return_pct']}%，"
                f"高於 KD 當天樣本的 {baseline_avg_return}%，可視為較佳延遲進場時間。"
            )
        else:
            recommendation_summary = (
                f"雖然 KD 後 {best_delayed_entry_timing['delay_days']} 天的首次 MA20_v2 對齊"
                f"平均報酬最高（{best_delayed_entry_timing['first_alignment_avg_return_pct']}%），"
                f"但仍未明顯高於 KD 當天樣本的 {baseline_avg_return}%，目前看不到更好的延遲進場時間。"
            )

    alignment_summary = "資料不足，無法判定 KD 與 MA20_v2 的時序對齊點。"
    if best_alignment_delay is not None:
        alignment_summary = (
            f"KD 後 {best_alignment_delay['delay_days']} 天最容易首次進入 MA20_v2，"
            f"共有 {best_alignment_delay['first_alignment_count']} 個樣本，"
            f"占 KD 樣本的 {best_alignment_delay['first_alignment_rate_pct']}%。"
        )

    return {
        "report_version": TIMING_ALIGNMENT_REPORT_VERSION,
        "generated_at": get_taiwan_now().isoformat(),
        "evaluation_horizon": "next_available_report",
        "evaluated_days": evaluated_days,
        "kd_event_sample_count": kd_event_sample_count,
        "lookahead_days": list(TIMING_ALIGNMENT_LOOKAHEAD_DAYS),
        "trigger_condition": {
            "condition": "kd_low_turn_up",
            "label": CONDITION_DEFINITIONS["kd_low_turn_up"]["label"],
            "description": CONDITION_DEFINITIONS["kd_low_turn_up"]["description"],
        },
        "alignment_condition": {
            "condition": "ma20_v2",
            "label": STEADY_V2_BLOCKER_CONDITION_DEFINITIONS["ma20_v2"]["label"],
            "description": STEADY_V2_BLOCKER_CONDITION_DEFINITIONS["ma20_v2"]["description"],
        },
        "event_day_baseline": {
            "sample_count": kd_event_sample_count,
            "avg_return_pct": baseline_avg_return,
            "win_rate_pct": _win_rate(event_returns),
            "avg_close": _mean(event_closes),
            "avg_ma20_gap_pct": _mean(event_gaps),
            "already_in_ma20_v2_count": already_in_ma20_v2_count,
            "already_in_ma20_v2_rate_pct": _round_number((already_in_ma20_v2_count / kd_event_sample_count) * 100) if kd_event_sample_count else None,
        },
        "delay_alignment": delay_alignment,
        "first_alignment_distribution": first_alignment_distribution,
        "best_alignment_delay": best_alignment_delay,
        "best_delayed_entry_timing": best_delayed_entry_timing,
        "recommendation": {
            "recommended_delay_days": recommended_delay_days,
            "beats_kd_event_baseline": beats_baseline,
            "baseline_kd_avg_return_pct": baseline_avg_return,
            "summary": recommendation_summary,
        },
        "timing_alignment_summary": alignment_summary,
        "event_samples": event_samples,
    }


def _co_strictest_conditions(ranked_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not ranked_items:
        return []
    first = ranked_items[0]
    pass_rate = first.get("pass_rate_pct")
    pass_count = first.get("pass_count")
    if pass_rate is None:
        return []
    return [
        item for item in ranked_items
        if item.get("pass_rate_pct") == pass_rate and item.get("pass_count") == pass_count
    ]


def _build_strategy_blocker_summary(
    strategy_name: str,
    definition: Dict[str, Any],
    strategy_hit_count: int,
    condition_summaries: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    required_conditions = [
        condition_summaries[name]
        for name in definition.get("condition_names") or []
        if name in condition_summaries
    ]
    ranked_conditions = _rank_signal_condition_summaries(required_conditions)
    strictest_conditions = _co_strictest_conditions(ranked_conditions)
    strictest_condition = strictest_conditions[0] if strictest_conditions else (ranked_conditions[0] if ranked_conditions else None)
    condition_pass_counts = {
        item["condition"]: item["pass_count"]
        for item in required_conditions
    }

    if strategy_hit_count > 0:
        summary = f"{definition['label']}當天命中 {strategy_hit_count} 檔。"
    else:
        condition_text = "、".join(
            f"{item['label']}通過 {item['pass_count']} 檔"
            for item in required_conditions
        )
        summary = f"{definition['label']}當天 0 檔，{condition_text}。" if condition_text else f"{definition['label']}當天 0 檔。"

    return {
        "strategy": strategy_name,
        "label": definition["label"],
        "description": definition["description"],
        "hit_count": strategy_hit_count,
        "required_conditions": list(definition.get("condition_names") or []),
        "condition_pass_counts": condition_pass_counts,
        "strictest_condition": strictest_condition,
        "strictest_conditions": strictest_conditions,
        "summary": summary,
    }


def _build_daily_signal_summary(
    candidate_count: int,
    strategy_hits: Dict[str, int],
    condition_summaries: Dict[str, Dict[str, Any]],
    strictest_conditions: List[Dict[str, Any]],
) -> str:
    condition_text = "、".join(
        f"{summary['label']} {summary['pass_count']} 檔"
        for summary in condition_summaries.values()
    )
    strictest_text = ""
    if strictest_conditions:
        strictest_labels = "、".join(item["label"] for item in strictest_conditions)
        strictest_text = f" 最嚴條件為 {strictest_labels}。"

    if sum(strategy_hits.values()) == 0:
        return f"今天 {candidate_count} 檔候選中，{condition_text}，因此兩條策略都沒有命中。{strictest_text}".strip()

    return (
        f"今天 {candidate_count} 檔候選中，{condition_text}；"
        f"狙擊型 {strategy_hits.get('sniper', 0)} 檔、穩定型 {strategy_hits.get('steady', 0)} 檔。{strictest_text}"
    ).strip()


def _build_signal_day_summary(
    day: Dict[str, Any],
    lower_third_cutoff: Optional[float],
) -> Dict[str, Any]:
    samples = list(day.get("samples") or [])
    candidate_count = int(day.get("candidate_count") or len(samples))
    condition_pass_counts = {name: 0 for name in CONDITION_DEFINITIONS.keys()}
    strategy_hits = {name: 0 for name in STRATEGY_DEFINITIONS.keys()}
    any_strategy_hit_count = 0

    for sample in samples:
        condition_flags = _build_signal_condition_flags(sample, lower_third_cutoff)
        for condition_name, is_hit in condition_flags.items():
            if is_hit:
                condition_pass_counts[condition_name] += 1

        matched_any_strategy = False
        for strategy_name, definition in STRATEGY_DEFINITIONS.items():
            if all(condition_flags.get(condition_name) for condition_name in definition.get("condition_names") or []):
                strategy_hits[strategy_name] += 1
                matched_any_strategy = True

        if matched_any_strategy:
            any_strategy_hit_count += 1

    condition_summaries = {
        condition_name: _build_signal_condition_summary(condition_name, pass_count, candidate_count)
        for condition_name, pass_count in condition_pass_counts.items()
    }
    ranked_conditions = _rank_signal_condition_summaries(condition_summaries.values())
    strictest_conditions = _co_strictest_conditions(ranked_conditions)
    strictest_condition = strictest_conditions[0] if strictest_conditions else (ranked_conditions[0] if ranked_conditions else None)
    strategy_blockers = {
        strategy_name: _build_strategy_blocker_summary(
            strategy_name,
            definition,
            strategy_hits[strategy_name],
            condition_summaries,
        )
        for strategy_name, definition in STRATEGY_DEFINITIONS.items()
    }

    return {
        "date": day.get("date"),
        "previous_date": day.get("previous_date"),
        "previous_universe_available": bool(day.get("previous_universe_available")),
        "candidate_count": candidate_count,
        "strategy_hits": strategy_hits,
        "any_strategy_hit_count": any_strategy_hit_count,
        "conditions": condition_summaries,
        "ranking_by_strictness": ranked_conditions,
        "strictest_condition": strictest_condition,
        "strictest_conditions": strictest_conditions,
        "strategy_blockers": strategy_blockers,
        "zero_hit_diagnosis": {
            "is_zero_hit_day": any_strategy_hit_count == 0,
            "summary": _build_daily_signal_summary(candidate_count, strategy_hits, condition_summaries, strictest_conditions),
        },
    }


def _build_weekly_signal_summary(daily_hit_counts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    weekly_map: Dict[str, Dict[str, Any]] = {}

    for day in daily_hit_counts:
        date_str = str(day.get("date") or "")
        if not date_str:
            continue
        week_key = _iso_week_key(date_str)
        entry = weekly_map.setdefault(week_key, {
            "week": week_key,
            "start_date": date_str,
            "end_date": date_str,
            "day_count": 0,
            "candidate_count": 0,
            "strategy_hits": {name: 0 for name in STRATEGY_DEFINITIONS.keys()},
            "any_strategy_hit_count": 0,
            "days_with_any_strategy_hit": 0,
            "days_with_strategy_hits": {name: 0 for name in STRATEGY_DEFINITIONS.keys()},
        })
        entry["start_date"] = min(entry["start_date"], date_str)
        entry["end_date"] = max(entry["end_date"], date_str)
        entry["day_count"] += 1
        entry["candidate_count"] += int(day.get("candidate_count") or 0)
        entry["any_strategy_hit_count"] += int(day.get("any_strategy_hit_count") or 0)
        if int(day.get("any_strategy_hit_count") or 0) > 0:
            entry["days_with_any_strategy_hit"] += 1

        for strategy_name in STRATEGY_DEFINITIONS.keys():
            hit_count = int((day.get("strategy_hits") or {}).get(strategy_name) or 0)
            entry["strategy_hits"][strategy_name] += hit_count
            if hit_count > 0:
                entry["days_with_strategy_hits"][strategy_name] += 1

    return [weekly_map[key] for key in sorted(weekly_map.keys())]


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
    ma20_v2_section = _build_ma20_v2_factor(trading_samples)
    retest_ma20_section = _build_retest_ma20_factor(trading_samples)
    volume_expand_section = _build_volume_expand_factor(trading_samples)
    low_k_turn_section = _build_low_k_turn_factor(trading_samples)
    ma20_variant_comparison = _build_ma20_variant_comparison(trading_samples)

    legacy_factors = {
        "hit_count": hit_count_section,
        "technical": technical_section,
        "zone": zone_section,
    }
    test_factors = {
        "low_position_ma20": low_position_section,
        "just_break_ma20": break_ma20_section,
        "ma20_v2": ma20_v2_section,
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
        "ma20_variant_comparison": ma20_variant_comparison,
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


def generate_factor_combination_analysis_report(
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
    _, lower_third_cutoff, _ = _low_position_cutoffs(trading_samples)

    single_factor_baselines = {
        "just_break_ma20": _build_positive_factor_baseline(
            "just_break_ma20",
            "剛跌破 MA20",
            "剛跌破組",
            trading_samples,
            _is_just_break_ma20,
        ),
        "low_position_ma20": _build_positive_factor_baseline(
            "low_position_ma20",
            "低位因子",
            "低位組",
            trading_samples,
            lambda sample: _is_low_position_sample(sample, lower_third_cutoff),
        ),
        "low_k_turn_up": _build_positive_factor_baseline(
            "low_k_turn_up",
            "KD 低檔翻揚",
            "低檔翻揚組",
            trading_samples,
            _is_low_k_turn_up,
        ),
    }

    combinations = {
        "just_break_ma20_plus_low_k_turn_up": _build_factor_combination_summary(
            "just_break_ma20_plus_low_k_turn_up",
            "剛跌破 MA20 + KD 低檔翻揚",
            trading_samples,
            lambda sample: _is_just_break_ma20(sample) and _is_low_k_turn_up(sample),
            ["just_break_ma20", "low_k_turn_up"],
            single_factor_baselines,
        ),
        "just_break_ma20_plus_low_position_ma20": _build_factor_combination_summary(
            "just_break_ma20_plus_low_position_ma20",
            "剛跌破 MA20 + 低位因子",
            trading_samples,
            lambda sample: _is_just_break_ma20(sample) and _is_low_position_sample(sample, lower_third_cutoff),
            ["just_break_ma20", "low_position_ma20"],
            single_factor_baselines,
        ),
        "low_k_turn_up_plus_low_position_ma20": _build_factor_combination_summary(
            "low_k_turn_up_plus_low_position_ma20",
            "KD 低檔翻揚 + 低位因子",
            trading_samples,
            lambda sample: _is_low_k_turn_up(sample) and _is_low_position_sample(sample, lower_third_cutoff),
            ["low_k_turn_up", "low_position_ma20"],
            single_factor_baselines,
        ),
        "all_three": _build_factor_combination_summary(
            "all_three",
            "剛跌破 MA20 + KD 低檔翻揚 + 低位因子",
            trading_samples,
            lambda sample: _is_just_break_ma20(sample) and _is_low_k_turn_up(sample) and _is_low_position_sample(sample, lower_third_cutoff),
            ["just_break_ma20", "low_k_turn_up", "low_position_ma20"],
            single_factor_baselines,
        ),
    }

    ranked_by_avg_return = sorted(
        combinations.values(),
        key=lambda item: ((item.get("avg_return_pct") if item.get("avg_return_pct") is not None else float("-inf")), item.get("sample_count") or 0),
        reverse=True,
    )
    ranked_by_win_rate = sorted(
        combinations.values(),
        key=lambda item: ((item.get("win_rate_pct") if item.get("win_rate_pct") is not None else float("-inf")), item.get("sample_count") or 0),
        reverse=True,
    )

    best_single_factor = max(
        (item for item in single_factor_baselines.values() if item.get("avg_return_pct") is not None),
        key=lambda item: item["avg_return_pct"],
        default=None,
    )
    strongest_combination = next((item for item in ranked_by_avg_return if item.get("avg_return_pct") is not None), None)
    highest_win_rate_combination = next((item for item in ranked_by_win_rate if item.get("win_rate_pct") is not None), None)
    strongest_edge_vs_best_single = _safe_diff(
        (strongest_combination or {}).get("avg_return_pct"),
        (best_single_factor or {}).get("avg_return_pct"),
    )

    combinations_beating_single_factors = [
        item for item in ranked_by_avg_return
        if item.get("beats_constituent_single_factors") is True
    ]

    return {
        "report_version": FACTOR_COMBINATION_ANALYSIS_REPORT_VERSION,
        "generated_at": get_taiwan_now().isoformat(),
        "evaluation_horizon": "next_available_report",
        "evaluated_days": evaluated_days,
        "candidate_samples": len(trading_samples),
        "combination_names": list(combinations.keys()),
        "low_position_definition": {
            "metric": "(close - ma20) / ma20",
            "positive_group": "lower_third",
            "lower_third_cutoff": _round_number(lower_third_cutoff, digits=6),
        },
        "single_factor_baselines": single_factor_baselines,
        "combinations": combinations,
        "ranking_by_avg_return": [
            _summarize_factor_combination(item)
            for item in ranked_by_avg_return
        ],
        "ranking_by_win_rate": [
            _summarize_factor_combination(item)
            for item in ranked_by_win_rate
        ],
        "best_single_factor": best_single_factor,
        "strongest_combination": _summarize_factor_combination(strongest_combination),
        "highest_win_rate_combination": _summarize_factor_combination(highest_win_rate_combination),
        "strongest_combination_vs_best_single_factor": {
            "avg_return_edge_pct": strongest_edge_vs_best_single,
            "is_stronger": (
                strongest_edge_vs_best_single is not None and strongest_edge_vs_best_single > 0
            ),
        },
        "combination_superiority_confirmed": len(combinations_beating_single_factors) > 0,
        "combinations_beating_single_factors": [
            _summarize_factor_combination(item)
            for item in combinations_beating_single_factors
        ],
    }


def generate_strategy_analysis_report(
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
    factor_combination_report = generate_factor_combination_analysis_report(
        ordered_reports,
        market_prices=market_lookup,
        universe_reports_by_date=universe_reports_by_date,
    )
    combinations = factor_combination_report.get("combinations") or {}
    low_position_definition = factor_combination_report.get("low_position_definition") or {}
    lower_third_cutoff = _as_float(low_position_definition.get("lower_third_cutoff"))
    single_factor_baselines = {
        "just_break_ma20": _build_positive_factor_baseline(
            "just_break_ma20",
            "剛跌破 MA20",
            "剛跌破組",
            trading_samples,
            _is_just_break_ma20,
        ),
        "ma20_v2": _build_positive_factor_baseline(
            "ma20_v2",
            "接近 MA20 區間",
            "接近 MA20 / 3 日內跌破組",
            trading_samples,
            _is_ma20_v2,
        ),
        "low_position_ma20": _build_positive_factor_baseline(
            "low_position_ma20",
            "低位因子",
            "低位組",
            trading_samples,
            lambda sample: _is_low_position_sample(sample, lower_third_cutoff),
        ),
        "low_k_turn_up": _build_positive_factor_baseline(
            "low_k_turn_up",
            "KD 低檔翻揚",
            "低檔翻揚組",
            trading_samples,
            _is_low_k_turn_up,
        ),
    }

    strategies = {
        strategy_name: _build_strategy_summary(
            strategy_name,
            definition,
            combinations.get(definition["combination_source"]),
        )
        for strategy_name, definition in STRATEGY_DEFINITIONS.items()
    }
    strategies_v2 = {
        strategy_name: _build_strategy_variant_summary(
            strategy_name,
            definition,
            trading_samples,
            single_factor_baselines,
            lower_third_cutoff,
        )
        for strategy_name, definition in STRATEGY_V2_DEFINITIONS.items()
    }
    strategy_variants = {
        **strategies,
        **strategies_v2,
    }

    ranked_by_avg_return = sorted(
        strategies.values(),
        key=lambda item: ((item.get("avg_return_pct") if item.get("avg_return_pct") is not None else float("-inf")), item.get("sample_count") or 0),
        reverse=True,
    )
    ranked_by_win_rate = sorted(
        strategies.values(),
        key=lambda item: ((item.get("win_rate_pct") if item.get("win_rate_pct") is not None else float("-inf")), item.get("sample_count") or 0),
        reverse=True,
    )
    variant_ranked_by_avg_return = sorted(
        strategy_variants.values(),
        key=lambda item: ((item.get("avg_return_pct") if item.get("avg_return_pct") is not None else float("-inf")), item.get("sample_count") or 0),
        reverse=True,
    )
    variant_ranked_by_win_rate = sorted(
        strategy_variants.values(),
        key=lambda item: ((item.get("win_rate_pct") if item.get("win_rate_pct") is not None else float("-inf")), item.get("sample_count") or 0),
        reverse=True,
    )

    high_return_strategy = next((item for item in ranked_by_avg_return if item.get("avg_return_pct") is not None), None)
    sniper_strategy = strategies.get("sniper")
    steady_profile = strategies.get("steady")
    strategy_variant_comparison = {
        "sniper": _build_strategy_variant_comparison(
            "sniper",
            STRATEGY_DEFINITIONS["sniper"]["label"],
            strategies.get("sniper"),
            strategies_v2.get("sniper_v2"),
        ),
        "steady": _build_strategy_variant_comparison(
            "steady",
            STRATEGY_DEFINITIONS["steady"]["label"],
            strategies.get("steady"),
            strategies_v2.get("steady_v2"),
        ),
    }
    v2_summary = {
        "families_with_more_hits": [
            family_name
            for family_name, summary in strategy_variant_comparison.items()
            if summary.get("v2_hit_count_increase")
        ],
        "families_with_positive_avg_return": [
            family_name
            for family_name, summary in strategy_variant_comparison.items()
            if summary.get("v2_avg_return_positive")
        ],
        "families_meeting_v19_goal": [
            family_name
            for family_name, summary in strategy_variant_comparison.items()
            if summary.get("meets_v19_goal")
        ],
    }

    return {
        "report_version": STRATEGY_ANALYSIS_REPORT_VERSION,
        "generated_at": get_taiwan_now().isoformat(),
        "evaluation_horizon": factor_combination_report.get("evaluation_horizon"),
        "evaluated_days": evaluated_days,
        "candidate_samples": len(trading_samples),
        "strategy_names": list(STRATEGY_DEFINITIONS.keys()),
        "strategy_v2_names": list(STRATEGY_V2_DEFINITIONS.keys()),
        "strategy_variant_names": list(strategy_variants.keys()),
        "low_position_definition": low_position_definition,
        "strategies": strategies,
        "strategies_v2": strategies_v2,
        "strategy_variants": strategy_variants,
        "ranking_by_avg_return": [
            _summarize_strategy(item)
            for item in ranked_by_avg_return
        ],
        "ranking_by_win_rate": [
            _summarize_strategy(item)
            for item in ranked_by_win_rate
        ],
        "variant_ranking_by_avg_return": [
            _summarize_strategy(item)
            for item in variant_ranked_by_avg_return
        ],
        "variant_ranking_by_win_rate": [
            _summarize_strategy(item)
            for item in variant_ranked_by_win_rate
        ],
        "style_choice": {
            "high_return": _summarize_strategy(sniper_strategy or high_return_strategy),
            "steady": _summarize_strategy(steady_profile),
        },
        "strategy_difference": {
            "sniper_minus_steady_avg_return_pct": _safe_diff(
                (sniper_strategy or {}).get("avg_return_pct"),
                (steady_profile or {}).get("avg_return_pct"),
            ),
            "steady_minus_sniper_win_rate_pct": _safe_diff(
                (steady_profile or {}).get("win_rate_pct"),
                (sniper_strategy or {}).get("win_rate_pct"),
            ),
        },
        "strategy_variant_comparison": strategy_variant_comparison,
        "v2_summary": v2_summary,
    }


def generate_signal_density_report(
    priority_reports: List[Dict[str, Any]],
    market_prices: Optional[Any] = None,
    universe_reports_by_date: Optional[Dict[str, Dict[str, Any]]] = None,
    strategy_analysis_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ordered_reports = sorted(priority_reports, key=lambda item: str(item.get("date") or ""))
    strategy_report = strategy_analysis_report or generate_strategy_analysis_report(
        ordered_reports,
        market_prices=market_prices,
        universe_reports_by_date=universe_reports_by_date,
    )
    low_position_definition = strategy_report.get("low_position_definition") or {}
    lower_third_cutoff = _as_float(low_position_definition.get("lower_third_cutoff"))

    signal_days = _build_signal_sample_days(ordered_reports, universe_reports_by_date=universe_reports_by_date)
    daily_hit_counts = [
        _build_signal_day_summary(day, lower_third_cutoff)
        for day in signal_days
    ]
    weekly_hit_counts = _build_weekly_signal_summary(daily_hit_counts)

    total_candidate_samples = sum(int(day.get("candidate_count") or 0) for day in daily_hit_counts)
    overall_condition_summaries = {
        condition_name: _build_signal_condition_summary(
            condition_name,
            sum(int(((day.get("conditions") or {}).get(condition_name) or {}).get("pass_count") or 0) for day in daily_hit_counts),
            total_candidate_samples,
        )
        for condition_name in CONDITION_DEFINITIONS.keys()
    }
    overall_ranking = _rank_signal_condition_summaries(overall_condition_summaries.values())
    overall_strictest_conditions = _co_strictest_conditions(overall_ranking)
    overall_strictest_condition = overall_strictest_conditions[0] if overall_strictest_conditions else (overall_ranking[0] if overall_ranking else None)

    latest_day_summary = daily_hit_counts[-1] if daily_hit_counts else None
    current_week_summary = None
    if latest_day_summary and latest_day_summary.get("date"):
        latest_week = _iso_week_key(str(latest_day_summary.get("date")))
        current_week_summary = next((item for item in weekly_hit_counts if item.get("week") == latest_week), None)

    return {
        "report_version": SIGNAL_DENSITY_REPORT_VERSION,
        "generated_at": get_taiwan_now().isoformat(),
        "latest_date": ordered_reports[-1].get("date") if ordered_reports else None,
        "strategy_names": list(STRATEGY_DEFINITIONS.keys()),
        "condition_names": list(CONDITION_DEFINITIONS.keys()),
        "condition_definitions": CONDITION_DEFINITIONS,
        "low_position_definition": low_position_definition,
        "daily_hit_counts": daily_hit_counts,
        "weekly_hit_counts": weekly_hit_counts,
        "overall_condition_density": {
            "candidate_samples": total_candidate_samples,
            "conditions": overall_condition_summaries,
            "ranking_by_strictness": overall_ranking,
            "strictest_condition": overall_strictest_condition,
            "strictest_conditions": overall_strictest_conditions,
        },
        "latest_day_summary": latest_day_summary,
        "current_week_summary": current_week_summary,
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


def save_factor_combination_analysis_report(report: Dict[str, Any], base_dir: Optional[Path] = None) -> Path:
    return _save_json(_factor_combination_analysis_path(base_dir), report)


def save_strategy_analysis_report(report: Dict[str, Any], base_dir: Optional[Path] = None) -> Path:
    return _save_json(_strategy_analysis_path(base_dir), report)


def save_signal_density_report(report: Dict[str, Any], base_dir: Optional[Path] = None) -> Path:
    return _save_json(_signal_density_path(base_dir), report)


def save_steady_v2_blockers_report(report: Dict[str, Any], base_dir: Optional[Path] = None) -> Path:
    return _save_json(_steady_v2_blockers_path(base_dir), report)


def save_timing_alignment_report(report: Dict[str, Any], base_dir: Optional[Path] = None) -> Path:
    return _save_json(_timing_alignment_path(base_dir), report)


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


def generate_factor_combination_analysis_from_reports(base_dir: Optional[Path] = None, market_prices: Optional[Any] = None) -> Path:
    report = generate_factor_combination_analysis_report(
        load_priority_reports(base_dir=base_dir),
        market_prices=market_prices,
        universe_reports_by_date=load_universe_reports_by_date(base_dir=base_dir),
    )
    return save_factor_combination_analysis_report(report, base_dir=base_dir)


def generate_strategy_analysis_from_reports(base_dir: Optional[Path] = None, market_prices: Optional[Any] = None) -> Path:
    report = generate_strategy_analysis_report(
        load_priority_reports(base_dir=base_dir),
        market_prices=market_prices,
        universe_reports_by_date=load_universe_reports_by_date(base_dir=base_dir),
    )
    return save_strategy_analysis_report(report, base_dir=base_dir)


def generate_signal_density_from_reports(base_dir: Optional[Path] = None, market_prices: Optional[Any] = None) -> Path:
    priority_reports = load_priority_reports(base_dir=base_dir)
    universe_reports_by_date = load_universe_reports_by_date(base_dir=base_dir)
    strategy_report = generate_strategy_analysis_report(
        priority_reports,
        market_prices=market_prices,
        universe_reports_by_date=universe_reports_by_date,
    )
    report = generate_signal_density_report(
        priority_reports,
        market_prices=market_prices,
        universe_reports_by_date=universe_reports_by_date,
        strategy_analysis_report=strategy_report,
    )
    return save_signal_density_report(report, base_dir=base_dir)


def generate_steady_v2_blockers_from_reports(base_dir: Optional[Path] = None, market_prices: Optional[Any] = None) -> Path:
    priority_reports = load_priority_reports(base_dir=base_dir)
    universe_reports_by_date = load_universe_reports_by_date(base_dir=base_dir)
    strategy_report = generate_strategy_analysis_report(
        priority_reports,
        market_prices=market_prices,
        universe_reports_by_date=universe_reports_by_date,
    )
    report = generate_steady_v2_blockers_report(
        priority_reports,
        market_prices=market_prices,
        universe_reports_by_date=universe_reports_by_date,
        strategy_analysis_report=strategy_report,
    )
    return save_steady_v2_blockers_report(report, base_dir=base_dir)


def generate_timing_alignment_from_reports(base_dir: Optional[Path] = None, market_prices: Optional[Any] = None) -> Path:
    priority_reports = load_priority_reports(base_dir=base_dir)
    universe_reports_by_date = load_universe_reports_by_date(base_dir=base_dir)
    report = generate_timing_alignment_report(
        priority_reports,
        market_prices=market_prices,
        universe_reports_by_date=universe_reports_by_date,
    )
    return save_timing_alignment_report(report, base_dir=base_dir)


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
    factor_combination_analysis_path = generate_factor_combination_analysis_from_reports(base_dir=base_dir, market_prices=market_prices)
    strategy_analysis_path = generate_strategy_analysis_from_reports(base_dir=base_dir, market_prices=market_prices)
    signal_density_path = generate_signal_density_from_reports(base_dir=base_dir, market_prices=market_prices)
    steady_v2_blockers_path = generate_steady_v2_blockers_from_reports(base_dir=base_dir, market_prices=market_prices)
    timing_alignment_path = generate_timing_alignment_from_reports(base_dir=base_dir, market_prices=market_prices)
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
        "factor_combination_analysis_path": str(factor_combination_analysis_path),
        "strategy_analysis_path": str(strategy_analysis_path),
        "signal_density_path": str(signal_density_path),
        "steady_v2_blockers_path": str(steady_v2_blockers_path),
        "timing_alignment_path": str(timing_alignment_path),
        "current_context_path": str(reports_dir / f"{current_date}-context.json") if current_date else None,
        "current_priority_path": str(_priority_report_path(current_date, base_dir)) if current_date else None,
        "history_window": history_window,
        "skipped": skipped,
    }