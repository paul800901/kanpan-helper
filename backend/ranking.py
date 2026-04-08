"""排名與打分模組"""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from backend.calc_indicators import StockIndicators
from backend.config import SCORE_WEIGHTS, INSTITUTIONAL_DAYS


@dataclass
class StockScore:
    """股票評分結果"""
    symbol: str
    score: int
    trend: str        # 偏多/偏空/盤整/資料不足
    volume: str       # 放量/縮量/正常/資料不足
    institutional: str  # 連X買/連X賣/單日大買/單日大賣/無明顯動作/資料不足
    kd_state: str     # 高檔/低檔/一般/資料不足
    
    # 詳細分數
    trend_score: int
    volume_score: int
    institutional_score: int
    kd_score: int
    
    # 原始指標
    latest_close: Optional[float] = None
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    k_value: Optional[float] = None
    d_value: Optional[float] = None
    volume_ratio: Optional[float] = None  # 今日量 / 20日均量
    institutional_consecutive_days: int = 0
    institutional_total_net: int = 0
    has_sufficient_data: bool = True
    data_issues: List[str] = None
    
    # 排名資訊（由 rank_stocks 設定）
    rank: int = 0
    rank_percentile: float = 0.0
    total_stocks: int = 0


def evaluate_trend(indicators: StockIndicators) -> Tuple[str, int]:
    """
    評估趨勢
    
    Returns:
        (趨勢描述, 分數 0-30)
    """
    # 檢查資料充足性
    if not indicators.has_sufficient_data or indicators.ma20 is None:
        return "資料不足", 0
    
    close = indicators.latest_close
    ma5 = indicators.ma5
    ma20 = indicators.ma20
    
    if close is None or ma5 is None:
        return "資料不足", 0
    
    score = 0
    
    # 多頭排列：收盤 > MA5 > MA20
    if close > ma5 > ma20:
        trend = "偏多"
        score = 30
    # 站上均線
    elif close > ma5 and close > ma20:
        trend = "偏多"
        score = 25
    # MA5 上彎
    elif ma5 > ma20:
        trend = "偏多"
        score = 20
    # 空頭排列
    elif close < ma5 < ma20:
        trend = "偏空"
        score = 5
    # 跌破均線
    elif close < ma5 and close < ma20:
        trend = "偏空"
        score = 8
    else:
        trend = "盤整"
        score = 15
    
    return trend, score


def evaluate_volume(indicators: StockIndicators) -> Tuple[str, int, Optional[float]]:
    """
    評估成交量
    
    Returns:
        (成交量描述, 分數 0-25, volume_ratio)
    """
    if indicators.volume_ratio is None:
        return "資料不足", 12, None
    
    ratio = indicators.volume_ratio
    
    if ratio >= 2.0:
        return "爆量", 20, ratio  # 爆量需觀察，給中高分
    elif ratio >= 1.5:
        return "放量", 25, ratio   # 健康放量
    elif ratio >= 1.2:
        return "微增", 22, ratio
    elif ratio >= 0.8:
        return "正常", 15, ratio
    elif ratio >= 0.5:
        return "縮量", 10, ratio
    else:
        return "窒息量", 5, ratio


def evaluate_institutional(indicators: StockIndicators) -> Tuple[str, int]:
    """
    評估法人動向
    
    根據 institutional_signal 判斷分數
    
    Returns:
        (法人描述, 分數 0-25)
    """
    signal = indicators.institutional_signal
    days = indicators.institutional_consecutive_days
    
    if signal == "資料不足":
        return "資料不足", 12
    
    # 連買（days 為正）
    if days >= 5:
        return f"連{days}買", 25
    elif days == 4:
        return "連4買", 23
    elif days == 3:
        return "連3買", 20
    elif days == 2:
        return "連2買", 15
    elif days == 1:
        return "連1買", 12
    
    # 連賣（days 為負）
    elif days <= -5:
        return f"連{abs(days)}賣", 5
    elif days == -4:
        return "連4賣", 6
    elif days == -3:
        return "連3賣", 7
    elif days == -2:
        return "連2賣", 8
    elif days == -1:
        return "連1賣", 10
    
    # 單日大買/大賣
    elif signal == "單日大買":
        return "單日大買", 18
    elif signal == "單日大賣":
        return "單日大賣", 8
    elif signal == "單日小買":
        return "單日小買", 14
    elif signal == "單日小賣":
        return "單日小賣", 11
    
    else:
        return "無明顯動作", 12


