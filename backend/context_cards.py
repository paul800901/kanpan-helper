"""v9-pre 可追溯情境卡產生器。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

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


REPORT_VERSION = "v9-context"
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_RELATION = {"aligned", "conflict", "neutral"}
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
    if report.get("trace_catalog") != trace_catalog():
        raise ContextCardsError("trace_catalog 與固定 dictionary/taxonomy 不一致")
    stock_mapping_catalog = report.get("stock_mapping_catalog")
    if not isinstance(stock_mapping_catalog, dict):
        raise ContextCardsError("stock_mapping_catalog 必須存在")
    template = stock_mapping_catalog_template()
    if stock_mapping_catalog.get("theme_stock_mapping_version") != template["theme_stock_mapping_version"]:
        raise ContextCardsError("stock_mapping_catalog 版本錯誤")
    if stock_mapping_catalog.get("theme_stock_rules") != template["theme_stock_rules"]:
        raise ContextCardsError("stock_mapping_catalog 規則與固定 mapping 不一致")
    if not isinstance(stock_mapping_catalog.get("themes_to_stocks"), dict):
        raise ContextCardsError("stock_mapping_catalog.themes_to_stocks 必須是物件")
    cards = report.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ContextCardsError("cards 必須是非空列表")
    for card in cards:
        validate_context_card(card, banned_terms=banned_terms)
        for candidate in card.get("candidate_stocks", []):
            mapped_symbols = stock_mapping_catalog["themes_to_stocks"].get(candidate["from_theme"], [])
            if candidate["symbol"] not in mapped_symbols:
                raise ContextCardsError(f"候選股票不在固定 mapping 表內: {candidate}")


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
        "trace_catalog": trace_catalog(),
        "stock_mapping_catalog": stock_mapping_catalog,
        "card_count": len(cards),
        "cards": cards[:5],
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
    report = generate_context_report(full_report, universe_report=universe_report, ai_report=ai_report)
    return save_context_report(report, date_str=date_str, base_dir=base_dir)
