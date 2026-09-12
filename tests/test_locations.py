from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from ingest_support import FakeClient, course

from agent2learn.convert import convert_vault
from agent2learn.errors import A2LError
from agent2learn.ground import resolve_item, select_sources
from agent2learn.index import resolve_course
from agent2learn.ingest import ingest_files, ingest_metadata
from agent2learn.vault import Vault

pytestmark = pytest.mark.usefixtures("no_network")


def _toc() -> dict[str, object]:
    return {
        "Modules": [
            {
                "ModuleId": 1,
                "Title": "Week 1",
                "Modules": [],
                "Topics": [
                    {
                        "TopicId": 1,
                        "Title": "Lecture.txt",
                        "TypeIdentifier": "File",
                        "Url": "/lecture.txt",
                    }
                ],
            }
        ]
    }


def _assignment(identifier: int, title: str, *, prompt: bool = True) -> dict[str, object]:
    row: dict[str, object] = {"Id": identifier, "Name": title}
    if prompt:
        row["CustomInstructions"] = {"Html": "<p>Use the class network model.</p>"}
    return row


@pytest.mark.parametrize("long_codes", [False, True])
def test_distinct_course_ids_never_share_metadata_or_user_files(
    tmp_path: Path, long_codes: bool
) -> None:
    prefix = "COURSE_" + "INTERDISCIPLINARY_" * 5 if long_codes else "COURSE101"
    first = course(111111, code=prefix + "_A" if long_codes else prefix)
    second = course(222222, code=prefix + "_B" if long_codes else prefix)
    client = FakeClient(
        [first, second],
        responses={
            "/111111/dropbox/folders/": [_assignment(1, "First course work", prompt=False)],
            "/222222/dropbox/folders/": [_assignment(2, "Second course work", prompt=False)],
        },
    )
    vault = Vault(Vault.claim(tmp_path / "vault"))

    metadata = ingest_metadata(client, vault, client.school)

    assert len({entry.directory for entry in metadata.courses}) == 2
    rows = [
        json.loads((entry.directory / "_meta/assignments.json").read_text(encoding="utf-8"))
        for entry in metadata.courses
    ]
    assert [{row["id"] for row in values} for values in rows] == [{1}, {2}]
    assert all(row["missing_since"] is None for values in rows for row in values)


@pytest.mark.parametrize(
    "state", ["empty", "metadata", "manifest", "legacy-metadata", "legacy-manifest"]
)
def test_course_renames_reuse_proven_paths_without_moving_student_work(
    tmp_path: Path, state: str
) -> None:
    original = course()
    client = FakeClient([original], tocs={} if state == "empty" else {111111: _toc()})
    vault = Vault(Vault.claim(tmp_path / "vault"))
    first = ingest_metadata(client, vault, client.school).courses[0].directory
    if "manifest" in state:
        ingest_files(client, vault, client.school)
    if state.startswith("legacy-"):
        (first / "_meta/course.json").unlink(missing_ok=True)
    note = first / "DRAFT.md"
    note.write_bytes(b"Student work must not move.\n")
    client.courses = [replace(original, code="RENAMED101", name="Renamed course")]

    second = ingest_metadata(client, vault, client.school).courses[0].directory

    assert second == first
    assert note.read_bytes() == b"Student work must not move.\n"
    assert resolve_course(vault, "RENAMED101") == first


@pytest.mark.parametrize("prompt", [False, True])
def test_truncated_assignment_names_resolve_by_stable_id_without_sharing_folders(
    tmp_path: Path, prompt: bool
) -> None:
    prefix = "Assignment 1 - Network flow analysis, sensitivity, and interpretation "
    client = FakeClient(
        [course()],
        responses={
            "/dropbox/folders/": [
                _assignment(700001, prefix + "one", prompt=prompt),
                _assignment(700002, prefix + "two", prompt=prompt),
            ]
        },
    )
    vault = Vault(Vault.claim(tmp_path / "vault"))
    directory = ingest_metadata(client, vault, client.school).courses[0].directory

    first = resolve_item(directory, "700001")
    second = resolve_item(directory, "700002")

    assert first != second
    assert resolve_item(directory, prefix + "one") == first
    assert resolve_item(directory, prefix + "two") == second
    assert all(len(path.name) <= 60 for path in (first, second))


