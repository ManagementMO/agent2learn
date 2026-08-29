"""The evidence scan cites course material and never claims correctness."""

from __future__ import annotations

import json
import os
import time
from hashlib import sha256
from pathlib import Path

import pytest
from conftest import flatten_help, strip_ansi
from typer.testing import CliRunner

from agent2learn import config
from agent2learn.check import (
    CANDIDATE_FLOOR_BP,
    CHECK_ALGORITHM_VERSION,
    DISCLOSURE,
    STRONG_MATCH_FLOOR_BP,
    Claim,
    LineIndex,
    ScanSource,
    check,
    exact_score,
    render,
    render_json,
    score_bp,
    segment,
)
from agent2learn.cli import app
from agent2learn.errors import A2LError
from agent2learn.index import write_content_map
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault

_TIMESTAMP = "2026-08-25T12:00:00Z"
_MATERIAL = Path(__file__).parent / "fixtures" / "check"


def _register(vault: Vault, course: Path, name: str, source_id: str) -> dict[str, object]:
    """Archive one fixture twin with the provenance the scan requires."""
    twin = course / "content" / f"{name}.md"
    source = course / "content" / f"{name}.pdf"
    twin.parent.mkdir(parents=True, exist_ok=True)
    twin_bytes = (_MATERIAL / f"{name}.md").read_bytes()
    source_bytes = f"synthetic source bytes for {name}\n".encode()
    twin.write_bytes(twin_bytes)
    source.write_bytes(source_bytes)
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
    vault.mark(f"uwaterloo:101:topic:{source_id}", entry)
    return {
        "source_key": f"uwaterloo:101:topic:{source_id}",
        "source_id": source_id,
        "topic_id": int(source_id),
        "course_code": "COURSE101",
        "course_name": "Synthetic Optimisation",
        "term": "1265",
        "title": name.replace("-", " "),
        "kind": "File",
        "module_path": ["Lectures"],
        "availability": "markdown_ready",
        "source_path": entry.path,
        "path": artifact.path,
        "sha256": source_hash,
        "source_sha256": source_hash,
    }


@pytest.fixture
def fixture_course(tmp_path: Path) -> tuple[Vault, Path]:
    root = Vault.claim(tmp_path / "vault")
    vault = Vault(root)
    course = root / "Spring 2026" / "COURSE101_1265"
    rows = [
        _register(vault, course, "MIP-Modelling", "20"),
        _register(vault, course, "Duality-in-LP", "21"),
        _register(vault, course, "Two-Stage-Stochastic-Programming", "22"),
        {
            "source_key": "uwaterloo:101:topic:70",
            "source_id": "70",
            "topic_id": 70,
            "course_code": "COURSE101",
            "course_name": "Synthetic Optimisation",
            "term": "1265",
            "title": "Week 7 Decomposition",
            "kind": "File",
            "module_path": ["Lectures"],
            "availability": "metadata_only",
            "source_path": None,
            "path": None,
            "next_action": "a2l fetch 70",
        },
    ]
    vault.save_manifest()
    write_content_map(course, rows)
    return vault, course


def _draft(tmp_path: Path, text: str, *, name: str = "DRAFT_lab4.md") -> Path:
    destination = tmp_path / name
    destination.write_text(text + "\n", encoding="utf-8", newline="\n")
    return destination


def test_matching_evidence_is_cited(fixture_course: tuple[Vault, Path], tmp_path: Path) -> None:
    _vault, course = fixture_course

    report = check(_draft(tmp_path, "we use binary variables y_i in {0,1}"), course)

    finding = report.findings[0]
    assert finding.status == "evidence_found"
    assert finding.citations[0].path.endswith("MIP-Modelling.md")
    assert finding.citations[0].retrieval_score_bp >= STRONG_MATCH_FLOOR_BP


