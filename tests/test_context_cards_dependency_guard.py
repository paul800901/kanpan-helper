from __future__ import annotations

import ast
from pathlib import Path
import unittest


CONTEXT_CARDS_MODULE = "backend.context_cards"
CONTEXT_CARDS_PATH = Path("backend/context_cards.py")
FORBIDDEN_SECOND_PAGE_MODULES = {
    "backend.priority_generation",
    "backend.priority_contract_io",
    "backend.priority_validation",
    "backend.priority_analysis",
    "backend.priority_facade",
}
FORBIDDEN_SECOND_PAGE_PREFIXES = ("backend.priority_",)


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_forbidden_second_page_module(module_name: str) -> bool:
    return module_name in FORBIDDEN_SECOND_PAGE_MODULES or module_name.startswith(FORBIDDEN_SECOND_PAGE_PREFIXES)


def _extract_forbidden_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_second_page_module(alias.name):
                    imports.append((getattr(node, "lineno", -1), alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_forbidden_second_page_module(module):
                imports.append((getattr(node, "lineno", -1), module))
            elif module == "backend":
                for alias in node.names:
                    candidate = f"backend.{alias.name}"
                    if _is_forbidden_second_page_module(candidate):
                        imports.append((getattr(node, "lineno", -1), candidate))

    return imports


class TestContextCardsDependencyGuard(unittest.TestCase):
    def test_context_cards_does_not_depend_on_second_page_internal_layers(self) -> None:
        root = _workspace_root()
        violations = [
            f"{CONTEXT_CARDS_PATH}:{line}:{imported_module}"
            for line, imported_module in _extract_forbidden_imports(root / CONTEXT_CARDS_PATH)
        ]
        self.assertEqual(
            violations,
            [],
            msg=(
                f"{CONTEXT_CARDS_MODULE} 不得反向依賴第二頁內層模組: "
                + ", ".join(violations)
            ),
        )


if __name__ == "__main__":
    unittest.main()