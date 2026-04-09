#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
看板助手 - AI 分析報告生成器（v6 獨立入口）

【設計原則】
- 只讀取既有 v5 正式報告（reports/YYYY-MM-DD.json）
- 只產生 AI 報告（reports/YYYY-MM-DD-ai.json）
- 不重新抓取資料、不重新評分、不覆蓋任何 v5 報告
- ENABLE_AI_ANALYSIS=true 時任何錯誤都直接 raise（fail-fast）

使用方法:
    ENABLE_AI_ANALYSIS=true python main_ai.py
    ENABLE_AI_ANALYSIS=true python main_ai.py --date 2026-04-09
"""
import sys
import argparse
import json
import os

# 設定 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import get_today_str
from backend.generate_report import generate_ai_report_if_enabled


def load_v5_report(date_str: str) -> dict:
    """
    載入既有 v5 全量報告。找不到或格式錯誤時直接 raise。
    """
    report_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports",
        f"{date_str}.json"
    )

    if not os.path.exists(report_path):
        raise FileNotFoundError(
            f"找不到 v5 報告：{report_path}\n"
            f"請先執行 v5 workflow 產生正式報告後，再執行 AI workflow。"
        )

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # 基本驗證：確認是 v5/v2 格式
    version = report.get("report_version", "")
    if not version.startswith("v2"):
        raise ValueError(
            f"報告版本不符：期望 v2/v2-lite，實際為 '{version}'。"
        )

    return report


def run_ai_pipeline(date_str: str) -> str:
    """
    執行 AI 報告生成流程。

    Args:
        date_str: 報告日期（YYYY-MM-DD）

    Returns:
        AI 報告檔案路徑
    """
    print("=" * 60)
    print("Kanpan Helper - AI 分析報告生成器 (v6)")
    print("=" * 60)
    print(f"\n目標日期: {date_str}")

    # Step 1: 載入既有 v5 報告（不重新產生）
    print("\n[Step 1] 載入 v5 正式報告")
    print("-" * 40)
    full_report = load_v5_report(date_str)
    print(f"[OK] 載入成功：{full_report.get('top_n', 0)} 檔股票，版本 {full_report.get('report_version')}")

    # Step 2: 執行 AI 分析（fail-fast：任何錯誤都 raise）
    print("\n[Step 2] 執行 AI 分析")
    print("-" * 40)
    ai_path = generate_ai_report_if_enabled(full_report, date_str)

    if ai_path is None:
        # generate_ai_report_if_enabled 只在 ENABLE_AI_ANALYSIS=false 時回 None
        raise EnvironmentError(
            "ENABLE_AI_ANALYSIS 未設為 true。"
            "AI workflow 必須設定此環境變數。"
        )

    print("\n" + "=" * 60)
    print(f"AI 報告產生完成：{ai_path}")
    print("=" * 60)
    return ai_path


def main():
    parser = argparse.ArgumentParser(
        description="看板助手 - AI 分析報告生成器（只讀 v5，不覆蓋正式報告）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  ENABLE_AI_ANALYSIS=true python main_ai.py
  ENABLE_AI_ANALYSIS=true python main_ai.py --date 2026-04-09

注意:
  必須先有 reports/YYYY-MM-DD.json（由 v5 workflow 產生）。
  本程式不會覆蓋任何 v5 報告。
"""
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="指定報告日期（YYYY-MM-DD），預設為今天"
    )
    args = parser.parse_args()

    date_str = args.date or get_today_str()

    try:
        run_ai_pipeline(date_str)
    except Exception as e:
        print(f"\n[FAIL] AI 報告生成失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
