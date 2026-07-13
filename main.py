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

from backend.config import get_today_str, get_taiwan_now
from backend.fetch_data import fetch_all_stocks, load_cached_data
from backend.calc_indicators import calculate_all_indicators, StockIndicators
from backend.ranking import rank_stocks, StockScore
from backend.generate_report import generate_report_v2, generate_lite_report, save_both_reports, generate_ai_report_if_enabled, generate_universe_report, save_universe_report, save_report, validate_report_consistency
from backend.priority_facade import backfill_priority_validation_reports
from backend.report_index import atomic_update_index


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
) -> Tuple[str, str, Optional[str], str, Optional[str], Optional[str], Optional[str]]:
    """
    執行完整分析流程
    
    Args:
        use_cache: 是否使用快取資料
        date_str: 指定日期（必須搭配 use_cache）
        symbols: 指定股票列表
        
    Returns:
        (完整報告路徑, 精簡報告路徑, AI報告路徑或None, universe, context, priority, history)
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
    
    all_stocks = rank_stocks(indicators, top_n=len(indicators))
    top_stocks = all_stocks[:5]
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
    
    bundle_id = f"{report_date}-{get_taiwan_now().strftime('%Y%m%dT%H%M%S%f')}"

    # 生成 v2 完整報告
    full_report = generate_report_v2(
        top_stocks=top_stocks,
        date_str=report_date,
        total_stocks_requested=total_requested,
        total_stocks_analyzed=total_analyzed,
        bundle_id=bundle_id
    )

    universe_report = generate_universe_report(all_stocks, report_date, bundle_id=bundle_id)

    # 讓首頁與個股頁共用同一份 universe 共用欄位，避免分流後漂移。
    lite_report = generate_lite_report(full_report, universe_report)

    # 生成前先做同日同源一致性檢查，不通過就直接 fail。
    validate_report_consistency(full_report, lite_report, universe_report)

    # 儲存報告（此時不更新 index.json，等 universe 與 AI 完成後一起更新）
    full_path = save_report(full_report, report_date, suffix="")
    lite_path = save_report(lite_report, report_date, suffix="-lite")
    universe_path = save_universe_report(universe_report, report_date)

    print(f"[OK] 報告已生成")
    print(f"   完整版: {full_path}")
    print(f"   精簡版: {lite_path}")
    print(f"   日期: {full_report['date']}")
    print(f"   請求檔數: {full_report['total_stocks_requested']}")
    print(f"   成功分析: {full_report['total_stocks_analyzed']}")
    print(f"   Top N: {full_report['top_n']}")
    print(f"   版本: {full_report['report_version']}")
    
    # Step 5: 生成 AI 分析報告（v6，選用）
    print("\n[Step 5] 生成 AI 分析報告 (v6)")
    print("-" * 40)
    
    try:
        ai_path = generate_ai_report_if_enabled(full_report, report_date)
    except Exception as e:
        # AI 摘要是加值資料；基礎報告已完成一致性驗證，不應因摘要品質檢查失敗而無法發布。
        ai_path = None
        print(f"[WARN] AI 分析生成失敗，將繼續發布基礎報告: {e}")

    if ai_path:
        print(f"[OK] AI 報告已生成: {ai_path}")
    else:
        print("[INFO] 本次未產生 AI 報告，前端將使用基礎資料顯示")
    
    # Step 6: 生成 Universe 報告 (v6.1)
    print("\n[Step 6] 生成 Universe 報告 (v6.1)")
    print("-" * 40)

    print(f"[OK] Universe 報告已生成: {universe_path}")
    print(f"   包含 {universe_report['total_stocks']} 檔股票")

    # Step 7: 產生 context / priority / factor 驗證層（v9 + v30）
    print("\n[Step 7] 產生 Context、Priority、steady v5 跨時間驗證、失效環境分析與啟用判斷報告")
    print("-" * 40)

    validation_result = backfill_priority_validation_reports(
        target_date=report_date,
        refresh_context=True,
    )
    context_path = validation_result.get("current_context_path")
    priority_path = validation_result.get("current_priority_path")
    history_path = validation_result.get("history_path")
    factor_analysis_path = validation_result.get("factor_analysis_path")
    factor_combination_analysis_path = validation_result.get("factor_combination_analysis_path")
    strategy_analysis_path = validation_result.get("strategy_analysis_path")
    signal_density_path = validation_result.get("signal_density_path")
    steady_v2_blockers_path = validation_result.get("steady_v2_blockers_path")
    timing_alignment_path = validation_result.get("timing_alignment_path")
    steady_v2_signature_path = validation_result.get("steady_v2_signature_path")
    steady_v4_tracking_path = validation_result.get("steady_v4_tracking_path")
    steady_v4_alpha_breakdown_path = validation_result.get("steady_v4_alpha_breakdown_path")
    steady_v5_long_term_validation_path = validation_result.get("steady_v5_long_term_validation_path")
    steady_v5_regime_analysis_path = validation_result.get("steady_v5_regime_analysis_path")
    strategy_activation_path = validation_result.get("strategy_activation_path")

    if context_path:
        print(f"[OK] Context 報告已就緒: {context_path}")
    if priority_path:
        print(f"[OK] Priority 快照已就緒: {priority_path}")
    if history_path:
        print(f"[OK] Priority 歷史統計已就緒: {history_path}")
    if factor_analysis_path:
        print(f"[OK] 因子分析已就緒: {factor_analysis_path}")
    if factor_combination_analysis_path:
        print(f"[OK] 因子組合分析已就緒: {factor_combination_analysis_path}")
    if strategy_analysis_path:
        print(f"[OK] 策略重組分析（含 steady_v5）已就緒: {strategy_analysis_path}")
    if signal_density_path:
        print(f"[OK] 訊號密度分析已就緒: {signal_density_path}")
    if steady_v2_blockers_path:
        print(f"[OK] steady_v2 阻塞分析已就緒: {steady_v2_blockers_path}")
    if timing_alignment_path:
        print(f"[OK] 時序對齊分析已就緒: {timing_alignment_path}")
    if steady_v2_signature_path:
        print(f"[OK] steady_v2 特徵分析已就緒: {steady_v2_signature_path}")
    if steady_v4_tracking_path:
        print(f"[OK] steady_v4 實戰追蹤已就緒: {steady_v4_tracking_path}")
    if steady_v4_alpha_breakdown_path:
        print(f"[OK] steady_v4 alpha 拆解已就緒: {steady_v4_alpha_breakdown_path}")
    if steady_v5_long_term_validation_path:
        print(f"[OK] steady_v5 跨時間驗證已就緒: {steady_v5_long_term_validation_path}")
    if steady_v5_regime_analysis_path:
        print(f"[OK] steady_v5 失效環境分析已就緒: {steady_v5_regime_analysis_path}")
    if strategy_activation_path:
        print(f"[OK] steady_v5 啟用判斷已就緒: {strategy_activation_path}")
    if validation_result.get("evaluated_days") is not None:
        print(f"[OK] 已可評估樣本天數: {validation_result['evaluated_days']}")
    if validation_result.get("history_window"):
        generated_days = len(validation_result["history_window"].get("generated") or [])
        target_days = len(validation_result["history_window"].get("target_dates") or [])
        print(f"[OK] v28 歷史樣本視窗: {target_days} 天目標，這次新補 {generated_days} 天")

    if validation_result.get("skipped"):
        print(f"[INFO] 有 {len(validation_result['skipped'])} 個歷史日期因缺資料而略過")

    # 最終一次更新 index.json（確保 has_universe=True）
    print("\n[Step 8] 更新索引 (has_universe=True)")
    try:
        atomic_update_index(report_date, has_lite=True, has_full=True, has_universe=True)
        print(f"[OK] 索引已更新，has_universe=True")
    except Exception as e:
        print(f"[ERROR] 索引更新失敗: {e}")
        raise

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
    
    return full_path, lite_path, ai_path, universe_path, context_path, priority_path, history_path


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
        full_path, lite_path, ai_path, universe_path, context_path, priority_path, history_path = run_pipeline(
            use_cache=args.use_cache,
            date_str=args.date,
            symbols=test_symbols
        )
        print(f"\n報告位置:")
        print(f"   完整版: {os.path.abspath(full_path)}")
        print(f"   精簡版: {os.path.abspath(lite_path)}")
        if ai_path:
            print(f"   AI版: {os.path.abspath(ai_path)}")
        print(f"   Universe: {os.path.abspath(universe_path)}")
        if context_path:
            print(f"   Context: {os.path.abspath(context_path)}")
        if priority_path:
            print(f"   Priority: {os.path.abspath(priority_path)}")
        if history_path:
            print(f"   Priority History: {os.path.abspath(history_path)}")
        
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
