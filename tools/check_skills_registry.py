"""Check Agent2Learn skill registry invariants and reviewed upstream mappings."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import cast
from urllib.request import urlopen

from agent2learn import skills

UPSTREAM_AGENTS_URL = "https://raw.githubusercontent.com/vercel-labs/skills/main/src/agents.ts"
UPSTREAM_KEYS = {
    "Claude Code": "claude-code",
    "Codex": "codex",
    "Cursor": "cursor",
    "Universal Agent Skills target": "universal",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true", help="Fetch reviewed upstream mappings")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    errors = skills.validate_repository_artifacts(args.root)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    print("Agent2Learn skills:", ", ".join(skills.SKILL_SLUGS))
    print("Agent2Learn target mappings:")
    for target in skills.target_registry():
        print(
            f"- {target.agent}: project {target.project_path.as_posix()} | "
            f"global {target.global_path.as_posix()}"
        )

    if not args.network:
        return 0

    upstream = _fetch_upstream()
    print("Reviewed upstream vercel-labs/skills mappings:")
    drift: list[str] = []
    for target in skills.target_registry():
        upstream_key = UPSTREAM_KEYS[target.agent]
        upstream_project, upstream_global = _upstream_paths(upstream, upstream_key)
        expected_project = target.project_path.as_posix()
        expected_global = target.global_path.as_posix()
        print(
            f"- {target.agent}: upstream project {upstream_project} | "
            f"Agent2Learn project {expected_project}; upstream global {upstream_global} | "
            f"Agent2Learn global {expected_global}"
        )
        if upstream_project != expected_project or upstream_global != expected_global:
            drift.append(target.agent)
    if drift:
        print("error: upstream target path drift: " + ", ".join(drift), file=sys.stderr)
        return 1
    return 0


def _fetch_upstream() -> str:
    with urlopen(UPSTREAM_AGENTS_URL, timeout=20) as response:  # noqa: S310 - fixed HTTPS URL
        return cast(bytes, response.read()).decode("utf-8")


def _upstream_paths(source: str, key: str) -> tuple[str, str]:
    block = _agent_block(source, key)
    project = _string_property(block, "skillsDir")
    global_value = _global_path(block)
    return project, global_value


def _agent_block(source: str, key: str) -> str:
    match = re.search(rf"  {re.escape(_quote_key(key))}: \{{(?P<body>.*?)\n  \}},", source, re.S)
    if match is None:
        raise ValueError(f"upstream agent missing: {key}")
    return str(match.group("body"))


def _quote_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_]+", key) else f"'{key}'"


def _string_property(block: str, name: str) -> str:
    match = re.search(rf"{name}: '([^']+)'", block)
    if match is None:
        raise ValueError(f"upstream property missing: {name}")
    return match.group(1)


def _global_path(block: str) -> str:
    if "join(claudeHome, 'skills')" in block:
        return ".claude/skills"
    if "join(codexHome, 'skills')" in block:
        return ".codex/skills"
    if "join(configHome, 'agents/skills')" in block:
        return ".config/agents/skills"
    match = re.search(r"globalSkillsDir: join\(home, '([^']+)'\)", block)
    if match is None:
        raise ValueError("upstream globalSkillsDir shape changed")
    return match.group(1)


if __name__ == "__main__":
    raise SystemExit(main())
