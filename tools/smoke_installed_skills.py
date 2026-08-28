"""Prove an installed wheel exposes four skills and a declined preview writes nothing."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from agent2learn.skills import SKILL_SLUGS, install, source_root


def main() -> int:
    root = source_root()
    discovered = tuple(sorted(path.parent.name for path in root.glob("*/SKILL.md")))
    if discovered != tuple(sorted(SKILL_SLUGS)):
        raise RuntimeError("installed wheel does not expose exactly four canonical skills")

    with TemporaryDirectory() as value:
        project = Path(value) / "vault"
        (project / ".agents").mkdir(parents=True)
        result = install(
            scope="project",
            project=project,
            source_root=root,
            confirm=lambda _preview: False,
        )
        if not result.cancelled or (project / ".agents" / "skills").exists():
            raise RuntimeError("declined installed-wheel skill preview wrote project state")
    print("installed wheel skills: 4 found; declined preview wrote nothing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
