"""Grounding packs select only current, provenance-backed course sources."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from conftest import strip_ansi
from typer.testing import CliRunner

from agent2learn import config
from agent2learn.cli import app
from agent2learn.errors import A2LError
from agent2learn.ground import (
    assignment_title,
    rank_lectures,
    resolve_item,
    select_sources,
    tok,
    write_grounding_pack,
)
from agent2learn.index import write_content_map
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault

_TIMESTAMP = "2026-08-25T12:00:00Z"


def _add_source(
    vault: Vault,
    course: Path,
    *,
    source_key: str,
    source_id: str,
    relative: str,
    markdown: str,
    title: str,
    module_path: tuple[str, ...],
) -> tuple[dict[str, object], ManifestEntry]:
    source = course / relative
    twin = source.with_suffix(".md")
    source.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = f"source bytes for {source_key}\n".encode()
    twin_bytes = markdown.encode()
    source.write_bytes(source_bytes)
    twin.write_bytes(twin_bytes)
    source_hash = sha256(source_bytes).hexdigest()
    artifact = DerivedArtifact(
        path=twin.relative_to(vault.root).as_posix(),
        sha256=sha256(twin_bytes).hexdigest(),
        source_sha256=source_hash,
        tool="synthetic",
        tool_version="1",
        created_at=_TIMESTAMP,
    )
    entry = ManifestEntry(
        path=source.relative_to(vault.root).as_posix(),
        sha256=source_hash,
        source_id=source_id,
        etag=None,
        last_modified=None,
        size=len(source_bytes),
        fetched_at=_TIMESTAMP,
        derived={"markdown": artifact},
    )
    vault.mark(source_key, entry)
    return (
        {
            "source_key": source_key,
            "source_id": source_id,
            "topic_id": int(source_id.rsplit("-", 1)[-1]),
            "course_code": "COURSE101",
            "course_name": "Synthetic Grounding",
            "term": "1265",
            "title": title,
            "kind": "File",
            "module_path": list(module_path),
            "availability": "markdown_ready",
            "source_path": entry.path,
            "path": artifact.path,
            "sha256": source_hash,
            "source_sha256": source_hash,
        },
        entry,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


@pytest.fixture
def grounding_course(tmp_path: Path) -> tuple[Vault, Path, Path, dict[str, ManifestEntry]]:
    root = Vault.claim(tmp_path / "vault")
    vault = Vault(root)
    course = root / "Spring 2026" / "COURSE101_1265"
    assignment = course / "assignments" / "Lab4"
    rows: list[dict[str, object]] = []
    entries: dict[str, ManifestEntry] = {}

    prompt_key = "uwaterloo:101:dropbox:4"
    prompt_row, prompt_entry = _add_source(
        vault,
        course,
        source_key=prompt_key,
        source_id="4",
        relative="assignments/Lab4/instructions.html",
        markdown="# Lab 4\n\nUse network flow capacity data.\n",
        title="Lab 4",
        module_path=("Assignments", "Lab 4"),
    )
    del prompt_row
    entries[prompt_key] = prompt_entry

    for key, source_id, relative, markdown, title, modules in (
        (
            "uwaterloo:101:attachment:4-1",
            "4-1",
            "content/Assignments/Lab 4/input.csv",
            "node,capacity\na,3\n",
            "input.csv",
            ("Assignments", "Lab 4"),
        ),
        (
            "uwaterloo:101:topic:10",
            "10",
            "content/Outlines/Course Outline.html",
            "# Course outline\n\nNetwork flow policy and schedule.\n",
            "Course Outline",
            ("Outlines",),
        ),
        (
            "uwaterloo:101:topic:20",
            "20",
            "content/Lectures/A Lecture.pdf",
            "network flow capacity deterministicterm\n",
            "A Lecture",
            ("Lectures",),
        ),
        (
            "uwaterloo:101:topic:21",
            "21",
            "content/Lectures/Z Lecture.pdf",
            "network flow capacity deterministicterm\n",
            "Z Lecture",
            ("Lectures",),
        ),
        (
            "uwaterloo:101:topic:22",
            "22",
            "content/Lectures/Unrelated.pdf",
            "a topic with no query overlap\n",
            "Unrelated",
            ("Lectures",),
        ),
        (
            "uwaterloo:101:topic:30",
            "30",
            "content/Lectures/Stale Twin.pdf",
            "network flow capacity network flow capacity\n",
            "Stale Twin",
            ("Lectures",),
        ),
        (
            "uwaterloo:101:topic:31",
            "31",
            "content/Lectures/Stale Source.pdf",
            "network flow capacity network flow capacity\n",
            "Stale Source",
            ("Lectures",),
        ),
    ):
        row, entry = _add_source(
            vault,
            course,
            source_key=key,
            source_id=source_id,
            relative=relative,
            markdown=markdown,
            title=title,
            module_path=modules,
        )
        rows.append(row)
        entries[key] = entry

    vault.save_manifest()
    write_content_map(course, rows)
    _write_json(
        course / "_meta" / "assignments.json",
        [
            {
                "id": 4,
                "title": "Lab 4",
                "instructions_html": prompt_entry.path,
                "instructions_md": prompt_entry.derived["markdown"].path,
                "instructions_sha256": prompt_entry.sha256,
            }
        ],
    )
    _write_json(
        course / "_meta" / "outlines.json",
        [{"source_key": "uwaterloo:101:topic:10", "status": "rendered"}],
    )

    # Both stale files keep strong query overlap on purpose. If they were merely off-topic the
    # pack would exclude them for scoring reasons and the freshness gates would never be tested.
    (course / "content" / "Lectures" / "Stale Twin.md").write_text(
        "network flow capacity network flow capacity locally modified\n", encoding="utf-8"
    )
    (course / "content" / "Lectures" / "Stale Source.pdf").write_bytes(b"changed source")

    for path, text in (
        (assignment / "DRAFT_old.md", "network flow capacity"),
        (assignment / "solution.md", "network flow capacity"),
        (assignment / "untracked-data.md", "network flow capacity"),
        (assignment / "GROUNDING.md", "old generated report"),
        (course / "INDEX.md", "network flow capacity"),
        (course / "check-report.md", "network flow capacity"),
        # Sits where lectures live and outscores every real lecture on the ranking query, so only
        # provenance can keep it out. A filename glob would rank it first.
        (
            course / "content" / "Lectures" / "untracked-solution.md",
            "deterministicterm deterministicterm " + "network flow " * 20,
        ),
        (root / ".a2l" / "AUDIT.md", "network flow capacity"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8", newline="\n")

    return vault, course, assignment, entries


def test_tokenizer_splits_letter_digit_boundaries() -> None:
    assert tok("Lab4") == ["lab4", "lab", "4"]
    assert tok("LAB4") == ["lab4", "lab", "4"]
    assert tok("lab_4") == ["lab", "4"]
    assert tok("Lab 4") == ["lab", "4"]
    assert tok("Lab4A") == ["lab4a", "lab", "4"]
    assert tok("Assignment 1") == ["assignment", "1"]
    assert tok("Café") == ["caf"]


def test_lab4_and_lab_space_4_resolve_to_the_same_assignment(
    grounding_course: tuple[Vault, Path, Path, dict[str, ManifestEntry]],
) -> None:
    _vault, course, assignment, _entries = grounding_course

    assert resolve_item(course, "Lab4") == assignment
    assert resolve_item(course, "Lab 4") == assignment


def test_ranked_lecture_ties_are_path_deterministic_and_ignore_unknown_files(
    grounding_course: tuple[Vault, Path, Path, dict[str, ManifestEntry]],
) -> None:
    _vault, course, _assignment, _entries = grounding_course

    ranked = rank_lectures(course, "deterministicterm", exclude=set())

    assert [path.name for path in ranked] == ["A Lecture.md", "Z Lecture.md"]


def test_rank_lectures_preserves_repeated_query_term_weight(
    grounding_course: tuple[Vault, Path, Path, dict[str, ManifestEntry]],
) -> None:
    _vault, course, _assignment, _entries = grounding_course
    (course / "content" / "Lectures" / "A Lecture.md").write_text(
        "duality sensitivity sensitivity sensitivity\n", encoding="utf-8", newline="\n"
    )
    (course / "content" / "Lectures" / "Z Lecture.md").write_text(
        "duality duality sensitivity\n", encoding="utf-8", newline="\n"
    )

    ranked = rank_lectures(
        course,
        "duality duality duality duality sensitivity",
        exclude=set(),
    )

    assert [path.name for path in ranked[:2]] == ["Z Lecture.md", "A Lecture.md"]


def test_pack_lists_every_verified_source_and_excludes_stale_or_generated_material(
    grounding_course: tuple[Vault, Path, Path, dict[str, ManifestEntry]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, course, assignment, entries = grounding_course
    monkeypatch.setattr("agent2learn.ground.clock.stamp", lambda: _TIMESTAMP)

    selected = select_sources(vault, course, "Lab4")
    pack = write_grounding_pack(vault, "COURSE101", "Lab 4")
    text = pack.path.read_text(encoding="utf-8")

    assert [(source.role, source.source_key) for source in selected] == [
        ("assignment_prompt", "uwaterloo:101:dropbox:4"),
        ("assignment_data", "uwaterloo:101:attachment:4-1"),
        ("course_outline", "uwaterloo:101:topic:10"),
        ("lecture", "uwaterloo:101:topic:20"),
        ("lecture", "uwaterloo:101:topic:21"),
    ]
    assert pack.path == assignment / "GROUNDING.md"
    assert pack.sources == selected
    assert "Read every file listed below before using this pack." in text
    for source in pack.sources:
        assert text.count(f"`{source.citation_path}:1`") == 1
        assert source.source_sha256 in text
        assert source.derived_sha256 in text
        assert entries[source.source_key].sha256 == source.source_sha256
    for forbidden in (
        "DRAFT_old.md",
        "solution.md",
        "untracked-data.md",
        "INDEX.md",
        "AUDIT.md",
        "check-report.md",
        "Stale Twin.md",
        "Stale Source.md",
    ):
        assert forbidden not in text


def test_unproven_assignment_prompt_and_data_never_enter_the_source_set(tmp_path: Path) -> None:
    root = Vault.claim(tmp_path / "vault")
    vault = Vault(root)
    course = root / "Term" / "COURSE101"
    assignment = course / "assignments" / "Lab 4"
    assignment.mkdir(parents=True)
    unproven_prompt = assignment / "instructions.md"
    unproven_prompt.write_text("invented prompt text\n", encoding="utf-8")
    (assignment / "data.md").write_text("invented data\n", encoding="utf-8")

    lecture_row, _lecture_entry = _add_source(
        vault,
        course,
        source_key="uwaterloo:101:topic:1",
        source_id="1",
        relative="content/Lecture.pdf",
        markdown="Lab4 retrieval material\n",
        title="Lecture",
        module_path=("Lectures",),
    )
    vault.save_manifest()
    fake_attachment = {
        "source_key": "uwaterloo:101:attachment:4-2",
        "source_id": "4-2",
        "topic_id": 2,
        "course_code": "COURSE101",
        "title": "data.md",
        "kind": "File",
        "module_path": ["Assignments", "Lab 4"],
        "availability": "markdown_ready",
        "source_path": "Term/COURSE101/assignments/Lab 4/data.csv",
        "path": "Term/COURSE101/assignments/Lab 4/data.md",
    }
    write_content_map(course, [lecture_row, fake_attachment])
    _write_json(
        course / "_meta" / "assignments.json",
        [
            {
                "id": 4,
                "title": "Lab 4",
                "instructions_html": "Term/COURSE101/assignments/Lab 4/instructions.html",
                "instructions_md": unproven_prompt.relative_to(root).as_posix(),
                "instructions_sha256": "0" * 64,
            }
        ],
    )
    _write_json(course / "_meta" / "outlines.json", [])

    selected = select_sources(vault, course, "Lab4")

    assert [(source.role, source.source_key) for source in selected] == [
        ("lecture", "uwaterloo:101:topic:1")
    ]


def test_public_ground_command_is_local_and_has_no_solve_option(
    grounding_course: tuple[Vault, Path, Path, dict[str, ManifestEntry]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, _course, assignment, _entries = grounding_course
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=vault.root))
    monkeypatch.setattr("agent2learn.ground.clock.stamp", lambda: _TIMESTAMP)
    runner = CliRunner()

    result = runner.invoke(app, ["ground", "COURSE101", "Lab4"])
    solve = runner.invoke(app, ["ground", "COURSE101", "Lab4", "--solve"])
    help_result = runner.invoke(app, ["ground", "--help"])

    assert result.exit_code == 0
    assert strip_ansi(result.stdout) == (
        "grounding pack: Spring 2026/COURSE101_1265/assignments/Lab4/GROUNDING.md\n"
    )
    assert (assignment / "GROUNDING.md").is_file()
    assert solve.exit_code == 2
    assert "No such option: --solve" in strip_ansi(solve.output)
    assert help_result.exit_code == 0
    assert "--solve" not in strip_ansi(help_result.output)


# ------------------------------------------------------------------------------------------
# The production pipeline names assignment folders ``{title} {dropbox id}`` (see
# ingest.py) so two assignments with one title cannot collide. Grounding must accept the
# title a student actually types, the bare id, and the folder name itself, and must map every
# form back to the assignments.json title that drives prompt lookup and data matching.
# ------------------------------------------------------------------------------------------


def _pipeline_shaped_course(
    tmp_path: Path, *, titles: tuple[tuple[str, int], ...]
) -> tuple[Vault, Path]:
    root = Vault.claim(tmp_path / "vault")
    vault = Vault(root)
    course = root / "Term 1261" / "COURSE101_sec01_1261_1261"
    for title, folder_id in titles:
        (course / "assignments" / f"{title} {folder_id}").mkdir(parents=True)
    rows: list[dict[str, object]] = []
    row, _entry = _add_source(
        vault,
        course,
        source_key="uwaterloo:101:topic:20",
        source_id="20",
        relative="content/Lectures/Flow.pdf",
        markdown="Practice upload material about network flow capacity.\n",
        title="Flow",
        module_path=("Lectures",),
    )
    rows.append(row)
    vault.save_manifest()
    write_content_map(course, rows)
    _write_json(
        course / "_meta" / "assignments.json",
        [{"id": folder_id, "title": title} for title, folder_id in titles],
    )
    _write_json(course / "_meta" / "outlines.json", [])
    return vault, course


@pytest.mark.parametrize(
    "item", ["Practice Upload", "practice upload", "700002", "Practice Upload 700002"]
)
def test_pipeline_named_folders_resolve_from_title_id_or_folder_name(
    tmp_path: Path, item: str
) -> None:
    _vault, course = _pipeline_shaped_course(tmp_path, titles=(("Practice Upload", 700002),))

    assert resolve_item(course, item) == course / "assignments" / "Practice Upload 700002"


def test_every_item_form_maps_back_to_the_assignments_json_title(tmp_path: Path) -> None:
    _vault, course = _pipeline_shaped_course(tmp_path, titles=(("Practice Upload", 700002),))

    for item in ("Practice Upload", "700002", "Practice Upload 700002"):
        assert assignment_title(course, item, fallback="x") == "Practice Upload", item


def test_same_titled_assignments_require_the_id_form(tmp_path: Path) -> None:
    _vault, course = _pipeline_shaped_course(tmp_path, titles=(("Quiz", 700010), ("Quiz", 700011)))

    with pytest.raises(A2LError, match="ambiguous"):
        resolve_item(course, "Quiz")
    assert resolve_item(course, "700011") == course / "assignments" / "Quiz 700011"
    assert resolve_item(course, "Quiz 700010") == course / "assignments" / "Quiz 700010"


def test_ranking_terms_come_from_the_title_not_the_folder_id(tmp_path: Path) -> None:
    """A folder id is not a lecture term; it must never inflate or poison retrieval."""
    vault, course = _pipeline_shaped_course(tmp_path, titles=(("Practice Upload", 700002),))

    selected = select_sources(vault, course, "Practice Upload 700002")

    assert [source.role for source in selected] == ["lecture"]


def test_an_empty_pack_names_the_real_cause_not_sync(tmp_path: Path) -> None:
    """Verified material exists; nothing matched this item. Blaming sync is a false next action."""
    vault, course = _pipeline_shaped_course(tmp_path, titles=(("Team Report", 700003),))
    from agent2learn.index import resolve_course as _rc  # noqa: F401

    with pytest.raises(A2LError) as raised:
        write_grounding_pack(vault, "COURSE101", "Team Report")

    message = str(raised.value)
    assert "a2l sync" not in message
    assert "Team Report" in message
    assert "matched" in message or "match" in message
