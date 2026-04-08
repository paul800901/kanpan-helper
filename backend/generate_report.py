"""報告生成模組 v2 - 實用化版本"""
import json
import os
from typing import List, Dict, Optional
from datetime import datetime
from backend.ranking import StockScore
from backend.config import get_today_str, get_report_path, get_taiwan_now

# 股票名稱對照表（常用股票）
STOCK_NAMES = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2412": "中華電",
    "2881": "富邦金", "2882": "國泰金", "2308": "台達電", "2303": "聯電",
    "3711": "日月光投控", "2891": "中信金", "2886": "兆豐金", "2884": "玉山金",
    "1216": "統一", "2885": "元大金", "2357": "華碩", "2382": "廣達",
    "2892": "第一金", "5880": "合庫金", "2880": "華南金", "2327": "國巨",
    "3034": "聯詠", "2883": "開發金", "2002": "中鋼", "3008": "大立光",
    "2890": "永豐金", "1101": "台泥", "3045": "台灣大", "2395": "研華",
    "5876": "上海商銀", "1326": "台化", "4904": "遠傳", "5871": "中租-KY",
    "2301": "光寶科", "2912": "統一超", "1402": "遠東新", "2887": "台新金",
    "1102": "亞泥", "2603": "長榮", "2408": "南亞科", "2615": "萬海",
    "2609": "陽明", "2610": "華航", "2618": "長榮航", "2606": "裕民",
    "2617": "台航", "1605": "華新", "2207": "和泰車", "1229": "聯華",
    "2634": "漢翔", "2363": "矽統"
}


def get_stock_name(symbol: str) -> str:
    """取得股票名稱"""
    return STOCK_NAMES.get(symbol, f"股票{symbol}")


def get_score_grade(score: int) -> str:
    """
    分數轉為等級
    75+ = A, 60-74 = B, 45-59 = C, <45 = D
    """
    if score >= 75:
        return "A"
    elif score >= 60:
        return "B"
    elif score >= 45:
        return "C"
    else:
        return "D"


def get_score_label(score: int) -> str:
    """
    分數轉為標籤
    75+ = 強, 60-74 = 中等, 45-59 = 普通, <45 = 弱
    """
    if score >= 75:
        return "強"
    elif score >= 60:
        return "中等"
    elif score >= 45:
        return "普通"
    else:
        return "弱"


def determine_action_bias(score: StockScore) -> str:
    """
    決定行動建議偏見
    
    規則：
    - 分數低於 50 或資料不足 → 暫不考慮
    - 分數 50-59 且有風險疑慮 → 偏保守
    - 分數 60+ 但資料不足或有明顯風險 → 觀察
    - 分數 60+ 且資料充足 → 可留意
    - 分數 75+ 且條件良好 → 可留意
    """
    # 資料不足降級邏輯
    if not score.has_sufficient_data:
        if score.score >= 60:
            return "觀察"
        else:
            return "暫不考慮"
    
    # 分數分級
    if score.score >= 75:
        # 高分但法人連賣或 KD 高檔 → 觀察
        if score.institutional_consecutive_days <= -2 or score.kd_state == "高檔鈍化":
            return "觀察"
        return "可留意"
    
    elif score.score >= 60:
        # 中等分數但有風險 → 觀察
        if score.trend == "偏空" or score.volume == "窒息量":
            return "觀察"
        return "可留意"
    
    elif score.score >= 50:
        # 偏低分數
        if score.trend == "偏多" and score.institutional_consecutive_days > 0:
            return "觀察"
        return "偏保守"
    
    else:
        return "暫不考慮"


def generate_one_line_summary(score: StockScore) -> str:
    """
    產生一句話摘要，15-30字內
    """
    name = get_stock_name(score.symbol)
    
    # 資料不足優先處理
    if not score.has_sufficient_data:
        return f"{name}技術資料不足，建議暫緩觀察。"
    
    parts = []
    
    # 趨勢
    if score.trend == "偏多":
        parts.append("短線偏強")
    elif score.trend == "偏空":
        parts.append("短線偏弱")
    else:
        parts.append("盤整格局")
    
    # 法人
    if score.institutional_consecutive_days >= 3:
        parts.append("法人買超")
    elif score.institutional_consecutive_days <= -2:
        parts.append("法人調節")
    
    # 量能
    if score.volume_ratio is not None:
        if score.volume_ratio < 0.6:
            parts.append("量能不足")
        elif score.volume_ratio > 1.5:
            parts.append("量能增溫")
    
    # KD
    if score.kd_state == "低檔金叉":
        parts.append("剛轉強")
    elif score.kd_state == "高檔鈍化":
        parts.append("高檔震盪")
    
    # 結論
    bias = determine_action_bias(score)
    if bias == "可留意":
        suffix = "可留意"
    elif bias == "觀察":
        suffix = "先觀察"
    elif bias == "偏保守":
        suffix = "偏保守"
    else:
        suffix = "暫不考慮"
    
    summary = "，".join(parts)
    result = f"{summary}，{suffix}。"
    
    # 確保在30字內
    if len(result) > 30:
        result = result[:29] + "..."
    
    return result


