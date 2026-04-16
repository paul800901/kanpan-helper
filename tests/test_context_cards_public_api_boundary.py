from __future__ import annotations

import ast
from pathlib import Path
import unittest

from backend import context_cards


EXPECTED_PUBLIC_API = [
    "generate_context_report",
    "generate_context_report_from_files",
]

WHITELISTED_PUBLIC_API = set(EXPECTED_PUBLIC_API)


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_test_like_script(path: Path) -> bool:
    name = path.name.lower()
    stem = path.stem.lower()
    return name.startswith("test_") or stem.endswith("_test")


def _context_cards_module_aliases(module: ast.AST) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "backend.context_cards":
                    aliases.add(alias.asname or "context_cards")
        if isinstance(node, ast.ImportFrom) and node.module == "backend":
            for alias in node.names:
                if alias.name == "context_cards":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _find_context_cards_public_api_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _context_cards_module_aliases(module)

        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module == "backend.context_cards":
                for alias in node.names:
                    imported_name = alias.name
                    if imported_name == "*":
                        violations.append(
                            f"{path.relative_to(_workspace_root())}:{getattr(node, 'lineno', '?')}:star import is not allowed"
                        )
                    elif imported_name not in WHITELISTED_PUBLIC_API:
                        violations.append(
                            f"{path.relative_to(_workspace_root())}:{getattr(node, 'lineno', '?')}:non-public import {imported_name}"
                        )

            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                attribute_name = node.attr
                if attribute_name.startswith("__"):
                    continue
                if attribute_name not in WHITELISTED_PUBLIC_API:
                    violations.append(
                        f"{path.relative_to(_workspace_root())}:{getattr(node, 'lineno', '?')}:non-public attribute {attribute_name}"
                    )

    return violations


class TestContextCardsPublicApiBoundary(unittest.TestCase):
    def test_context_cards_public_api_whitelist_is_explicit(self) -> None:
        self.assertEqual(context_cards.__all__, EXPECTED_PUBLIC_API)

    def test_main_does_not_use_non_public_context_cards_entries(self) -> None:
        root = _workspace_root()
        violations = _find_context_cards_public_api_violations([root / "main.py"])
        self.assertEqual(
            violations,
            [],
            msg=(
                "main.py 若使用 backend.context_cards，只能使用白名單公開 API: "
                + ", ".join(violations)
            ),
        )

    def test_scripts_entrypoints_do_not_use_non_public_context_cards_entries(self) -> None:
        root = _workspace_root()
        script_paths = [
            path
            for path in sorted((root / "scripts").rglob("*.py"))
            if not _is_test_like_script(path)
        ]
        violations = _find_context_cards_public_api_violations(script_paths)
        self.assertEqual(
            violations,
            [],
            msg=(
                "scripts/ 下非測試入口若使用 backend.context_cards，只能使用白名單公開 API: "
                + ", ".join(violations)
            ),
        )


if __name__ == "__main__":
    unittest.main()