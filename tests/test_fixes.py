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
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.config import get_today_str, get_taiwan_now, TAIWAN_TZ
from backend.calc_indicators import StockIndicators, calculate_indicators
from backend.ranking import score_stock, evaluate_institutional


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