def evaluate_kd(indicators: StockIndicators) -> Tuple[str, int]:
    """
    評估 KD 狀態
    
    Returns:
        (KD描述, 分數 0-20)
    """
    k = indicators.k_value
    d = indicators.d_value
    
    if k is None or d is None:
        return "資料不足", 10
    
    # KD 黃金交叉 (K 上穿 D)
    # 這裡簡化處理，只用當前值判斷
    
    if k > 80 and d > 80:
        return "高檔鈍化", 12  # 可能過熱
    elif k < 20 and d < 20:
        return "低檔鈍化", 18  # 可能反彈
    elif k > d:
        if k < 50:
            return "低檔金叉", 20  # 最佳狀態
        else:
            return "多頭延續", 18
    else:
        if k > 50:
            return "高檔死叉", 10  # 危險
        else:
            return "空頭延續", 8


def score_stock(indicators: StockIndicators) -> StockScore:
    """
    對單檔股票進行完整評分
    
    Args:
        indicators: 技術指標物件
        
    Returns:
        StockScore 評分結果
    """
    trend, trend_score = evaluate_trend(indicators)
    volume, volume_score, volume_ratio = evaluate_volume(indicators)
    institutional, inst_score = evaluate_institutional(indicators)
    kd_state, kd_score = evaluate_kd(indicators)
    
    total_score = trend_score + volume_score + inst_score + kd_score
    
    return StockScore(
        symbol=indicators.symbol,
        score=total_score,
        trend=trend,
        volume=volume,
        institutional=institutional,
        kd_state=kd_state,
        trend_score=trend_score,
        volume_score=volume_score,
        institutional_score=inst_score,
        kd_score=kd_score,
        latest_close=indicators.latest_close,
        ma5=indicators.ma5,
        ma20=indicators.ma20,
        k_value=indicators.k_value,
        d_value=indicators.d_value,
        volume_ratio=volume_ratio,
        institutional_consecutive_days=indicators.institutional_consecutive_days,
        institutional_total_net=indicators.institutional_total_net,
        has_sufficient_data=indicators.has_sufficient_data,
        data_issues=indicators.data_issues
    )


def rank_stocks(all_indicators: Dict[str, StockIndicators], top_n: int = 5) -> List[StockScore]:
    """
    對所有股票評分並取 Top N
    
    Args:
        all_indicators: 所有股票的技術指標
        top_n: 取前 N 名
        
    Returns:
        List[StockScore] 排序後的前 N 名（已設定 rank 屬性）
    """
    scores = []
    
    for symbol, indicators in all_indicators.items():
        score = score_stock(indicators)
        scores.append(score)
    
    # 依分數排序（高到低）
    scores.sort(key=lambda x: x.score, reverse=True)
    
    # 設定排名資訊
    total_count = len(scores)
    for i, score in enumerate(scores):
        # 使用 object.__setattr__ 因為 dataclass 可能為 frozen
        object.__setattr__(score, 'rank', i + 1)
        object.__setattr__(score, 'rank_percentile', round((total_count - i) / total_count * 100, 1))
        object.__setattr__(score, 'total_stocks', total_count)
    
    return scores[:top_n]


def scores_to_dict_list(scores: List[StockScore]) -> List[Dict]:
    """將評分結果轉為字典列表"""
    return [
        {
            "symbol": s.symbol,
            "score": s.score,
            "trend": s.trend,
            "volume": s.volume,
            "institutional": s.institutional,
            "kd_state": s.kd_state,
            "detail_scores": {
                "trend": s.trend_score,
                "volume": s.volume_score,
                "institutional": s.institutional_score,
                "kd": s.kd_score
            },
            "indicators": {
                "close": s.latest_close,
                "ma5": s.ma5,
                "ma20": s.ma20,
                "k": s.k_value,
                "d": s.d_value,
                "volume_ratio": s.volume_ratio
            }
        }
        for s in scores
    ]


if __name__ == "__main__":
    # 測試
    from backend.calc_indicators import StockIndicators
    
    test_ind = StockIndicators(
        symbol="2330",
        close_prices=[500, 505, 510, 515, 520, 525, 530, 528, 535, 540] * 4,
        high_prices=[510, 515, 520, 525, 530, 535, 540, 538, 545, 550] * 4,
        low_prices=[490, 495, 500, 505, 510, 515, 520, 518, 525, 530] * 4,
        volumes=[10000, 12000, 11000, 15000, 13000, 14000, 16000, 12000, 15000, 18000] * 4,
        dates=[]
    )
    # 模擬法人連3買
    test_ind.institutional_signal = "連3買"
    test_ind.institutional_consecutive_days = 3
    test_ind.institutional_total_net = 5000
    
    score = score_stock(test_ind)
    print(f"{score.symbol}: {score.score}分")
    print(f"  趨勢: {score.trend} ({score.trend_score})")
    print(f"  成交量: {score.volume} ({score.volume_score}), 量比: {score.volume_ratio}")
    print(f"  法人: {score.institutional} ({score.institutional_score})")
    print(f"  KD: {score.kd_state} ({score.kd_score})")