@pytest.mark.parametrize("prompt", [False, True])
def test_legacy_assignment_rename_keeps_its_existing_directory(
    tmp_path: Path, prompt: bool
) -> None:
    client = FakeClient(
        [course()],
        responses={"/dropbox/folders/": [_assignment(700001, "Problem Set 1", prompt=prompt)]},
    )
    vault = Vault(Vault.claim(tmp_path / "vault"))
    directory = ingest_metadata(client, vault, client.school).courses[0].directory
    original = resolve_item(directory, "700001")
    metadata_path = directory / "_meta/assignments.json"
    rows = json.loads(metadata_path.read_text(encoding="utf-8"))
    rows[0].pop("directory", None)
    metadata_path.write_text(json.dumps(rows), encoding="utf-8")
    draft = original / "DRAFT.md"
    draft.write_bytes(b"Existing answer draft.\n")
    client.responses["/dropbox/folders/"] = [_assignment(700001, "Network Exercise", prompt=prompt)]

    ingest_metadata(client, vault, client.school)

    assert resolve_item(directory, "700001") == original
    assert resolve_item(directory, "Network Exercise") == original
    assert draft.read_bytes() == b"Existing answer draft.\n"


def test_adding_a_prompt_reuses_the_hub_and_preserves_unowned_instructions(tmp_path: Path) -> None:
    client = FakeClient(
        [course()],
        responses={"/dropbox/folders/": [_assignment(700001, "Problem Set 1", prompt=False)]},
    )
    vault = Vault(Vault.claim(tmp_path / "vault"))
    directory = ingest_metadata(client, vault, client.school).courses[0].directory
    original = resolve_item(directory, "700001")
    draft = original / "DRAFT.md"
    draft.write_bytes(b"Existing answer draft.\n")
    unowned = original / "instructions.md"
    unowned.write_bytes(b"Student's existing notes.\n")
    client.responses["/dropbox/folders/"] = [_assignment(700001, "Problem Set 1")]

    ingest_metadata(client, vault, client.school)

    entry = vault.entry("uwaterloo:111111:dropbox:700001")
    assert entry is not None and (vault.root / entry.path).parent == original
    assert draft.read_bytes() == b"Existing answer draft.\n"
    assert unowned.read_bytes() == b"Student's existing notes.\n"
    twin = vault.root / entry.derived["markdown"].path
    before = twin.read_bytes()
    assert twin != unowned and twin.parent == original
    assert convert_vault(vault).skipped == 1
    assert twin.read_bytes() == before
    assert any(
        item.role == "assignment_prompt" for item in select_sources(vault, directory, "700001")
    )


def test_ambiguous_legacy_course_ownership_is_not_guessed(tmp_path: Path) -> None:
    vault = Vault(Vault.claim(tmp_path / "vault"))
    client = FakeClient([course()], tocs={111111: _toc()})
    original = ingest_metadata(client, vault, client.school).courses[0].directory
    (original / "_meta/course.json").unlink(missing_ok=True)
    other = original.with_name("Other legacy copy")
    (other / "_meta").mkdir(parents=True)
    payload = (original / "_meta/content_map.json").read_bytes()
    (other / "_meta/content_map.json").write_bytes(payload)

    with pytest.raises(A2LError, match="ambiguous|ownership"):
        ingest_metadata(client, vault, client.school)

    assert (original / "_meta/content_map.json").read_bytes() == payload
    assert (other / "_meta/content_map.json").read_bytes() == payload


@pytest.mark.parametrize("bad_version", [None, True, 1.0])
def test_invalid_course_ownership_is_refused_before_it_can_be_reassigned(
    tmp_path: Path, bad_version: object
) -> None:
    vault = Vault(Vault.claim(tmp_path / "vault"))
    client = FakeClient([course()], tocs={111111: _toc()})
    directory = ingest_metadata(client, vault, client.school).courses[0].directory
    ownership = directory / "_meta/course.json"
    raw = json.loads(ownership.read_text(encoding="utf-8"))
    raw["schema_version"] = bad_version
    payload = None if bad_version is None else raw
    ownership.write_text(json.dumps(payload), encoding="utf-8")
    before = ownership.read_bytes()

    with pytest.raises(A2LError, match="ownership"):
        ingest_metadata(client, vault, client.school)

    assert ownership.read_bytes() == before


def test_assignment_binding_cannot_escape_the_selected_course(tmp_path: Path) -> None:
    vault = Vault(Vault.claim(tmp_path / "vault"))
    client = FakeClient([course()], responses={"/dropbox/folders/": [_assignment(700001, "Lab 1")]})
    directory = ingest_metadata(client, vault, client.school).courses[0].directory
    metadata = directory / "_meta/assignments.json"
    rows = json.loads(metadata.read_text(encoding="utf-8"))
    rows[0]["directory"] = "../unrelated"
    metadata.write_text(json.dumps(rows), encoding="utf-8")
    before = metadata.read_bytes()

    with pytest.raises(A2LError, match="ownership"):
        ingest_metadata(client, vault, client.school)

    assert metadata.read_bytes() == before
