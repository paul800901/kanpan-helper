"""
報告索引管理模組
負責維護 reports/index.json
"""
import json
import os
from typing import List, Dict, Optional
from datetime import datetime
from backend.config import REPORTS_DIR, get_today_str

INDEX_FILE = os.path.join(REPORTS_DIR, "index.json")


def load_index() -> Dict:
    """載入現有索引，若不存在則回傳空結構"""
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    return {
        "latest_date": None,
        "reports": []
    }


def save_index(index_data: Dict):
    """儲存索引檔案"""
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def scan_existing_reports() -> List[Dict]:
    """
    掃描 reports 目錄，找出所有報告檔案
    
    Returns:
        List[Dict]: 報告資訊列表，依日期排序（新到舊）
    """
    reports = []
    
    if not os.path.exists(REPORTS_DIR):
        return reports
    
    for filename in os.listdir(REPORTS_DIR):
        # 尋找完整版報告 (YYYY-MM-DD.json，不含 -lite)
        if filename.endswith(".json") and not filename.endswith("-lite.json"):
            if filename == "index.json":
                continue
            
            date_str = filename.replace(".json", "")
            
            # 驗證日期格式
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            
            lite_file = f"{date_str}-lite.json"
            full_path = os.path.join(REPORTS_DIR, filename)
            lite_path = os.path.join(REPORTS_DIR, lite_file)
            
            report_info = {
                "date": date_str,
                "lite": lite_file if os.path.exists(lite_path) else None,
                "full": filename if os.path.exists(full_path) else None,
                "has_lite": os.path.exists(lite_path),
                "has_full": os.path.exists(full_path),
                "created_at": datetime.fromtimestamp(
                    os.path.getmtime(full_path)
                ).isoformat() if os.path.exists(full_path) else None
            }
            reports.append(report_info)
    
    # 依日期排序（新到舊）
    reports.sort(key=lambda x: x["date"], reverse=True)
    
    return reports


def rebuild_index() -> Dict:
    """
    重建完整索引
    
    Returns:
        Dict: 索引資料
    """
    reports = scan_existing_reports()
    
    index_data = {
        "latest_date": reports[0]["date"] if reports else None,
        "total_reports": len(reports),
        "reports": reports
    }
    
    save_index(index_data)
    return index_data


def add_report_to_index(date_str: str, has_lite: bool = True, has_full: bool = True):
    """
    新增單一報告到索引（用於產生報告後立即更新）
    
    Args:
        date_str: 日期字串 YYYY-MM-DD
        has_lite: 是否有精簡版
        has_full: 是否有完整版
    """
    index_data = load_index()
    
    # 檢查是否已存在
    existing = [r for r in index_data["reports"] if r["date"] == date_str]
    
    report_info = {
        "date": date_str,
        "lite": f"{date_str}-lite.json" if has_lite else None,
        "full": f"{date_str}.json" if has_full else None,
        "has_lite": has_lite,
        "has_full": has_full,
        "created_at": datetime.now().isoformat()
    }
    
    if existing:
        # 更新現有項目
        idx = index_data["reports"].index(existing[0])
        index_data["reports"][idx] = report_info
    else:
        # 新增項目
        index_data["reports"].append(report_info)
        # 重新排序
        index_data["reports"].sort(key=lambda x: x["date"], reverse=True)
    
    # 更新最新日期
    if index_data["reports"]:
        index_data["latest_date"] = index_data["reports"][0]["date"]
    
    index_data["total_reports"] = len(index_data["reports"])
    
    save_index(index_data)
    return index_data


def get_report_info(date_str: Optional[str] = None) -> Optional[Dict]:
    """
    取得特定日期的報告資訊
    
    Args:
        date_str: 日期，None 表示最新
        
    Returns:
        Dict 或 None
    """
    index_data = load_index()
    
    if date_str is None:
        date_str = index_data.get("latest_date")
    
    if not date_str:
        return None
    
    for report in index_data.get("reports", []):
        if report["date"] == date_str:
            return report
    
    return None


def get_available_dates() -> List[str]:
    """取得所有可用日期列表（新到舊）"""
    index_data = load_index()
    return [r["date"] for r in index_data.get("reports", [])]


if __name__ == "__main__":
    # 測試：重建索引
    print("重建報告索引...")
    index = rebuild_index()
    print(f"找到 {index['total_reports']} 份報告")
    print(f"最新日期: {index['latest_date']}")
    
    # 顯示前 5 筆
    for report in index['reports'][:5]:
        print(f"  {report['date']}: lite={report['has_lite']}, full={report['has_full']}")
