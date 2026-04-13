"""技術指標計算模組"""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class StockIndicators:
    """股票技術指標資料類別"""
    symbol: str
    
    # 價格資料
    close_prices: List[float]
    high_prices: List[float]
    low_prices: List[float]
    volumes: List[int]
    dates: List[str]
    open_prices: Optional[List[float]] = None
    
    # 移動平均線
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    
    # 均量與量比
    volume_ma20: Optional[float] = None
    volume_ratio: Optional[float] = None  # 今日量 / 20日均量
    
    # KD
    k_value: Optional[float] = None
    d_value: Optional[float] = None
    
    # 法人資料
    institutional_signal: str = "資料不足"  # 連X買/連X賣/單日大買/單日大賣/無明顯動作/資料不足
    institutional_consecutive_days: int = 0  # 連續買超/賣超天數（正值為買，負值為賣）
    institutional_total_net: int = 0     # 總淨買賣超（可正可負）
    institutional_latest_net: int = 0    # 最近一日淨買賣超
    
    # 最新價格
    latest_close: Optional[float] = None
    latest_volume: Optional[int] = None
    
    # 資料充足性標記
    has_sufficient_data: bool = True
    data_issues: List[str] = None
    
    def __post_init__(self):
        """計算所有指標"""
        self.data_issues = []

        if not self.open_prices or len(self.open_prices) != len(self.close_prices):
            self.open_prices = list(self.close_prices)
        
        if self.close_prices:
            self.latest_close = self.close_prices[-1]
            self.latest_volume = self.volumes[-1] if self.volumes else None
            
            self._calc_ma()
            self._calc_volume_ma()
            self._calc_kd()
    
    def _calc_ma(self):
        """計算移動平均線"""
        if len(self.close_prices) >= 5:
            self.ma5 = round(sum(self.close_prices[-5:]) / 5, 2)
        else:
            self.data_issues.append("MA5資料不足")
            
        if len(self.close_prices) >= 20:
            self.ma20 = round(sum(self.close_prices[-20:]) / 20, 2)
        else:
            self.data_issues.append("MA20資料不足")
            self.has_sufficient_data = False
    
    def _calc_volume_ma(self):
        """計算 20 日均量與量比"""
        if len(self.volumes) >= 20:
            self.volume_ma20 = sum(self.volumes[-20:]) / 20
            # 計算量比
            if self.latest_volume and self.volume_ma20 > 0:
                self.volume_ratio = round(self.latest_volume / self.volume_ma20, 2)
        else:
            self.data_issues.append("均量資料不足")
    
    def _calc_kd(self, n: int = 9):
        """
        計算 KD 指標
        RSV = (今日收盤 - N日最低) / (N日最高 - N日最低) * 100
        K = 2/3 * 昨日K + 1/3 * RSV
        D = 2/3 * 昨日D + 1/3 * K
        """
        if len(self.close_prices) < n:
            self.data_issues.append("KD資料不足")
            return
        
        # 計算 RSV 序列
        rsv_list = []
        for i in range(n - 1, len(self.close_prices)):
            period_low = min(self.low_prices[i - n + 1:i + 1])
            period_high = max(self.high_prices[i - n + 1:i + 1])
            close = self.close_prices[i]
            
            if period_high == period_low:
                rsv = 50
            else:
                rsv = (close - period_low) / (period_high - period_low) * 100
            rsv_list.append(rsv)
        
        # 計算 K, D
        k = 50  # 初始值
        d = 50
        
        for rsv in rsv_list:
            k = (2/3) * k + (1/3) * rsv
            d = (2/3) * d + (1/3) * k
        
        self.k_value = round(k, 2)
        self.d_value = round(d, 2)
    
    def calc_institutional(self, institutional_data: List[Dict]):
        """
        計算法人買賣指標
        
        FinMind 資料格式：每天有多筆（外資、投信、自營商分開）
        需要按日期聚合後再計算連續天數
        
        Args:
            institutional_data: FinMind 法人買賣超資料原始列表
        """
        if not institutional_data:
            self.data_issues.append("法人資料不足")
            self.institutional_signal = "資料不足"
            return
        
        # Step 1: 按日期聚合，計算每日總買賣超
        daily_net = defaultdict(int)
        
        for record in institutional_data:
            date = record.get("date")
            if not date:
                continue
            
            buy = int(record.get("buy", 0) or 0)
            sell = int(record.get("sell", 0) or 0)
            net = buy - sell
            
            daily_net[date] += net
        
        if not daily_net:
            self.data_issues.append("法人資料無效")
            self.institutional_signal = "資料不足"
            return
        
        # Step 2: 按日期排序（新到舊）
        sorted_dates = sorted(daily_net.keys(), reverse=True)
        
        # Step 3: 計算連續買超/賣超天數
        consecutive_days = 0
        total_net = 0
        
        # 判斷方向（以最近一日為準）
        latest_net = daily_net[sorted_dates[0]]
        direction = "buy" if latest_net > 0 else "sell" if latest_net < 0 else "neutral"
        
        if direction == "neutral":
            self.institutional_signal = "無明顯動作"
            self.institutional_latest_net = latest_net
            self.institutional_total_net = sum(daily_net.values())
            return
        
        # 計算連續天數
        for date in sorted_dates:
            net = daily_net[date]
            
            if direction == "buy" and net > 0:
                consecutive_days += 1
                total_net += net
            elif direction == "sell" and net < 0:
                consecutive_days -= 1  # 用負數表示連賣
                total_net += net  # net 是負的，所以會累加負值
            else:
                break  # 連續中斷
        
        # Step 4: 設定結果
        self.institutional_latest_net = latest_net
        self.institutional_total_net = total_net
        self.institutional_consecutive_days = consecutive_days
        
        # 產生訊號文字
        abs_days = abs(consecutive_days)
        if abs_days >= 3:
            if consecutive_days > 0:
                self.institutional_signal = f"連{abs_days}買"
            else:
                self.institutional_signal = f"連{abs_days}賣"
        elif abs_days == 1:
            # 單日大買/大賣判斷（以 1000 張為門檻）
            if abs(latest_net) >= 1000:
                if latest_net > 0:
                    self.institutional_signal = "單日大買"
                else:
                    self.institutional_signal = "單日大賣"
            else:
                if latest_net > 0:
                    self.institutional_signal = "單日小買"
                else:
                    self.institutional_signal = "單日小賣"
        else:
            self.institutional_signal = "無明顯動作"
    
    def to_dict(self) -> Dict:
        """轉換為字典"""
        return {
            "symbol": self.symbol,
            "latest_close": self.latest_close,
            "latest_volume": self.latest_volume,
            "ma5": self.ma5,
            "ma20": self.ma20,
            "volume_ma20": self.volume_ma20,
            "volume_ratio": self.volume_ratio,
            "k_value": self.k_value,
            "d_value": self.d_value,
            "institutional_signal": self.institutional_signal,
            "institutional_consecutive_days": self.institutional_consecutive_days,
            "institutional_total_net": self.institutional_total_net,
            "institutional_latest_net": self.institutional_latest_net,
            "has_sufficient_data": self.has_sufficient_data,
            "data_issues": self.data_issues
        }


