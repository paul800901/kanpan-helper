import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main


class TestAiFailureFallback(unittest.TestCase):
    def test_run_pipeline_continues_when_ai_generation_fails(self):
        full_report = {
            "date": "2026-07-13",
            "total_stocks_requested": 3,
            "total_stocks_analyzed": 3,
            "top_n": 3,
            "report_version": "v2",
            "summary": {"market_overview": "測試市場"},
            "stocks": [],
        }
        universe_report = {"total_stocks": 3}

        with patch("main.fetch_data_with_stats", return_value=({"2330": {}}, 3, 1)):
            with patch("main.calculate_all_indicators", return_value={}):
                with patch("main.rank_stocks", return_value=[]):
                    with patch("main.generate_report_v2", return_value=full_report):
                        with patch("main.generate_universe_report", return_value=universe_report):
                            with patch("main.generate_lite_report", return_value={}):
                                with patch("main.validate_report_consistency"):
                                    with patch("main.save_report", side_effect=["full.json", "lite.json"]):
                                        with patch("main.save_universe_report", return_value="universe.json"):
                                            with patch(
                                                "main.generate_ai_report_if_enabled",
                                                side_effect=RuntimeError("AI 摘要重複"),
                                            ):
                                                with patch(
                                                    "main.backfill_priority_validation_reports",
                                                    return_value={},
                                                ):
                                                    with patch("main.atomic_update_index"):
                                                        output = io.StringIO()
                                                        with redirect_stdout(output):
                                                            result = main.run_pipeline(
                                                                use_cache=False,
                                                                symbols=[],
                                                            )

        self.assertIsNone(result[2])
        self.assertIn("將繼續發布基礎報告", output.getvalue())


if __name__ == "__main__":
    unittest.main()
