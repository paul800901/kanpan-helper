#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
看板助手修正驗證測試

執行方式:
    python tests/test_fixes.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import backend.priority_validation as priority_validation_module
from backend.config import get_today_str, get_taiwan_now, TAIWAN_TZ
from backend.calc_indicators import StockIndicators, calculate_indicators
from backend.ranking import score_stock, evaluate_institutional, StockScore
from backend.generate_report import generate_report_v2, generate_lite_report, generate_universe_report, validate_report_consistency
from backend.priority_validation import generate_priority_snapshot, generate_priority_history_report, generate_factor_analysis_report, generate_factor_combination_analysis_report, generate_strategy_analysis_report, generate_signal_density_report, generate_steady_v2_blockers_report, generate_timing_alignment_report, generate_steady_v2_signature_report, generate_steady_v4_tracking_report, generate_steady_v4_alpha_breakdown_report, generate_steady_v5_long_term_validation_report, generate_steady_v5_regime_analysis_report, backfill_priority_validation_reports


class TestTaiwanTimezone(unittest.TestCase):
    """測試台灣時區功能"""
    
    def test_taiwan_tz_is_asia_taipei(self):
        """確認時區設定為 Asia/Taipei"""
        self.assertEqual(str(TAIWAN_TZ), "Asia/Taipei")
    
    def test_get_taiwan_now_returns_tz_aware(self):
        """確認 get_taiwan_now 回傳有時區資訊的時間"""
        now = get_taiwan_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(str(now.tzinfo), "Asia/Taipei")
    
    def test_get_today_str_format(self):
        """確認日期格式為 YYYY-MM-DD"""
        today = get_today_str()
        self.assertEqual(len(today), 10)
        self.assertEqual(today[4], '-')
        self.assertEqual(today[7], '-')
        # 驗證可以解析
        dt = datetime.strptime(today, "%Y-%m-%d")
        self.assertIsNotNone(dt)


class TestInstitutionalAggregation(unittest.TestCase):
    """測試法人資料聚合邏輯"""
    
    def test_same_date_aggregation(self):
        """測試同一天多筆法人資料正確聚合"""
        test_data = {
            "symbol": "2330",
            "candles": [
                {"date": "2024-01-05", "close": "500", "max": "510", "min": "490", "Trading_Volume": "10000"},
            ] * 20,
            "institutional": [
                # 同一天，不同法人類別
                {"date": "2024-01-05", "buy": "1000", "sell": "500"},   # 淨買 500
                {"date": "2024-01-05", "buy": "800", "sell": "200"},    # 淨買 600，當日總計 1100
                {"date": "2024-01-04", "buy": "500", "sell": "300"},   # 淨買 200
                {"date": "2024-01-03", "buy": "600", "sell": "100"},   # 淨買 500
            ]
        }
        
        ind = calculate_indicators(test_data)
        self.assertIsNotNone(ind)
        
        # 驗證連續買超天數（2024-01-05 淨買 1100，01-04 淨買 200，01-03 淨買 500）
        self.assertEqual(ind.institutional_consecutive_days, 3)
        self.assertEqual(ind.institutional_signal, "連3買")
        self.assertEqual(ind.institutional_latest_net, 1100)
        self.assertEqual(ind.institutional_total_net, 500 + 600 + 200 + 500)  # 1800
    
    def test_consecutive_sell_detection(self):
        """測試連續賣超偵測"""
        test_data = {
            "symbol": "2454",
            "candles": [{"date": "2024-01-05", "close": "500", "max": "510", "min": "490", "Trading_Volume": "10000"}] * 20,
            "institutional": [
                {"date": "2024-01-05", "buy": "100", "sell": "1000"},  # 淨賣 -900
                {"date": "2024-01-04", "buy": "200", "sell": "800"},   # 淨賣 -600
                {"date": "2024-01-03", "buy": "300", "sell": "700"},   # 淨賣 -400
            ]
        }
        
        ind = calculate_indicators(test_data)
        self.assertIsNotNone(ind)
        
        # 連續賣超天數應為負數
        self.assertEqual(ind.institutional_consecutive_days, -3)
        self.assertEqual(ind.institutional_signal, "連3賣")
        self.assertEqual(ind.institutional_latest_net, -900)
        self.assertLess(ind.institutional_total_net, 0)
    
    def test_single_day_large_buy(self):
        """測試單日大買判斷"""
        test_data = {
            "symbol": "2317",
            "candles": [{"date": "2024-01-05", "close": "500", "max": "510", "min": "490", "Trading_Volume": "10000"}] * 20,
            "institutional": [
                {"date": "2024-01-05", "buy": "5000", "sell": "1000"},  # 淨買 4000（大買）
                {"date": "2024-01-04", "buy": "200", "sell": "500"},   # 淨賣 -300（前一日賣超，中斷連買）
            ]
        }
        
        ind = calculate_indicators(test_data)
        self.assertIsNotNone(ind)
        
        # 只有一天買超，但金額超過 1000，應為「單日大買」
        self.assertEqual(ind.institutional_consecutive_days, 1)
        self.assertEqual(ind.institutional_signal, "單日大買")
    
    def test_empty_institutional_data(self):
        """測試法人資料不足情況"""
        test_data = {
            "symbol": "1234",
            "candles": [{"date": "2024-01-05", "close": "500", "max": "510", "min": "490", "Trading_Volume": "10000"}] * 20,
            "institutional": []
        }
        
        ind = calculate_indicators(test_data)
        self.assertIsNotNone(ind)
        
        self.assertEqual(ind.institutional_signal, "資料不足")
        self.assertIn("法人資料不足", ind.data_issues)


class TestVolumeRatio(unittest.TestCase):
    """測試量比計算"""
    
    def test_volume_ratio_calculation(self):
        """測試量比正確計算"""
        # 建立 20 天資料，每天成交量 10000
        candles = []
        for i in range(20):
            candles.append({
                "date": f"2024-01-{i+1:02d}",
                "close": "500",
                "max": "510",
                "min": "490",
                "Trading_Volume": "10000"
            })
        
        # 最後一天成交量 15000（量比應為 1.5）
        candles[-1]["Trading_Volume"] = "15000"
        
        test_data = {
            "symbol": "TEST",
            "candles": candles,
            "institutional": []
        }
        
        ind = calculate_indicators(test_data)
        self.assertIsNotNone(ind)
        self.assertAlmostEqual(ind.volume_ratio, 1.5, places=1)
    
    def test_volume_ratio_in_score(self):
        """測試量比傳遞到評分結果"""
        ind = StockIndicators(
            symbol="TEST",
            close_prices=[500] * 20,
            high_prices=[510] * 20,
            low_prices=[490] * 20,
            volumes=[10000] * 19 + [15000],  # 量比 1.5
            dates=[]
        )
        
        score = score_stock(ind)
        self.assertAlmostEqual(score.volume_ratio, 1.5, places=1)


