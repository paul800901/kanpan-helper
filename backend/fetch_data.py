# -*- coding: utf-8 -*-
"""資料抓取模組 - 從 FinMind 抓取股票資料"""
import requests
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from backend.config import (
    DATA_DIR, DEFAULT_STOCKS, get_today_str, get_cache_path, get_taiwan_now
)

class FinMindAPI:
    """FinMind API 客戶端"""
    
    BASE_URL = "https://api.finmindtrade.com/api/v4/data"
    
    def __init__(self):
        self.session = requests.Session()
    
    def get_stock_candles(self, symbol: str, days: int = 40) -> List[Dict]:
        """
        取得股票日 K 線資料
        
        Args:
            symbol: 股票代碼
            days: 要抓取的天數
            
        Returns:
            List[Dict]: 日 K 資料列表
        """
        end_date = get_taiwan_now()
        start_date = end_date - timedelta(days=days + 30)  # 多抓一些確保足夠交易日
        
        params = {
            "dataset": "TaiwanStockPrice",
            "data_id": symbol,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d")
        }
        
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("data"):
                # 只取最近 N 天
                return data["data"][-days:]
            return []
            
        except Exception as e:
            print(f"  [WARN] 抓取 {symbol} 價格資料失敗: {e}")
            return []
    
    def get_institutional_data(self, symbol: str, days: int = 10) -> List[Dict]:
        """
        取得法人買賣超資料
        
        回傳原始資料（未聚合），每個法人類別分開
        
        Args:
            symbol: 股票代碼
            days: 要抓取的天數
            
        Returns:
            List[Dict]: 法人資料列表（原始）
        """
        end_date = get_taiwan_now()
        start_date = end_date - timedelta(days=days + 30)
        
        params = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": symbol,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d")
        }
        
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("data"):
                # 按日期排序，但保留原始欄位（不聚合）
                sorted_data = sorted(data["data"], key=lambda x: x["date"])
                return sorted_data[-days:]
            return []
            
        except Exception as e:
            print(f"  [WARN] 抓取 {symbol} 法人資料失敗: {e}")
            return []


def fetch_all_stocks(
    symbols: Optional[List[str]] = None, 
    save_cache: bool = True
) -> Tuple[Dict[str, Dict], int]:
    """
    抓取所有股票的完整資料
    
    Args:
        symbols: 股票代碼列表，預設使用 DEFAULT_STOCKS
        save_cache: 是否儲存快取
        
    Returns:
        Tuple[Dict[str, Dict], int]: (股票資料字典, 實際成功抓取數)
    """
    if symbols is None:
        symbols = DEFAULT_STOCKS
    
    api = FinMindAPI()
    result = {}
    
    print(f"開始抓取 {len(symbols)} 檔股票資料...")
    
    for i, symbol in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] 抓取 {symbol}...", end=" ")
        
        # 抓取價格資料
        candles = api.get_stock_candles(symbol, days=40)
        if not candles or len(candles) < 20:
            print("[FAIL] 資料不足，跳過")
            continue
        
        # 抓取法人資料（原始資料，保留所有欄位）
        institutional = api.get_institutional_data(symbol, days=10)
        
        # 整理資料
        result[symbol] = {
            "symbol": symbol,
            "candles": candles,
            "institutional": institutional,
            "last_update": get_today_str()
        }
        
        print(f"[OK] (取得 {len(candles)} 天K線, {len(institutional)} 筆法人)")
    
    print(f"\n成功抓取 {len(result)} 檔股票")
    
    # 儲存快取
    if save_cache and result:
        cache_path = get_cache_path()
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"資料已快取: {cache_path}")
    
    return result, len(result)


def load_cached_data(date_str: Optional[str] = None) -> Optional[Dict[str, Dict]]:
    """
    載入快取資料
    
    Args:
        date_str: 日期字串，預設為今天
        
    Returns:
        Dict[str, Dict] 或 None
    """
    cache_path = get_cache_path(date_str)
    
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def get_cache_stats(date_str: Optional[str] = None) -> Optional[Dict]:
    """
    取得快取統計資訊
    
    Args:
        date_str: 日期字串
        
    Returns:
        Dict 包含 stocks_count, date 等資訊
    """
    data = load_cached_data(date_str)
    if data is None:
        return None
    
    return {
        "stocks_count": len(data),
        "date": date_str or get_today_str(),
        "symbols": list(data.keys())
    }


if __name__ == "__main__":
    # 測試抓取
    data, count = fetch_all_stocks(["2330", "2317", "2454"])
    print(f"\n測試完成，共 {count} 檔")
