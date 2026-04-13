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
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.config import get_today_str, get_taiwan_now, TAIWAN_TZ
from backend.calc_indicators import StockIndicators, calculate_indicators
from backend.ranking import score_stock, evaluate_institutional, StockScore
from backend.generate_report import generate_report_v2, generate_lite_report, generate_universe_report, validate_report_consistency
from backend.priority_validation import generate_priority_snapshot, backfill_priority_validation_reports


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
    ) -> dict:
        return {
            "symbol": symbol,
            "name": name,
            "rank": rank,
            "score": score,
            "action_bias": "可留意",
            "institutional": institutional,
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

            result = backfill_priority_validation_reports(base_dir=root, target_date=date_b)

            self.assertTrue((reports_dir / f"{date_a}-priority.json").exists())
            self.assertTrue((reports_dir / f"{date_b}-priority.json").exists())
            self.assertTrue((reports_dir / "priority-history.json").exists())
            self.assertEqual(result["available_dates"], [date_a, date_b])

            history = json.loads((reports_dir / "priority-history.json").read_text(encoding="utf-8"))
            self.assertEqual(history["stats"]["snapshot_count"], 2)
            self.assertEqual(history["stats"]["evaluated_snapshot_count"], 1)
            self.assertEqual(history["replay_days"][0]["date"], date_a)
            self.assertEqual(history["replay_days"][0]["next_report_date"], date_b)
            self.assertEqual(history["stats"]["hit_count_effect"][0]["hit_count"], 2)
            self.assertEqual(history["stats"]["top3_vs_all"]["top3_sample_count"], 3)

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