def generate_plain_reasons(score: StockScore) -> List[str]:
    """
    產生白話理由，給一般人看
    """
    reasons = []
    
    # 資料不足
    if not score.has_sufficient_data:
        reasons.append("部分技術資料不足，分析結果僅供參考")
        if score.score >= 60:
            reasons.append("即使分數不差，仍建議等資料完整再評估")
        return reasons
    
    # 趨勢（人話版）
    if score.trend == "偏多":
        if score.latest_close and score.ma5 and score.ma20:
            if score.latest_close > score.ma5 > score.ma20:
                reasons.append("股價站在短期與中期均線之上，短線偏強")
            else:
                reasons.append("股價站上短期均線，趨勢轉佳")
    elif score.trend == "偏空":
        reasons.append("股價處於相對弱勢，尚未站穩均線")
    else:
        reasons.append("股價在區間內盤整，方向待觀察")
    
    # 成交量（人話版，使用 volume_ratio）
    if score.volume_ratio is not None:
        ratio_pct = score.volume_ratio * 100
        if score.volume == "放量":
            reasons.append(f"成交量比平常多{ratio_pct:.0f}%，買盤有進場")
        elif score.volume == "爆量":
            reasons.append(f"成交量大增到{ratio_pct:.0f}%，市場關注度高")
        elif score.volume == "縮量":
            reasons.append(f"成交量只剩平常的{ratio_pct:.0f}%，觀望氣氛濃")
        elif score.volume == "窒息量":
            reasons.append(f"成交量縮到{ratio_pct:.0f}%，賣壓也減輕")
        else:
            reasons.append(f"成交量維持正常水準({ratio_pct:.0f}%)")
    
    # 法人（人話版）
    if score.institutional_consecutive_days >= 3:
        reasons.append(f"法人連續{score.institutional_consecutive_days}天買超，籌碼面有支撐")
    elif score.institutional_consecutive_days >= 1:
        reasons.append(f"法人近{score.institutional_consecutive_days}天偏買方")
    elif score.institutional_consecutive_days <= -3:
        reasons.append(f"法人連續{abs(score.institutional_consecutive_days)}天賣超，籌碼面承壓")
    elif score.institutional_consecutive_days <= -1:
        reasons.append(f"法人近{abs(score.institutional_consecutive_days)}天偏調節")
    elif score.institutional == "單日大買":
        reasons.append("法人單日大舉買超，態度積極")
    
    # KD（人話版）
    if score.kd_state == "低檔金叉":
        reasons.append("技術指標剛從低檔翻強，動能轉強")
    elif score.kd_state == "多頭延續":
        reasons.append("技術指標維持強勢，偏多格局")
    elif score.kd_state == "低檔鈍化":
        reasons.append("技術指標在低檔，跌深可能有反彈")
    
    return reasons if reasons else ["綜合評分進入前段"]


def generate_plain_risks(score: StockScore) -> List[str]:
    """
    產生白話風險，給一般人看
    """
    risks = []
    
    # 資料不足風險
    if not score.has_sufficient_data:
        risks.append("技術資料不完整，分析可能有偏差")
    
    # 趨勢風險
    if score.trend == "偏空":
        risks.append("股價尚未站穩，趨勢還在空方")
    elif score.trend == "盤整":
        risks.append("股價在盤整，突破方向不明")
    
    # 量能風險
    if score.volume_ratio is not None and score.volume_ratio < 0.6:
        risks.append("成交量太少，漲上去可能沒人追") 
    elif score.volume == "爆量":
        risks.append("爆出大量，要留意是否有人出貨")
    
    # 法人風險
    if score.institutional_consecutive_days <= -2:
        risks.append("法人持續賣超，籌碼面壓力大")
    
    # KD 風險
    if score.kd_state == "高檔鈍化":
        risks.append("技術指標在高檔，短線可能震盪")
    elif score.kd_state == "高檔死叉":
        risks.append("技術指標剛轉弱，留意是否走勢變差")
    elif score.kd_state == "空頭延續":
        risks.append("技術指標偏弱，還沒翻強")
    
    # 預設風險
    if not risks:
        risks.append("大盤若有系統性風險，個股也會受影響")
    
    risks.append("以上僅供參考，不構成投資建議")
    
    return risks


