"""Validation layer for second-page contracts and third-page scenario cards.

layer: validation
allowed dependencies: stdlib only
internal layer
external callers should use backend.priority_facade
not intended as direct app/script entrypoint
tests may import internal modules, but app / script entrypoints should not
"""

from __future__ import annotations

from typing import Any, Dict


PRIORITY_VALIDATION_V10_1_SCHEMA_VERSION = "priority-validation-v10.1"

PRIORITY_SNAPSHOT_V10_1_REQUIRED_FIELDS = [
    "as_of_date",
    "market_regime",
    "breadth_state",
    "volume_state",
    "leader_state",
    "validation_summary",
    "confidence",
    "generated_at",
]

PRIORITY_CANDIDATE_V10_1_REQUIRED_FIELDS = [
    "symbol",
    "name",
    "score",
    "rank",
    "score_grade",
    "category",
    "theme",
    "validation_reason",
    "risk_note",
]

VALID_PRIORITY_CONFIDENCE = {"low", "medium", "high"}


class ValidationError(Exception):
    """驗證錯誤基礎類別"""


class ScenarioCardValidationError(ValidationError):
    """情境卡 v9.1 contract 驗證失敗"""


class PriorityValidationError(ValidationError):
    """第二頁 Priority Validation contract 驗證失敗"""


def validate_scenario_card_v9_source_types(card: Dict[str, Any], card_id: str) -> None:
    """驗證 source_types 規則"""
    if "source_types" not in card:
        raise ScenarioCardValidationError(f"[{card_id}] 缺少 source_types 欄位")
    if not isinstance(card["source_types"], list) or not card["source_types"]:
        raise ScenarioCardValidationError(f"[{card_id}] source_types 必須是非空陣列")
    if any(not isinstance(item, str) or not item.strip() for item in card["source_types"]):
        raise ScenarioCardValidationError(f"[{card_id}] source_types 內含空值或非字串元素")
    if len(card["source_types"]) != len(set(card["source_types"])):
        raise ScenarioCardValidationError(f"[{card_id}] source_types 不可重複")


def validate_scenario_card_v9_priority_rank(card: Dict[str, Any], card_id: str) -> None:
    """驗證 priority_rank 規則"""
    if "priority_rank" not in card:
        raise ScenarioCardValidationError(f"[{card_id}] 缺少 priority_rank 欄位")
    if not isinstance(card["priority_rank"], int):
        raise ScenarioCardValidationError(f"[{card_id}] priority_rank 必須是整數")


# Internal compatibility only: validator entrypoints below are for internal
# layers/tests. External app/script callers should use backend.priority_facade.
def validate_scenario_cards_v9_contract(context_report: Dict[str, Any]) -> None:
    """
    正式驗證 scenario_cards_v9 v9.1 contract
    - 每張卡的 source_types 符合規格
    - 每張卡的 priority_rank 符合規格
    - priority_rank 唯一且連續
    - 陣列順序與 priority_rank 一致

    V9.3 GUARD: 第三頁驗證不得依賴 legacy 欄位
    - scenario_cards_v9 完整時，不依賴 legacy 也能過
    - scenario_cards_v9 缺失時，不能靠 legacy 偷過
    """
    schema_version = context_report.get("scenario_cards_v9_schema_version")
    if schema_version != "scenario-cards-v9":
        return

    cards = context_report.get("scenario_cards_v9")
    if not isinstance(cards, list) or not cards:
        raise ScenarioCardValidationError(
            "scenario_cards_v9 必須是非空列表，第三頁不能靠 legacy cards 欄位補救"
        )

    if "cards" in str(cards) and len(cards) == 0:
        pass

    seen_ranks = set()
    for index, card in enumerate(cards):
        card_id = str(card.get("id") or f"card_{index}")

        validate_scenario_card_v9_source_types(card, card_id)
        validate_scenario_card_v9_priority_rank(card, card_id)

        rank = card["priority_rank"]
        if rank in seen_ranks:
            raise ScenarioCardValidationError(f"priority_rank 重複: {rank}")
        seen_ranks.add(rank)

        expected_rank = index + 1
        if rank != expected_rank:
            raise ScenarioCardValidationError(
                f"[{card_id}] priority_rank {rank} 與陣列位置 {expected_rank} 不一致"
            )

    expected_ranks = set(range(1, len(cards) + 1))
    if seen_ranks != expected_ranks:
        raise ScenarioCardValidationError(
            f"priority_rank 必須是連續的 1..{len(cards)}，實際: {sorted(seen_ranks)}"
        )


def validate_priority_snapshot_v10_1(snapshot: Dict[str, Any]) -> None:
    """驗證第二頁 priority_snapshot_v10_1 contract"""
    missing = [field for field in PRIORITY_SNAPSHOT_V10_1_REQUIRED_FIELDS if field not in snapshot]
    if missing:
        raise PriorityValidationError(f"priority_snapshot_v10_1 缺少欄位: {missing}")

    if snapshot.get("confidence") not in VALID_PRIORITY_CONFIDENCE:
        raise PriorityValidationError(
            f"priority_snapshot_v10_1 confidence 不合法: {snapshot.get('confidence')}"
        )


def validate_priority_candidate_v10_1(candidate: Dict[str, Any], index: int) -> None:
    """驗證第二頁 priority_candidates_v10_1 單筆 contract"""
    missing = [field for field in PRIORITY_CANDIDATE_V10_1_REQUIRED_FIELDS if field not in candidate]
    if missing:
        raise PriorityValidationError(f"priority_candidates_v10_1[{index}] 缺少欄位: {missing}")

    if not isinstance(candidate.get("score"), (int, float)):
        raise PriorityValidationError(f"priority_candidates_v10_1[{index}] score 必須是數字")

    if not isinstance(candidate.get("rank"), int):
        raise PriorityValidationError(f"priority_candidates_v10_1[{index}] rank 必須是整數")


def validate_priority_validation_v10_1_contract(context_report: Dict[str, Any], strict_mode: bool = False) -> None:
    """V10.3: 第二頁 validation layer entry point."""
    schema_version = context_report.get("priority_validation_v10_1_schema_version")
    has_schema_version = schema_version == PRIORITY_VALIDATION_V10_1_SCHEMA_VERSION

    if strict_mode and schema_version and not has_schema_version:
        raise PriorityValidationError(
            f"priority_validation_v10_1_schema_version 必須是 '{PRIORITY_VALIDATION_V10_1_SCHEMA_VERSION}'，"
            f"但找到 '{schema_version}'"
        )

    if not has_schema_version and not strict_mode:
        return

    has_legacy_cards = bool(context_report.get("cards"))
    has_legacy_trace = bool(context_report.get("trace_catalog"))

    snapshot = context_report.get("priority_snapshot_v10_1")
    if not snapshot:
        error_msg = "priority_snapshot_v10_1 必須存在，第二頁不能靠 legacy 欄位直接輸出"
        if has_legacy_cards or has_legacy_trace:
            error_msg += "\n[V10.2 Guard] 檢測到 legacy 欄位存在但 contract 缺失，請重新生成報告"
        raise PriorityValidationError(error_msg)
    validate_priority_snapshot_v10_1(snapshot)

    candidates = context_report.get("priority_candidates_v10_1")
    if not isinstance(candidates, list):
        raise PriorityValidationError("priority_candidates_v10_1 必須是陣列")

    for index, candidate in enumerate(candidates):
        validate_priority_candidate_v10_1(candidate, index)