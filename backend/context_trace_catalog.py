"""v9-pre 情境卡 trace dictionary 與 taxonomy。"""

from __future__ import annotations

from typing import Any, Dict


KEYWORD_DICTIONARY_VERSION = "context-keywords-v1"
THEME_TAXONOMY_VERSION = "context-themes-v1"
EVENT_TRACE_VERSION = "context-events-v1"
THEME_STOCK_MAPPING_VERSION = "context-theme-stocks-v1"

KEYWORD_DICTIONARY: Dict[str, Dict[str, str]] = {
    "breadth_positive": {"label": "中高分占優", "source": "score_distribution"},
    "breadth_cautious": {"label": "中低分偏多", "source": "score_distribution"},
    "front_concentration": {"label": "前段集中", "source": "sector_concentration"},
    "volume_overlap": {"label": "放量重疊", "source": "volume_cluster"},
    "sector_concentration": {"label": "族群集中", "source": "sector_concentration"},
    "volume_resonance": {"label": "量能共振", "source": "volume_cluster"},
    "volume_cluster": {"label": "放量群聚", "source": "volume_cluster"},
    "limited_diffusion": {"label": "擴散有限", "source": "volume_cluster"},
    "volume_validation": {"label": "量能驗證", "source": "volume_cluster"},
    "signal_convergence": {"label": "弱訊號收斂", "source": "trace_overlay"},
    "signal_divergence": {"label": "弱訊號分歧", "source": "trace_overlay"},
    "ai_bullish": {"label": "AI偏多", "source": "ai_market_overview"},
    "ai_neutral": {"label": "AI中性", "source": "ai_market_overview"},
    "ai_cautious": {"label": "AI偏保守", "source": "ai_market_overview"},
    "technical_bullish": {"label": "技術偏多", "source": "score_distribution"},
    "technical_neutral": {"label": "技術中性", "source": "score_distribution"},
    "technical_cautious": {"label": "技術偏保守", "source": "score_distribution"},
    "sector_electronics": {"label": "電子", "source": "sector_concentration"},
    "sector_semiconductor": {"label": "半導體", "source": "sector_concentration"},
    "sector_finance": {"label": "金融", "source": "sector_concentration"},
    "sector_materials": {"label": "原物料", "source": "sector_concentration"},
    "sector_transport": {"label": "航運", "source": "sector_concentration"},
    "sector_other": {"label": "其他族群", "source": "sector_concentration"},
    "data_shortage": {"label": "資料不足", "source": "system"},
    "ui_fallback": {"label": "頁面保底", "source": "system"},
}

THEME_TAXONOMY: Dict[str, Dict[str, str]] = {
    "market_breadth": {"label": "盤面廣度", "family": "market_structure"},
    "electronics_axis": {"label": "電子主軸", "family": "industry_axis"},
    "semiconductor_axis": {"label": "半導體主軸", "family": "industry_axis"},
    "finance_axis": {"label": "金融主軸", "family": "industry_axis"},
    "materials_axis": {"label": "原物料主軸", "family": "industry_axis"},
    "transport_axis": {"label": "航運主軸", "family": "industry_axis"},
    "other_axis": {"label": "其他族群主軸", "family": "industry_axis"},
    "rotation_concentration": {"label": "集中輪動", "family": "market_structure"},
    "volume_focus": {"label": "量能聚焦", "family": "flow_structure"},
    "ai_overlay": {"label": "AI摘要對照", "family": "overlay"},
    "trace_convergence": {"label": "情境收斂", "family": "overlay"},
    "trace_divergence": {"label": "情境分歧", "family": "overlay"},
    "technical_overlay": {"label": "技術對照", "family": "overlay"},
    "system_fallback": {"label": "系統保底", "family": "fallback"},
    "trace_pending": {"label": "情境待補", "family": "fallback"},
}