def generate_stock_report_v2(score: StockScore) -> Dict:
    """
    產生單一股票的 v2 格式報告
    """
    return {
        "symbol": score.symbol,
        "name": get_stock_name(score.symbol),
        "rank": score.rank,
        "rank_note": f"本日第 {score.rank} 名",
        "score": score.score,
        "score_grade": get_score_grade(score.score),
        "score_label": get_score_label(score.score),
        "action_bias": determine_action_bias(score),
        "one_line_summary": generate_one_line_summary(score),
        "plain_reasons": generate_plain_reasons(score),
        "plain_risks": generate_plain_risks(score),
        "indicators": {
            "close": score.latest_close,
            "ma5": score.ma5,
            "ma20": score.ma20,
            "k": score.k_value,
            "d": score.d_value,
            "volume_ratio": score.volume_ratio
        },
        "signals": {
            "trend": score.trend,
            "volume": score.volume,
            "institutional": score.institutional,
            "kd": score.kd_state
        },
        "institutional_detail": {
            "consecutive_days": score.institutional_consecutive_days,
            "total_net": score.institutional_total_net
        } if score.institutional not in ["資料不足", "無明顯動作"] else None,
        "data_quality": {
            "has_sufficient_data": score.has_sufficient_data,
            "issues": score.data_issues
        }
    }


def generate_report_summary(all_scores: List[StockScore]) -> Dict:
    """
    產生報告頂層摘要區
    """
    if not all_scores:
        return {
            "market_overview": "無法產生摘要",
            "top_picks": [],
            "watchlist": [],
            "avoid_list": []
        }
    
    # 分類股票
    top_picks = []
    watchlist = []
    avoid_list = []
    
    for score in all_scores:
        bias = determine_action_bias(score)
        stock_info = {
            "symbol": score.symbol,
            "name": get_stock_name(score.symbol),
            "score": score.score,
            "action_bias": bias
        }
        
        if bias == "可留意":
            top_picks.append(stock_info)
        elif bias == "觀察":
            watchlist.append(stock_info)
        elif bias in ["偏保守", "暫不考慮"]:
            avoid_list.append(stock_info)
    
    # 市場概述
    avg_score = sum(s.score for s in all_scores) / len(all_scores)
    strong_count = len([s for s in all_scores if s.score >= 75])
    weak_count = len([s for s in all_scores if s.score < 50])
    
    if avg_score >= 65:
        market_overview = f"本日平均強度中等偏強({avg_score:.0f}分)，強勢股{strong_count}檔"
    elif avg_score >= 50:
        market_overview = f"本日平均強度普通({avg_score:.0f}分)，個股表現分歧"
    else:
        market_overview = f"本日平均強度偏弱({avg_score:.0f}分)，弱勢股{weak_count}檔"
    
    return {
        "market_overview": market_overview,
        "top_picks": top_picks[:5],  # 最多5檔
        "watchlist": watchlist[:5],
        "avoid_list": avoid_list[:5]
    }


def generate_report_v2(
    top_stocks: List[StockScore],
    date_str: Optional[str] = None,
    total_stocks_requested: int = 0,
    total_stocks_analyzed: int = 0
) -> Dict:
    """
    產生 v2 完整報告
    """
    if date_str is None:
        date_str = get_today_str()
    
    # 產生每檔股票報告
    stocks_data = [generate_stock_report_v2(score) for score in top_stocks]
    
    # 產生摘要區
    summary = generate_report_summary(top_stocks)
    
    report = {
        "report_version": "v2",
        "date": date_str,
        "generated_at": get_taiwan_now().isoformat(),
        "total_stocks_requested": total_stocks_requested,
        "total_stocks_analyzed": total_stocks_analyzed,
        "top_n": len(top_stocks),
        "summary": summary,
        "stocks": stocks_data,
        "disclaimer": "本報告僅供參考，不構成任何投資建議或買賣建議。投資人應自行判斷並承擔風險。"
    }
    
    return report


