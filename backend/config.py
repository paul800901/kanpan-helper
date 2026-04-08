"""系統設定"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# 路徑設定
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

# 確保目錄存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# 台灣時區
TAIWAN_TZ = ZoneInfo("Asia/Taipei")

# 股票清單（台灣前 50 大權值股）
DEFAULT_STOCKS = [
    "2330", "2317", "2454", "2412", "2881", "2882", "2308", "2303", "3711", "2891",
    "2886", "2884", "1216", "2885", "2357", "2382", "2892", "5880", "2880", "2327",
    "3034", "2883", "2002", "3008", "2890", "1101", "3045", "2395", "5876", "1326",
    "4904", "5871", "2301", "2912", "1402", "2887", "1102", "2603", "2408", "2615",
    "2609", "2610", "2618", "2606", "2617", "1605", "2207", "1229", "2634", "2363"
]

# 技術指標參數
MA_SHORT = 5
MA_LONG = 20
VOLUME_MA_DAYS = 20

# KD 參數
KD_RSV_DAYS = 9
KD_K_DEFAULT = 50
KD_D_DEFAULT = 50

# 法人連買判斷天數
INSTITUTIONAL_DAYS = 3

# 分數權重
SCORE_WEIGHTS = {
    "trend": 30,        # 趨勢分數
    "volume": 25,       # 成交量分數
    "institutional": 25, # 法人分數
    "kd": 20            # KD 分數
}

def get_taiwan_now():
    """取得台灣時區的目前時間"""
    return datetime.now(TAIWAN_TZ)

def get_today_str():
    """取得今天日期字串（台灣時區）"""
    return get_taiwan_now().strftime("%Y-%m-%d")

def get_report_path(date_str=None):
    """取得報告檔案路徑"""
    if date_str is None:
        date_str = get_today_str()
    return os.path.join(REPORTS_DIR, f"{date_str}.json")

def get_cache_path(date_str=None):
    """取得快取檔案路徑"""
    if date_str is None:
        date_str = get_today_str()
    return os.path.join(DATA_DIR, f"stock_data_{date_str}.json")
