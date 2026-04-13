#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填 v20 排序驗證、單因子、組合、策略、密度與阻塞分析報告。"""

from __future__ import annotations

import argparse
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.priority_validation import backfill_priority_validation_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 v20 排序驗證層 reports")
    parser.add_argument(
        "--refresh-context",
        action="store_true",
        help="重新產生既有 context 報告",
    )
    parser.add_argument(
        "--min-evaluated-days",
        type=int,
        default=20,
        help="至少保留多少個已可評估的交易日樣本（預設 20）",
    )
    parser.add_argument(
        "--skip-history-window",
        action="store_true",
        help="只重算 context / priority / history，不自動補齊最近樣本視窗",
    )
    args = parser.parse_args()

    result = backfill_priority_validation_reports(
        refresh_context=args.refresh_context,
        min_evaluated_days=args.min_evaluated_days,
        auto_backfill_history=not args.skip_history_window,
    )

    print("[OK] v20 回填完成")
    print(f"   可回放日期: {len(result['available_dates'])}")
    print(f"   已可評估日期: {result['evaluated_days']}")
    print(f"   Priority 檔案: {len(result['priority_paths'])}")
    print(f"   History: {result['history_path']}")
    print(f"   Factor Analysis: {result['factor_analysis_path']}")
    print(f"   Factor Combination Analysis: {result['factor_combination_analysis_path']}")
    print(f"   Strategy Analysis: {result['strategy_analysis_path']}")
    print(f"   Signal Density: {result['signal_density_path']}")
    print(f"   steady_v2 Blockers: {result['steady_v2_blockers_path']}")

    if result.get("history_window"):
        print(f"   歷史目標日期: {len(result['history_window']['target_dates'])}")
        print(f"   新補報告日期: {len(result['history_window']['generated'])}")

    if result.get("skipped"):
        print(f"   略過日期: {len(result['skipped'])}")
        for item in result["skipped"]:
            print(f"   - {item['date']}: {item['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())