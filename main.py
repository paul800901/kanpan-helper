#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
看板助手 - 每日股票分析報告生成器

使用方法:
    python main.py                    # 執行完整流程
    python main.py --test             # 測試模式（只跑3檔）
    python main.py --use-cache        # 使用今日快取
    python main.py --use-cache --date 2024-03-15  # 使用指定日期快取
"""
import sys
import argparse
from typing import Optional, Tuple, Dict, List

# 設定 Python 路徑
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import get_today_str
from backend.fetch_data import fetch_all_stocks, load_cached_data
from backend.calc_indicators import calculate_all_indicators, StockIndicators
from backend.ranking import rank_stocks, StockScore
from backend.generate_report import generate_report_v2, generate_lite_report, save_both_reports


def fetch_data_with_stats(
    use_cache: bool = False, 
    date_str: Optional[str] = None,
    symbols: Optional[List[str]] = None
) -> Tuple[Dict[str, Dict], int, int]:
    """
    取得股票資料並回傳統計資訊
    
    Returns:
        Tuple[資料字典, 請求數, 成功數]
    """
    if symbols is None:
        from backend.config import DEFAULT_STOCKS
        symbols = DEFAULT_STOCKS
    
    requested = len(symbols)
    
    if use_cache:
        if date_str:
            print(f"嘗試載入 {date_str} 的快取資料...")
            stock_data = load_cached_data(date_str)
            if stock_data is None:
                raise FileNotFoundError(f"找不到 {date_str} 的快取資料")
            print(f"[OK] 載入 {len(stock_data)} 檔快取資料")
            return stock_data, requested, len(stock_data)
        else:
            print("嘗試載入今日快取資料...")
            stock_data = load_cached_data()
            if stock_data is None:
                raise FileNotFoundError("找不到今日快取資料")
            print(f"[OK] 載入 {len(stock_data)} 檔快取資料")
            return stock_data, requested, len(stock_data)
    else:
        stock_data, success_count = fetch_all_stocks(symbols=symbols, save_cache=True)
        return stock_data, requested, success_count


def run_pipeline(
    use_cache: bool = False, 
    date_str: Optional[str] = None,
    symbols: Optional[List[str]] = None
) -> str:
    """
    執行完整分析流程
    
    Args:
        use_cache: 是否使用快取資料
        date_str: 指定日期（必須搭配 use_cache）
        symbols: 指定股票列表
        
    Returns:
        報告檔案路徑
    """
    print("=" * 60)
    print("Kanpan Helper - 每日股票分析")
    print("=" * 60)
    
    # Step 1: 取得資料
    print("\n[Step 1] 取得股票資料")
    print("-" * 40)
    
    try:
        stock_data, total_requested, total_analyzed = fetch_data_with_stats(
            use_cache=use_cache,
            date_str=date_str,
            symbols=symbols
        )
    except FileNotFoundError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
    
    if not stock_data:
        print("[FAIL] 無法取得股票資料，程式結束")
        sys.exit(1)
    
    print(f"[OK] 取得 {len(stock_data)} 檔股票資料")
    print(f"   請求: {total_requested} 檔, 成功: {total_analyzed} 檔")
    
    # Step 2: 計算技術指標
    print("\n[Step 2] 計算技術指標")
    print("-" * 40)
    
    indicators = calculate_all_indicators(stock_data)
    print(f"[OK] 完成 {len(indicators)} 檔股票的指標計算")
    print(f"   計算項目: MA5, MA20, 20日均量, 量比, KD, 法人")
    
    # 檢查資料充足性
    insufficient = [s for s in indicators.values() if not s.has_sufficient_data]
    if insufficient:
        print(f"   [WARN] {len(insufficient)} 檔資料不足: {', '.join(s.symbol for s in insufficient)}")
    
    # Step 3: 評分排名
    print("\n[Step 3] 評分與排名")
    print("-" * 40)
    
    top_stocks = rank_stocks(indicators, top_n=5)
    print(f"[OK] 評分完成，選出 Top {len(top_stocks)}:")
    
    for i, stock in enumerate(top_stocks, 1):
        vol_str = f", 量比:{stock.volume_ratio:.2f}" if stock.volume_ratio else ""
        print(f"   {i}. {stock.symbol} - {stock.score}分 "
              f"(趨勢:{stock.trend}, 量:{stock.volume}, "
              f"法人:{stock.institutional}, KD:{stock.kd_state}{vol_str})")
    
    # Step 4: 生成報告
    print("\n[Step 4] 生成分析報告 (v2)")
    print("-" * 40)
    
    # 使用報告日期：如果從快取載入，使用快取日期；否則使用今天
    report_date = date_str if (use_cache and date_str) else get_today_str()
    
    # 生成 v2 完整報告
    full_report = generate_report_v2(
        top_stocks=top_stocks,
        date_str=report_date,
        total_stocks_requested=total_requested,
        total_stocks_analyzed=total_analyzed
    )
    
    # 生成精簡版
    lite_report = generate_lite_report(full_report)
    
    # 儲存兩份報告
    full_path, lite_path = save_both_reports(full_report, lite_report, report_date)
    
    print(f"[OK] 報告已生成")
    print(f"   完整版: {full_path}")
    print(f"   精簡版: {lite_path}")
    print(f"   日期: {full_report['date']}")
    print(f"   請求檔數: {full_report['total_stocks_requested']}")
    print(f"   成功分析: {full_report['total_stocks_analyzed']}")
    print(f"   Top N: {full_report['top_n']}")
    print(f"   版本: {full_report['report_version']}")
    
    # 顯示摘要
    print("\n[報告摘要]")
    print("-" * 40)
    print(f"\n市場概況: {full_report['summary']['market_overview']}")
    print(f"\n推薦名單:")
    for stock in full_report['stocks'][:3]:
        print(f"   {stock['rank']}. [{stock['symbol']} {stock['name']}] "
              f"{stock['score']}分({stock['score_grade']}/{stock['score_label']}) - {stock['action_bias']}")
        print(f"      {stock['one_line_summary']}")
    
    print("\n" + "=" * 60)
    print("流程完成！")
    print("=" * 60)
    
    return full_path, lite_path


def main():
    """主程式入口"""
    parser = argparse.ArgumentParser(
        description="看板助手 - 每日股票分析報告生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python main.py                               # 執行完整流程
  python main.py --test                        # 測試模式（只跑3檔）
  python main.py --use-cache                   # 使用今日快取
  python main.py --use-cache --date 2024-03-15 # 使用指定日期快取
  
注意:
  --date 參數必須搭配 --use-cache 使用
        """
    )
    
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="使用快取資料，不重新抓取"
    )
    
    parser.add_argument(
        "--date",
        type=str,
        help="指定日期 (YYYY-MM-DD)，必須搭配 --use-cache 使用"
    )
    
    parser.add_argument(
        "--test",
        action="store_true",
        help="使用測試模式（只跑3檔股票）"
    )
    
    args = parser.parse_args()
    
    # 檢查 --date 語法：必須搭配 --use-cache
    if args.date and not args.use_cache:
        print("[錯誤] 指定日期 (--date) 目前僅支援搭配 --use-cache 使用")
        print("       請執行: python main.py --use-cache --date YYYY-MM-DD")
        sys.exit(1)
    
    # 測試模式
    test_symbols = None
    if args.test:
        print("[測試模式] 只分析 3 檔股票")
        test_symbols = ["2330", "2317", "2454"]
    
    try:
        full_path, lite_path = run_pipeline(
            use_cache=args.use_cache,
            date_str=args.date,
            symbols=test_symbols
        )
        print(f"\n報告位置:")
        print(f"   完整版: {os.path.abspath(full_path)}")
        print(f"   精簡版: {os.path.abspath(lite_path)}")
        
    except KeyboardInterrupt:
        print("\n\n使用者中斷")
        sys.exit(0)
    except Exception as e:
        print(f"\n[錯誤] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
