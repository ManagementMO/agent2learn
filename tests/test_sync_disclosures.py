"""A student must see coverage limits even when a different sync phase fails."""

from __future__ import annotations

import pytest

from agent2learn import cli, pipeline
from agent2learn.convert import ConversionReport
from agent2learn.ingest import FileReport, MetadataReport, OutlineReport, TopicRecord

QUIZ_GAP = "quizzes unavailable (HTTP 403; not_authorized; Quizzing.SeeQuizzing)"


def test_failed_conversion_does_not_hide_known_quiz_permission_gap() -> None:
    metadata = MetadataReport(courses=(), topic_count=1, deadline_count=2, gaps=(QUIZ_GAP,))
    report = pipeline.PipelineReport(
        scope="all",
        include_media=False,
        include_grades=False,
        include_discussions=False,
        metadata=metadata,
        outlines=OutlineReport(),
        files=FileReport(downloaded=1),
        conversion=ConversionReport(gaps=1, errors=("synthetic conversion error",)),
        indexed_courses=1,
        snapshot_path=".a2l/snapshots/synthetic.json",
        audit_path=".a2l/AUDIT.md",
        gaps=(QUIZ_GAP,),
        errors=("conversion incomplete",),
        exit_code=1,
    )

    output = pipeline.render_report(report)

    assert "sync incomplete" in output
    assert QUIZ_GAP in output
    assert "2 known deadlines" in output
    assert "sync completed" not in output
    assert "a2l auth" not in output


@pytest.mark.parametrize("gaps", [(), (QUIZ_GAP,)])
def test_live_metadata_summary_qualifies_unverified_deadlines(
    capsys: pytest.CaptureFixture[str], gaps: tuple[str, ...]
) -> None:
    cli._print_sync_metadata(MetadataReport(courses=(), topic_count=1, deadline_count=2, gaps=gaps))

    output = capsys.readouterr().out

    assert ("2 known deadlines" if gaps else "2 deadlines") in output
    assert output.count("metadata ·") == 1


@pytest.mark.parametrize("remote_size", [None, 2_147_483_649])
def test_empty_priority_explains_no_download_and_safe_full_option(
    capsys: pytest.CaptureFixture[str],
    remote_size: int | None,
) -> None:
    topic = TopicRecord(
        source_key="uwaterloo:111111:topic:1",
        source_id="1",
        topic_id=1,
        course_org_unit_id=111111,
        course_code="COURSE101",
        course_name="Synthetic Course",
        term="1269",
        title="Notes.html",
        kind="File",
        module_path=("Notes",),
        module_ids=(1,),
        view_url="https://learn.example.invalid/topic/1",
        outline_url=None,
        url_path="/content/notes.html",
        external_host=None,
        etag=None,
        last_modified=None,
        is_broken=False,
        remote_size=remote_size,
    )

    cli._print_file_estimates([topic])
    output = capsys.readouterr().out

    if remote_size is None:
        assert "unknown sizes" in output
        assert "excluded from priority" in output
    assert "priority will download no documents" in output
    assert "a2l sync --all" in output
    assert "per-file size limit" in output
    assert "--allow-large" not in output
