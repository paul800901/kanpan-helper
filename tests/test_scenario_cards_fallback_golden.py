"""golden regression for third-page fallback scenario output
protects fallback card contract fields and fallback ordering from unintended drift
"""

from __future__ import annotations

from datetime import datetime
import unittest

from backend.context_cards import generate_context_report


def make_fallback_full_report(date_str: str) -> dict:
    return {
        "report_version": "v1-full",
        "date": date_str,
        "generated_at": f"{date_str}T08:00:00+08:00",
        "summary": {
            "market_overview": "資料不足，僅保留第三頁 fallback 路徑檢查。",
            "top_picks": [],
            "watchlist": [],
        },
    }


class TestScenarioCardsFallbackGolden(unittest.TestCase):
    def test_scenario_cards_v9_fallback_output_matches_golden(self) -> None:
        date_str = "2026-04-10"

        # This fixture intentionally omits both full_report["stocks"] and universe_report.
        # That forces _build_v9_snapshot(...) to return None, so fallback cards are expected.
        # The fallback path here is the success condition of the test, not a test failure.
        report = generate_context_report(make_fallback_full_report(date_str))

        self.assertEqual(report["scenario_cards_v9_schema_version"], "scenario-cards-v9")

        cards = report["scenario_cards_v9"]
        self.assertEqual(len(cards), 3)
        self.assertEqual([card["id"] for card in cards], ["fallback-1", "fallback-2", "fallback-3"])
        self.assertTrue(all(card["is_fallback"] for card in cards))

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
                    "id": "fallback-1",
                    "title": "保底情境卡 1",
                    "confidence": "low",
                    "relation_to_technical": "neutral",
                    "source_types": ["system_fallback"],
                    "themes": ["制度環境"],
                    "priority_score": -996,
                    "priority_rank": 1,
                    "priority_reasons": [
                        "訊號來源 1 類",
                        "confidence=low",
                        "技術面中性",
                        "無制度層支持",
                        "缺少量能與廣度交叉驗證",
                        "reasoning_chain=weak",
                        "fallback 卡固定排後",
                    ],
                    "is_fallback": True,
                },
                {
                    "id": "fallback-2",
                    "title": "保底情境卡 2",
                    "confidence": "low",
                    "relation_to_technical": "neutral",
                    "source_types": ["system_fallback"],
                    "themes": ["制度環境"],
                    "priority_score": -996,
                    "priority_rank": 2,
                    "priority_reasons": [
                        "訊號來源 1 類",
                        "confidence=low",
                        "技術面中性",
                        "無制度層支持",
                        "缺少量能與廣度交叉驗證",
                        "reasoning_chain=weak",
                        "fallback 卡固定排後",
                    ],
                    "is_fallback": True,
                },
                {
                    "id": "fallback-3",
                    "title": "保底情境卡 3",
                    "confidence": "low",
                    "relation_to_technical": "neutral",
                    "source_types": ["system_fallback"],
                    "themes": ["制度環境"],
                    "priority_score": -996,
                    "priority_rank": 3,
                    "priority_reasons": [
                        "訊號來源 1 類",
                        "confidence=low",
                        "技術面中性",
                        "無制度層支持",
                        "缺少量能與廣度交叉驗證",
                        "reasoning_chain=weak",
                        "fallback 卡固定排後",
                    ],
                    "is_fallback": True,
                },
            ],
        )

        self.assertIn("缺少 full/universe 報表", cards[0]["summary"])
        self.assertIn("缺少類別集中度資料", cards[1]["summary"])
        self.assertIn("缺少量能資料", cards[2]["summary"])

        for card in cards:
            generated_at = datetime.fromisoformat(card["generated_at"])
            self.assertIsNotNone(generated_at.tzinfo)


if __name__ == "__main__":
    unittest.main()