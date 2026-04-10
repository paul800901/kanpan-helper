"""
報告索引管理模組
負責維護 reports/index.json

v5 更新：新增原子化安全更新機制，確保 index.json 不會因中間失敗而損毀
"""
import json
import os
import shutil
from typing import List, Dict, Optional
from datetime import datetime
from backend.config import REPORTS_DIR, get_today_str

INDEX_FILE = os.path.join(REPORTS_DIR, "index.json")
INDEX_TEMP_FILE = os.path.join(REPORTS_DIR, "index.json.tmp")
INDEX_BACKUP_FILE = os.path.join(REPORTS_DIR, "index.json.bak")


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
        "total_reports": 0,
        "reports": []
    }


def save_index(index_data: Dict):
    """儲存索引檔案（內部使用，不建議外部直接呼叫）"""
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
            if filename == "index.json" or filename == "index.json.tmp":
                continue
            
            date_str = filename.replace(".json", "")
            
            # 驗證日期格式
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            
            lite_file = f"{date_str}-lite.json"
            universe_file = f"{date_str}-universe.json"
            full_path = os.path.join(REPORTS_DIR, filename)
            lite_path = os.path.join(REPORTS_DIR, lite_file)
            universe_path = os.path.join(REPORTS_DIR, universe_file)

            report_info = {
                "date": date_str,
                "lite": lite_file if os.path.exists(lite_path) else None,
                "full": filename if os.path.exists(full_path) else None,
                "has_lite": os.path.exists(lite_path),
                "has_full": os.path.exists(full_path),
                "has_universe": os.path.exists(universe_path),
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


def validate_single_report(filepath: str) -> bool:
    """
    驗證單一報告檔案是否有效
    
    Args:
        filepath: 檔案路徑
        
    Returns:
        bool: 是否有效
    """
    if not os.path.exists(filepath):
        return False
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 基本結構驗證（單一報告）
            if isinstance(data, dict) and "date" in data:
                datetime.strptime(data["date"], "%Y-%m-%d")
                return True
    except (json.JSONDecodeError, KeyError, ValueError, IOError):
        pass
    
    return False


def validate_index_file(filepath: str) -> bool:
    """
    驗證索引檔案是否有效
    
    Args:
        filepath: 檔案路徑
        
    Returns:
        bool: 是否有效
    """
    if not os.path.exists(filepath):
        return False
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 基本結構驗證（索引格式）
            if isinstance(data, dict) and "reports" in data and "latest_date" in data:
                if isinstance(data["reports"], list):
                    return True
    except (json.JSONDecodeError, KeyError, ValueError, IOError):
        pass
    
    return False


def atomic_update_index(date_str: str, has_lite: bool = True, has_full: bool = True, has_universe: bool = False) -> Dict:
    """
    原子化更新索引（v5 安全更新核心）
    
    確保只有在所有報告檔案都成功且格式正確後，才更新索引。
    任一失敗都保留舊的 index.json。
    
    步驟：
    1. 檢查報告檔案是否存在且有效
    2. 載入現有索引並更新
    3. 寫入到暫存檔 (index.json.tmp)
    4. 驗證暫存檔格式正確（使用 validate_index_file）
    5. 備份原檔為 index.json.bak（若存在）
    6. 原子替換：shutil.move(index.json.tmp, index.json)
    7. 刪除備份檔
    
    Args:
        date_str: 日期字串 YYYY-MM-DD
        has_lite: 是否有精簡版
        has_full: 是否有完整版
        
    Returns:
        Dict: 更新後的索引資料
        
    Raises:
        FileNotFoundError: 報告檔案不存在或無效
        ValueError: JSON 格式無效
        RuntimeError: 更新失敗
    """
    # 步驟 1: 檢查報告檔案是否存在且有效（使用單一報告驗證）
    lite_path = os.path.join(REPORTS_DIR, f"{date_str}-lite.json")
    full_path = os.path.join(REPORTS_DIR, f"{date_str}.json")
    universe_path_check = os.path.join(REPORTS_DIR, f"{date_str}-universe.json")

    if has_lite and not validate_single_report(lite_path):
        raise FileNotFoundError(f"精簡版報告檔案無效或不存在: {lite_path}")
    if has_full and not validate_single_report(full_path):
        raise FileNotFoundError(f"完整版報告檔案無效或不存在: {full_path}")
    if has_universe and not os.path.exists(universe_path_check):
        raise FileNotFoundError(f"Universe 報告檔案不存在: {universe_path_check}")
    
    # 步驟 2: 載入現有索引並更新
    index_data = load_index()
    
    # 檢查是否已存在
    existing_report = None
    for i, report in enumerate(index_data["reports"]):
        if report["date"] == date_str:
            existing_report = (i, report)
            break
    
    report_info = {
        "date": date_str,
        "lite": f"{date_str}-lite.json" if has_lite else None,
        "full": f"{date_str}.json" if has_full else None,
        "has_lite": has_lite,
        "has_full": has_full,
        "has_universe": has_universe,
        "created_at": datetime.now().isoformat()
    }
    
    if existing_report:
        # 更新現有項目
        idx, _ = existing_report
        index_data["reports"][idx] = report_info
    else:
        # 新增項目
        index_data["reports"].append(report_info)
        # 重新排序（新到舊）
        index_data["reports"].sort(key=lambda x: x["date"], reverse=True)
    
    # 更新最新日期和總數
    if index_data["reports"]:
        index_data["latest_date"] = index_data["reports"][0]["date"]
    index_data["total_reports"] = len(index_data["reports"])
    
    # 步驟 3: 寫入到暫存檔
    try:
        with open(INDEX_TEMP_FILE, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"無法寫入暫存索引檔: {e}")
    
    # 步驟 4: 驗證暫存檔格式（使用索引驗證）
    if not validate_index_file(INDEX_TEMP_FILE):
        # 刪除無效的暫存檔
        if os.path.exists(INDEX_TEMP_FILE):
            os.remove(INDEX_TEMP_FILE)
        raise ValueError("暫存索引檔格式驗證失敗")
    
    # 步驟 5: 備份原檔（若存在）
    if os.path.exists(INDEX_FILE):
        try:
            shutil.copy2(INDEX_FILE, INDEX_BACKUP_FILE)
        except Exception as e:
            # 刪除暫存檔
            if os.path.exists(INDEX_TEMP_FILE):
                os.remove(INDEX_TEMP_FILE)
            raise RuntimeError(f"無法備份原索引檔: {e}")
    
    # 步驟 6: 原子替換（關鍵步驟）
    try:
        # 在 Unix-like 系統上，這是原子操作
        shutil.move(INDEX_TEMP_FILE, INDEX_FILE)
    except Exception as e:
        # 嘗試恢復備份
        if os.path.exists(INDEX_BACKUP_FILE):
            try:
                shutil.copy2(INDEX_BACKUP_FILE, INDEX_FILE)
            except:
                pass
        raise RuntimeError(f"無法原子替換索引檔: {e}")
    
    # 步驟 7: 刪除備份檔（確認成功後才刪除）
    if os.path.exists(INDEX_BACKUP_FILE):
        try:
            os.remove(INDEX_BACKUP_FILE)
        except:
            pass  # 備份檔刪除失敗不影響主要功能
    
    # 確認暫存檔已清理
    if os.path.exists(INDEX_TEMP_FILE):
        try:
            os.remove(INDEX_TEMP_FILE)
        except:
            pass
    
    return index_data


def add_report_to_index(date_str: str, has_lite: bool = True, has_full: bool = True):
    """
    新增單一報告到索引（舊版 API，保留相容性）
    
    警告：此函式直接修改 index.json，不具備原子性保護。
    建議使用 atomic_update_index() 取代。
    
    Args:
        date_str: 日期字串 YYYY-MM-DD
        has_lite: 是否有精簡版
        has_full: 是否有完整版
    """
    # 發出棄用警告
    import warnings
    warnings.warn(
        "add_report_to_index() 已棄用，請改用 atomic_update_index()",
        DeprecationWarning,
        stacklevel=2
    )
    
    # 執行原子化更新
    return atomic_update_index(date_str, has_lite, has_full)


def safe_update_index(date_str: str, has_lite: bool = True, has_full: bool = True):
    """
    安全更新索引（v5 舊版 API，現已更名為 atomic_update_index）
    
    為保持相容性，此函式保留，但內部轉呼叫 atomic_update_index。
    """
    return atomic_update_index(date_str, has_lite, has_full)


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


def restore_index_backup() -> bool:
    """
    從備份恢復索引（緊急使用）
    
    Returns:
        bool: 是否成功恢復
    """
    if os.path.exists(INDEX_BACKUP_FILE):
        try:
            shutil.copy2(INDEX_BACKUP_FILE, INDEX_FILE)
            return True
        except:
            pass
    return False


if __name__ == "__main__":
    # 測試：重建索引
    print("重建報告索引...")
    index = rebuild_index()
    print(f"找到 {index['total_reports']} 份報告")
    print(f"最新日期: {index['latest_date']}")
    
    # 顯示前 5 筆
    for report in index['reports'][:5]:
        print(f"  {report['date']}: lite={report['has_lite']}, full={report['has_full']}")