def calculate_indicators(stock_data: Dict) -> Optional[StockIndicators]:
    """
    從原始資料計算所有技術指標
    
    Args:
        stock_data: fetch_data 回傳的單檔股票資料
        
    Returns:
        StockIndicators 物件或 None
    """
    candles = stock_data.get("candles", [])
    
    if len(candles) < 20:
        return None
    
    # 提取資料
    try:
        open_prices = [float(c.get("open", c["close"])) for c in candles]
        close_prices = [float(c["close"]) for c in candles]
        high_prices = [float(c["max"]) for c in candles]
        low_prices = [float(c["min"]) for c in candles]
        volumes = [int(c["Trading_Volume"]) for c in candles]
        dates = [c["date"] for c in candles]
    except (KeyError, ValueError) as e:
        print(f"  [WARN] {stock_data['symbol']} 資料格式錯誤: {e}")
        return None
    
    # 建立指標物件
    indicators = StockIndicators(
        symbol=stock_data["symbol"],
        close_prices=close_prices,
        high_prices=high_prices,
        low_prices=low_prices,
        volumes=volumes,
        dates=dates,
        open_prices=open_prices
    )
    
    # 計算法人指標
    institutional_data = stock_data.get("institutional", [])
    indicators.calc_institutional(institutional_data)
    
    return indicators


def calculate_all_indicators(all_stock_data: Dict[str, Dict]) -> Dict[str, StockIndicators]:
    """
    計算所有股票的技術指標
    
    Args:
        all_stock_data: fetch_all_stocks 回傳的字典
        
    Returns:
        Dict[str, StockIndicators]
    """
    results = {}
    
    for symbol, data in all_stock_data.items():
        indicators = calculate_indicators(data)
        if indicators:
            results[symbol] = indicators
    
    return results


if __name__ == "__main__":
    # 測試法人聚合邏輯
    test_data = {
        "symbol": "2330",
        "candles": [
            {"date": "2024-01-01", "close": "500", "max": "510", "min": "490", "Trading_Volume": "10000"},
        ] * 20,
        "institutional": [
            # 同一天多筆（不同法人類別）
            {"date": "2024-01-05", "buy": "1000", "sell": "500"},  # 淨買 500
            {"date": "2024-01-05", "buy": "800", "sell": "200"},   # 淨買 600，當日總計 1100
            {"date": "2024-01-04", "buy": "500", "sell": "300"},  # 淨買 200
            {"date": "2024-01-03", "buy": "600", "sell": "100"},  # 淨買 500
        ]
    }
    
    ind = calculate_indicators(test_data)
    if ind:
        print("法人測試結果:")
        print(f"  訊號: {ind.institutional_signal}")
        print(f"  連續天數: {ind.institutional_consecutive_days}")
        print(f"  總淨買超: {ind.institutional_total_net}")
        print(f"  最近一日: {ind.institutional_latest_net}")