class TestInstitutionalScoring(unittest.TestCase):
    """測試法人評分邏輯"""
    
    def test_consecutive_buy_scoring(self):
        """測試連買分數"""
        ind = StockIndicators(
            symbol="TEST",
            close_prices=[500] * 20,
            high_prices=[510] * 20,
            low_prices=[490] * 20,
            volumes=[10000] * 20,
            dates=[]
        )
        
        test_cases = [
            (5, "連5買", 25),
            (4, "連4買", 23),
            (3, "連3買", 20),
            (2, "連2買", 15),
            (1, "連1買", 12),
        ]
        
        for days, expected_signal, expected_score in test_cases:
            ind.institutional_signal = expected_signal
            ind.institutional_consecutive_days = days
            
            signal, score = evaluate_institutional(ind)
            self.assertEqual(signal, expected_signal)
            self.assertEqual(score, expected_score)

    def test_consecutive_sell_scoring(self):
        """測試連賣分數"""
        ind = StockIndicators(
            symbol="TEST",
            close_prices=[500] * 20,
            high_prices=[510] * 20,
            low_prices=[490] * 20,
            volumes=[10000] * 20,
            dates=[]
        )
        
        test_cases = [
            (-5, "連5賣", 5),
            (-4, "連4賣", 6),
            (-3, "連3賣", 7),
            (-2, "連2賣", 8),
            (-1, "連1賣", 10),
        ]
        
        for days, expected_signal, expected_score in test_cases:
            ind.institutional_signal = expected_signal
            ind.institutional_consecutive_days = days
            
            signal, score = evaluate_institutional(ind)
            self.assertEqual(signal, expected_signal)
            self.assertEqual(score, expected_score)


class TestReportConsistency(unittest.TestCase):
    """測試 lite / universe 同源與一致性檢查"""

    def make_score(self, symbol: str, score: int, rank: int) -> StockScore:
        return StockScore(
            symbol=symbol,
            score=score,
            trend="偏多",
            volume="放量",
            institutional="連2買",
            kd_state="多頭延續",
            trend_score=30,
            volume_score=25,
            institutional_score=15,
            kd_score=18,
            latest_close=100.0 + rank,
            ma5=95.0 + rank,
            ma20=90.0 + rank,
            k_value=70.0 + rank,
            d_value=60.0 + rank,
            volume_ratio=1.5,
            institutional_consecutive_days=2,
            institutional_total_net=5000,
            has_sufficient_data=True,
            data_issues=[],
            rank=rank,
            rank_percentile=100.0 - rank,
            total_stocks=3
        )

    def test_lite_report_uses_universe_shared_fields(self):
        all_scores = [
            self.make_score("2330", 88, 1),
            self.make_score("2317", 80, 2),
            self.make_score("2454", 70, 3),
        ]

        top_scores = all_scores[:2]
        full_report = generate_report_v2(
            top_scores,
            date_str="2026-04-12",
            total_stocks_requested=3,
            total_stocks_analyzed=3,
            bundle_id="bundle-test"
        )
        universe_report = generate_universe_report(all_scores, date_str="2026-04-12", bundle_id="bundle-test")
        lite_report = generate_lite_report(full_report, universe_report)

        self.assertEqual(lite_report["metadata"]["bundle_id"], "bundle-test")
        self.assertEqual(lite_report["stocks"][0]["symbol"], universe_report["stocks"][0]["symbol"])
        self.assertEqual(lite_report["stocks"][0]["score"], universe_report["stocks"][0]["score"])
        self.assertEqual(lite_report["stocks"][0]["indicators"]["close"], universe_report["stocks"][0]["indicators"]["close"])
        self.assertEqual(lite_report["stocks"][0]["signals"]["trend"], universe_report["stocks"][0]["trend"])

        validate_report_consistency(full_report, lite_report, universe_report)

    def test_validate_report_consistency_rejects_mismatch(self):
        all_scores = [
            self.make_score("2330", 88, 1),
            self.make_score("2317", 80, 2),
        ]

        full_report = generate_report_v2(
            all_scores,
            date_str="2026-04-12",
            total_stocks_requested=2,
            total_stocks_analyzed=2,
            bundle_id="bundle-test"
        )
        universe_report = generate_universe_report(all_scores, date_str="2026-04-12", bundle_id="bundle-test")
        lite_report = generate_lite_report(full_report, universe_report)
        lite_report["stocks"][0]["indicators"]["close"] = 999.0

        with self.assertRaises(ValueError):
            validate_report_consistency(full_report, lite_report, universe_report)

    def test_validate_report_consistency_rejects_bundle_mismatch(self):
        all_scores = [
            self.make_score("2330", 88, 1),
            self.make_score("2317", 80, 2),
        ]

        full_report = generate_report_v2(
            all_scores,
            date_str="2026-04-12",
            total_stocks_requested=2,
            total_stocks_analyzed=2,
            bundle_id="bundle-a"
        )
        universe_report = generate_universe_report(all_scores, date_str="2026-04-12", bundle_id="bundle-b")
        lite_report = generate_lite_report(full_report, universe_report)
        lite_report["metadata"]["bundle_id"] = "bundle-c"

        with self.assertRaises(ValueError):
            validate_report_consistency(full_report, lite_report, universe_report)


