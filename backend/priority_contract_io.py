"""Second-page contract I/O layer.

Responsibilities:
- second-page contract I/O only
- not a truth source by itself
- not a validator rule module
- not a generation layer
- responsible for loading/saving -priority.json and composing validation payload

layer: contract I/O
allowed dependencies: stdlib + backend.config + backend.priority_validation
internal layer
external callers should use backend.priority_facade
not intended as direct app/script entrypoint
tests may import internal modules, but app / script entrypoints should not
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.config import get_today_str
from backend.priority_validation import (
    PriorityValidationError,
    ScenarioCardValidationError,
    validate_priority_validation_v10_1_contract,
    validate_scenario_cards_v9_contract,
)


PRIORITY_CONTRACT_FIELD_NAMES = (
    "priority_validation_v10_1_schema_version",
    "priority_snapshot_v10_1",
    "priority_candidates_v10_1",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _reports_dir(base_dir: Optional[Path] = None) -> Path:
    root = base_dir or _repo_root()
    return root / "reports"


def _load_json(path: Path, required: bool = True) -> Optional[Dict[str, Any]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"找不到檔案：{path}")
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_json(path: Path, payload: Dict[str, Any]) -> Path:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def _context_report_path(date_str: str, base_dir: Optional[Path] = None) -> Path:
    """YYYY-MM-DD-context.json: context / 第三頁來源報告。"""
    return _reports_dir(base_dir) / f"{date_str}-context.json"


def _priority_report_path(date_str: str, base_dir: Optional[Path] = None) -> Path:
    """YYYY-MM-DD-priority.json: 第二頁正式 contract 報告。"""
    return _reports_dir(base_dir) / f"{date_str}-priority.json"


def _load_context_report(
    date_str: str,
    base_dir: Optional[Path] = None,
    required: bool = True,
) -> Optional[Dict[str, Any]]:
    return _load_json(_context_report_path(date_str, base_dir), required=required)


def _save_priority_contract_report(
    report: Dict[str, Any],
    date_str: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Path:
    target_date = date_str or str(report.get("date") or get_today_str())
    return _save_json(_priority_report_path(target_date, base_dir), report)


def _load_priority_contract_report(
    date_str: str,
    base_dir: Optional[Path] = None,
    required: bool = True,
) -> Optional[Dict[str, Any]]:
    return _load_json(_priority_report_path(date_str, base_dir), required=required)


def _build_priority_contract_payload(
    context_report: Dict[str, Any],
    priority_report: Dict[str, Any],
) -> Dict[str, Any]:
    payload = dict(context_report)
    for field_name in PRIORITY_CONTRACT_FIELD_NAMES:
        if field_name in priority_report:
            payload[field_name] = priority_report[field_name]
    return payload


def _load_priority_contract_payload(
    date_str: str,
    base_dir: Optional[Path] = None,
) -> tuple[Path, Dict[str, Any]]:
    context_path = _context_report_path(date_str, base_dir)
    context_report = _load_context_report(date_str, base_dir=base_dir, required=True) or {}
    priority_report = _load_priority_contract_report(date_str, base_dir=base_dir, required=True) or {}
    payload = _build_priority_contract_payload(context_report, priority_report)
    return context_path, payload


def _validate_priority_contract_payload(
    payload: Dict[str, Any],
    context_path: Path,
) -> None:
    validate_scenario_cards_v9_contract(payload)
    has_scenario_cards_v9_schema = payload.get("scenario_cards_v9_schema_version") == "scenario-cards-v9"

    if has_scenario_cards_v9_schema and not payload.get("scenario_cards_v9"):
        raise ScenarioCardValidationError(
            f"{context_path} 缺少第三頁單一真相源 scenario_cards_v9，"
            "不得回退到使用 legacy cards 欄位"
        )

    for card in payload.get("scenario_cards_v9") or []:
        if not card.get("source_types") or not isinstance(card.get("priority_rank"), int):
            raise ScenarioCardValidationError(
                f"{context_path} 的 scenario_cards_v9 包含不符合 v9.1 contract 的卡片，"
                "請檢查 source_types 與 priority_rank"
            )

    try:
        validate_priority_validation_v10_1_contract(payload, strict_mode=True)
    except PriorityValidationError as exc:
        raise PriorityValidationError(f"{context_path} v10.1 contract 驗證失敗: {exc}") from exc