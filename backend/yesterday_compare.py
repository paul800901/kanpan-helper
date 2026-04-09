"""v6 前次報告比較模組

從 reports/ 目錄中找出最近一份可用報告，提供與今日數據的比較功能。
注意：不是單純找 "昨天"，而是找 "小於今天日期的最近一份報告"。
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from backend.config import get_report_path, get_taiwan_now


def parse_date_from_filename(filename: str) -> Optional[str]:
    """從檔名解析日期 (YYYY-MM-DD)"""
    # 匹配 YYYY-MM-DD 格式
    match = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    return None


def list_available_report_dates() -> List[Tuple[str, datetime]]:
    """
    列出 reports/ 目錄中所有可用報告的日期
    
    Returns:
        List[Tuple[日期字串, 日期物件]]，按日期新到舊排序
    """
    reports_dir = os.path.dirname(get_report_path())
    
    if not os.path.exists(reports_dir):
        return []
    
    dates = []
    seen = set()
    
    for filename in os.listdir(reports_dir):
        # 只考慮 -lite.json 或 -ai.json 結尾的報告檔
        if not (filename.endswith('-lite.json') or filename.endswith('-ai.json')):
            continue
        
        date_str = parse_date_from_filename(filename)
        if not date_str or date_str in seen:
            continue
        
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            dates.append((date_str, date_obj))
            seen.add(date_str)
        except ValueError:
            continue
    
    # 按日期新到舊排序
    dates.sort(key=lambda x: x[1], reverse=True)
    return dates


def find_previous_report_date(today_str: str) -> Optional[str]:
    """
    找出小於今天日期的最近一份可用報告日期
    
    Args:
        today_str: 今天日期 (YYYY-MM-DD)
        
    Returns:
        前次報告日期，或 None（如果找不到）
    """
    try:
        today = datetime.strptime(today_str, "%Y-%m-%d")
    except ValueError:
        print(f"[ERROR] 無效的日期格式: {today_str}")
        return None
    
    available_dates = list_available_report_dates()
    
    for date_str, date_obj in available_dates:
        if date_obj < today:
            return date_str
    
    return None


def load_report_by_date(date_str: str, prefer_ai: bool = True) -> Optional[Dict]:
    """
    載入指定日期的報告
    
    Args:
        date_str: 日期字串 (YYYY-MM-DD)
        prefer_ai: 是否優先嘗試 AI 版本報告
        
    Returns:
        報告字典或 None
    """
    reports_dir = os.path.dirname(get_report_path())
    
    if prefer_ai:
        # 先嘗試 AI 版本
        ai_path = os.path.join(reports_dir, f"{date_str}-ai.json")
        if os.path.exists(ai_path):
            try:
                with open(ai_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARN] 無法載入 AI 報告 {date_str}-ai.json: {e}")
        
        # 再嘗試 lite 版本
        lite_path = os.path.join(reports_dir, f"{date_str}-lite.json")
        if os.path.exists(lite_path):
            try:
                with open(lite_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARN] 無法載入 lite 報告 {date_str}-lite.json: {e}")
    else:
        # 只嘗試 lite 版本
        lite_path = os.path.join(reports_dir, f"{date_str}-lite.json")
        if os.path.exists(lite_path):
            try:
                with open(lite_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARN] 無法載入 lite 報告 {date_str}-lite.json: {e}")
    
    return None


def load_yesterday_report(today_str: Optional[str] = None) -> Optional[Dict]:
    """
    載入前次報告（小於今天日期的最近一份可用報告）
    
    注意：不是單純找 "昨天"，而是從 reports/ 目錄找最近可用報告。
    這能處理週末、連假、或中間幾天沒產報告的情況。
    
    Args:
        today_str: 今天日期，預設從台灣時區取得
        
    Returns:
        前次報告字典，或 None（如果找不到任何前次報告）
    """
    if today_str is None:
        from backend.config import get_today_str
        today_str = get_today_str()
    
    previous_date = find_previous_report_date(today_str)
    
    if not previous_date:
        print(f"[INFO] 找不到 {today_str} 之前的任何可用報告")
        return None
    
    print(f"[INFO] 找到前次報告日期: {previous_date}")
    
    report = load_report_by_date(previous_date, prefer_ai=True)
    
    if report:
        print(f"[OK] 成功載入 {previous_date} 的報告")
        return report
    else:
        print(f"[WARN] 找不到 {previous_date} 的報告檔案")
        return None


def compare_stock_changes(today_stock: Dict, yesterday_stock: Optional[Dict]) -> Dict:
    """
    比較單一股票與前次報告的變化
    
    Args:
        today_stock: 今日股票資料
        yesterday_stock: 前次報告中的股票資料，None 表示新入榜
        
    Returns:
        變化資訊字典
    """
    if not yesterday_stock:
        return {
            "score_change": 0,
            "rank_change": 0,
            "is_new": True,
            "summary": "新入榜"
        }
    
    today_score = today_stock.get("score", 0)
    yesterday_score = yesterday_stock.get("score", 0)
    today_rank = today_stock.get("rank", 999)
    yesterday_rank = yesterday_stock.get("rank", 999)
    
    score_change = today_score - yesterday_score
    rank_change = yesterday_rank - today_rank  # 排名上升為正數
    
    # 產生變化摘要
    if score_change > 5:
        summary = f"分數上升{score_change}分，轉強"
    elif score_change < -5:
        summary = f"分數下降{abs(score_change)}分，轉弱"
    elif rank_change >= 3:
        summary = f"排名上升{rank_change}名"
    elif rank_change <= -3:
        summary = f"排名下降{abs(rank_change)}名"
    else:
        summary = "與前次持平"
    
    return {
        "score_change": score_change,
        "rank_change": rank_change,
        "is_new": False,
        "summary": summary
    }


def get_newcomers_and_dropout(today_stocks: List[Dict], yesterday_stocks: List[Dict]) -> Dict:
    """取得今日新入榜與前次落榜股票"""
    today_symbols = {s["symbol"] for s in today_stocks}
    yesterday_symbols = {s["symbol"] for s in yesterday_stocks}
    
    newcomers = [s for s in today_stocks if s["symbol"] not in yesterday_symbols]
    dropouts = [s for s in yesterday_stocks if s["symbol"] not in today_symbols]
    
    return {
        "newcomers": [{"symbol": s["symbol"], "name": s["name"], "score": s["score"]} for s in newcomers],
        "dropouts": [{"symbol": s["symbol"], "name": s["name"], "score": s["score"]} for s in dropouts]
    }


# 測試
if __name__ == "__main__":
    print("測試前次報告查找功能...")
    
    available = list_available_report_dates()
    print(f"\n找到 {len(available)} 份可用報告:")
    for date_str, date_obj in available[:5]:
        print(f"  - {date_str}")
    
    from backend.config import get_today_str
    today = get_today_str()
    print(f"\n今天日期: {today}")
    
    previous = find_previous_report_date(today)
    if previous:
        print(f"前次報告日期: {previous}")
    else:
        print("找不到前次報告")
    
    report = load_yesterday_report()
    if report:
        print(f"\n成功載入報告，日期: {report.get('date')}")
        stocks = report.get('stocks', [])
        print(f"包含 {len(stocks)} 檔股票")
    else:
        print("\n無法載入前次報告")
