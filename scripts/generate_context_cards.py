#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""產生 v9-pre 可追溯情境卡 JSON。"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import get_today_str
from backend.context_cards import generate_context_report_from_files


def main() -> int:
    parser = argparse.ArgumentParser(description="產生 v9-pre 可追溯情境卡 JSON")
    parser.add_argument("--date", type=str, default=get_today_str(), help="指定日期 YYYY-MM-DD")
    args = parser.parse_args()

    output_path = generate_context_report_from_files(args.date)
    print(f"[OK] 已產生情境卡: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
