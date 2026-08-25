"""Keep filesystem naming and atomic replacement centralized in ``paths.py``."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[1] / "src"


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def test_forbidden_filesystem_primitives_are_only_called_from_paths() -> None:
    forbidden = {"os.chmod", "os.replace", "os.path.join"}

    for source_path in SRC.rglob("*.py"):
        if source_path.name == "paths.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _dotted_name(node.func)
            assert called not in forbidden, f"{called} escaped paths.py in {source_path}"


def test_collision_helpers_do_not_use_exists_as_the_collision_check() -> None:
    paths_file = SRC / "agent2learn" / "paths.py"
    if not paths_file.exists():
        return

    tree = ast.parse(paths_file.read_text(encoding="utf-8"), filename=str(paths_file))
    collision_names = {"collides", "unique_path"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in collision_names:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            assert child.func.attr != "exists", (
                f"{node.name} must scan normalized directory entries, not call exists()"
            )