def generate_lite_report(full_report: Dict) -> Dict:
    """
    產生精簡版報告，只保留前端顯示需要的欄位
    """
    lite_stocks = []
    
    for stock in full_report.get("stocks", []):
        lite_stock = {
            "symbol": stock["symbol"],
            "name": stock["name"],
            "rank": stock["rank"],
            "score": stock["score"],
            "score_grade": stock["score_grade"],
            "score_label": stock["score_label"],
            "action_bias": stock["action_bias"],
            "one_line_summary": stock["one_line_summary"],
            "plain_reasons": stock["plain_reasons"][:2] if stock["plain_reasons"] else [],  # 最多2條
            "plain_risks": stock["plain_risks"][:2] if stock["plain_risks"] else [],
            "indicators": {
                "close": stock["indicators"]["close"],
                "volume_ratio": stock["indicators"]["volume_ratio"]
            },
            "signals": {
                "trend": stock["signals"]["trend"],
                "institutional": stock["signals"]["institutional"]
            }
        }
        lite_stocks.append(lite_stock)
    
    return {
        "report_version": "v2-lite",
        "date": full_report["date"],
        "top_n": full_report["top_n"],
        "summary": {
            "market_overview": full_report["summary"]["market_overview"],
            "top_picks": [{"symbol": s["symbol"], "name": s["name"]} for s in full_report["summary"]["top_picks"]]
        },
        "stocks": lite_stocks
    }


def save_report(report: Dict, date_str: Optional[str] = None, suffix: str = "") -> str:
    """
    儲存報告到檔案
    
    Args:
        report: 報告字典
        date_str: 日期字串
        suffix: 檔名後綴（如 "-lite"）
        
    Returns:
        儲存的檔案路徑
    """
    if date_str is None:
        date_str = get_today_str()
    
    filename = f"{date_str}{suffix}.json"
    file_path = os.path.join(os.path.dirname(get_report_path()), filename)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    return file_path


def save_both_reports(
    full_report: Dict,
    lite_report: Dict,
    date_str: Optional[str] = None
) -> tuple:
    """
    儲存完整版與精簡版報告，並更新索引
    
    Returns:
        (完整版路徑, 精簡版路徑)
    """
    full_path = save_report(full_report, date_str, suffix="")
    lite_path = save_report(lite_report, date_str, suffix="-lite")
    
    # 更新索引
    try:
        from backend.report_index import add_report_to_index
        actual_date = date_str or full_report.get("date", get_today_str())
        add_report_to_index(actual_date, has_lite=True, has_full=True)
    except Exception as e:
        print(f"[WARN] 更新索引失敗: {e}")
    
    return full_path, lite_path


def load_report(date_str: Optional[str] = None, lite: bool = False) -> Optional[Dict]:
    """
    載入報告
    
    Args:
        date_str: 日期字串，預設為今天
        lite: 是否載入精簡版
        
    Returns:
        報告字典或 None
    """
    suffix = "-lite" if lite else ""
    if date_str is None:
        date_str = get_today_str()
    
    filename = f"{date_str}{suffix}.json"
    file_path = os.path.join(os.path.dirname(get_report_path()), filename)
    
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


if __name__ == "__main__":
    # 測試
    from backend.ranking import StockScore
    
    test_scores = [
        StockScore(
            symbol="2330",
            score=78,
            trend="偏多",
            volume="放量",
            institutional="連3買",
            kd_state="低檔金叉",
            trend_score=28,
            volume_score=25,
            institutional_score=20,
            kd_score=5,
            latest_close=580.0,
            ma5=575.0,
            ma20=560.0,
            k_value=45.2,
            d_value=38.5,
            volume_ratio=1.55,
            institutional_consecutive_days=3,
            institutional_total_net=5000,
            has_sufficient_data=True,
            rank=1,
            rank_percentile=95.0,
            total_stocks=50
        ),
        StockScore(
            symbol="2317",
            score=52,
            trend="盤整",
            volume="正常",
            institutional="無明顯動作",
            kd_state="盤整",
            trend_score=15,
            volume_score=15,
            institutional_score=12,
            kd_score=10,
            latest_close=105.0,
            ma5=104.0,
            ma20=106.0,
            k_value=52.0,
            d_value=50.0,
            volume_ratio=0.95,
            institutional_consecutive_days=0,
            institutional_total_net=0,
            has_sufficient_data=True,
            rank=2,
            rank_percentile=90.0,
            total_stocks=50
        )
    ]
    
    report = generate_report_v2(test_scores, total_stocks_requested=50, total_stocks_analyzed=48)
    lite = generate_lite_report(report)
    
    print("=== 完整版報告 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n=== 精簡版報告 ===")
    print(json.dumps(lite, ensure_ascii=False, indent=2))