CATEGORY_TRACE_MAP: Dict[str, Dict[str, str]] = {
    "電子": {"keyword": "sector_electronics", "theme": "electronics_axis"},
    "半導體": {"keyword": "sector_semiconductor", "theme": "semiconductor_axis"},
    "金融": {"keyword": "sector_finance", "theme": "finance_axis"},
    "金融保險": {"keyword": "sector_finance", "theme": "finance_axis"},
    "銀行保險": {"keyword": "sector_finance", "theme": "finance_axis"},
    "鋼鐵": {"keyword": "sector_materials", "theme": "materials_axis"},
    "水泥": {"keyword": "sector_materials", "theme": "materials_axis"},
    "塑膠": {"keyword": "sector_materials", "theme": "materials_axis"},
    "化工": {"keyword": "sector_materials", "theme": "materials_axis"},
    "航運": {"keyword": "sector_transport", "theme": "transport_axis"},
}

EVENT_TRACE_MAP: Dict[str, Dict[str, Any]] = {
    "breadth_axis_overlap": {
        "keywords": ["{breadth_signal}", "front_concentration", "volume_overlap", "{primary_sector_keyword}"],
        "themes": ["market_breadth", "{primary_sector_theme}", "{secondary_sector_theme}"],
    },
    "sector_axis_convergence": {
        "keywords": ["sector_concentration", "volume_resonance", "{primary_sector_keyword}", "{secondary_sector_keyword}"],
        "themes": ["{primary_sector_theme}", "{secondary_sector_theme}", "rotation_concentration"],
    },
    "volume_focus_limited_diffusion": {
        "keywords": ["volume_cluster", "limited_diffusion", "{primary_sector_keyword}", "{secondary_sector_keyword}"],
        "themes": ["volume_focus", "{primary_sector_theme}", "{secondary_sector_theme}"],
    },
    "ai_technical_overlay": {
        "keywords": ["{ai_direction_keyword}", "{technical_direction_keyword}", "volume_validation", "{alignment_keyword}"],
        "themes": ["ai_overlay", "{alignment_theme}", "{primary_sector_theme}", "{secondary_sector_theme}"],
    },
    "context_unavailable": {
        "keywords": ["data_shortage", "ui_fallback"],
        "themes": ["system_fallback", "trace_pending"],
    },
}

THEME_STOCK_RULES: Dict[str, Dict[str, Any]] = {
    "market_breadth": {
        "selector": "none",
        "categories": [],
        "description": "盤面廣度屬於市場結構層，不直接映射股票。",
    },
    "electronics_axis": {
        "selector": "category",
        "categories": ["電子"],
        "description": "電子主軸固定映射到當日 universe 中 category=電子 的全量股票池。",
    },
    "semiconductor_axis": {
        "selector": "category",
        "categories": ["半導體"],
        "description": "半導體主軸固定映射到當日 universe 中 category=半導體 的全量股票池。",
    },
    "finance_axis": {
        "selector": "category",
        "categories": ["金融", "金融保險", "銀行保險"],
        "description": "金融主軸固定映射到當日 universe 中的金融類別股票池。",
    },
    "materials_axis": {
        "selector": "category",
        "categories": ["鋼鐵", "水泥", "塑膠", "化工"],
        "description": "原物料主軸固定映射到當日 universe 中的原物料相關類別股票池。",
    },
    "transport_axis": {
        "selector": "category",
        "categories": ["航運"],
        "description": "航運主軸固定映射到當日 universe 中 category=航運 的全量股票池。",
    },
    "other_axis": {
        "selector": "category",
        "categories": ["其他"],
        "description": "其他族群主軸固定映射到當日 universe 中未歸類為既有主題的股票池。",
    },
    "rotation_concentration": {
        "selector": "none",
        "categories": [],
        "description": "集中輪動屬於市場結構層，不直接映射股票。",
    },
    "volume_focus": {
        "selector": "none",
        "categories": [],
        "description": "量能聚焦屬於量能結構層，不直接映射股票。",
    },
    "ai_overlay": {
        "selector": "none",
        "categories": [],
        "description": "AI摘要對照屬於覆蓋層，不直接映射股票。",
    },
    "trace_convergence": {
        "selector": "none",
        "categories": [],
        "description": "情境收斂屬於覆蓋層，不直接映射股票。",
    },
    "trace_divergence": {
        "selector": "none",
        "categories": [],
        "description": "情境分歧屬於覆蓋層，不直接映射股票。",
    },
    "technical_overlay": {
        "selector": "none",
        "categories": [],
        "description": "技術對照屬於覆蓋層，不直接映射股票。",
    },
    "system_fallback": {
        "selector": "none",
        "categories": [],
        "description": "系統保底不直接映射股票。",
    },
    "trace_pending": {
        "selector": "none",
        "categories": [],
        "description": "情境待補不直接映射股票。",
    },
}