def test_no_matching_evidence_names_no_source(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course

    report = check(_draft(tmp_path, "apply Benders decomposition"), course)

    finding = report.findings[0]
    assert finding.status == "no_matching_evidence"
    assert finding.citations == []
    assert finding.note is not None
    assert "no matching evidence" in finding.note


def test_connective_prose_is_skipped(fixture_course: tuple[Vault, Path], tmp_path: Path) -> None:
    _vault, course = fixture_course

    report = check(_draft(tmp_path, "Next, we consider the following."), course)

    assert report.findings[0].status == "skipped"
    assert report.findings[0].citations == []


def test_empty_source_set_is_an_error_not_a_pass(tmp_path: Path) -> None:
    draft = _draft(tmp_path, "we use binary variables y_i in {0,1}")

    with pytest.raises(A2LError):
        check(draft, tmp_path / "not-a-course")


def test_a_vault_with_no_verified_material_is_an_error(tmp_path: Path) -> None:
    root = Vault.claim(tmp_path / "vault")
    course = root / "Spring 2026" / "COURSE101_1265"
    write_content_map(course, [])
    draft = _draft(tmp_path, "we use binary variables y_i in {0,1}")

    with pytest.raises(A2LError):
        check(draft, course)


def test_path_null_reports_coverage_gap(fixture_course: tuple[Vault, Path], tmp_path: Path) -> None:
    _vault, course = fixture_course

    report = check(_draft(tmp_path, "use the decomposition from Week 7"), course)

    gap = report.coverage_gaps[0]
    assert gap.fetch_command is not None
    assert gap.fetch_command.startswith("a2l fetch ")
    assert gap.availability == "metadata_only"


def test_user_authored_and_generated_files_are_never_evidence(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course
    claim = "use an invented frobnication method"
    # Both siblings would score a perfect match if the scan trusted the filesystem.
    for name in ("DRAFT_old.md", "GROUNDING.md", "INDEX.md"):
        (course / "content" / name).write_text(
            f"We {claim} here.\n", encoding="utf-8", newline="\n"
        )

    report = check(_draft(tmp_path, claim), course)

    assert report.findings[0].status == "no_matching_evidence"
    assert report.findings[0].citations == []


def test_a_draft_never_cites_itself(fixture_course: tuple[Vault, Path]) -> None:
    _vault, course = fixture_course
    draft = course / "content" / "MIP-Modelling.md"

    report = check(draft, course)

    cited = {citation.path for finding in report.findings for citation in finding.citations}
    assert draft.relative_to(course.parent.parent).as_posix() not in cited


def test_opposite_comparison_operators_are_offered_for_comparison(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course

    report = check(
        _draft(tmp_path, "The relaxation gap is less than zero for degenerate instances."),
        course,
    )

    finding = report.findings[0]
    assert finding.status == "possible_conflict"
    assert finding.citations[0].path.endswith("MIP-Modelling.md")
    assert finding.note is not None
    assert "may say something different" in finding.note


def test_opposite_polarity_is_offered_for_comparison(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course

    report = check(_draft(tmp_path, "The dual is not bounded at optimality."), course)

    assert report.findings[0].status == "possible_conflict"


def test_a_differing_number_alone_is_never_a_conflict(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course

    report = check(_draft(tmp_path, "We solve the teaching instance with n = 20 machines."), course)

    finding = report.findings[0]
    assert finding.status == "related_evidence"
    assert finding.citations[0].retrieval_score_bp >= CANDIDATE_FLOOR_BP


def test_notation_reports_a_candidate_without_asserting_the_correct_term(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course

    report = check(
        _draft(tmp_path, "Every cost coefficents value scales one decision variable."),
        course,
    )

    flagged = {item.term: item for item in report.notation}
    assert "coefficents" in flagged
    candidate = flagged["coefficents"]
    assert candidate.candidate == "coefficient"
    assert candidate.citation is not None
    assert candidate.citation.path.endswith("MIP-Modelling.md")


def test_segmentation_separates_code_formula_and_steps() -> None:
    draft = "\n".join(
        [
            "We define the primal problem.",
            "",
            "1. Take the dual of the relaxation.",
            "",
            "```python",
            "solver.optimize(model)",
            "```",
            "",
            "$$",
            "x_1 + x_2 <= 4",
            "$$",
        ]
    )

    claims = segment(draft, ".md")

    kinds = {claim.kind for claim in claims}
    assert "code" in kinds
    assert "step" in kinds
    assert "formula" in kinds
    assert [claim.line for claim in claims] == sorted(claim.line for claim in claims)


def test_notebook_code_cells_become_one_claim_each() -> None:
    notebook = json.dumps(
        {
            "cells": [
                {"cell_type": "markdown", "source": ["We use binary variables.\n"]},
                {"cell_type": "code", "source": ["import model\n", "model.solve()\n"]},
                {"cell_type": "code", "source": ["print(model.objective)\n"]},
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )

    claims = segment(notebook, ".ipynb")

    assert [claim.kind for claim in claims].count("code") == 2


def test_rendered_report_leads_with_the_experimental_disclosure(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course
    report = check(_draft(tmp_path, "we use binary variables y_i in {0,1}"), course)

    text = render(report)

    assert text.splitlines()[0].strip() == DISCLOSURE
    for forbidden in ("verified", "correct", "contradicted", "graded", "proves"):
        assert forbidden not in text.casefold().replace("not proof", "")


def test_json_report_pins_algorithm_and_source_revisions(
    fixture_course: tuple[Vault, Path], tmp_path: Path
) -> None:
    _vault, course = fixture_course
    report = check(_draft(tmp_path, "we use binary variables y_i in {0,1}"), course)

    payload = json.loads(render_json(report))

    assert payload["check_algorithm_version"] == CHECK_ALGORITHM_VERSION
    assert payload["disclosure"] == DISCLOSURE
    claim = payload["findings"][0]
    assert set(claim) >= {"line", "text", "status", "score_bp", "citations", "note"}
    revision = payload["revisions"][claim["citations"][0]["path"]]
    assert set(revision) == {"source_sha256", "derived_sha256"}


def test_strict_exit_code_and_help_disclaim_proof(
    fixture_course: tuple[Vault, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, _course = fixture_course
    monkeypatch.setattr(config, "load", lambda: config.Config(vault=vault.root))
    draft = _draft(tmp_path, "apply Benders decomposition")
    runner = CliRunner()

    lenient = runner.invoke(app, ["check", str(draft), "--course", "COURSE101"])
    strict = runner.invoke(app, ["check", str(draft), "--course", "COURSE101", "--strict"])
    help_result = runner.invoke(app, ["check", "--help"])

    assert lenient.exit_code == 0
    assert strict.exit_code != 0
    assert DISCLOSURE in strip_ansi(lenient.stdout)
    flattened = flatten_help(help_result.output)
    assert "not proof of correctness, incorrectness, policy compliance" in flattened
    assert "academic integrity" in flattened


@pytest.mark.benchmark
def test_one_hundred_claims_against_fifty_thousand_lines(tmp_path: Path) -> None:
    """The retrieval budget, measured rather than asserted by default.

    The spec targets under two seconds for 100 claims against a 50,000-line corpus on a two-core
    runner. Wall-clock is noisy on shared CI, so the timing is only enforced when
    ``A2L_BENCHMARK_STRICT`` is set; correctness and scale are always checked.
    """
    corpus = tmp_path / "corpus.md"
    corpus.write_text(
        "\n".join(
            f"Line {number} discusses dual simplex pivoting for instance {number % 97}."
            for number in range(50_000)
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sources = [
        ScanSource(
            path=corpus,
            citation_path="Term/COURSE/content/corpus.md",
            source_sha256="a" * 64,
            derived_sha256="b" * 64,
        )
    ]
    claims = [
        Claim(line=number, text=f"dual simplex pivoting for instance {number}", kind="prose")
        for number in range(100)
    ]

    started = time.perf_counter()
    index = LineIndex(sources)
    results = [index.retrieve(claim) for claim in claims]
    elapsed = time.perf_counter() - started

    assert len(index) == 50_000
    assert all(result for result in results)
    print(f"\n100 claims / 50,000 lines in {elapsed:.2f}s")
    if os.environ.get("A2L_BENCHMARK_STRICT"):
        assert elapsed < 2.0, f"retrieval budget exceeded: {elapsed:.2f}s"


@pytest.mark.parametrize("total_terms", range(1, 7))
@pytest.mark.parametrize("total_values", range(0, 4))
def test_integer_scoring_equals_the_rational_definition(
    total_terms: int, total_values: int
) -> None:
    """The fast path must be the rational formula, not an approximation of it."""
    for matched_terms in range(total_terms + 1):
        for matched_values in range(total_values + 1):
            expected = int(
                exact_score(matched_terms, total_terms, matched_values, total_values) * 10_000
            )
            assert score_bp(matched_terms, total_terms, matched_values, total_values) == expected
