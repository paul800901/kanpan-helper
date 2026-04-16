"""golden regression for third-page scenario_cards_v9 output
protects scenario card ordering / priority / contract fields from unintended drift
"""

from __future__ import annotations

from datetime import datetime
import unittest

from backend.context_cards import generate_context_report


def make_universe_stock(
    symbol: str,
    name: str,
    category: str,
    rank: int,
    score: int,
    volume_ratio: float,
) -> dict:
    return {
        "symbol": symbol,
        "name": name,
        "category": category,
        "rank": rank,
        "score": score,
        "volume_ratio": volume_ratio,
        "indicators": {
            "volume_ratio": volume_ratio,
        },
    }


def make_full_report(date_str: str) -> dict:
    return {
        "report_version": "v1-full",
        "date": date_str,
        "generated_at": f"{date_str}T08:00:00+08:00",
        "summary": {
            "market_overview": "市場強度約 78分，強勢股 6檔，結構維持偏多。",
            "top_picks": ["alpha", "beta", "gamma"],
            "watchlist": ["delta", "epsilon"],
        },
    }


def make_universe_report(date_str: str) -> dict:
    return {
        "report_version": "v1-universe",
        "date": date_str,
        "generated_at": f"{date_str}T08:05:00+08:00",
        "stocks": [
            make_universe_stock("T01", "Alpha Semi", "半導體", 1, 86, 1.80),
            make_universe_stock("T02", "Beta Semi", "半導體", 2, 82, 1.70),
            make_universe_stock("T03", "Gamma Semi", "半導體", 3, 79, 1.60),
            make_universe_stock("T04", "Delta Electronic", "電子", 4, 74, 1.55),
            make_universe_stock("T05", "Epsilon Electronic", "電子", 5, 68, 1.20),
            make_universe_stock("T06", "Zeta Shipping", "航運", 6, 43, 0.90),
        ],
    }


def make_ai_report(date_str: str) -> dict:
    return {
        "generated_at": f"{date_str}T08:10:00+08:00",
        "market_overview_ai": "市場氛圍偏多，結構與情緒大致同向。",
    }


def make_activation_report(date_str: str) -> dict:
    return {
        "as_of_date": date_str,
        "generated_at": f"{date_str}T08:15:00+08:00",
        "current_market_snapshot": {
            "market_trend": {"market_trend": "上升"},
            "capital_concentration": {"label": "集中"},
            "volume": {"label": "放量"},
        },
        "decision": {
            "action": "降權",
            "pass_count": 2,
            "total_condition_count": 3,
            "failed_conditions": ["資金集中度"],
        },
    }


class TestScenarioCardsContractGolden(unittest.TestCase):
    def test_scenario_cards_v9_core_output_matches_golden(self) -> None:
        date_str = "2026-04-10"
        report = generate_context_report(
            make_full_report(date_str),
            universe_report=make_universe_report(date_str),
            ai_report=make_ai_report(date_str),
            activation_report=make_activation_report(date_str),
        )

        self.assertEqual(report["scenario_cards_v9_schema_version"], "scenario-cards-v9")

        cards = report["scenario_cards_v9"]
        self.assertEqual(len(cards), 5)
        self.assertEqual(
            [card["id"] for card in cards],
            [
                "ai-overlay",
                "regime-activation",
                "sector-concentration",
                "volume-focus",
                "breadth-balance",
            ],
        )
        self.assertEqual(
            [
                {
                    "id": card["id"],
                    "title": card["title"],
                    "confidence": card["confidence"],
                    "relation_to_technical": card["relation_to_technical"],
                    "source_types": card["source_types"],
                    "themes": card["themes"],
                    "priority_score": card["priority_score"],
                    "priority_rank": card["priority_rank"],
                    "priority_reasons": card["priority_reasons"],
                    "is_fallback": card["is_fallback"],
                }
                for card in cards
            ],
            [
                {
                    "id": "ai-overlay",
                    "title": "AI 摘要與技術面對照",
                    "confidence": "high",
                    "relation_to_technical": "aligned",
                    "source_types": [
                        "ai_market_overview",
                        "score_distribution",
                        "volume_anomaly",
                        "strategy_activation",
                    ],
                    "themes": ["情緒校準", "敘事驗證"],
                    "priority_score": 16,
                    "priority_rank": 1,
                    "priority_reasons": [
                        "訊號來源 4 類",
                        "confidence=high",
                        "技術面一致",
                        "有制度層支持",
                        "量能與廣度交叉驗證成立",
                        "reasoning_chain=strong",
                    ],
                    "is_fallback": False,
                },
                {
                    "id": "regime-activation",
                    "title": "steady_v5 啟用環境",
                    "confidence": "medium",
                    "relation_to_technical": "aligned",
                    "source_types": [
                        "strategy_activation",
                        "score_distribution",
                        "sector_concentration",
                        "volume_anomaly",
                    ],
                    "themes": ["制度環境", "策略適配"],
                    "priority_score": 15,
                    "priority_rank": 2,
                    "priority_reasons": [
                        "訊號來源 4 類",
                        "confidence=medium",
                        "技術面一致",
                        "有制度層支持",
                        "量能與廣度交叉驗證成立",
                        "reasoning_chain=strong",
                    ],
                    "is_fallback": False,
                },
                {
                    "id": "sector-concentration",
                    "title": "主軸集中度",
                    "confidence": "high",
                    "relation_to_technical": "aligned",
                    "source_types": [
                        "sector_concentration",
                        "volume_anomaly",
                        "strategy_activation",
                    ],
                    "themes": ["資金輪動", "主流收斂"],
                    "priority_score": 15,
                    "priority_rank": 3,
                    "priority_reasons": [
                        "訊號來源 3 類",
                        "confidence=high",
                        "技術面一致",
                        "有制度層支持",
                        "量能與廣度交叉驗證成立",
                        "reasoning_chain=strong",
                    ],
                    "is_fallback": False,
                },
                {
                    "id": "volume-focus",
                    "title": "量能異常與擴散",
                    "confidence": "high",
                    "relation_to_technical": "aligned",
                    "source_types": [
                        "volume_anomaly",
                        "score_distribution",
                        "strategy_activation",
                    ],
                    "themes": ["量能擴張", "結構分化"],
                    "priority_score": 15,
                    "priority_rank": 4,
                    "priority_reasons": [
                        "訊號來源 3 類",
                        "confidence=high",
                        "技術面一致",
                        "有制度層支持",
                        "量能與廣度交叉驗證成立",
                        "reasoning_chain=strong",
                    ],
                    "is_fallback": False,
                },
                {
                    "id": "breadth-balance",
                    "title": "盤面廣度與強弱分布",
                    "confidence": "medium",
                    "relation_to_technical": "aligned",
                    "source_types": [
                        "market_overview",
                        "score_distribution",
                        "ai_market_overview",
                    ],
                    "themes": ["市場廣度", "情緒校準"],
                    "priority_score": 11,
                    "priority_rank": 5,
                    "priority_reasons": [
                        "訊號來源 3 類",
                        "confidence=medium",
                        "技術面一致",
                        "無制度層支持",
                        "量能或廣度部分驗證",
                        "reasoning_chain=strong",
                    ],
                    "is_fallback": False,
                },
            ],
        )

        for card in cards:
            generated_at = datetime.fromisoformat(card["generated_at"])
            self.assertIsNotNone(generated_at.tzinfo)


if __name__ == "__main__":
    unittest.main()