"""third-page contract generation module.

this module owns third-page contract generation
external callers should use only the whitelisted public entrypoints
this module may depend on stdlib and minimal existing shared/base helpers only
this module must not depend on second-page internal layers
internal _build_* / _derive_* / _normalize_* / _validate_* helpers are not public API
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.config import get_taiwan_now, get_today_str
from backend.context_trace_catalog import (
    EVENT_TRACE_MAP,
    KEYWORD_DICTIONARY,
    THEME_TAXONOMY,
    build_trace,
    resolve_theme_stock_mapping,
    sector_trace_keys,
    stock_mapping_catalog_template,
    theme_label,
    trace_catalog,
    trace_keyword_labels,
    trace_theme_labels,
)


__all__ = [
    "generate_context_report",
    "generate_context_report_from_files",
]


REPORT_VERSION = "v9-context"
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_RELATION = {"aligned", "conflict", "neutral"}
SCENARIO_CARDS_V9_SCHEMA_VERSION = "scenario-cards-v9"
SCENARIO_CARDS_V9_REQUIRED_FIELDS = [
    "id",
    "title",
    "summary",
    "confidence",
    "relation_to_technical",
    "source_types",
    "source_type",
    "themes",
    "reasoning_chain",
    "priority_score",
    "priority_rank",
    "priority_reasons",
    "is_fallback",
    "generated_at",
]
CANDIDATE_REQUIRED_FIELDS = ["symbol", "from_theme", "trace_event", "reason"]
REQUIRED_CARD_FIELDS = [
    "id",
    "title",
    "event",
    "anomaly",
    "keywords",
    "themes",
    "trace",
    "candidate_stocks",
    "reasoning_chain",
    "confidence",
    "relation_to_technical",
    "source_type",
    "generated_at",
]
PROHIBITED_ADVICE_PHRASES = (
    "買進",
    "買入",
    "賣出",
    "進場",
    "出場",
    "加碼",
    "減碼",
    "停損",
    "停利",
    "候選股票",
    "個股點名",
    "建議買",
    "建議賣",
    "可留意",
    "立即",
    "追價",
    "抄底",
    "布局",
    "佈局",
)
SOURCE_COVERAGE_POINTS = {1: 1, 2: 2, 3: 3, 4: 4}
CONFIDENCE_POINTS = {"high": 3, "medium": 2, "low": 1}
TECHNICAL_ALIGNMENT_POINTS = {"aligned": 3, "neutral": 1, "conflict": 0}
INSTITUTIONAL_SUPPORT_POINTS = 2
CROSS_VALIDATION_POINTS = {"none": 0, "partial": 1, "confirmed": 2}
REASONING_CHAIN_POINTS = {"weak": 0, "basic": 1, "strong": 2}
FALLBACK_PENALTY = -999
VOLUME_SIGNAL_SOURCES = {"volume_anomaly", "volume_cluster"}
STRUCTURE_SIGNAL_SOURCES = {"score_distribution", "sector_concentration", "market_overview"}


class ContextCardsError(Exception):
    """情境卡生成或驗證錯誤。"""


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


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_legacy_trace_catalog(report: Dict[str, Any]) -> Dict[str, Any]:
    """LEGACY DEPRECATED: 集中讀取 trace_catalog，僅限相容用途
    
    可用於：priority validation（第二頁排序驗證）
    不可用於：第三頁市場情境卡 render
    """
    return report.get("trace_catalog") or {}


def _get_legacy_stock_mapping_catalog(report: Dict[str, Any]) -> Dict[str, Any]:
    """LEGACY DEPRECATED: 集中讀取 stock_mapping_catalog，僅限相容用途
    
    可用於：priority validation（第二頁排序驗證）、股票映射驗證
    不可用於：第三頁市場情境卡 render
    """
    catalog = report.get("stock_mapping_catalog")
    if not isinstance(catalog, dict):
        return {}
    return catalog


def _get_legacy_cards(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """LEGACY DEPRECATED: 集中讀取 cards，僅限相容用途
    
    可用於：priority validation（第二頁排序驗證）、舊版 trace 系統
    不可用於：第三頁市場情境卡 render
    """
    cards = report.get("cards")
    if not isinstance(cards, list):
        return []
    return cards


def _score_bucket(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _category_summary(counter: Counter[str], limit: int = 2) -> str:
    if not counter:
        return "分布未明"
    parts = []
    for category, count in counter.most_common(limit):
        parts.append(f"{category}{count}項")
    return "、".join(parts)


def _clean_direction(text: str) -> str:
    if any(token in text for token in ("偏多", "主流", "強勢", "積極")):
        return "偏多"
    if any(token in text for token in ("偏弱", "保守", "防守", "分歧", "震盪")):
        return "偏保守"
    return "中性"


def _normalize_relation_to_technical(value: Any) -> str:
    relation = str(value or "").strip()
    if relation == "diverged":
        return "conflict"
    return relation if relation in VALID_RELATION else ""


def _technical_direction(avg_score: float, strong_count: int, weak_count: int) -> str:
    if avg_score >= 65 and strong_count >= weak_count:
        return "偏多"
    if avg_score < 55 or weak_count > strong_count:
        return "偏保守"
    return "中性"


def _relation_label(ai_direction: str, technical_direction: str) -> str:
    if ai_direction == "中性" or technical_direction == "中性":
        return "neutral"
    if ai_direction == technical_direction:
        return "aligned"
    return "conflict"


def _parse_market_overview_meta(text: str) -> Dict[str, Optional[float]]:
    source = str(text or "")
    score_match = re.search(r"(\d+(?:\.\d+)?)分", source)
    strong_match = re.search(r"強勢股\s*(\d+)\s*檔", source)
    return {
        "strength_score": _as_float(score_match.group(1)) if score_match else None,
        "strong_stock_count": _as_float(strong_match.group(1)) if strong_match else None,
    }


def _average(values: Iterable[Optional[float]]) -> Optional[float]:
    nums = [float(value) for value in values if value is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _format_num(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def _format_pct(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "--"
    return f"{value * 100:.{digits}f}%"


def _select_generated_at(*values: Optional[str]) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return get_taiwan_now().isoformat()


def _volume_ratio(stock: Dict[str, Any]) -> Optional[float]:
    direct = _as_float(stock.get("volume_ratio"))
    if direct is not None:
        return direct
    return _as_float((stock.get("indicators") or {}).get("volume_ratio"))


def _unique_strings(values: Iterable[Any], limit: int = 4) -> List[str]:
    items: List[str] = []
    seen: Set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _top_labels(counter: Counter[str], limit: int = 2) -> List[str]:
    return [label for label, _ in counter.most_common(limit)]


def _market_theme_labels(categories: Sequence[str], fallback: str) -> List[str]:
    labels = [f"{category}主軸" for category in categories if category and category != "其他"]
    if not labels:
        labels.append(fallback)
    return labels


def _sector_trace_bindings(categories: Sequence[str]) -> Dict[str, str]:
    normalized = [str(category or "其他").strip() or "其他" for category in categories]
    primary = sector_trace_keys(normalized[0] if normalized else "其他")
    secondary = sector_trace_keys(normalized[1] if len(normalized) > 1 else normalized[0] if normalized else "其他")
    return {
        "primary_sector_keyword": primary["keyword"],
        "primary_sector_theme": primary["theme"],
        "secondary_sector_keyword": secondary["keyword"],
        "secondary_sector_theme": secondary["theme"],
    }


def _ai_direction_keyword(direction: str) -> str:
    return {
        "偏多": "ai_bullish",
        "偏保守": "ai_cautious",
        "中性": "ai_neutral",
    }.get(direction, "ai_neutral")


def _technical_direction_keyword(direction: str) -> str:
    return {
        "偏多": "technical_bullish",
        "偏保守": "technical_cautious",
        "中性": "technical_neutral",
    }.get(direction, "technical_neutral")


def _alignment_trace_bindings(relation: str) -> Dict[str, str]:
    if relation == "aligned":
        return {
            "alignment_keyword": "signal_convergence",
            "alignment_theme": "trace_convergence",
        }
    return {
        "alignment_keyword": "signal_divergence",
        "alignment_theme": "trace_divergence",
    }


def _contains_prohibited_phrase(text: str) -> bool:
    return any(phrase in text for phrase in PROHIBITED_ADVICE_PHRASES)


def _card_texts(card: Dict[str, Any]) -> Iterable[str]:
    yield str(card.get("title", ""))
    yield str(card.get("event", ""))
    yield str(card.get("anomaly", ""))
    yield str(card.get("source_type", ""))
    for item in card.get("keywords", []):
        yield str(item)
    for item in card.get("themes", []):
        yield str(item)
    trace = card.get("trace") or {}
    yield str(trace.get("event", ""))
    for item in trace.get("keywords", []):
        yield str(item)
    for item in trace.get("themes", []):
        yield str(item)
    for item in card.get("reasoning_chain", []):
        yield str(item)


def validate_context_card(card: Dict[str, Any], banned_terms: Optional[Set[str]] = None) -> None:
    missing = [field for field in REQUIRED_CARD_FIELDS if field not in card]
    if missing:
        raise ContextCardsError(f"情境卡缺少欄位: {missing}")

    for field in ["id", "title", "event", "anomaly", "source_type", "generated_at"]:
        if not isinstance(card.get(field), str) or not card[field].strip():
            raise ContextCardsError(f"情境卡欄位 {field} 必須是非空字串")

    for field in ["keywords", "themes"]:
        values = card.get(field)
        if not isinstance(values, list) or not (2 <= len(values) <= 4):
            raise ContextCardsError(f"情境卡 {field} 必須是 2 到 4 項的列表")
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise ContextCardsError(f"情境卡 {field} 內含空值")

    candidate_stocks = card.get("candidate_stocks")
    if not isinstance(candidate_stocks, list):
        raise ContextCardsError("情境卡 candidate_stocks 必須是列表")

    trace = card.get("trace")
    if not isinstance(trace, dict):
        raise ContextCardsError("情境卡 trace 必須是物件")
    for field in ["event", "keywords", "themes"]:
        if field not in trace:
            raise ContextCardsError(f"情境卡 trace 缺少欄位: {field}")
    if trace.get("event") not in EVENT_TRACE_MAP:
        raise ContextCardsError(f"情境卡 trace.event 不合法: {trace.get('event')}")
    if not isinstance(trace.get("keywords"), list) or not trace["keywords"]:
        raise ContextCardsError("情境卡 trace.keywords 必須是非空列表")
    if not isinstance(trace.get("themes"), list) or not trace["themes"]:
        raise ContextCardsError("情境卡 trace.themes 必須是非空列表")
    if any(keyword_id not in KEYWORD_DICTIONARY for keyword_id in trace["keywords"]):
        raise ContextCardsError(f"情境卡 trace.keywords 不在 dictionary: {trace['keywords']}")
    if any(theme_id not in THEME_TAXONOMY for theme_id in trace["themes"]):
        raise ContextCardsError(f"情境卡 trace.themes 不在 taxonomy: {trace['themes']}")
    if card["keywords"] != trace_keyword_labels(trace["keywords"]):
        raise ContextCardsError(f"情境卡 keywords 與 trace 不一致: {card['id']}")
    if card["themes"] != trace_theme_labels(trace["themes"]):
        raise ContextCardsError(f"情境卡 themes 與 trace 不一致: {card['id']}")

    for candidate in candidate_stocks:
        if not isinstance(candidate, dict):
            raise ContextCardsError(f"候選股票格式錯誤: {card['id']}")
        missing = [field for field in CANDIDATE_REQUIRED_FIELDS if field not in candidate]
        if missing:
            raise ContextCardsError(f"候選股票缺少欄位: {missing}")
        for field in CANDIDATE_REQUIRED_FIELDS:
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                raise ContextCardsError(f"候選股票欄位 {field} 必須是非空字串")
        if candidate["from_theme"] not in trace["themes"]:
            raise ContextCardsError(f"候選股票 from_theme 不在 trace.themes: {candidate}")
        if candidate["trace_event"] != trace["event"]:
            raise ContextCardsError(f"候選股票 trace_event 與卡片 trace 不一致: {candidate}")
        if _contains_prohibited_phrase(candidate["reason"]):
            raise ContextCardsError(f"候選股票 reason 含有禁止建議字樣: {candidate}")

    if card.get("confidence") not in VALID_CONFIDENCE:
        raise ContextCardsError(f"情境卡 confidence 不合法: {card.get('confidence')}")
    if card.get("relation_to_technical") not in VALID_RELATION:
        raise ContextCardsError(
            f"情境卡 relation_to_technical 不合法: {card.get('relation_to_technical')}"
        )

    reasoning_chain = card.get("reasoning_chain")
    if not isinstance(reasoning_chain, list) or not (3 <= len(reasoning_chain) <= 4):
        raise ContextCardsError("情境卡 reasoning_chain 必須是 3 到 4 項的列表")
    if any(not isinstance(item, str) or not item.strip() for item in reasoning_chain):
        raise ContextCardsError("情境卡 reasoning_chain 內含空值")

    combined_text = "\n".join(_card_texts(card))
    if _contains_prohibited_phrase(combined_text):
        raise ContextCardsError(f"情境卡包含禁止的買賣建議字樣: {card['id']}")

    if banned_terms:
        for term in banned_terms:
            if term and term in combined_text:
                raise ContextCardsError(f"情境卡包含股票名稱或代號: {term}")


def validate_context_report(report: Dict[str, Any], banned_terms: Optional[Set[str]] = None) -> None:
    if report.get("report_version") != REPORT_VERSION:
        raise ContextCardsError(f"report_version 錯誤: {report.get('report_version')}")
    if not isinstance(report.get("date"), str) or not report["date"].strip():
        raise ContextCardsError("date 必須是非空字串")
    if not isinstance(report.get("generated_at"), str) or not report["generated_at"].strip():
        raise ContextCardsError("generated_at 必須是非空字串")
    
    # LEGACY DEPRECATED: trace_catalog, stock_mapping_catalog, cards
    # 這些欄位仍保持相容性驗證，但已標記為 deprecated，不得再作為第三頁主來源
    trace_catalog_data = _get_legacy_trace_catalog(report)
    if trace_catalog_data != trace_catalog():
        raise ContextCardsError("trace_catalog 與固定 dictionary/taxonomy 不一致")
    
    stock_mapping_catalog = _get_legacy_stock_mapping_catalog(report)
    if not stock_mapping_catalog:
        raise ContextCardsError("stock_mapping_catalog 必須存在")
    template = stock_mapping_catalog_template()
    if stock_mapping_catalog.get("theme_stock_mapping_version") != template["theme_stock_mapping_version"]:
        raise ContextCardsError("stock_mapping_catalog 版本錯誤")
    if stock_mapping_catalog.get("theme_stock_rules") != template["theme_stock_rules"]:
        raise ContextCardsError("stock_mapping_catalog 規則與固定 mapping 不一致")
    if not isinstance(stock_mapping_catalog.get("themes_to_stocks"), dict):
        raise ContextCardsError("stock_mapping_catalog.themes_to_stocks 必須是物件")
    
    cards = _get_legacy_cards(report)
    if not cards:
        raise ContextCardsError("cards 必須是非空列表")
    for card in cards:
        validate_context_card(card, banned_terms=banned_terms)
        for candidate in card.get("candidate_stocks", []):
            mapped_symbols = stock_mapping_catalog["themes_to_stocks"].get(candidate["from_theme"], [])
            if candidate["symbol"] not in mapped_symbols:
                raise ContextCardsError(f"候選股票不在固定 mapping 表內: {candidate}")
    # END LEGACY DEPRECATED

    # THIRD-PAGE SINGLE SOURCE OF TRUTH: scenario_cards_v9
    # 第三頁市場情境卡唯一真相源，所有第三頁 render 必須只讀此欄位
    if report.get("scenario_cards_v9_schema_version") != SCENARIO_CARDS_V9_SCHEMA_VERSION:
        raise ContextCardsError("scenario_cards_v9_schema_version 錯誤")
    scenario_cards_v9 = report.get("scenario_cards_v9")
    if not isinstance(scenario_cards_v9, list) or not scenario_cards_v9:
        raise ContextCardsError("scenario_cards_v9 必須是非空列表")
    for card in scenario_cards_v9:
        validate_scenario_card_v9(card, banned_terms=banned_terms)


def _build_card(
    card_id: str,
    title: str,
    event: str,
    anomaly: str,
    trace: Dict[str, Any],
    candidate_stocks: Sequence[Dict[str, str]],
    reasoning_chain: Sequence[str],
    confidence: str,
    relation_to_technical: str,
    source_type: str,
    generated_at: str,
) -> Dict[str, Any]:
    return {
        "id": card_id,
        "title": title,
        "event": event,
        "anomaly": anomaly,
        "keywords": _unique_strings(trace_keyword_labels(trace["keywords"])),
        "themes": _unique_strings(trace_theme_labels(trace["themes"])),
        "trace": trace,
        "candidate_stocks": list(candidate_stocks),
        "reasoning_chain": list(reasoning_chain)[:4],
        "confidence": confidence,
        "relation_to_technical": relation_to_technical,
        "source_type": source_type,
        "generated_at": generated_at,
    }


def _fallback_card(index: int, date_str: str, generated_at: str, reason: str) -> Dict[str, Any]:
    trace = build_trace("context_unavailable", {})
    return _build_card(
        f"fallback-{index}",
        "情境資料不足",
        "目前可用資料不足，暫時無法穩定整理出完整市場情境。",
        reason,
        trace,
        [],
        [
            f"情境卡日期為 {date_str}，目前維持頁面可讀取狀態。",
            "既有首頁與個股頁保持原樣，這次升級只影響第三頁情境層。",
            "待固定 schema 與 trace 資料補齊後，頁面會自動恢復可追溯情境卡。",
        ],
        "low",
        "neutral",
        "system_fallback",
        generated_at,
    )


def _build_v9_snapshot(
    full_report: Dict[str, Any],
    universe_report: Optional[Dict[str, Any]],
    ai_report: Optional[Dict[str, Any]],
    activation_report: Optional[Dict[str, Any]],
    date_str: str,
) -> Optional[Dict[str, Any]]:
    universe_stocks = list((universe_report or {}).get("stocks") or full_report.get("stocks") or [])
    full_stocks = list(full_report.get("stocks") or [])
    stocks = universe_stocks or full_stocks
    if not stocks:
        return None

    summary = full_report.get("summary") or {}
    market_overview = str(summary.get("market_overview") or "")
    market_meta = _parse_market_overview_meta(market_overview)

    top_sample = sorted(
        stocks,
        key=lambda stock: (
            stock.get("rank") is None,
            stock.get("rank", 9999),
            -(_as_float(stock.get("score")) or 0.0),
        ),
    )[: min(10, len(stocks))]
    category_counter = Counter(str(stock.get("category") or "其他").strip() or "其他" for stock in top_sample)
    top_category_entries = category_counter.most_common(2)
    top_two_total = sum(count for _, count in top_category_entries)
    top_two_share = (top_two_total / len(top_sample)) if top_sample else None
    top_sample_avg_volume_ratio = _average(_volume_ratio(stock) for stock in top_sample)

    hot_stocks = [stock for stock in stocks if (_volume_ratio(stock) or 0) >= 1.5]
    hot_category_counter = Counter(str(stock.get("category") or "其他").strip() or "其他" for stock in hot_stocks)
    overlap_categories = [
        category
        for category, _ in category_counter.most_common(3)
        if hot_category_counter.get(category)
    ]

    positive_count = 0
    cautious_count = 0
    avg_score = _average(_as_float(stock.get("score")) for stock in stocks)
    for stock in stocks:
        bucket = _score_bucket(_as_float(stock.get("score")))
        if bucket in {"A", "B"}:
            positive_count += 1
        elif bucket in {"C", "D"}:
            cautious_count += 1

    technical_direction = "中性"
    if avg_score is not None:
        if avg_score >= 65 and positive_count >= cautious_count:
            technical_direction = "偏多"
        elif avg_score < 55 or cautious_count > positive_count:
            technical_direction = "偏保守"

    return {
        "date": date_str,
        "total_count": len(stocks),
        "avg_score": avg_score,
        "positive_count": positive_count,
        "cautious_count": cautious_count,
        "top_sample_count": len(top_sample),
        "top_sample_avg_volume_ratio": top_sample_avg_volume_ratio,
        "category_counter": category_counter,
        "top_category_entries": top_category_entries,
        "top_category_labels": [label for label, _ in top_category_entries],
        "top_two_share": top_two_share,
        "hot_stocks": hot_stocks,
        "hot_category_counter": hot_category_counter,
        "hot_share": (len(hot_stocks) / len(stocks)) if stocks else None,
        "hot_high_score_count": sum(1 for stock in hot_stocks if (_as_float(stock.get("score")) or 0) >= 60),
        "overlap_categories": overlap_categories,
        "technical_direction": technical_direction,
        "ai_direction": _clean_direction(str((ai_report or {}).get("market_overview_ai") or "")),
        "market_overview": market_overview,
        "market_strength_score": market_meta["strength_score"],
        "market_strong_count": (
            int(market_meta["strong_stock_count"])
            if market_meta["strong_stock_count"] is not None
            else len(summary.get("top_picks") or []) if isinstance(summary.get("top_picks"), list) else None
        ),
        "watchlist_count": len(summary.get("watchlist") or []) if isinstance(summary.get("watchlist"), list) else 0,
        "ai_market_overview": str((ai_report or {}).get("market_overview_ai") or ""),
        "generated_at": _select_generated_at(
            (universe_report or {}).get("generated_at"),
            full_report.get("generated_at"),
            (ai_report or {}).get("generated_at"),
            (activation_report or {}).get("generated_at"),
        ),
    }


def _format_strength_score(snapshot: Dict[str, Any]) -> str:
    if snapshot.get("market_strength_score") is not None:
        return f"{_format_num(snapshot['market_strength_score'], 0)} 分"
    if snapshot.get("avg_score") is not None:
        return f"{_format_num(snapshot['avg_score'])} 分"
    return "--"


def _build_v9_card(
    card_id: str,
    title: str,
    summary: str,
    confidence: str,
    relation_to_technical: str,
    source_type: str,
    themes: Sequence[str],
    reasoning_chain: Sequence[str],
    generated_at: str,
    is_fallback: bool = False,
) -> Dict[str, Any]:
    source_types = _parse_source_types(source_type)
    return {
        "id": card_id,
        "title": title,
        "summary": summary.strip(),
        "confidence": confidence,
        "relation_to_technical": _normalize_relation_to_technical(relation_to_technical) or "neutral",
        "source_types": source_types,
        "source_type": "+".join(source_types),
        "themes": _unique_strings(themes, limit=4),
        "reasoning_chain": [str(item).strip() for item in reasoning_chain if str(item).strip()],
        "priority_score": 0,
        "priority_rank": 0,
        "priority_reasons": [],
        "is_fallback": bool(is_fallback),
        "generated_at": generated_at,
    }


def _build_v9_summary(event: str, anomaly: str) -> str:
    event_text = str(event or "").strip()
    anomaly_text = str(anomaly or "").strip()
    return f"{event_text} {anomaly_text}".strip()


def _build_v9_fallback_card(index: int, reason: str, generated_at: str) -> Dict[str, Any]:
    event = "目前可用市場資料不足，第三頁先保留弱訊號載體。"
    return _build_v9_card(
        f"fallback-{index}",
        f"保底情境卡 {index}",
        _build_v9_summary(event, reason),
        "low",
        "neutral",
        "system_fallback",
        ["制度環境"],
        [
            "訊號 A：必要市場資料缺口過大，無法完成雙訊號以上的交叉判讀。",
            "訊號 B：為了維持固定 schema，系統先保留第三頁載體，不中斷其他頁面使用。",
            "交叉判讀：當前資訊不足以形成可驗證的弱訊號，所以只能回退到保底描述。",
            "限制：這個 fallback 不影響首頁、股票總覽與個股頁的既有功能。",
        ],
        generated_at,
        is_fallback=True,
    )


def _build_v9_breadth_card(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not snapshot:
        return _build_v9_fallback_card(1, "缺少 full/universe 報表，無法建立盤面廣度推理卡。", get_taiwan_now().isoformat())

    breadth_gap = int(snapshot["positive_count"]) - int(snapshot["cautious_count"])
    score_text = _format_strength_score(snapshot)
    strong_count_text = f"{snapshot['market_strong_count']} 檔" if snapshot.get("market_strong_count") is not None else "未提供"
    ai_aligned = snapshot["ai_direction"] != "中性" and snapshot["ai_direction"] == snapshot["technical_direction"]
    event = "市場廣度、總覽分數與 AI 方向同向，偏強結構具備可驗證的弱訊號。"

    if breadth_gap < 0:
        event = (
            "市場廣度與 AI 方向同時轉保守，偏弱結構已形成可追蹤弱訊號。"
            if ai_aligned
            else "市場廣度偏保守，但 AI 敘事沒有完全同步，偏弱訊號仍待驗證。"
        )
    elif abs(breadth_gap) < 6:
        event = "整體分數仍偏正面，但廣度優勢尚未拉開，市場只形成初步弱訊號。"
    elif not ai_aligned:
        event = (
            "盤面廣度偏強，但 AI 敘事仍偏保留，偏強訊號需要後續驗證。"
            if snapshot["ai_direction"] == "中性"
            else "盤面廣度與 AI 方向不同步，這層偏強訊號暫時只算待確認。"
        )

    confidence = "low"
    if abs(breadth_gap) >= 10 and snapshot.get("avg_score") is not None and snapshot["avg_score"] >= 60:
        confidence = "high" if ai_aligned or snapshot["ai_direction"] == "中性" else "medium"
    elif abs(breadth_gap) >= 4 and snapshot.get("avg_score") is not None:
        confidence = "medium"

    anomaly = f"市場總覽約 {score_text}，強勢樣本約 {strong_count_text}，A/B {snapshot['positive_count']} 檔、C/D {snapshot['cautious_count']} 檔。"
    return _build_v9_card(
        "breadth-balance",
        "盤面廣度與強弱分布",
        _build_v9_summary(event, anomaly),
        confidence,
        "neutral" if snapshot["technical_direction"] == "中性" else "aligned",
        "market_overview+score_distribution+ai_market_overview",
        ["市場廣度", "情緒校準"],
        [
            f"訊號 A：市場總覽顯示平均強度約 {score_text}，強勢樣本約 {strong_count_text}，代表風險承擔沒有快速收縮。",
            f"訊號 B：A/B 比 C/D {'多' if breadth_gap >= 0 else '少'} {abs(breadth_gap)} 檔，平均分數約 {_format_num(snapshot.get('avg_score'))}，盤面不是只靠少數極端樣本撐住。",
            (
                f"交叉判讀：AI 方向目前為「{snapshot['ai_direction']}」，與橫截面結構同向，情緒端暫時有接到結構訊號。"
                if ai_aligned
                else (
                    "交叉判讀：AI 方向目前為「中性」，代表情緒端仍保留中性，這個弱訊號只完成一部分驗證。"
                    if snapshot["ai_direction"] == "中性"
                    else f"交叉判讀：AI 方向目前為「{snapshot['ai_direction']}」，與橫截面不同向，情緒端還沒有完全接球。"
                )
            ),
            "限制：這張卡只保留市場層推理，不延伸到任何股票與操作結論。",
        ],
        snapshot["generated_at"],
    )


def _build_v9_sector_card(snapshot: Optional[Dict[str, Any]], activation_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not snapshot or not snapshot["top_category_entries"]:
        return _build_v9_fallback_card(2, "缺少類別集中度資料，無法建立主軸收斂推理卡。", (snapshot or {}).get("generated_at") or get_taiwan_now().isoformat())

    has_activation = bool(activation_report)
    capital_label = str((((activation_report or {}).get("current_market_snapshot") or {}).get("capital_concentration") or {}).get("label") or "未提供")
    overlap_text = "、".join(snapshot["overlap_categories"]) if snapshot["overlap_categories"] else "尚未與主軸明顯重疊"
    top_summary = _category_summary(snapshot["category_counter"])
    event = "主軸集中與放量重疊同時出現，盤面開始形成可追蹤的弱主題。"

    if (snapshot.get("top_two_share") or 0) < 0.45:
        event = "前段類別仍偏分散，主題輪動尚未沉澱成穩定弱訊號。"
    elif not snapshot["overlap_categories"]:
        event = "前段類別已有主軸，但放量訊號沒有同步跟上，主題仍在試圖成形。"
    elif has_activation and capital_label != "集中":
        event = "前段主軸已有輪廓，但制度層仍把集中度視為可接受範圍，代表主題尚未完全鎖定。"

    anomaly = f"前 {snapshot['top_sample_count']} 名樣本中，前兩大類別占比約 {_format_pct(snapshot.get('top_two_share'))}，放量重疊類別為 {overlap_text}。"
    return _build_v9_card(
        "sector-concentration",
        "主軸集中度",
        _build_v9_summary(event, anomaly),
        "high" if (snapshot.get("top_two_share") or 0) >= 0.6 and snapshot["overlap_categories"] else "medium" if (snapshot.get("top_two_share") or 0) >= 0.45 else "low",
        "aligned" if (snapshot.get("top_two_share") or 0) >= 0.45 and snapshot["overlap_categories"] else "neutral",
        "sector_concentration+volume_anomaly+strategy_activation" if has_activation else "sector_concentration+volume_anomaly",
        ["資金輪動", "主流收斂"],
        [
            f"訊號 A：前 {snapshot['top_sample_count']} 名樣本裡，主軸目前集中在 {top_summary}，代表資金注意力開始收斂。",
            f"訊號 B：放量樣本與前段主軸重疊在 {overlap_text}，用來確認主題不是只有排名集中，還有量能呼應。",
            f"訊號 C：steady_v5 的資金集中度欄位目前標記為「{capital_label}」，制度層也把這個結構納入環境判讀。",
            (
                "交叉判讀：類別集中與量能重疊同時存在，主題輪廓比較像可追蹤的弱訊號。"
                if (snapshot.get("top_two_share") or 0) >= 0.45 and snapshot["overlap_categories"]
                else "交叉判讀：集中度或量能其中一邊尚未到位，所以只能先視為題材輪動線索。"
            ),
        ],
        snapshot["generated_at"],
    )


def _build_v9_volume_card(snapshot: Optional[Dict[str, Any]], activation_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not snapshot:
        return _build_v9_fallback_card(3, "缺少量能資料，無法建立量能擴散推理卡。", get_taiwan_now().isoformat())

    has_activation = bool(activation_report)
    volume_label = str((((activation_report or {}).get("current_market_snapshot") or {}).get("volume") or {}).get("label") or "未提供")
    hot_summary = _category_summary(snapshot["hot_category_counter"])
    front_avg_volume_text = _format_num(snapshot.get("top_sample_avg_volume_ratio"), 2)
    event = "量能擴散與高分結構同步，市場注意力不是孤點放量。"

    if not snapshot["hot_stocks"]:
        event = "量能尚未形成有效擴散，市場只剩局部觀察訊號。"
    elif has_activation and volume_label != "放量":
        event = "局部放量已出現，但制度層未確認整體放量，弱訊號仍偏早。"
    elif snapshot["hot_high_score_count"] < max(1, (len(snapshot["hot_stocks"]) + 1) // 2):
        event = "有放量，但高分結構承接不足，訊號品質仍待確認。"

    anomaly = f"量比大於等於 1.5 的樣本共 {len(snapshot['hot_stocks'])} 檔，占全體約 {_format_pct(snapshot.get('hot_share'))}；前段平均量比約 {front_avg_volume_text}，制度量能標記為「{volume_label}」。"
    return _build_v9_card(
        "volume-focus",
        "量能異常與擴散",
        _build_v9_summary(event, anomaly),
        "high" if len(snapshot["hot_stocks"]) >= 4 and snapshot["hot_high_score_count"] >= 2 and volume_label == "放量" else "medium" if len(snapshot["hot_stocks"]) >= 2 else "low",
        "aligned" if volume_label == "放量" and snapshot["hot_high_score_count"] >= max(1, len(snapshot["hot_stocks"]) // 2) else "neutral",
        "volume_anomaly+score_distribution+strategy_activation" if has_activation else "volume_anomaly+score_distribution",
        ["量能擴張", "結構分化"],
        [
            f"訊號 A：放量樣本主要落在 {hot_summary}，共 {len(snapshot['hot_stocks'])} 檔，占全體約 {_format_pct(snapshot.get('hot_share'))}。",
            f"訊號 B：放量樣本中有 {snapshot['hot_high_score_count']} 檔同時位於 A/B 區，而整體 breadth 仍是 A/B {snapshot['positive_count']} 對 C/D {snapshot['cautious_count']}，代表量能不是只落在弱勢端。",
            f"訊號 C：steady_v5 的量能欄位標記為「{volume_label}」，前段平均量比約 {front_avg_volume_text}，可用來確認放量是否只是零星雜訊。",
            (
                "交叉判讀：量能、廣度與制度量能同向，這層訊號比較像市場注意力已開始擴散。"
                if len(snapshot["hot_stocks"]) >= 4 and snapshot["hot_high_score_count"] >= 2 and volume_label == "放量"
                else "交叉判讀：量能雖有變化，但廣度或制度層尚未完全接手，所以目前只能算弱訊號。"
            ),
        ],
        snapshot["generated_at"],
    )


def _build_v9_ai_overlay_card(
    snapshot: Optional[Dict[str, Any]],
    ai_report: Optional[Dict[str, Any]],
    activation_report: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not snapshot or not str((ai_report or {}).get("market_overview_ai") or "").strip():
        return None

    has_activation = bool(activation_report)
    relation = _relation_label(snapshot["ai_direction"], snapshot["technical_direction"])
    decision = (activation_report or {}).get("decision") or {}
    pass_count = int(decision.get("pass_count") or 0)
    total_count = int(decision.get("total_condition_count") or 3)
    action = str(decision.get("action") or "未提供").strip() or "未提供"
    event = "AI 敘事與橫截面、制度訊號大致同向，可作為市場情緒的弱驗證。"
    if relation == "conflict":
        event = "AI 敘事方向與橫截面、制度訊號有落差，這張卡只保留分歧。"
    elif relation == "neutral" or pass_count < 2:
        event = "AI 敘事提供方向，但橫截面或制度訊號仍只做到部分驗證。"

    anomaly = f"AI 方向「{snapshot['ai_direction']}」，技術結構「{snapshot['technical_direction']}」，steady_v5 通過 {pass_count}/{total_count} 項。"
    return _build_v9_card(
        "ai-overlay",
        "AI 摘要與技術面對照",
        _build_v9_summary(event, anomaly),
        "high" if relation == "aligned" and pass_count >= 2 and (snapshot.get("hot_share") or 0) >= 0.08 else "low" if relation == "conflict" else "medium",
        relation,
        "ai_market_overview+score_distribution+volume_anomaly+strategy_activation" if has_activation else "ai_market_overview+score_distribution+volume_anomaly",
        ["情緒校準", "敘事驗證"],
        [
            f"訊號 A：AI 只提供市場方向，這裡先把它壓縮成「{snapshot['ai_direction']}」，不帶入任何股票敘事。",
            f"訊號 B：橫截面目前平均分數約 {_format_num(snapshot.get('avg_score'))}，放量樣本占比約 {_format_pct(snapshot.get('hot_share'))}，用來檢查敘事是否有結構支撐。",
            f"訊號 C：steady_v5 目前通過 {pass_count}/{total_count} 項條件，狀態為「{action}」，可用來判斷制度面是否同意這個方向。",
            (
                "交叉判讀：AI、橫截面與制度訊號大致同向，這層敘事比較像可驗證的弱訊號。"
                if relation == "aligned"
                else "交叉判讀：AI 有方向，但橫截面或制度面還沒完全跟上，所以只能當補充線索。"
                if relation == "neutral"
                else "交叉判讀：AI 與橫截面不同向，代表情緒端和市場結構存在落差。"
            ),
        ],
        _select_generated_at((ai_report or {}).get("generated_at"), snapshot["generated_at"]),
    )


def _build_v9_activation_card(snapshot: Optional[Dict[str, Any]], activation_report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not snapshot or not activation_report or not isinstance(activation_report, dict):
        return None

    decision = activation_report.get("decision") or {}
    market_snapshot = activation_report.get("current_market_snapshot") or {}
    pass_count = int(decision.get("pass_count") or 0)
    total_count = int(decision.get("total_condition_count") or 3)
    action = str(decision.get("action") or "未提供").strip() or "未提供"
    trend = str(((market_snapshot.get("market_trend") or {}).get("market_trend")) or "--")
    concentration = str(((market_snapshot.get("capital_concentration") or {}).get("label")) or "--")
    volume = str(((market_snapshot.get("volume") or {}).get("label")) or "--")
    failed_conditions = "、".join(decision.get("failed_conditions") or []) if isinstance(decision.get("failed_conditions"), list) else "無"
    is_aligned_date = str(activation_report.get("as_of_date") or "") == str((snapshot or {}).get("date") or "")
    breadth_text = f"A/B {snapshot['positive_count']} 對 C/D {snapshot['cautious_count']}" if snapshot else "breadth 未提供"
    concentration_share_text = _format_pct((snapshot or {}).get("top_two_share"))
    event = "steady_v5 條件不足，制度層與目前市場結構仍有缺口。"
    if not is_aligned_date:
        event = "steady_v5 最新環境判讀可作背景座標，但不能直接覆蓋所選日期。"
    elif pass_count == total_count:
        event = "steady_v5 適用環境完整，制度層與市場結構同向。"
    elif pass_count >= 2:
        event = "steady_v5 只通過部分條件，顯示環境接近但還不是完整型態。"

    relation = "neutral"
    if trend == "上升" and snapshot:
        if snapshot["technical_direction"] == "偏多":
            relation = "aligned"
        elif snapshot["technical_direction"] == "偏保守":
            relation = "conflict"

    anomaly = f"大盤趨勢 {trend}、資金集中度 {concentration}、量能 {volume}；{breadth_text}，前兩大類別占比約 {concentration_share_text}。"
    return _build_v9_card(
        "regime-activation",
        "steady_v5 啟用環境",
        _build_v9_summary(event, anomaly),
        "high" if is_aligned_date and pass_count == total_count else "medium" if is_aligned_date and pass_count >= 2 else "low",
        relation,
        "strategy_activation+score_distribution+sector_concentration+volume_anomaly",
        ["制度環境", "策略適配"],
        [
            f"訊號 A：steady_v5 目前通過 {pass_count}/{total_count} 項條件，未通過的主要缺口是 {failed_conditions or '無'}。",
            f"訊號 B：同一批市場橫截面資料裡，平均分數約 {_format_num((snapshot or {}).get('avg_score'))}，{breadth_text}，代表風險承擔是否還撐得住。",
            f"訊號 C：前兩大類別占比約 {concentration_share_text}，而量能標記為「{volume}」，可用來判斷是分散輪動還是集中衝刺。",
            "同日校準：這張卡與目前日期對齊，所以可以拿來當制度背景。"
            if is_aligned_date
            else f"日期限制：啟用判斷日期為 {activation_report.get('as_of_date')}，與目前查看日期不同，只能當背景參考。",
            "限制：這張卡只保留制度與市場結構的交叉判讀，不轉成股票清單或操作指令。",
        ],
        _select_generated_at(activation_report.get("generated_at")),
    )


def _parse_source_types(source_type: str) -> List[str]:
    return _unique_strings(str(source_type or "").split("+"), limit=8)


def _is_fallback_scenario_card(card: Dict[str, Any]) -> bool:
    return bool(card.get("is_fallback")) or str(card.get("id") or "").startswith("fallback-")


def _get_source_coverage_score(card: Dict[str, Any]) -> Tuple[int, int]:
    count = min(len(_parse_source_types(card.get("source_type") or "")), 4)
    return count, SOURCE_COVERAGE_POINTS.get(count, 0)


def _get_confidence_score(card: Dict[str, Any]) -> int:
    return CONFIDENCE_POINTS.get(str(card.get("confidence") or ""), 0)


def _get_technical_alignment_score(card: Dict[str, Any]) -> int:
    return TECHNICAL_ALIGNMENT_POINTS.get(_normalize_relation_to_technical(card.get("relation_to_technical")), 0)


def _get_institutional_support_score(card: Dict[str, Any], activation_report: Optional[Dict[str, Any]]) -> int:
    if not activation_report:
        return 0
    return INSTITUTIONAL_SUPPORT_POINTS if "strategy_activation" in _parse_source_types(card.get("source_type") or "") else 0


def _get_cross_validation_score(card: Dict[str, Any]) -> Tuple[str, int]:
    sources = set(_parse_source_types(card.get("source_type") or ""))
    has_volume_signal = bool(sources & VOLUME_SIGNAL_SOURCES)
    has_structure_signal = bool(sources & STRUCTURE_SIGNAL_SOURCES)
    if has_volume_signal and has_structure_signal:
        return "confirmed", CROSS_VALIDATION_POINTS["confirmed"]
    if has_volume_signal or has_structure_signal:
        return "partial", CROSS_VALIDATION_POINTS["partial"]
    return "none", CROSS_VALIDATION_POINTS["none"]


def _get_reasoning_chain_score(card: Dict[str, Any]) -> Tuple[str, int]:
    if _is_fallback_scenario_card(card):
        return "weak", REASONING_CHAIN_POINTS["weak"]
    lines = [str(item).strip() for item in card.get("reasoning_chain") or [] if str(item).strip()]
    joined = " ".join(lines)
    has_connector = any(token in joined for token in ("交叉判讀", "因此", "代表", "顯示", "支持", "驗證", "呼應"))
    if len(lines) >= 3 and has_connector:
        return "strong", REASONING_CHAIN_POINTS["strong"]
    if len(lines) >= 2:
        return "basic", REASONING_CHAIN_POINTS["basic"]
    return "weak", REASONING_CHAIN_POINTS["weak"]


def _build_card_priority(card: Dict[str, Any], activation_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    source_count, source_coverage_score = _get_source_coverage_score(card)
    confidence_score = _get_confidence_score(card)
    normalized_relation = _normalize_relation_to_technical(card.get("relation_to_technical")) or "neutral"
    technical_alignment_score = _get_technical_alignment_score(card)
    institutional_support_score = _get_institutional_support_score(card, activation_report)
    cross_validation_level, cross_validation_score = _get_cross_validation_score(card)
    reasoning_chain_level, reasoning_chain_score = _get_reasoning_chain_score(card)
    is_fallback = _is_fallback_scenario_card(card)
    fallback_penalty = FALLBACK_PENALTY if is_fallback else 0

    reasons = [
        f"訊號來源 {source_count} 類",
        f"confidence={card.get('confidence')}",
        "技術面一致" if normalized_relation == "aligned" else "技術面中性" if normalized_relation == "neutral" else "技術面衝突",
        "有制度層支持" if institutional_support_score > 0 else "無制度層支持",
        "量能與廣度交叉驗證成立" if cross_validation_level == "confirmed" else "量能或廣度部分驗證" if cross_validation_level == "partial" else "缺少量能與廣度交叉驗證",
        f"reasoning_chain={reasoning_chain_level}",
    ]
    if is_fallback:
        reasons.append("fallback 卡固定排後")

    return {
        "priority_score": (
            source_coverage_score
            + confidence_score
            + technical_alignment_score
            + institutional_support_score
            + cross_validation_score
            + reasoning_chain_score
            + fallback_penalty
        ),
        "priority_reasons": reasons,
        "is_fallback": is_fallback,
        "_priority_breakdown": {
            "source_coverage_score": source_coverage_score,
            "source_count": source_count,
            "confidence_score": confidence_score,
            "technical_alignment_score": technical_alignment_score,
            "institutional_support_score": institutional_support_score,
            "cross_validation_score": cross_validation_score,
            "reasoning_chain_score": reasoning_chain_score,
            "fallback_penalty": fallback_penalty,
        },
    }


def _sort_scenario_cards_v9(cards: List[Dict[str, Any]], activation_report: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked_cards: List[Dict[str, Any]] = []
    for index, card in enumerate(cards):
        ranked = dict(card)
        ranked.update(_build_card_priority(card, activation_report))
        ranked_cards.append(ranked)

    CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}
    RELATION_ORDER = {"aligned": 3, "neutral": 2, "conflict": 1}

    def _sort_key(item: Dict[str, Any]) -> Tuple[int, int, int, int, str]:
        return (
            1 if item["is_fallback"] else 0,
            -int(item["priority_score"]),
            -len(item.get("source_types", [])),
            -CONFIDENCE_ORDER.get(item.get("confidence", ""), 0),
            -RELATION_ORDER.get(_normalize_relation_to_technical(item.get("relation_to_technical")), 0),
            str(item.get("id", "")),
        )

    ordered = sorted(ranked_cards, key=_sort_key)
    for rank, card in enumerate(ordered, start=1):
        card["priority_rank"] = rank
        card.pop("_priority_breakdown", None)
    return ordered


def _card_texts_v9(card: Dict[str, Any]) -> Iterable[str]:
    yield str(card.get("id") or "")
    yield str(card.get("title") or "")
    yield str(card.get("summary") or "")
    yield str(card.get("source_type") or "")
    for item in card.get("themes", []) or []:
        yield str(item)
    for item in card.get("reasoning_chain", []) or []:
        yield str(item)
    for item in card.get("priority_reasons", []) or []:
        yield str(item)


def validate_scenario_card_v9(card: Dict[str, Any], banned_terms: Optional[Set[str]] = None) -> None:
    missing = [field for field in SCENARIO_CARDS_V9_REQUIRED_FIELDS if field not in card]
    if missing:
        raise ContextCardsError(f"scenario_cards_v9 缺少欄位: {missing}")

    for field in ["id", "title", "summary", "source_type", "generated_at"]:
        if not isinstance(card.get(field), str) or not str(card.get(field)).strip():
            raise ContextCardsError(f"scenario_cards_v9 欄位 {field} 必須是非空字串")

    if not isinstance(card.get("source_types"), list) or not card["source_types"]:
        raise ContextCardsError("scenario_cards_v9 source_types 必須是非空陣列")
    if any(not isinstance(item, str) or not item.strip() for item in card["source_types"]):
        raise ContextCardsError("scenario_cards_v9 source_types 內含空值")
    if len(card["source_types"]) != len(set(card["source_types"])):
        raise ContextCardsError("scenario_cards_v9 source_types 不可重複")

    if not isinstance(card.get("priority_rank"), int):
        raise ContextCardsError("scenario_cards_v9 priority_rank 必須是整數")

    if card.get("confidence") not in VALID_CONFIDENCE:
        raise ContextCardsError(f"scenario_cards_v9 confidence 不合法: {card.get('confidence')}")
    if _normalize_relation_to_technical(card.get("relation_to_technical")) not in VALID_RELATION:
        raise ContextCardsError(f"scenario_cards_v9 relation_to_technical 不合法: {card.get('relation_to_technical')}")
    if not isinstance(card.get("themes"), list) or not card["themes"]:
        raise ContextCardsError("scenario_cards_v9 themes 必須是非空列表")
    if any(not isinstance(item, str) or not item.strip() for item in card["themes"]):
        raise ContextCardsError("scenario_cards_v9 themes 內含空值")
    if not isinstance(card.get("reasoning_chain"), list) or len(card["reasoning_chain"]) < 3:
        raise ContextCardsError("scenario_cards_v9 reasoning_chain 至少需要 3 項")
    if any(not isinstance(item, str) or not item.strip() for item in card["reasoning_chain"]):
        raise ContextCardsError("scenario_cards_v9 reasoning_chain 內含空值")
    if not isinstance(card.get("priority_score"), int):
        raise ContextCardsError("scenario_cards_v9 priority_score 必須是整數")
    if not isinstance(card.get("priority_reasons"), list) or not card["priority_reasons"]:
        raise ContextCardsError("scenario_cards_v9 priority_reasons 必須是非空列表")
    if any(not isinstance(item, str) or not item.strip() for item in card["priority_reasons"]):
        raise ContextCardsError("scenario_cards_v9 priority_reasons 內含空值")
    if not isinstance(card.get("is_fallback"), bool):
        raise ContextCardsError("scenario_cards_v9 is_fallback 必須是布林值")

    combined_text = "\n".join(_card_texts_v9(card))
    if _contains_prohibited_phrase(combined_text):
        raise ContextCardsError(f"scenario_cards_v9 包含禁止的買賣建議字樣: {card['id']}")
    if banned_terms:
        for term in banned_terms:
            if term and term in combined_text:
                raise ContextCardsError(f"scenario_cards_v9 包含股票名稱或代號: {term}")


def _build_scenario_cards_v9(
    full_report: Dict[str, Any],
    universe_report: Optional[Dict[str, Any]],
    ai_report: Optional[Dict[str, Any]],
    activation_report: Optional[Dict[str, Any]],
    banned_terms: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    date_str = str(full_report.get("date") or get_today_str())
    snapshot = _build_v9_snapshot(full_report, universe_report, ai_report, activation_report, date_str)
    generated_at = (snapshot or {}).get("generated_at") or get_taiwan_now().isoformat()

    cards: List[Dict[str, Any]] = [
        _build_v9_breadth_card(snapshot),
        _build_v9_sector_card(snapshot, activation_report),
        _build_v9_volume_card(snapshot, activation_report),
    ]
    ai_card = _build_v9_ai_overlay_card(snapshot, ai_report, activation_report)
    if ai_card:
        cards.append(ai_card)
    activation_card = _build_v9_activation_card(snapshot, activation_report)
    if activation_card:
        cards.append(activation_card)

    while len(cards) < 3:
        cards.append(
            _build_v9_fallback_card(len(cards) + 1, "可用市場資料不足，已補上保底卡。", generated_at)
        )

    ranked_cards = _sort_scenario_cards_v9(cards[:5], activation_report)
    validated_cards: List[Dict[str, Any]] = []
    replaced = False
    for card in ranked_cards:
        try:
            validate_scenario_card_v9(card, banned_terms=banned_terms)
            validated_cards.append(card)
        except ContextCardsError:
            replaced = True
            validated_cards.append(
                _build_v9_fallback_card(len(validated_cards) + 1, "原始情境卡內容不符合 v9 contract，已改用保底卡。", generated_at)
            )

    if replaced:
        validated_cards = _sort_scenario_cards_v9(validated_cards, activation_report)
        for card in validated_cards:
            validate_scenario_card_v9(card, banned_terms=banned_terms)
    return validated_cards


def _build_signal_snapshot(
    universe_stocks: List[Dict[str, Any]],
    market_overview: str,
    ai_market_overview: str,
) -> Dict[str, Any]:
    scores = [_as_float(stock.get("score")) for stock in universe_stocks]
    valid_scores = [score for score in scores if score is not None]
    avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
    bucket_counter = Counter(_score_bucket(score) for score in valid_scores)
    strong_count = bucket_counter["A"]
    medium_count = bucket_counter["B"]
    cautious_count = bucket_counter["C"]
    weak_count = bucket_counter["D"]

    top_stocks = sorted(
        universe_stocks,
        key=lambda stock: (
            stock.get("rank") is None,
            stock.get("rank", 9999),
            -_as_float(stock.get("score")) if _as_float(stock.get("score")) is not None else 0,
        ),
    )[:10]
    top_category_counter = Counter(str(stock.get("category") or "其他") for stock in top_stocks)
    top_categories = _top_labels(top_category_counter)
    top_two_total = sum(count for _, count in top_category_counter.most_common(2))
    top_two_share = top_two_total / len(top_stocks) if top_stocks else 0.0

    hot_stocks = [stock for stock in universe_stocks if (_volume_ratio(stock) or 0) >= 1.5]
    hot_category_counter = Counter(str(stock.get("category") or "其他") for stock in hot_stocks)
    hot_categories = _top_labels(hot_category_counter)
    hot_share = len(hot_stocks) / len(universe_stocks) if universe_stocks else 0.0
    hot_high_score_count = sum(1 for stock in hot_stocks if (_as_float(stock.get("score")) or 0) >= 60)
    overlap_categories = [category for category in hot_categories if category in top_categories]

    market_direction = _clean_direction(market_overview)
    ai_direction = _clean_direction(ai_market_overview)
    technical_direction = _technical_direction(avg_score, strong_count, weak_count)

    return {
        "avg_score": avg_score,
        "strong_count": strong_count,
        "medium_count": medium_count,
        "cautious_count": cautious_count,
        "weak_count": weak_count,
        "bucket_counter": bucket_counter,
        "market_direction": market_direction,
        "ai_direction": ai_direction,
        "technical_direction": technical_direction,
        "top_category_counter": top_category_counter,
        "top_categories": top_categories,
        "top_two_total": top_two_total,
        "top_two_share": top_two_share,
        "hot_stocks": hot_stocks,
        "hot_category_counter": hot_category_counter,
        "hot_categories": hot_categories,
        "hot_share": hot_share,
        "hot_high_score_count": hot_high_score_count,
        "overlap_categories": overlap_categories,
        "market_overview": market_overview,
        "ai_market_overview": ai_market_overview,
        "universe_count": len(universe_stocks),
    }


def _build_stock_lookup(universe_stocks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for stock in universe_stocks:
        symbol = str(stock.get("symbol") or "").strip()
        if symbol and symbol not in lookup:
            lookup[symbol] = stock
    return lookup


def _candidate_reason(theme_id: str, symbol: str, stock_lookup: Dict[str, Dict[str, Any]], stock_mapping_catalog: Dict[str, Any]) -> str:
    stock = stock_lookup.get(symbol, {})
    category = str(stock.get("category") or "其他").strip() or "其他"
    rule = stock_mapping_catalog["theme_stock_rules"][theme_id]
    theme_text = theme_label(theme_id)
    if rule["selector"] == "category":
        return (
            f"{theme_text} 依固定 mapping 對應類別 {', '.join(rule['categories'])}；"
            f"{symbol} 在當日 universe 的類別為 {category}，因此納入此股票池。"
        )
    return f"{theme_text} 在這一版沒有直接股票池。"


def _export_candidate_stocks(
    trace: Dict[str, Any],
    stock_mapping_catalog: Dict[str, Any],
    stock_lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    seen_pairs: Set[tuple[str, str]] = set()
    themes_to_stocks = stock_mapping_catalog["themes_to_stocks"]

    for theme_id in trace["themes"]:
        for symbol in themes_to_stocks.get(theme_id, []):
            pair = (theme_id, symbol)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            candidates.append(
                {
                    "symbol": symbol,
                    "from_theme": theme_id,
                    "trace_event": trace["event"],
                    "reason": _candidate_reason(theme_id, symbol, stock_lookup, stock_mapping_catalog),
                }
            )

    return candidates


def _build_market_breadth_card(
    signals: Dict[str, Any],
    stock_mapping_catalog: Dict[str, Any],
    stock_lookup: Dict[str, Dict[str, Any]],
    generated_at: str,
) -> Dict[str, Any]:
    positive_count = signals["strong_count"] + signals["medium_count"]
    cautious_count = signals["cautious_count"] + signals["weak_count"]
    top_summary = _category_summary(signals["top_category_counter"])
    hot_summary = _category_summary(signals["hot_category_counter"])
    trace = build_trace(
        "breadth_axis_overlap",
        {
            **_sector_trace_bindings(signals["top_categories"]),
            "breadth_signal": "breadth_positive" if positive_count >= cautious_count else "breadth_cautious",
        },
    )
    if positive_count >= cautious_count:
        event = "中高分樣本占優，前段族群與放量區域彼此重疊，盤面主軸可被描述。"
    else:
        event = "中低分樣本仍偏多，但前段與放量區域已有局部重疊，盤面開始出現可追蹤主軸。"

    anomaly = (
        f"A/B 合計 {positive_count} 檔、C/D 合計 {cautious_count} 檔，"
        f"前兩大類別占前段樣本約 {signals['top_two_share']:.0%}，"
        f"放量樣本 {len(signals['hot_stocks'])} 檔。"
    )
    reasoning_chain = [
        f"分數分布上，A/B 合計 {positive_count} 檔高於 C/D 的 {cautious_count} 檔，平均分數約 {signals['avg_score']:.1f}。",
        f"前段 10 筆樣本集中在 {top_summary}，前兩大類別占比約 {signals['top_two_share']:.0%}。",
        f"量比異常樣本共有 {len(signals['hot_stocks'])} 檔，主要落在 {hot_summary}，沒有脫離前段主軸。",
        f"既有市場總覽語氣偏向「{signals['market_direction']}」，可與上述橫截面結果互相驗證。",
    ]
    confidence = "high" if signals["top_two_share"] >= 0.6 and len(signals["hot_stocks"]) >= 3 else "medium"
    return _build_card(
        "breadth-balance",
        "盤面廣度與主軸",
        event,
        anomaly,
        trace,
        _export_candidate_stocks(trace, stock_mapping_catalog, stock_lookup),
        reasoning_chain,
        confidence,
        "aligned",
        "score_distribution+sector_concentration+volume_cluster+market_overview",
        generated_at,
    )


def _build_sector_concentration_card(
    signals: Dict[str, Any],
    stock_mapping_catalog: Dict[str, Any],
    stock_lookup: Dict[str, Dict[str, Any]],
    generated_at: str,
) -> Dict[str, Any]:
    top_category, top_count = signals["top_category_counter"].most_common(1)[0]
    hot_summary = _category_summary(signals["hot_category_counter"])
    overlap_summary = "、".join(signals["overlap_categories"]) if signals["overlap_categories"] else "目前重疊有限"
    trace = build_trace(
        "sector_axis_convergence",
        _sector_trace_bindings(signals["overlap_categories"] or signals["top_categories"]),
    )
    event = "前段類別與放量類別有交集，盤面不是全面輪動，而是局部主軸共振。"
    anomaly = (
        f"前 10 筆樣本中以 {top_category} 最集中，共 {top_count} 筆；"
        f"前兩大類別合計 {signals['top_two_total']} 筆，占比約 {signals['top_two_share']:.0%}。"
    )
    reasoning_chain = [
        f"前段樣本類別以 {_category_summary(signals['top_category_counter'])} 為主，主軸集中度偏高。",
        f"放量樣本則主要落在 {hot_summary}，與前段類別重疊在 {overlap_summary}。",
        f"若只有分數靠前而量能不跟，主軸說服力會下降；目前至少存在局部共振。",
        f"平均分數約 {signals['avg_score']:.1f}，代表這不是單一異常點，而是有橫截面支撐的題材聚焦。",
    ]
    confidence = "high" if signals["top_two_share"] >= 0.5 and signals["overlap_categories"] else "medium"
    return _build_card(
        "sector-concentration",
        "主軸題材收斂",
        event,
        anomaly,
        trace,
        _export_candidate_stocks(trace, stock_mapping_catalog, stock_lookup),
        reasoning_chain,
        confidence,
        "aligned",
        "sector_concentration+volume_cluster+score_distribution",
        generated_at,
    )


def _build_volume_cluster_card(
    signals: Dict[str, Any],
    stock_mapping_catalog: Dict[str, Any],
    stock_lookup: Dict[str, Dict[str, Any]],
    generated_at: str,
) -> Dict[str, Any]:
    hot_count = len(signals["hot_stocks"])
    hot_summary = _category_summary(signals["hot_category_counter"])
    top_summary = _category_summary(signals["top_category_counter"])
    trace = build_trace(
        "volume_focus_limited_diffusion",
        _sector_trace_bindings(signals["hot_categories"] or signals["top_categories"]),
    )
    if hot_count:
        event = "量能異常集中，但擴散率仍有限，市場注意力偏向少數區域。"
        anomaly = (
            f"量比大於等於 1.5 的樣本共有 {hot_count} 筆，占全體約 {signals['hot_share']:.0%}；"
            f"其中 {signals['hot_high_score_count']} 筆同時落在中高分區。"
        )
        reasoning_chain = [
            f"放量樣本占全體約 {signals['hot_share']:.0%}，表示資金注意力不是全面擴散，而是局部聚焦。",
            f"其中 {signals['hot_high_score_count']} 筆同時位於 A/B 區，顯示放量並非單純低分雜訊。",
            f"放量類別主要在 {hot_summary}，且與前段類別 {top_summary} 仍有交集。",
            "因此這張卡描述的是局部關注度升高，而不是全面行情已經成形。",
        ]
        relation = "aligned" if signals["hot_high_score_count"] >= max(1, hot_count // 2) else "neutral"
        confidence = "high" if hot_count >= 4 and signals["hot_high_score_count"] >= 3 else "medium"
    else:
        event = "量能異常沒有形成群聚，盤面暫時缺少可延伸的注意力主軸。"
        anomaly = "量比大於等於 1.5 的樣本不足，量能無法對分數分布形成第二層驗證。"
        reasoning_chain = [
            "分數分布雖可提供強弱排序，但沒有量能群聚時，第二層訊號仍偏薄。",
            "前段類別若缺乏成交量承接，就只能先記為結構輪廓，不能視為主軸共振。",
            "AI 或市場總覽若偏多，也不能取代量能不足的事實，因此本卡維持中性。",
        ]
        relation = "neutral"
        confidence = "medium"

    return _build_card(
        "volume-cluster",
        "量能聚焦與擴散",
        event,
        anomaly,
        trace,
        _export_candidate_stocks(trace, stock_mapping_catalog, stock_lookup),
        reasoning_chain,
        confidence,
        relation,
        "volume_cluster+score_distribution+sector_concentration",
        generated_at,
    )


def _build_ai_alignment_card(
    signals: Dict[str, Any],
    stock_mapping_catalog: Dict[str, Any],
    stock_lookup: Dict[str, Dict[str, Any]],
    generated_at: str,
) -> Dict[str, Any]:
    relation = _relation_label(signals["ai_direction"], signals["technical_direction"])
    trace = build_trace(
        "ai_technical_overlay",
        {
            "ai_direction_keyword": _ai_direction_keyword(signals["ai_direction"]),
            "technical_direction_keyword": _technical_direction_keyword(signals["technical_direction"]),
            **_alignment_trace_bindings(relation),
            **_sector_trace_bindings(signals["top_categories"]),
        },
    )
    if relation == "aligned":
        event = "AI 摘要方向與橫截面資料同向，弱訊號之間有初步收斂。"
    elif relation == "conflict":
        event = "AI 摘要方向與橫截面資料有落差，第三頁應保留疑點而不是擴張敘事。"
    else:
        event = "AI 摘要提供方向感，但橫截面資料仍保留中性空間。"

    anomaly = (
        f"AI 摘要偏向「{signals['ai_direction']}」，"
        f"技術橫截面偏向「{signals['technical_direction']}」，"
        f"放量樣本占比約 {signals['hot_share']:.0%}。"
    )
    reasoning_chain = [
        "AI market overview 只作為情境方向補充，不參與單一標的結論。",
        f"技術橫截面平均分數約 {signals['avg_score']:.1f}，A/B 合計 {signals['strong_count'] + signals['medium_count']} 筆，C/D 合計 {signals['cautious_count'] + signals['weak_count']} 筆。",
        f"量能異常樣本占比約 {signals['hot_share']:.0%}，可用來檢查 AI 方向是否有成交量承接。",
        "當 AI 方向與橫截面一致時，情境可信度提高；若不一致，則維持保留而不外推。",
    ]
    confidence = "high" if relation == "aligned" and signals["hot_share"] >= 0.08 else "medium"
    return _build_card(
        "ai-market-alignment",
        "AI 方向與橫截面對照",
        event,
        anomaly,
        trace,
        _export_candidate_stocks(trace, stock_mapping_catalog, stock_lookup),
        reasoning_chain,
        confidence,
        relation,
        "ai_market_overview+score_distribution+volume_cluster",
        generated_at,
    )


def _collect_banned_terms(*reports: Optional[Dict[str, Any]]) -> Set[str]:
    banned_terms: Set[str] = set()
    for report in reports:
        if not report:
            continue
        for stock in report.get("stocks", []) or []:
            symbol = str(stock.get("symbol") or "").strip()
            name = str(stock.get("name") or "").strip()
            if symbol:
                banned_terms.add(symbol)
            if name:
                banned_terms.add(name)
    return banned_terms


def generate_context_report(
    full_report: Dict[str, Any],
    universe_report: Optional[Dict[str, Any]] = None,
    ai_report: Optional[Dict[str, Any]] = None,
    activation_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    generated_at = get_taiwan_now().isoformat()
    date_str = str(full_report.get("date") or get_today_str())
    market_overview = str((full_report.get("summary") or {}).get("market_overview") or "今日市場資料已載入")
    ai_market_overview = str((ai_report or {}).get("market_overview_ai") or "").strip()

    universe_stocks = list((universe_report or {}).get("stocks") or full_report.get("stocks") or [])
    cards: List[Dict[str, Any]] = []
    stock_mapping_catalog = resolve_theme_stock_mapping(universe_stocks)
    stock_lookup = _build_stock_lookup(universe_stocks)

    if universe_stocks:
        signals = _build_signal_snapshot(universe_stocks, market_overview, ai_market_overview)
        cards.append(_build_market_breadth_card(signals, stock_mapping_catalog, stock_lookup, generated_at))
        cards.append(_build_sector_concentration_card(signals, stock_mapping_catalog, stock_lookup, generated_at))
        cards.append(_build_volume_cluster_card(signals, stock_mapping_catalog, stock_lookup, generated_at))

    if ai_market_overview and universe_stocks:
        cards.append(_build_ai_alignment_card(signals, stock_mapping_catalog, stock_lookup, generated_at))

    if not cards:
        cards.append(_fallback_card(1, date_str, generated_at, "缺少可用的市場橫截面資料。"))

    while len(cards) < 3:
        cards.append(
            _fallback_card(
                len(cards) + 1,
                date_str,
                generated_at,
                "可用情境來源不足，已以保底卡補足固定載體。",
            )
        )

    report = {
        "report_version": REPORT_VERSION,
        "date": date_str,
        "generated_at": generated_at,
        # LEGACY DEPRECATED: trace_catalog, stock_mapping_catalog, cards
        # 這些欄位仍保留以維持相容性，但已標記為 deprecated，不得再作為第三頁主來源
        "trace_catalog": trace_catalog(),
        "stock_mapping_catalog": stock_mapping_catalog,
        "card_count": len(cards),
        "cards": cards[:5],
        # THIRD-PAGE SINGLE SOURCE OF TRUTH: scenario_cards_v9
        # 第三頁市場情境卡唯一真相源，frontend 必須只讀此欄位
        "scenario_cards_v9_schema_version": SCENARIO_CARDS_V9_SCHEMA_VERSION,
        "scenario_cards_v9": _build_scenario_cards_v9(
            full_report,
            universe_report,
            ai_report,
            activation_report,
            banned_terms=_collect_banned_terms(full_report, universe_report),
        ),
    }

    banned_terms = _collect_banned_terms(full_report, universe_report)
    validate_context_report(report, banned_terms=banned_terms)
    return report


def save_context_report(report: Dict[str, Any], date_str: Optional[str] = None, base_dir: Optional[Path] = None) -> Path:
    target_date = date_str or str(report.get("date") or get_today_str())
    path = _reports_dir(base_dir) / f"{target_date}-context.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return path


def generate_context_report_from_files(date_str: str, base_dir: Optional[Path] = None) -> Path:
    reports_dir = _reports_dir(base_dir)
    full_report = _load_json(reports_dir / f"{date_str}.json", required=True)
    universe_report = _load_json(reports_dir / f"{date_str}-universe.json", required=False)
    ai_report = _load_json(reports_dir / f"{date_str}-ai.json", required=False)
    activation_report = _load_json(reports_dir / "strategy_activation.json", required=False)
    if str((activation_report or {}).get("as_of_date") or "") != date_str:
        activation_report = None
    report = generate_context_report(
        full_report,
        universe_report=universe_report,
        ai_report=ai_report,
        activation_report=activation_report,
    )
    return save_context_report(report, date_str=date_str, base_dir=base_dir)
