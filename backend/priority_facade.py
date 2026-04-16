"""second-page external entrypoints only

layer: public facade
allowed dependencies: backend.priority_analysis only
external callers should use this module

thin facade over analysis / generation / contract_io / validation layers
not a truth source
not a validator
not a generation layer
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.priority_analysis import (
    backfill_priority_validation_reports as _backfill_priority_validation_reports,
    generate_priority_snapshot_from_files as _generate_priority_snapshot_from_files,
    load_priority_reports as _load_priority_reports,
    load_universe_reports_by_date as _load_universe_reports_by_date,
)


def generate_priority_snapshot_from_files(
    date_str: str,
    base_dir: Optional[Path] = None,
    next_date: Optional[str] = None,
    refresh_context: bool = False,
) -> Path:
    return _generate_priority_snapshot_from_files(
        date_str,
        base_dir=base_dir,
        next_date=next_date,
        refresh_context=refresh_context,
    )


def backfill_priority_validation_reports(
    base_dir: Optional[Path] = None,
    refresh_context: bool = False,
    target_date: Optional[str] = None,
    min_evaluated_days: int = 20,
    auto_backfill_history: Optional[bool] = None,
    market_prices: Optional[Any] = None,
) -> Dict[str, Any]:
    return _backfill_priority_validation_reports(
        base_dir=base_dir,
        refresh_context=refresh_context,
        target_date=target_date,
        min_evaluated_days=min_evaluated_days,
        auto_backfill_history=auto_backfill_history,
        market_prices=market_prices,
    )


def load_priority_reports(base_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    return _load_priority_reports(base_dir=base_dir)


def load_universe_reports_by_date(base_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    return _load_universe_reports_by_date(base_dir=base_dir)


# External public API whitelist for second-page callers.
__all__ = [
    "generate_priority_snapshot_from_files",
    "backfill_priority_validation_reports",
    "load_priority_reports",
    "load_universe_reports_by_date",
]