from __future__ import annotations

from pathlib import Path
import unittest

from backend import context_cards


EXPECTED_PUBLIC_API = [
    "generate_context_report",
    "generate_context_report_from_files",
]

REQUIRED_SCENARIO_CARD_FILES = [
    Path("backend/SCENARIO_CARDS_V9_DONE.md"),
    Path("tests/test_scenario_cards_contract_golden.py"),
    Path("tests/test_scenario_cards_fallback_golden.py"),
    Path("tests/test_context_cards_public_api_boundary.py"),
    Path("tests/test_context_cards_dependency_guard.py"),
]

REQUIRED_DONE_SECTIONS = [
    "## 已完成",
    "## 單一真相源",
    "## 不得回退",
    "## 允許維護",
]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


class TestScenarioCardsDoneContract(unittest.TestCase):
    def test_context_cards_public_api_remains_whitelisted(self) -> None:
        self.assertEqual(context_cards.__all__, EXPECTED_PUBLIC_API)

    def test_scenario_cards_done_definition_file_exists_and_has_required_sections(self) -> None:
        root = _workspace_root()
        done_path = root / "backend" / "SCENARIO_CARDS_V9_DONE.md"
        self.assertTrue(done_path.exists(), msg="第三頁完成定義文件必須存在")

        content = done_path.read_text(encoding="utf-8")
        for section in REQUIRED_DONE_SECTIONS:
            self.assertIn(section, content, msg=f"完成定義文件缺少章節: {section}")

    def test_required_scenario_cards_guard_and_golden_tests_exist(self) -> None:
        root = _workspace_root()
        missing = [str(path) for path in REQUIRED_SCENARIO_CARD_FILES if not (root / path).exists()]
        self.assertEqual(missing, [], msg="第三頁封板必要檔案缺失: " + ", ".join(missing))


if __name__ == "__main__":
    unittest.main()