class TestPriorityValidation(unittest.TestCase):
    """測試 v11 排序驗證層。"""

    def make_universe_stock(
        self,
        symbol: str,
        name: str,
        score: int,
        close: float,
        ma5: float,
        ma20: float,
        k_value: float,
        volume_ratio: float,
        institutional: str,
        rank: int,
        category: str = "電子",
    ) -> dict:
        return {
            "symbol": symbol,
            "name": name,
            "category": category,
            "rank": rank,
            "score": score,
            "action_bias": "可留意",
            "institutional": institutional,
            "volume_ratio": volume_ratio,
            "indicators": {
                "close": close,
                "ma5": ma5,
                "ma20": ma20,
                "k": k_value,
                "volume_ratio": volume_ratio,
            },
        }

    def make_context_report(self, date_str: str) -> dict:
        return {
            "report_version": "v9-context",
            "date": date_str,
            "trace_catalog": {
                "theme_taxonomy": {
                    "theme_a": {"label": "主題 A"},
                    "theme_b": {"label": "主題 B"},
                    "theme_c": {"label": "主題 C"},
                }
            },
            "cards": [
                {
                    "title": "卡片一",
                    "trace": {"event": "event_1"},
                    "candidate_stocks": [
                        {"symbol": "BBB", "from_theme": "theme_a", "trace_event": "event_1", "reason": "第一張卡出現"},
                        {"symbol": "CCC", "from_theme": "theme_a", "trace_event": "event_1", "reason": "第一張卡出現"},
                        {"symbol": "AAA", "from_theme": "theme_a", "trace_event": "event_1", "reason": "第一張卡出現"},
                        {"symbol": "DDD", "from_theme": "theme_a", "trace_event": "event_1", "reason": "第一張卡出現"},
                    ],
                },
                {
                    "title": "卡片二",
                    "trace": {"event": "event_2"},
                    "candidate_stocks": [
                        {"symbol": "BBB", "from_theme": "theme_b", "trace_event": "event_2", "reason": "第二張卡再出現"},
                        {"symbol": "CCC", "from_theme": "theme_b", "trace_event": "event_2", "reason": "第二張卡再出現"},
                    ],
                },
            ],
        }

    def make_universe_report(self, date_str: str) -> dict:
        return {
            "report_version": "v1-universe",
            "date": date_str,
            "stocks": [
                self.make_universe_stock("BBB", "Beta", 85, 100.0, 100.5, 95.0, 70.0, 1.2, "連2買", 1),
                self.make_universe_stock("CCC", "Gamma", 85, 110.0, 100.0, 95.0, 70.0, 1.2, "連2買", 2),
                self.make_universe_stock("DDD", "Delta", 65, 99.0, 100.0, 100.0, 25.0, 0.8, "資料不足", 3),
                self.make_universe_stock("AAA", "Alpha", 45, 90.0, 95.0, 100.0, 20.0, 0.9, "連1賣", 4),
            ],
        }

    def make_next_universe_report(self, date_str: str) -> dict:
        return {
            "report_version": "v1-universe",
            "date": date_str,
            "stocks": [
                self.make_universe_stock("BBB", "Beta", 86, 103.0, 101.0, 96.0, 72.0, 1.1, "連3買", 1),
                self.make_universe_stock("CCC", "Gamma", 84, 109.0, 101.0, 96.0, 68.0, 1.1, "連2買", 2),
                self.make_universe_stock("DDD", "Delta", 68, 104.94, 100.5, 100.5, 28.0, 1.0, "資料不足", 3),
                self.make_universe_stock("AAA", "Alpha", 42, 85.0, 94.0, 99.0, 18.0, 0.8, "連2賣", 4),
            ],
        }

    def make_combo_previous_universe_report(self, date_str: str) -> dict:
        return {
            "report_version": "v1-universe",
            "date": date_str,
            "stocks": [
                self.make_universe_stock("BBB", "Beta", 80, 102.0, 101.0, 100.0, 12.0, 0.9, "連2買", 1),
                self.make_universe_stock("CCC", "Gamma", 75, 104.0, 103.0, 100.0, 40.0, 1.1, "連1買", 2),
                self.make_universe_stock("DDD", "Delta", 70, 99.0, 99.5, 100.0, 18.0, 0.9, "資料不足", 3),
                self.make_universe_stock("AAA", "Alpha", 68, 100.5, 100.2, 100.0, 35.0, 1.0, "資料不足", 4),
            ],
        }

    def make_combo_current_universe_report(self, date_str: str) -> dict:
        return {
            "report_version": "v1-universe",
            "date": date_str,
            "stocks": [
                self.make_universe_stock("BBB", "Beta", 78, 95.0, 97.0, 100.0, 31.0, 0.8, "連1買", 1),
                self.make_universe_stock("CCC", "Gamma", 74, 99.6, 101.0, 100.0, 34.0, 1.0, "連1買", 2),
                self.make_universe_stock("DDD", "Delta", 69, 97.0, 98.5, 100.0, 22.0, 0.9, "資料不足", 3),
                self.make_universe_stock("AAA", "Alpha", 67, 100.2, 100.0, 100.0, 38.0, 1.0, "資料不足", 4),
            ],
        }

    def make_combo_next_universe_report(self, date_str: str) -> dict:
        return {
            "report_version": "v1-universe",
            "date": date_str,
            "stocks": [
                self.make_universe_stock("BBB", "Beta", 82, 100.0, 98.0, 99.5, 35.0, 1.1, "連2買", 1),
                self.make_universe_stock("CCC", "Gamma", 73, 99.8, 101.0, 100.0, 36.0, 1.0, "連1買", 2),
                self.make_universe_stock("DDD", "Delta", 68, 98.0, 98.0, 99.5, 25.0, 1.0, "資料不足", 3),
                self.make_universe_stock("AAA", "Alpha", 66, 100.0, 100.0, 100.0, 37.0, 1.0, "資料不足", 4),
            ],
        }

    def make_timing_followup_universe_report(self, date_str: str) -> dict:
        return {
            "report_version": "v1-universe",
            "date": date_str,
            "stocks": [
                self.make_universe_stock("BBB", "Beta", 83, 101.0, 98.5, 99.0, 33.0, 1.0, "連2買", 1),
                self.make_universe_stock("CCC", "Gamma", 74, 100.0, 100.8, 100.0, 32.0, 1.0, "連1買", 2),
                self.make_universe_stock("DDD", "Delta", 72, 101.0, 99.0, 100.0, 24.0, 1.0, "資料不足", 3),
                self.make_universe_stock("AAA", "Alpha", 65, 100.1, 100.0, 100.0, 36.0, 1.0, "資料不足", 4),
            ],
        }

    def make_regime_universe_report(self, date_str: str, categories: list[str], volume_ratio: float) -> dict:
        stocks = []
        for index, category in enumerate(categories):
            stocks.append(
                self.make_universe_stock(
                    f"R{index:02d}",
                    f"Regime {index}",
                    max(60, 90 - index),
                    100.0 + index,
                    99.0 + index,
                    98.0 + index,
                    60.0,
                    volume_ratio,
                    "連1買",
                    index + 1,
                    category=category,
                )
            )
        return {
            "report_version": "v1-universe",
            "date": date_str,
            "stocks": stocks,
        }

    def test_priority_snapshot_mirrors_frontend_sorting(self):
        context_report = self.make_context_report("2026-04-10")
        universe_report = self.make_universe_report("2026-04-10")
        next_universe_report = self.make_next_universe_report("2026-04-11")

        report = generate_priority_snapshot(
            context_report,
            universe_report,
            next_universe_report=next_universe_report,
            next_date="2026-04-11",
        )

        ordered_symbols = [candidate["symbol"] for candidate in report["candidates"]]
        self.assertEqual(ordered_symbols, ["BBB", "CCC", "DDD", "AAA"])
        self.assertEqual(report["candidates"][0]["technical_state"]["advice"], "強勢續看")
        self.assertTrue(report["candidates"][0]["technical_state"]["in_pilot_zone"])
        self.assertAlmostEqual(report["evaluation"]["top3_avg_return_pct"], 2.697, places=3)
        self.assertAlmostEqual(report["evaluation"]["all_avg_return_pct"], 0.6338, places=4)

    def test_backfill_generates_priority_history(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reports_dir = root / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)

            date_a = "2026-04-10"
            date_b = "2026-04-11"

            (reports_dir / f"{date_a}.json").write_text(json.dumps({"date": date_a}, ensure_ascii=False), encoding="utf-8")
            (reports_dir / f"{date_b}.json").write_text(json.dumps({"date": date_b}, ensure_ascii=False), encoding="utf-8")
            (reports_dir / f"{date_a}-context.json").write_text(json.dumps(self.make_context_report(date_a), ensure_ascii=False), encoding="utf-8")
            (reports_dir / f"{date_b}-context.json").write_text(json.dumps(self.make_context_report(date_b), ensure_ascii=False), encoding="utf-8")
            (reports_dir / f"{date_a}-universe.json").write_text(json.dumps(self.make_universe_report(date_a), ensure_ascii=False), encoding="utf-8")
            (reports_dir / f"{date_b}-universe.json").write_text(json.dumps(self.make_next_universe_report(date_b), ensure_ascii=False), encoding="utf-8")

            result = backfill_priority_validation_reports(
                base_dir=root,
                target_date=date_b,
                min_evaluated_days=1,
                auto_backfill_history=False,
                market_prices={
                    date_a: 100.0,
                    date_b: 101.0,
                },
            )

            self.assertTrue((reports_dir / f"{date_a}-priority.json").exists())
            self.assertTrue((reports_dir / f"{date_b}-priority.json").exists())
            self.assertTrue((reports_dir / "priority-history.json").exists())
            self.assertTrue((reports_dir / "factor_combination_analysis.json").exists())
            self.assertTrue((reports_dir / "strategy_analysis.json").exists())
            self.assertTrue((reports_dir / "signal_density.json").exists())
            self.assertTrue((reports_dir / "steady_v2_blockers.json").exists())
            self.assertTrue((reports_dir / "timing_alignment.json").exists())
            self.assertTrue((reports_dir / "steady_v2_signature.json").exists())
            self.assertTrue((reports_dir / "steady_v4_tracking.json").exists())
            self.assertTrue((reports_dir / "steady_v4_alpha_breakdown.json").exists())
            self.assertTrue((reports_dir / "steady_v5_long_term_validation.json").exists())
            self.assertTrue((reports_dir / "steady_v5_regime_analysis.json").exists())
            self.assertEqual(result["available_dates"], [date_a, date_b])
            self.assertTrue(result["strategy_analysis_path"].endswith("strategy_analysis.json"))
            self.assertTrue(result["signal_density_path"].endswith("signal_density.json"))
            self.assertTrue(result["steady_v2_blockers_path"].endswith("steady_v2_blockers.json"))
            self.assertTrue(result["timing_alignment_path"].endswith("timing_alignment.json"))
            self.assertTrue(result["steady_v2_signature_path"].endswith("steady_v2_signature.json"))
            self.assertTrue(result["steady_v4_tracking_path"].endswith("steady_v4_tracking.json"))
            self.assertTrue(result["steady_v4_alpha_breakdown_path"].endswith("steady_v4_alpha_breakdown.json"))
            self.assertTrue(result["steady_v5_long_term_validation_path"].endswith("steady_v5_long_term_validation.json"))
            self.assertTrue(result["steady_v5_regime_analysis_path"].endswith("steady_v5_regime_analysis.json"))

            history = json.loads((reports_dir / "priority-history.json").read_text(encoding="utf-8"))
            self.assertEqual(history["stats"]["snapshot_count"], 2)
            self.assertEqual(history["stats"]["evaluated_snapshot_count"], 1)
            self.assertEqual(history["replay_days"][0]["date"], date_a)
            self.assertEqual(history["replay_days"][0]["next_report_date"], date_b)
            self.assertEqual(history["stats"]["hit_count_effect"][0]["hit_count"], 2)
            self.assertEqual(history["stats"]["top3_vs_all"]["top3_sample_count"], 3)

    def test_priority_history_adds_topn_and_benchmark_fields(self):
        report = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            self.make_universe_report("2026-04-10"),
            next_universe_report=self.make_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        history = generate_priority_history_report(
            [report],
            market_prices={
                "2026-04-10": 100.0,
                "2026-04-11": 101.0,
            },
        )

        self.assertAlmostEqual(history["stats"]["top1_avg_return"], 3.0, places=4)
        self.assertAlmostEqual(history["stats"]["top3_avg_return"], 2.697, places=3)
        self.assertAlmostEqual(history["stats"]["top5_avg_return"], 0.6338, places=4)
        self.assertAlmostEqual(history["stats"]["benchmark_return"]["market_avg_return"], 1.0, places=4)
        self.assertAlmostEqual(history["stats"]["benchmark_return"]["random_selection_expected_return"], 0.6338, places=4)
        self.assertAlmostEqual(history["stats"]["topn_vs_benchmark"]["top1_minus_market"], 2.0, places=4)
        self.assertTrue(history["stats"]["validation_readiness"]["is_sample_size_ready"] is False)
        self.assertEqual(history["replay_days"][0]["top1_returns"][0]["symbol"], "BBB")
        self.assertEqual(history["replay_days"][0]["benchmark_return"]["market_return"], 1.0)

    def test_factor_analysis_breaks_down_three_factors(self):
        report = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            self.make_universe_report("2026-04-10"),
            next_universe_report=self.make_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        factor_analysis = generate_factor_analysis_report(
            [report],
            market_prices={
                "2026-04-10": 100.0,
                "2026-04-11": 101.0,
            },
            universe_reports_by_date={
                "2026-04-10": self.make_universe_report("2026-04-10"),
            },
        )

        self.assertEqual(factor_analysis["report_version"], "v18-factor-analysis")
        self.assertEqual(factor_analysis["evaluated_days"], 1)
        self.assertEqual(factor_analysis["candidate_samples"], 4)
        self.assertIn("hit_count", factor_analysis["legacy_factor_names"])
        self.assertIn("low_position_ma20", factor_analysis["test_factor_names"])
        self.assertIn("ma20_v2", factor_analysis["test_factor_names"])
        self.assertEqual(factor_analysis["factors"]["hit_count"]["high_group"]["factor_value"], 2)
        self.assertEqual(factor_analysis["factors"]["hit_count"]["low_group"]["factor_value"], 1)
        self.assertEqual(factor_analysis["factors"]["technical"]["high_group"]["label"], "強勢續看")
        self.assertEqual(factor_analysis["factors"]["zone"]["high_group"]["label"], "試單區優先")
        self.assertIn("low_position_ma20", factor_analysis["factors"])
        self.assertIn("just_break_ma20", factor_analysis["factors"])
        self.assertIn("ma20_v2", factor_analysis["factors"])
        self.assertGreater(factor_analysis["ma20_variant_comparison"]["variants"]["ma20_v2"]["pass_rate_pct"], 10)
        self.assertGreater(factor_analysis["ma20_variant_comparison"]["variants"]["ma20_v2"]["avg_return_pct"], 0)
        self.assertEqual(factor_analysis["ma20_variant_comparison"]["requirements"]["pass_rate_over_10_pct"], True)
        self.assertEqual(factor_analysis["ma20_variant_comparison"]["requirements"]["positive_avg_return"], True)
        self.assertIn(factor_analysis["factors"]["zone"]["verdict"], ["有效", "拖累", "中性"])
        self.assertGreaterEqual(len(factor_analysis["factor_effect_ranking"]), 9)
        self.assertIn("positive_factors", factor_analysis)
        self.assertIn("drag_factors", factor_analysis)

    def test_factor_combination_analysis_finds_strongest_combo(self):
        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=self.make_combo_current_universe_report("2026-04-10"),
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            self.make_combo_current_universe_report("2026-04-10"),
            next_universe_report=self.make_combo_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        combination_analysis = generate_factor_combination_analysis_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": self.make_combo_current_universe_report("2026-04-10"),
            },
        )

        self.assertEqual(combination_analysis["report_version"], "v15-factor-combination-analysis")
        self.assertEqual(combination_analysis["evaluated_days"], 2)
        self.assertIn("just_break_ma20_plus_low_position_ma20", combination_analysis["combination_names"])
        self.assertIn("low_k_turn_up", combination_analysis["single_factor_baselines"])
        self.assertEqual(combination_analysis["combinations"]["just_break_ma20_plus_low_position_ma20"]["sample_count"], 1)
        self.assertAlmostEqual(
            combination_analysis["combinations"]["just_break_ma20_plus_low_position_ma20"]["avg_return_pct"],
            5.2632,
            places=4,
        )
        self.assertTrue(combination_analysis["combination_superiority_confirmed"])
        self.assertTrue(combination_analysis["strongest_combination_vs_best_single_factor"]["is_stronger"])
        self.assertEqual(
            combination_analysis["strongest_combination"]["combination"],
            "just_break_ma20_plus_low_position_ma20",
        )

    def test_strategy_analysis_splits_sniper_and_steady(self):
        current_universe = self.make_combo_current_universe_report("2026-04-10")
        for stock in current_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["k"] = 25.0
                stock["indicators"]["volume_ratio"] = 1.3

        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=current_universe,
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            current_universe,
            next_universe_report=self.make_combo_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        combination_analysis = generate_factor_combination_analysis_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": current_universe,
            },
        )
        strategy_analysis = generate_strategy_analysis_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": current_universe,
            },
        )

        self.assertEqual(strategy_analysis["report_version"], "v27-strategy-analysis")
        self.assertEqual(strategy_analysis["strategies"]["sniper"]["label"], "狙擊型")
        self.assertEqual(strategy_analysis["strategies"]["steady"]["label"], "穩定型")
        self.assertEqual(
            strategy_analysis["strategies"]["sniper"]["avg_return_pct"],
            combination_analysis["combinations"]["just_break_ma20_plus_low_position_ma20"]["avg_return_pct"],
        )
        self.assertEqual(
            strategy_analysis["strategies"]["steady"]["win_rate_pct"],
            combination_analysis["combinations"]["low_k_turn_up_plus_low_position_ma20"]["win_rate_pct"],
        )
        self.assertEqual(strategy_analysis["style_choice"]["high_return"]["strategy"], "sniper")
        self.assertEqual(strategy_analysis["style_choice"]["steady"]["strategy"], "steady")
        self.assertIn("sniper_v2", strategy_analysis["strategy_v2_names"])
        self.assertIn("steady_v2", strategy_analysis["strategy_v2_names"])
        self.assertIn("steady_v3", strategy_analysis["strategy_v3_names"])
        self.assertIn("steady_v4", strategy_analysis["strategy_v4_names"])
        self.assertIn("steady_v5", strategy_analysis["strategy_v5_names"])
        self.assertIn("steady_v3_volume", strategy_analysis["strategy_experiment_names"])
        self.assertEqual(strategy_analysis["strategies_v2"]["sniper_v2"]["generation"], "v2")
        self.assertEqual(strategy_analysis["strategies_v2"]["steady_v2"]["generation"], "v2")
        self.assertEqual(strategy_analysis["strategies_v3"]["steady_v3"]["generation"], "v3")
        self.assertEqual(strategy_analysis["strategies_v4"]["steady_v4"]["generation"], "v4")
        self.assertEqual(strategy_analysis["strategies_v5"]["steady_v5"]["generation"], "v5")
        self.assertEqual(strategy_analysis["strategies_v4"]["steady_v4"]["factor_names"], ["low_k_turn_up", "steady_v4_k_band", "steady_v4_ma20_distance"])
        self.assertEqual(strategy_analysis["strategies_v5"]["steady_v5"]["factor_names"], ["low_k_turn_up", "steady_v4_k_band", "steady_v4_ma20_distance", "steady_v5_pullback_limit"])
        self.assertEqual(strategy_analysis["v24_summary"]["steady_rebuild"]["k_band"]["min"], 24.0)
        self.assertEqual(strategy_analysis["v24_summary"]["steady_rebuild"]["k_band"]["max"], 30.0)
        self.assertEqual(strategy_analysis["v24_summary"]["steady_rebuild"]["ma20_distance_pct_lt"], 2.08)
        self.assertEqual(strategy_analysis["strategies_v3"]["steady_v3"]["best_single_factor"]["factor"], "low_k_turn_up")
        self.assertEqual(strategy_analysis["strategy_variant_comparison"]["sniper"]["v1"]["strategy"], "sniper")
        self.assertEqual(strategy_analysis["strategy_variant_comparison"]["sniper"]["v2"]["strategy"], "sniper_v2")
        self.assertEqual(strategy_analysis["strategy_variant_comparison"]["steady"]["v1"]["strategy"], "steady")
        self.assertEqual(strategy_analysis["strategy_variant_comparison"]["steady"]["v2"]["strategy"], "steady_v2")
        self.assertEqual(strategy_analysis["strategy_variant_comparison"]["steady"]["v3"]["strategy"], "steady_v3")
        self.assertEqual(strategy_analysis["strategy_variant_comparison"]["steady"]["v4"]["strategy"], "steady_v4")
        self.assertEqual(strategy_analysis["strategy_variant_comparison"]["steady"]["v5"]["strategy"], "steady_v5")
        self.assertEqual(
            strategy_analysis["strategy_variant_comparison"]["steady"]["optional_tests"]["kd_plus_low_position"]["strategy"],
            "steady",
        )
        self.assertEqual(
            strategy_analysis["strategy_variant_comparison"]["steady"]["optional_tests"]["kd_plus_volume_expand"]["strategy"],
            "steady_v3_volume",
        )
        self.assertTrue(strategy_analysis["strategy_variant_comparison"]["sniper"]["v2_avg_return_positive"])
        self.assertTrue(strategy_analysis["strategy_variant_comparison"]["steady"]["v3_hit_count_recovered"])
        self.assertIn("v4_hit_count_gt_v2", strategy_analysis["strategy_variant_comparison"]["steady"])
        self.assertIn("v5_alpha_profile", strategy_analysis["strategy_variant_comparison"]["steady"])
        self.assertIn("steady_rebuild", strategy_analysis["v24_summary"])
        self.assertEqual(strategy_analysis["v24_summary"]["steady_rebuild"]["target_strategy"], "steady_v4")
        self.assertIn("steady_alpha_repair", strategy_analysis["v27_summary"])
        self.assertEqual(strategy_analysis["v27_summary"]["steady_alpha_repair"]["target_strategy"], "steady_v5")
        self.assertIn("steady_rewrite", strategy_analysis["v22_summary"])
        self.assertEqual(strategy_analysis["v22_summary"]["steady_rewrite"]["target_strategy"], "steady_v3")
        self.assertIn("families_with_more_hits", strategy_analysis["v2_summary"])
        self.assertIn("sniper", strategy_analysis["v2_summary"]["families_with_more_hits"])
        self.assertIn("sniper", strategy_analysis["v2_summary"]["families_with_positive_avg_return"])
        self.assertTrue(strategy_analysis["strategy_variant_comparison"]["sniper"]["meets_v19_goal"])

    def test_strategy_analysis_v27_repair_turns_steady_v5_alpha_positive(self):
        previous_universe = self.make_combo_previous_universe_report("2026-04-09")
        current_universe = self.make_combo_current_universe_report("2026-04-10")
        next_universe = self.make_combo_next_universe_report("2026-04-11")

        for stock in previous_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 100.0
                stock["indicators"]["k"] = 12.0
            if stock["symbol"] == "CCC":
                stock["indicators"]["close"] = 101.0
                stock["indicators"]["k"] = 20.0
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 102.5
                stock["indicators"]["k"] = 18.0
            if stock["symbol"] == "AAA":
                stock["indicators"]["close"] = 100.8
                stock["indicators"]["k"] = 22.0

        for stock in current_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 98.5
                stock["indicators"]["k"] = 25.0
                stock["indicators"]["volume_ratio"] = 1.3
            if stock["symbol"] == "CCC":
                stock["indicators"]["close"] = 99.8
                stock["indicators"]["k"] = 26.0
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 99.5
                stock["indicators"]["k"] = 24.0
                stock["indicators"]["volume_ratio"] = 0.7
            if stock["symbol"] == "AAA":
                stock["indicators"]["close"] = 100.2
                stock["indicators"]["k"] = 27.0

        for stock in next_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 100.0
            if stock["symbol"] == "CCC":
                stock["indicators"]["close"] = 100.8
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 98.0
            if stock["symbol"] == "AAA":
                stock["indicators"]["close"] = 101.2

        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            previous_universe,
            next_universe_report=current_universe,
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            current_universe,
            next_universe_report=next_universe,
            next_date="2026-04-11",
        )

        strategy_analysis = generate_strategy_analysis_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": previous_universe,
                "2026-04-10": current_universe,
            },
        )

        steady_comparison = strategy_analysis["strategy_variant_comparison"]["steady"]
        self.assertEqual(strategy_analysis["strategies_v4"]["steady_v4"]["hit_count"], 4)
        self.assertEqual(strategy_analysis["strategies_v5"]["steady_v5"]["hit_count"], 3)
        self.assertLess(steady_comparison["v4_alpha_profile"]["avg_alpha_pct"], 0)
        self.assertGreater(steady_comparison["v5_alpha_profile"]["avg_alpha_pct"], 0)
        self.assertEqual(
            [item["symbol"] for item in steady_comparison["v5_alpha_profile"]["samples"]],
            ["BBB", "CCC", "AAA"],
        )
        self.assertTrue(steady_comparison["v5_hit_count_reasonable"])
        self.assertTrue(steady_comparison["v5_win_rate_not_collapsed"])
        self.assertTrue(steady_comparison["v5_alpha_positive"])
        self.assertTrue(steady_comparison["meets_v27_goal"])
        self.assertTrue(strategy_analysis["v27_summary"]["steady_alpha_repair"]["meets_v27_goal"])

    def test_steady_v5_long_term_validation_report_builds_windows(self):
        previous_universe = self.make_combo_previous_universe_report("2026-04-09")
        current_universe = self.make_combo_current_universe_report("2026-04-10")
        next_universe = self.make_combo_next_universe_report("2026-04-11")

        for stock in previous_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 100.0
                stock["indicators"]["k"] = 12.0
            if stock["symbol"] == "CCC":
                stock["indicators"]["close"] = 101.0
                stock["indicators"]["k"] = 20.0
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 102.5
                stock["indicators"]["k"] = 18.0
            if stock["symbol"] == "AAA":
                stock["indicators"]["close"] = 100.8
                stock["indicators"]["k"] = 22.0

        for stock in current_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 98.5
                stock["indicators"]["k"] = 25.0
                stock["indicators"]["volume_ratio"] = 1.3
            if stock["symbol"] == "CCC":
                stock["indicators"]["close"] = 99.8
                stock["indicators"]["k"] = 26.0
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 99.5
                stock["indicators"]["k"] = 24.0
                stock["indicators"]["volume_ratio"] = 0.7
            if stock["symbol"] == "AAA":
                stock["indicators"]["close"] = 100.2
                stock["indicators"]["k"] = 27.0

        for stock in next_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 100.0
            if stock["symbol"] == "CCC":
                stock["indicators"]["close"] = 100.8
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 98.0
            if stock["symbol"] == "AAA":
                stock["indicators"]["close"] = 101.2

        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            previous_universe,
            next_universe_report=current_universe,
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            current_universe,
            next_universe_report=next_universe,
            next_date="2026-04-11",
        )

        validation = generate_steady_v5_long_term_validation_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": previous_universe,
                "2026-04-10": current_universe,
            },
        )

        self.assertEqual(validation["report_version"], "v28-steady-v5-long-term-validation")
        self.assertEqual(validation["validation_target"]["strategy"], "steady_v5")
        self.assertEqual(validation["validation_target"]["base_strategy"], "steady_v4")
        self.assertEqual(validation["assessment_rules"]["windows"], [60, 120])
        self.assertEqual(validation["strategy_baseline_snapshot"]["strategy"], "steady_v5")
        self.assertEqual(validation["evaluated_days"], 2)
        self.assertEqual(len(validation["daily_validation"]), 2)
        self.assertIn("overall_alpha", validation)
        self.assertIn("overall_winrate", validation)
        self.assertIn("segmented_alpha", validation)
        self.assertIn("segmented_winrate", validation)
        self.assertIn("rolling_alpha", validation)
        self.assertIn("rolling_winrate", validation)
        self.assertIn("60d", validation["validation_windows"])
        self.assertIn("120d", validation["validation_windows"])
        self.assertIn("60d", validation["overall_alpha"])
        self.assertIn("120d", validation["overall_winrate"])
        self.assertEqual(validation["segmented_alpha"]["segment_days"], 30)
        self.assertEqual(validation["rolling_alpha"]["rolling_window_days"], 10)
        self.assertFalse(validation["validation_windows"]["60d"]["is_ready"])
        self.assertFalse(validation["validation_windows"]["120d"]["is_ready"])
        self.assertGreater(validation["validation_windows"]["60d"]["avg_alpha_pct"], 0)
        self.assertTrue(validation["validation_windows"]["60d"]["alpha_positive"])
        self.assertTrue(validation["validation_windows"]["60d"]["has_not_broken"])
        self.assertIsNone(validation["latest_assessment"]["alpha_confirmed"])
        self.assertIn("60 天視窗尚未完成", validation["summary"])

    def test_steady_v5_segmented_and_rolling_validation_helpers(self):
        base_date = datetime(2026, 1, 1)
        alpha_by_block = [0.6, 0.4, 0.5, 0.3, 0.7, 0.2, 0.8, 0.4, 0.6, 0.3, 0.5, 0.2]
        daily_records = []

        for index in range(120):
            block_index = index // 10
            alpha_pct = alpha_by_block[block_index]
            next_day_return_pct = 1.2 if index % 5 else -0.2
            market_return_pct = next_day_return_pct - alpha_pct
            date_str = (base_date + timedelta(days=index)).strftime("%Y-%m-%d")
            daily_records.append({
                "date": date_str,
                "next_report_date": date_str,
                "steady_v5_hit_count": 1,
                "avg_return_pct": next_day_return_pct,
                "avg_alpha_pct": alpha_pct,
                "steady_v5_hits": [{
                    "next_day_return_pct": next_day_return_pct,
                    "market_return_pct": market_return_pct,
                    "alpha_pct": alpha_pct,
                }],
            })

        segmented = priority_validation_module._build_steady_v5_segmented_validation(120, daily_records)
        self.assertTrue(segmented["is_ready"])
        self.assertEqual(segmented["segment_days"], 30)
        self.assertEqual(len(segmented["segments"]), 4)
        self.assertEqual(segmented["segments"][0]["label"], "第1段（前30天）")
        self.assertEqual(segmented["segments"][-1]["label"], "第4段（後30天）")
        self.assertTrue(segmented["assessment"]["all_segments_alpha_positive"])
        self.assertTrue(segmented["assessment"]["all_segments_not_broken"])

        rolling = priority_validation_module._build_steady_v5_rolling_validation(120, daily_records)
        self.assertTrue(rolling["is_ready"])
        self.assertEqual(rolling["rolling_window_days"], 10)
        self.assertEqual(rolling["step_days"], 10)
        self.assertEqual(len(rolling["windows"]), 12)
        self.assertEqual(rolling["assessment"]["negative_window_count"], 0)
        self.assertEqual(rolling["assessment"]["longest_negative_streak"], 0)
        self.assertTrue(rolling["assessment"]["has_no_long_negative_streak"])

    def test_steady_v5_regime_analysis_report_identifies_market_regimes(self):
        base_date = datetime(2026, 1, 1)
        alpha_by_block = [0.8, 0.6, -0.5, 0.7, -0.4, 0.3, 0.9, 0.6, 0.5, -1.2, -0.8, 0.4]
        daily_records = []
        universe_reports_by_date = {}

        for index in range(120):
            block_index = index // 10
            alpha_pct = alpha_by_block[block_index]
            is_negative_block = alpha_pct < 0
            date_str = (base_date + timedelta(days=index)).strftime("%Y-%m-%d")
            next_date_str = (base_date + timedelta(days=index + 1)).strftime("%Y-%m-%d")
            if is_negative_block:
                market_return_pct = -0.6 if index % 2 == 0 else 0.4
                categories = ["金融", "航運", "化工", "食品", "電子", "半導體", "水泥", "航空", "鋼鐵", "電信"]
                volume_ratio = 0.72
            else:
                market_return_pct = 0.35
                categories = ["半導體", "半導體", "電子", "電子", "半導體", "電子", "半導體", "電子", "金融", "航運"]
                volume_ratio = 1.32

            next_day_return_pct = market_return_pct + alpha_pct
            daily_records.append({
                "date": date_str,
                "next_report_date": next_date_str,
                "steady_v5_hit_count": 2,
                "market_return_pct": market_return_pct,
                "avg_return_pct": next_day_return_pct,
                "win_rate_pct": 100.0 if next_day_return_pct > 0 else 0.0,
                "avg_alpha_pct": alpha_pct,
                "steady_v5_hits": [
                    {
                        "symbol": f"H{index:03d}A",
                        "next_day_return_pct": next_day_return_pct,
                        "market_return_pct": market_return_pct,
                        "alpha_pct": alpha_pct,
                    },
                    {
                        "symbol": f"H{index:03d}B",
                        "next_day_return_pct": next_day_return_pct,
                        "market_return_pct": market_return_pct,
                        "alpha_pct": alpha_pct,
                    },
                ],
            })
            universe_reports_by_date[date_str] = self.make_regime_universe_report(date_str, categories, volume_ratio)

        analysis = generate_steady_v5_regime_analysis_report(
            [],
            universe_reports_by_date=universe_reports_by_date,
            long_term_validation_report={
                "report_version": "v28-steady-v5-long-term-validation",
                "evaluation_horizon": {
                    "start_date": daily_records[0]["date"],
                    "end_date": daily_records[-1]["date"],
                },
                "daily_validation": daily_records,
            },
        )

        self.assertEqual(analysis["report_version"], "v29-steady-v5-regime-analysis")
        self.assertEqual(analysis["source_validation"]["available_window_count"], 12)
        self.assertEqual(len(analysis["negative_alpha_windows"]), 4)
        self.assertEqual(len(analysis["negative_alpha_periods"]), 3)
        self.assertEqual(analysis["regime_comparison"]["negative_alpha"]["market_trend"]["dominant_label"], "下降")
        self.assertEqual(analysis["regime_comparison"]["negative_alpha"]["volatility"]["dominant_label"], "震盪")
        self.assertEqual(analysis["regime_comparison"]["negative_alpha"]["sector_concentration"]["dominant_label"], "分散輪動")
        self.assertEqual(analysis["regime_comparison"]["negative_alpha"]["volume"]["dominant_label"], "縮量")
        self.assertEqual(analysis["regime_comparison"]["positive_alpha"]["market_trend"]["dominant_label"], "上升")
        self.assertEqual(analysis["regime_comparison"]["positive_alpha"]["volatility"]["dominant_label"], "單邊")
        self.assertEqual(analysis["regime_comparison"]["positive_alpha"]["sector_concentration"]["dominant_label"], "族群集中")
        self.assertEqual(analysis["regime_comparison"]["positive_alpha"]["volume"]["dominant_label"], "放量")
        self.assertTrue(analysis["answers"]["clear_regime_detected"])
        self.assertIn("steady_v5 較適合", analysis["answers"]["works_in"])
        self.assertIn("steady_v5 較容易在", analysis["answers"]["fails_in"])


    def test_signal_density_report_tracks_daily_weekly_hits_and_blockers(self):
        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=self.make_combo_current_universe_report("2026-04-10"),
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            self.make_combo_current_universe_report("2026-04-10"),
            next_universe_report=self.make_combo_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        signal_density = generate_signal_density_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": self.make_combo_current_universe_report("2026-04-10"),
            },
        )

        self.assertEqual(signal_density["report_version"], "v17-signal-density-analysis")
        self.assertEqual(len(signal_density["daily_hit_counts"]), 2)
        self.assertEqual(signal_density["daily_hit_counts"][0]["strategy_hits"]["sniper"], 0)
        self.assertEqual(signal_density["daily_hit_counts"][0]["zero_hit_diagnosis"]["is_zero_hit_day"], True)
        self.assertEqual(signal_density["daily_hit_counts"][0]["strategy_blockers"]["sniper"]["strictest_condition"]["condition"], "ma20_break")
        self.assertEqual(signal_density["daily_hit_counts"][0]["strategy_blockers"]["steady"]["strictest_condition"]["condition"], "kd_low_turn_up")
        self.assertEqual(signal_density["daily_hit_counts"][1]["strategy_hits"]["sniper"], 1)
        self.assertEqual(signal_density["daily_hit_counts"][1]["strategy_hits"]["steady"], 1)
        self.assertEqual(signal_density["weekly_hit_counts"][0]["strategy_hits"]["sniper"], 1)
        self.assertEqual(signal_density["weekly_hit_counts"][0]["strategy_hits"]["steady"], 1)
        self.assertEqual(signal_density["overall_condition_density"]["strictest_condition"]["condition"], "kd_low_turn_up")
        self.assertEqual(signal_density["latest_day_summary"]["strictest_condition"]["condition"], "kd_low_turn_up")

    def test_steady_v2_blockers_report_finds_bottleneck(self):
        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=self.make_combo_current_universe_report("2026-04-10"),
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            self.make_combo_current_universe_report("2026-04-10"),
            next_universe_report=self.make_combo_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        blockers = generate_steady_v2_blockers_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": self.make_combo_current_universe_report("2026-04-10"),
            },
        )

        self.assertEqual(blockers["report_version"], "v20-steady-v2-blockers")
        self.assertEqual(blockers["strategy_target"]["v2_strategy"], "steady_v2")
        self.assertIn("ma20_v2", blockers["condition_names"])
        self.assertEqual(blockers["bottleneck_summary"]["overall_strictest_condition"]["condition"], "kd_low_turn_up")
        self.assertEqual(
            blockers["bottleneck_summary"]["transition_from_v1_to_v2"]["bottleneck_condition"]["condition"],
            "ma20_v2",
        )
        self.assertEqual(blockers["strategy_variant_snapshot"]["v2"]["strategy"], "steady_v2")
        self.assertGreater(
            blockers["conditions"]["ma20_v2"]["pass_rate_pct"],
            blockers["conditions"]["kd_low_turn_up"]["pass_rate_pct"],
        )
        self.assertGreater(
            blockers["pairwise_intersections"]["kd_low_turn_up__low_position"]["pass_count"],
            blockers["pairwise_intersections"]["ma20_v2__kd_low_turn_up"]["pass_count"],
        )

    def test_timing_alignment_report_finds_best_delay(self):
        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=self.make_combo_current_universe_report("2026-04-10"),
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            self.make_combo_current_universe_report("2026-04-10"),
            next_universe_report=self.make_combo_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        timing = generate_timing_alignment_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": self.make_combo_current_universe_report("2026-04-10"),
                "2026-04-11": self.make_combo_next_universe_report("2026-04-11"),
                "2026-04-12": self.make_timing_followup_universe_report("2026-04-12"),
            },
        )

        self.assertEqual(timing["report_version"], "v21-timing-alignment")
        self.assertEqual(timing["kd_event_sample_count"], 1)
        self.assertEqual(timing["delay_alignment"]["day_1"]["aligned_count"], 1)
        self.assertEqual(timing["delay_alignment"]["day_1"]["first_alignment_count"], 1)
        self.assertEqual(timing["best_alignment_delay"]["delay_days"], 1)
        self.assertEqual(timing["best_delayed_entry_timing"]["delay_days"], 1)
        self.assertEqual(timing["recommendation"]["recommended_delay_days"], 1)
        self.assertTrue(timing["recommendation"]["beats_kd_event_baseline"])
        self.assertEqual(timing["event_samples"][0]["first_alignment_delay_days"], 1)
        self.assertTrue(timing["event_samples"][0]["lookahead"]["day_1"]["in_ma20_v2"])

    def test_steady_v2_signature_report_finds_ma20_and_selloff_features(self):
        current_universe = self.make_combo_current_universe_report("2026-04-10")
        for stock in current_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 98.5
                stock["indicators"]["k"] = 25.0
                stock["indicators"]["volume_ratio"] = 1.3

        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=current_universe,
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            current_universe,
            next_universe_report=self.make_combo_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        signature = generate_steady_v2_signature_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": current_universe,
            },
        )

        self.assertEqual(signature["report_version"], "v23-steady-v2-signature")
        self.assertEqual(signature["strategy_target"]["focus_strategy"], "steady_v2")
        self.assertEqual(signature["sample_partition"]["steady_v2_count"], 1)
        self.assertEqual(signature["sample_partition"]["steady_v3_total_count"], 2)
        self.assertEqual(signature["sample_partition"]["steady_v3_other_count"], 1)
        self.assertEqual(signature["groups"]["steady_v2"]["samples"][0]["symbol"], "BBB")
        self.assertEqual(signature["groups"]["steady_v3_other"]["samples"][0]["symbol"], "DDD")
        self.assertEqual(signature["metric_comparison"]["abs_ma20_gap_pct"]["direction"], "v2_lower")
        self.assertEqual(signature["metric_comparison"]["has_sharp_drop"]["direction"], "v2_higher")
        self.assertIn("ma20_distance", [item["feature_key"] for item in signature["key_signatures"]])
        self.assertEqual(len(signature["key_signatures"]), 2)
        self.assertIn("更貼近 MA20", signature["signature_summary"])

    def test_steady_v4_tracking_report_builds_daily_log_and_windows(self):
        current_universe = self.make_combo_current_universe_report("2026-04-10")
        for stock in current_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 98.5
                stock["indicators"]["k"] = 25.0

        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=current_universe,
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            current_universe,
            next_universe_report=self.make_combo_next_universe_report("2026-04-11"),
            next_date="2026-04-11",
        )

        tracking = generate_steady_v4_tracking_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": current_universe,
            },
        )

        self.assertEqual(tracking["report_version"], "v25-steady-v4-tracking")
        self.assertEqual(tracking["tracking_target"]["strategy"], "steady_v4")
        self.assertEqual(tracking["tracking_target"]["factor_names"], ["low_k_turn_up", "steady_v4_k_band", "steady_v4_ma20_distance"])
        self.assertEqual(tracking["assessment_rules"]["stability"]["min_win_rate_pct"], 60.0)
        self.assertEqual(tracking["evaluated_days"], 2)
        self.assertEqual(len(tracking["daily_tracking"]), 2)
        self.assertEqual(tracking["daily_tracking"][0]["date"], "2026-04-09")
        self.assertEqual(tracking["daily_tracking"][0]["steady_v4_hit_count"], 0)
        self.assertEqual(tracking["daily_tracking"][1]["date"], "2026-04-10")
        self.assertEqual(tracking["daily_tracking"][1]["steady_v4_hit_count"], 1)
        self.assertEqual(tracking["daily_tracking"][1]["steady_v4_hits"][0]["symbol"], "BBB")
        self.assertAlmostEqual(tracking["daily_tracking"][1]["steady_v4_hits"][0]["next_day_return_pct"], 1.5228, places=4)
        self.assertAlmostEqual(tracking["daily_tracking"][1]["edge_vs_market_pct"], 0.5327, places=4)
        self.assertFalse(tracking["tracking_windows"]["20d"]["is_ready"])
        self.assertEqual(tracking["tracking_windows"]["20d"]["observed_days"], 2)
        self.assertEqual(tracking["tracking_windows"]["20d"]["total_hits"], 1)
        self.assertTrue(tracking["tracking_windows"]["20d"]["is_stable"])
        self.assertTrue(tracking["tracking_windows"]["20d"]["has_edge"])
        self.assertFalse(tracking["tracking_windows"]["50d"]["is_ready"])
        self.assertIsNone(tracking["latest_assessment"]["stability_confirmed"])
        self.assertIsNone(tracking["latest_assessment"]["edge_confirmed"])
        self.assertIn("20 天視窗尚未完成", tracking["summary"])

    def test_steady_v4_alpha_breakdown_report_finds_winners_and_drags(self):
        current_universe = self.make_combo_current_universe_report("2026-04-10")
        for stock in current_universe["stocks"]:
            if stock["symbol"] == "BBB":
                stock["indicators"]["close"] = 98.5
                stock["indicators"]["k"] = 25.0
                stock["indicators"]["volume_ratio"] = 1.3
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 99.5
                stock["indicators"]["k"] = 24.0
                stock["indicators"]["volume_ratio"] = 0.7

        next_universe = self.make_combo_next_universe_report("2026-04-11")
        for stock in next_universe["stocks"]:
            if stock["symbol"] == "DDD":
                stock["indicators"]["close"] = 98.0

        report_a = generate_priority_snapshot(
            self.make_context_report("2026-04-09"),
            self.make_combo_previous_universe_report("2026-04-09"),
            next_universe_report=current_universe,
            next_date="2026-04-10",
        )
        report_b = generate_priority_snapshot(
            self.make_context_report("2026-04-10"),
            current_universe,
            next_universe_report=next_universe,
            next_date="2026-04-11",
        )

        alpha = generate_steady_v4_alpha_breakdown_report(
            [report_a, report_b],
            market_prices={
                "2026-04-09": 100.0,
                "2026-04-10": 101.0,
                "2026-04-11": 102.0,
            },
            universe_reports_by_date={
                "2026-04-09": self.make_combo_previous_universe_report("2026-04-09"),
                "2026-04-10": current_universe,
            },
        )

        self.assertEqual(alpha["report_version"], "v26-steady-v4-alpha-breakdown")
        self.assertEqual(alpha["strategy_target"]["strategy"], "steady_v4")
        self.assertEqual(alpha["benchmark_target"]["type"], "market_return")
        self.assertEqual(alpha["sample_partition"]["steady_v4_hit_count"], 2)
        self.assertEqual(alpha["sample_partition"]["outperform_market_count"], 1)
        self.assertEqual(alpha["sample_partition"]["underperform_market_count"], 1)
        self.assertTrue(alpha["benchmark_comparison"]["market_stronger"])
        self.assertEqual(alpha["groups"]["outperform_market"]["samples"][0]["symbol"], "BBB")
        self.assertEqual(alpha["groups"]["underperform_market"]["samples"][0]["symbol"], "DDD")
        self.assertEqual(alpha["outperforming_stocks"][0]["symbol"], "BBB")
        self.assertEqual(alpha["dragging_stocks"][0]["symbol"], "DDD")
        self.assertEqual(alpha["alpha_metric_comparison"]["volume_ratio"]["direction"], "focus_higher")
        self.assertEqual(alpha["drag_metric_comparison"]["volume_ratio"]["direction"], "focus_lower")
        self.assertGreaterEqual(len(alpha["key_alpha_signatures"]), 1)
        self.assertGreaterEqual(len(alpha["key_drag_signatures"]), 1)
        self.assertIn("無法打敗市場", alpha["summary"])

if __name__ == "__main__":
    # 執行單元測試
    print("=" * 60)
    print("執行單元測試")
    print("=" * 60)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 加入所有測試類別
    suite.addTests(loader.loadTestsFromTestCase(TestTaiwanTimezone))
    suite.addTests(loader.loadTestsFromTestCase(TestInstitutionalAggregation))
    suite.addTests(loader.loadTestsFromTestCase(TestVolumeRatio))
    suite.addTests(loader.loadTestsFromTestCase(TestInstitutionalScoring))
    suite.addTests(loader.loadTestsFromTestCase(TestReportConsistency))
    suite.addTests(loader.loadTestsFromTestCase(TestPriorityValidation))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 總結
    print("\n" + "=" * 60)
    print("測試總結")
    print("=" * 60)
    
    if result.wasSuccessful():
        print("[PASS] 所有測試通過！")
        sys.exit(0)
    else:
        print("[FAIL] 部分測試失敗")
        sys.exit(1)
