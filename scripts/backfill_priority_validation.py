#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填 v11 排序驗證報告。"""

from __future__ import annotations

import argparse
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.priority_validation import backfill_priority_validation_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 v11 排序驗證層 reports")
    parser.add_argument(
        "--refresh-context",
        action="store_true",
        help="重新產生既有 context 報告",
    )
    args = parser.parse_args()

    result = backfill_priority_validation_reports(refresh_context=args.refresh_context)

    print("[OK] v11 回填完成")
    print(f"   可回放日期: {len(result['available_dates'])}")
    print(f"   Priority 檔案: {len(result['priority_paths'])}")
    print(f"   History: {result['history_path']}")

    if result.get("skipped"):
        print(f"   略過日期: {len(result['skipped'])}")
        for item in result["skipped"]:
            print(f"   - {item['date']}: {item['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())