import unittest

from backend.ai_analyzer import AIAnalyzer, AIAnalyzerError


class TestAiDuplicateThreshold(unittest.TestCase):
    def setUp(self):
        # _check_duplicates does not use the API client; skip credential setup.
        self.analyzer = object.__new__(AIAnalyzer)

    @staticmethod
    def _stocks(why_texts, risk_texts=None):
        if risk_texts is None:
            risk_texts = [""] * len(why_texts)
        return [
            {"why_selected_ai": why, "risk_ai": risk}
            for why, risk in zip(why_texts, risk_texts)
        ]

    def test_historical_shared_market_phrases_are_allowed(self):
        why_texts = [
            "量比1.22微增，KD多頭延續，法人連2買",
            "爆量2.26倍，法人連2買，KD多頭延續",
            "KD高檔鈍化，法人連2買，量比1.32微增",
            "量比1.03正常，KD多頭延續，法人連2買",
            "量比0.81偏低，KD多頭延續，法人連2買",
        ]

        self.analyzer._check_duplicates(self._stocks(why_texts))

    def test_exactly_point_seven_five_similarity_is_allowed(self):
        why_texts = ["甲乙丙", "甲乙丙丁", "甲乙丙戊"]

        self.analyzer._check_duplicates(self._stocks(why_texts))

    def test_copy_pasted_why_selected_is_rejected(self):
        why_texts = ["KD多頭延續法人連買"] * 3

        with self.assertRaisesRegex(AIAnalyzerError, "why_selected_ai 重複過多"):
            self.analyzer._check_duplicates(self._stocks(why_texts))

    def test_copy_pasted_risk_is_rejected(self):
        why_texts = ["甲技術面", "乙法人面", "丙量價面"]
        risk_texts = ["爆量不續攻容易回檔"] * 3

        with self.assertRaisesRegex(AIAnalyzerError, "risk_ai 重複過多"):
            self.analyzer._check_duplicates(self._stocks(why_texts, risk_texts))


if __name__ == "__main__":
    unittest.main()