def keyword_label(keyword_id: str) -> str:
    return KEYWORD_DICTIONARY[keyword_id]["label"]


def theme_label(theme_id: str) -> str:
    return THEME_TAXONOMY[theme_id]["label"]


def trace_keyword_labels(keyword_ids: list[str]) -> list[str]:
    return [keyword_label(keyword_id) for keyword_id in keyword_ids]


def trace_theme_labels(theme_ids: list[str]) -> list[str]:
    return [theme_label(theme_id) for theme_id in theme_ids]


def sector_trace_keys(category: str) -> Dict[str, str]:
    return CATEGORY_TRACE_MAP.get(category, {"keyword": "sector_other", "theme": "other_axis"})


def build_trace(event_id: str, bindings: Dict[str, str]) -> Dict[str, Any]:
    if event_id not in EVENT_TRACE_MAP:
        raise KeyError(f"未知 event trace: {event_id}")

    template = EVENT_TRACE_MAP[event_id]

    def expand(items: list[str]) -> list[str]:
        resolved: list[str] = []
        for item in items:
            if item.startswith("{") and item.endswith("}"):
                key = item[1:-1]
                item = bindings[key]
            if item not in resolved:
                resolved.append(item)
        return resolved

    return {
        "event": event_id,
        "keywords": expand(template["keywords"]),
        "themes": expand(template["themes"]),
    }


def trace_catalog() -> Dict[str, Any]:
    return {
        "keyword_dictionary_version": KEYWORD_DICTIONARY_VERSION,
        "theme_taxonomy_version": THEME_TAXONOMY_VERSION,
        "event_trace_version": EVENT_TRACE_VERSION,
        "keyword_dictionary": {key: value["label"] for key, value in KEYWORD_DICTIONARY.items()},
        "theme_taxonomy": {
            key: {"label": value["label"], "family": value["family"]}
            for key, value in THEME_TAXONOMY.items()
        },
        "event_trace_map": EVENT_TRACE_MAP,
    }


def stock_mapping_catalog_template() -> Dict[str, Any]:
    return {
        "theme_stock_mapping_version": THEME_STOCK_MAPPING_VERSION,
        "theme_stock_rules": THEME_STOCK_RULES,
    }


def resolve_theme_stock_mapping(universe_stocks: list[dict[str, Any]]) -> Dict[str, Any]:
    themes_to_stocks: Dict[str, list[str]] = {}
    for theme_id, rule in THEME_STOCK_RULES.items():
        if rule["selector"] != "category":
            themes_to_stocks[theme_id] = []
            continue

        allowed_categories = set(rule["categories"])
        symbols: list[str] = []
        seen: set[str] = set()
        for stock in universe_stocks:
            category = str(stock.get("category") or "其他").strip() or "其他"
            symbol = str(stock.get("symbol") or "").strip()
            if not symbol or category not in allowed_categories or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        themes_to_stocks[theme_id] = symbols

    return {
        **stock_mapping_catalog_template(),
        "themes_to_stocks": themes_to_stocks,
    }