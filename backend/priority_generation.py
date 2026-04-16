"""V10.4 Priority Generation Layer

第二頁 Priority Validation 的 Generation Layer
責任：從 legacy / universe 資料生成 priority_validation_v10_1 正式 contract

layer: generation
allowed dependencies: stdlib + shared base helpers only
internal layer
external callers should use backend.priority_facade
not intended as direct app/script entrypoint
tests may import internal modules, but app / script entrypoints should not

限制：
- 唯一可讀取 legacy 結構（cards, trace_catalog, stock_mapping_catalog）的層
- 禁止輸出 legacy 結構給 frontend
- 禁止在 validation layer 使用
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import re
from functools import cmp_to_key
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from backend.config import get_taiwan_now, get_today_str
from backend.fetch_data import FinMindAPI
from backend.historical_reports import MARKET_INDEX_ID


PRIORITY_REPORT_VERSION = "v12-priority-validation"
SORT_RULE_DESCRIPTION = "先比命中情境數，再比技術面狀態，最後比區間位置（試單區優先）；同分保留原出現順序。"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_EVALUATED_DAYS = 20
MA20_V2_BAND_PCT = 0.02
MA20_V2_RECENT_BREAK_LOOKBACK = 3
TIMING_ALIGNMENT_LOOKAHEAD_DAYS = [1, 2, 3]
STEADY_V4_TRACKING_WINDOW_DAYS = [20, 50]
STEADY_V4_TRACKING_STABLE_WIN_RATE_PCT = 60.0
STEADY_V2_SIGNATURE_SHARP_DROP_THRESHOLD_PCT = -3.0
STEADY_V4_K_MIN = 24.0
STEADY_V4_K_MAX = 30.0
STEADY_V4_MA20_DISTANCE_PCT = 0.0208
STEADY_V4_CLOSE_RETURN_RATIO = 0.7
STEADY_V5_PULLBACK_ABS_LIMIT_PCT = 2.1
STEADY_V5_MIN_HIT_SHARE_VS_V4 = 0.75
STEADY_V5_MAX_WIN_RATE_DROP_PCT = 10.0
STEADY_V5_LONG_TERM_WINDOW_DAYS = [60, 120]
STEADY_V5_LONG_TERM_MIN_AVAILABLE_DATES = max(STEADY_V5_LONG_TERM_WINDOW_DAYS) + 5
STEADY_V5_LONG_TERM_SEGMENT_DAYS = 30
STEADY_V5_LONG_TERM_ROLLING_WINDOW_DAYS = 10
STEADY_V5_LONG_TERM_ROLLING_STEP_DAYS = 10
STEADY_V5_LONG_TERM_MAX_NEGATIVE_ROLLING_STREAK = 2
STEADY_V5_REGIME_ANALYSIS_WINDOW_DAYS = max(STEADY_V5_LONG_TERM_WINDOW_DAYS)
STEADY_V5_REGIME_DIRECTIONAL_EFFICIENCY_THRESHOLD_PCT = 60.0
STEADY_V5_REGIME_FRONT_SAMPLE_SIZE = 10
STEADY_V5_REGIME_CONCENTRATION_SHARE_PCT = 50.0
STEADY_V5_REGIME_VOLUME_EXPANSION_RATIO = 1.0
STEADY_V5_ACTIVATION_TREND_WINDOW_DAYS = STEADY_V5_LONG_TERM_ROLLING_WINDOW_DAYS
STEADY_V5_ACTIVATION_DOWNWEIGHT_MIN_PASS_COUNT = 2

# =============================================================================
# V10.1: 第二頁 Priority Validation 正式 Contract
# =============================================================================

PRIORITY_VALIDATION_V10_1_SCHEMA_VERSION = "priority-validation-v10.1"


# =============================================================================
# Utility Functions
# =============================================================================

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


def to_num(value: Any) -> Optional[float]:
    """安全轉換為數字"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _as_float(value: Any) -> Optional[float]:
    """將值轉換為浮點數"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return None


# =============================================================================
# Technical Analysis Utilities
# =============================================================================

def get_advice_priority(advice: Optional[str]) -> int:
    """將建議轉換為優先級數值（越高越好）"""
    if not advice:
        return 0
    advice = str(advice).strip()
    # 正面建議優先
    if "追價" in advice or "強勢突破" in advice:
        return 5
    if "試單" in advice or "跟進" in advice:
        return 4
    if "觀察" in advice or "盤整" in advice:
        return 3
    if "減碼" in advice or "弱勢" in advice:
        return 2
    if "觀望" in advice or "迴避" in advice:
        return 1
    return 0


def get_zone_priority(zone_flags: Optional[Dict[str, bool]]) -> int:
    """將區間標記轉換為優先級數值（越高越好）"""
    if not zone_flags:
        return 0
    if zone_flags.get("in_pilot_zone"):
        return 3  # 試單區優先
    if zone_flags.get("in_observe_zone"):
        return 2  # 觀察區次之
    if zone_flags.get("is_weak_blocked"):
        return 0  # 弱勢阻擋區最後
    return 1


def get_zone_priority_label(zone_flags: Optional[Dict[str, bool]]) -> str:
    """將區間標記轉換為顯示標籤"""
    if not zone_flags:
        return "區間外"
    if zone_flags.get("in_pilot_zone"):
        return "試單區優先"
    if zone_flags.get("in_observe_zone"):
        return "觀察區"
    if zone_flags.get("is_weak_blocked"):
        return "弱勢阻擋"
    return "區間外"


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


def build_technical_map(report: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """建立股票代號到技術資料的映射"""
    if not report:
        return {}
    stocks = report.get("stocks", [])
    result: Dict[str, Dict[str, Any]] = {}
    for stock in stocks:
        symbol = str(stock.get("symbol") or "").strip()
        if symbol:
            normalized_stock = dict(stock)
            indicators = normalized_stock.get("indicators") or {}
            summary = normalized_stock.get("summary") if isinstance(normalized_stock.get("summary"), dict) else None
            if not summary or not summary.get("advice"):
                summary = get_decision_summary(normalized_stock)
            zone_flags = normalized_stock.get("zone_flags") if isinstance(normalized_stock.get("zone_flags"), dict) else None
            if not zone_flags:
                zone_flags = get_zone_flags(normalized_stock, summary)
            if not normalized_stock.get("advice"):
                normalized_stock["advice"] = summary.get("advice")
            result[symbol] = {
                "stock": normalized_stock,
                "indicators": indicators,
                "summary": summary,
                "zone_flags": zone_flags,
            }
    return result


def compare_candidate_items(left: Dict[str, Any], right: Dict[str, Any], technical_map: Dict[str, Dict[str, Any]]) -> int:
    """比較兩個候選項目的排序（返回 -1, 0, 1）"""
    # 1. 先比命中情境數
    left_hits = int(left.get("hit_count") or 0)
    right_hits = int(right.get("hit_count") or 0)
    if left_hits != right_hits:
        return -1 if left_hits > right_hits else 1
    
    # 2. 再比技術面狀態
    left_symbol = str(left.get("symbol") or "")
    right_symbol = str(right.get("symbol") or "")
    left_tech = technical_map.get(left_symbol, {})
    right_tech = technical_map.get(right_symbol, {})
    
    left_stock = left_tech.get("stock", {})
    right_stock = right_tech.get("stock", {})
    
    left_advice = str(left_stock.get("advice") or "")
    right_advice = str(right_stock.get("advice") or "")
    
    left_priority = get_advice_priority(left_advice)
    right_priority = get_advice_priority(right_advice)
    
    if left_priority != right_priority:
        return -1 if left_priority > right_priority else 1
    
    # 3. 再比分數
    left_score = to_num(left_stock.get("score"))
    right_score = to_num(right_stock.get("score"))
    if left_score is not None and right_score is not None:
        if left_score != right_score:
            return -1 if left_score > right_score else 1
    elif left_score is not None:
        return -1
    elif right_score is not None:
        return 1
    
    # 4. 最後比出現順序
    left_order = int(left.get("first_seen_order") or 0)
    right_order = int(right.get("first_seen_order") or 0)
    if left_order != right_order:
        return -1 if left_order < right_order else 1
    
    return 0


def build_priority_explanation(item: Dict[str, Any], technical: Optional[Dict[str, Any]]) -> str:
    """建立排序說明"""
    parts = []
    
    # 情境命中
    hit_count = int(item.get("hit_count") or 0)
    if hit_count > 0:
        parts.append(f"命中 {hit_count} 個情境")
    
    # 技術面狀態
    if technical:
        stock = technical.get("stock", {})
        advice = str(stock.get("advice") or "").strip()
        if advice and advice != "技術資料不足":
            parts.append(f"技術面: {advice}")
        
        indicators = technical.get("indicators", {})
        score = to_num(indicators.get("score"))
        if score is not None:
            parts.append(f"分數 {score:.1f}")
    
    return "; ".join(parts) if parts else "綜合排序入選"


# =============================================================================
# V10.4 Legacy Generation Adapters (backend generation layer only)
# =============================================================================

def _get_priority_legacy_trace_catalog(context_report: Dict[str, Any]) -> Dict[str, Any]:
    """V10.4: 第二頁 legacy generation adapter（backend generation layer only）
    
    責任邊界（V10.4 Generation Layer）：
    - **所屬層**：backend generation layer（priority generation adapter）
    - **用途**：從 legacy 結構讀取原始 trace 資訊，供產生 priority_snapshot_v10_1
    - **限制**：不是 truth source，不是 validator input，不是 frontend input
    
    允許使用：
    - _build_candidate_entries() - generation layer
    - _theme_label() - generation layer helper
    - generate_priority_snapshot() - generation layer entry
    
    禁止使用：
    - validate_priority_validation_v10_1_contract() - validation layer
    - frontend render - UI layer
    - 任何輸出層直接暴露
    
    警告：此函式是 legacy generation input adapter，不是正式 contract source。
    若用於 validation/ui 層，會導致「legacy 偷渡」違反 V10.4 分層原則。
    """
    return context_report.get("trace_catalog") or {}


def _get_priority_legacy_cards(context_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """V10.4: 第二頁 legacy generation adapter（backend generation layer only）
    
    責任邊界（V10.4 Generation Layer）：
    - **所屬層**：backend generation layer（priority generation adapter）
    - **用途**：從 legacy 結構讀取原始 cards，供產生 priority_candidates_v10_1
    - **限制**：不是 truth source，不是 validator input，不是 frontend input
    
    允許使用：
    - _build_candidate_entries() - generation layer
    - generate_priority_snapshot() - generation layer entry
    
    禁止使用：
    - validate_priority_validation_v10_1_contract() - validation layer
    - frontend render - UI layer
    - 任何輸出層直接暴露
    
    警告：此函式是 legacy generation input adapter，不是正式 contract source。
    若用於 validation/ui 層，會導致「legacy 偷渡」違反 V10.4 分層原則。
    """
    cards = context_report.get("cards")
    if not isinstance(cards, list):
        return []
    return cards


def _get_priority_legacy_stock_mapping_catalog(context_report: Dict[str, Any]) -> Dict[str, Any]:
    """V10.4: 第二頁 legacy generation adapter（backend generation layer only）
    
    責任邊界（V10.4 Generation Layer）：
    - **所屬層**：backend generation layer（priority generation adapter）
    - **用途**：從 legacy 結構讀取股票映射資訊，供產生 priority_snapshot_v10_1
    - **限制**：不是 truth source，不是 validator input，不是 frontend input
    
    允許使用：
    - generate_priority_snapshot() - generation layer entry
    - 其他第二頁 generation layer 函式
    
    禁止使用：
    - validate_priority_validation_v10_1_contract() - validation layer
    - frontend render - UI layer
    - 任何輸出層直接暴露
    
    警告：此函式是 legacy generation input adapter，不是正式 contract source。
    若用於 validation/ui 層，會導致「legacy 偷渡」違反 V10.4 分層原則。
    """
    return context_report.get("stock_mapping_catalog") or {}


def _theme_label(context_report: Dict[str, Any], theme_id: str) -> str:
    """V10.4: 第二頁 generation layer helper
    
    責任邊界：
    - **所屬層**：backend generation layer
    - **用途**：priority candidates 生成時解析 theme 標籤
    - **依賴**：_get_priority_legacy_trace_catalog() - generation layer only
    
    禁止：validation layer、frontend、任何輸出層直接呼叫
    """
    taxonomy = ((_get_priority_legacy_trace_catalog(context_report).get("theme_taxonomy") or {}))
    return ((taxonomy.get(theme_id) or {}).get("label")) or theme_id


def _event_label(event_map: Dict[str, str], event_id: str) -> str:
    return event_map.get(event_id, event_id)


# =============================================================================
# Candidate Building
# =============================================================================

def _build_candidate_entries(context_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """V10.4: 第二頁核心函式，與第三頁完全解耦
    
    責任邊界：
    - 只處理第二頁 priority validation 的候選股票生成
    - 只讀取第二頁真相源（cards, trace_catalog）
    - 不讀取、不依賴、不處理 scenario_cards_v9
    
    解耦保證：
    - 即使 scenario_cards_v9 缺失，此函式仍能正常運作
    - 即使第三頁關閉，第二頁仍能獨立運作
    """
    # V10.4: 使用第二頁 generation layer 專用的 legacy adapter
    cards = _get_priority_legacy_cards(context_report)
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


# =============================================================================
# V10.1 Contract Derivation Functions
# =============================================================================

def _score_to_grade(score: Optional[float]) -> str:
    """將分數轉換為等級"""
    if score is None:
        return "N/A"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _derive_market_regime(candidates: List[Dict[str, Any]], universe_report: Dict[str, Any]) -> str:
    """V10.1: 推導市場 regime"""
    if not candidates:
        return "unknown"
    
    # 根據前段候選股票的分數分布判斷
    top_scores = [c["technical_state"]["score"] for c in candidates[:5] if c["technical_state"]["score"]]
    avg_score = sum(top_scores) / len(top_scores) if top_scores else 0
    
    if avg_score >= 65:
        return "trending"
    if avg_score >= 55:
        return "balanced"
    return "choppy"


def _derive_breadth_state(universe_report: Dict[str, Any]) -> str:
    """V10.1: 推導廣度狀態"""
    stocks = universe_report.get("stocks", [])
    if not stocks:
        return "unknown"
    
    scores = [s.get("score") for s in stocks if s.get("score")]
    if not scores:
        return "unknown"
    
    strong = sum(1 for s in scores if s >= 60)
    weak = sum(1 for s in scores if s < 55)
    
    if strong > weak * 1.5:
        return "strong_breadth"
    if weak > strong * 1.5:
        return "weak_breadth"
    return "mixed_breadth"


def _derive_volume_state(universe_report: Dict[str, Any]) -> str:
    """V10.1: 推導量能狀態"""
    stocks = universe_report.get("stocks", [])
    if not stocks:
        return "unknown"
    
    volume_ratios = [
        (s.get("indicators") or {}).get("volume_ratio")
        for s in stocks
        if (s.get("indicators") or {}).get("volume_ratio")
    ]
    
    if not volume_ratios:
        return "unknown"
    
    avg_ratio = sum(volume_ratios) / len(volume_ratios)
    
    if avg_ratio >= 1.3:
        return "expanding"
    if avg_ratio <= 0.8:
        return "contracting"
    return "neutral"


def _derive_leader_state(candidates: List[Dict[str, Any]]) -> str:
    """V10.1: 推導領漲股狀態"""
    if not candidates:
        return "unknown"
    
    top3_scores = [c["technical_state"]["score"] for c in candidates[:3] if c["technical_state"]["score"]]
    if not top3_scores:
        return "unknown"
    
    avg_top3 = sum(top3_scores) / len(top3_scores)
    
    if avg_top3 >= 70:
        return "strong_leaders"
    if avg_top3 >= 60:
        return "moderate_leaders"
    return "weak_leaders"


def _derive_priority_confidence(candidates: List[Dict[str, Any]], universe_report: Dict[str, Any]) -> str:
    """V10.1: 推導整體信心度"""
    if len(candidates) < 5:
        return "low"
    
    # 檢查資料完整性
    has_scores = sum(1 for c in candidates if c["technical_state"]["score"] is not None)
    score_ratio = has_scores / len(candidates) if candidates else 0
    
    if score_ratio >= 0.9 and len(candidates) >= 10:
        return "high"
    if score_ratio >= 0.7:
        return "medium"
    return "low"


def _build_validation_summary(
    market_regime: str,
    breadth_state: str,
    volume_state: str,
    leader_state: str,
    candidate_count: int
) -> str:
    """V10.1: 生成驗證摘要"""
    parts = [
        f"市場狀態: {market_regime}",
        f"廣度: {breadth_state}",
        f"量能: {volume_state}",
        f"領漲: {leader_state}",
        f"候選數: {candidate_count}",
    ]
    return "; ".join(parts)


def _derive_category(candidate: Dict[str, Any]) -> str:
    """V10.1: 推導股票類別"""
    # 嘗試從 theme 推導
    theme = candidate.get("primary_theme", "")
    if "電子" in theme or "半導體" in theme:
        return "電子"
    if "金融" in theme:
        return "金融"
    if "傳產" in theme or "原物料" in theme:
        return "傳產"
    return "其他"


def _build_candidate_validation_reason(candidate: Dict[str, Any]) -> str:
    """V10.1: 生成候選股票驗證理由"""
    reasons = []
    
    if candidate.get("hit_count", 0) > 0:
        reasons.append(f"命中 {candidate['hit_count']} 情境")
    
    advice = candidate.get("technical_state", {}).get("advice", "")
    if advice and advice != "技術資料不足":
        reasons.append(f"技術面: {advice}")
    
    zone = candidate.get("technical_state", {}).get("zone_label", "")
    if zone and zone != "區間外":
        reasons.append(f"位置: {zone}")
    
    return "; ".join(reasons) if reasons else "綜合排序入選"


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


# =============================================================================
# Main Generation Entry Point
# =============================================================================

# Internal compatibility only: analysis/tests may call this generation entrypoint,
# but external app/script callers should use backend.priority_facade.

def generate_priority_snapshot(
    context_report: Dict[str, Any],
    universe_report: Dict[str, Any],
    next_universe_report: Optional[Dict[str, Any]] = None,
    next_date: Optional[str] = None,
) -> Dict[str, Any]:
    """V10.4: 第二頁 generation layer entry point
    
    責任邊界（V10.4 Generation Layer）：
    - **所屬層**：backend generation layer（唯一可讀 legacy 的層）
    - **用途**：從 legacy 資料生成第二頁正式 contract
    - **輸出**：priority_snapshot_v10_1 + priority_candidates_v10_1
    
    Legacy 存取（僅限此層）：
    - _get_priority_legacy_cards() - 讀取 legacy cards
    - _get_priority_legacy_trace_catalog() - 讀取 legacy trace
    - _get_priority_legacy_stock_mapping_catalog() - 讀取 legacy mapping
    
    禁止：
    - 不得輸出 legacy 結構給 frontend
    - 不得繞過 contract 直接暴露原始資料
    - 不得在 validation layer 讀取此函式使用的 legacy 資料
    
    解耦保證：
    - 此函式輸入不需要 scenario_cards_v9
    - 此函式輸出只包含 priority_validation_v10_1 正式欄位
    - 第三頁關閉不影響第二頁運作
    """
    # V10.4: generation layer 內部邏輯，使用 legacy adapters 產生正式 contract
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

    # V10.1: 生成第二頁正式 contract 欄位
    # 從既有 legacy 資料整理出正式欄位，供 frontend 第二頁 render-only 使用
    
    # 計算市場狀態摘要
    market_regime = _derive_market_regime(candidates, universe_report)
    breadth_state = _derive_breadth_state(universe_report)
    volume_state = _derive_volume_state(universe_report)
    leader_state = _derive_leader_state(candidates)
    
    # 計算整體信心度
    confidence = _derive_priority_confidence(candidates, universe_report)
    
    # 生成驗證摘要
    validation_summary = _build_validation_summary(
        market_regime, breadth_state, volume_state, leader_state, len(candidates)
    )
    
    # V10.1: 第二頁正式 snapshot
    priority_snapshot_v10_1 = {
        "as_of_date": date_str,
        "market_regime": market_regime,
        "breadth_state": breadth_state,
        "volume_state": volume_state,
        "leader_state": leader_state,
        "validation_summary": validation_summary,
        "confidence": confidence,
        "generated_at": generated_at,
    }
    
    # V10.1: 第二頁正式 candidates（簡化版，供 frontend render-only）
    priority_candidates_v10_1 = [
        {
            "symbol": c["symbol"],
            "name": c["name"],
            "score": int(c["technical_state"]["score"] or 0),
            "rank": c["priority_rank"],
            "score_grade": _score_to_grade(c["technical_state"]["score"]),
            "category": _derive_category(c),
            "theme": c["primary_theme"],
            "validation_reason": _build_candidate_validation_reason(c),
            "risk_note": c["technical_state"]["risk"],
            "trace_ref": None,  # V10.1: 保留欄位，未來可填入 trace 參考
        }
        for c in candidates[:20]  # 只取前 20 名
    ]
    
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
        # V10.1: 第二頁正式 contract 欄位
        "priority_validation_v10_1_schema_version": PRIORITY_VALIDATION_V10_1_SCHEMA_VERSION,
        "priority_snapshot_v10_1": priority_snapshot_v10_1,
        "priority_candidates_v10_1": priority_candidates_v10_1,
    }
