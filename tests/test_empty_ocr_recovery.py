"""Empty recognition is an unresolved page, not evidence of a missing OCR installation."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from conftest import FILES, fixture_bytes

from agent2learn import convert
from agent2learn import index as course_index
from agent2learn.ground import verified_sources
from agent2learn.vault import ManifestEntry, Vault


@pytest.fixture
def mapped_pdf(tmp_path: Path) -> tuple[Vault, Path]:
    vault = Vault(tmp_path / "vault")
    course_dir = vault.root / "Winter 2026" / "COURSE101"
    source = course_dir / "content" / "lecture01.pdf"
    source.parent.mkdir(parents=True)
    payload = fixture_bytes("lecture01.pdf")
    source.write_bytes(payload)
    vault.mark(
        "uwaterloo:111111:topic:1",
        ManifestEntry(
            path=source.relative_to(vault.root).as_posix(),
            sha256=sha256(payload).hexdigest(),
            source_id="1",
            etag=None,
            last_modified=None,
            size=len(payload),
            fetched_at="2026-08-25T12:00:00Z",
        ),
    )
    vault.save_manifest()
    course_index.write_content_map(
        course_dir,
        [
            {
                "source_key": "uwaterloo:111111:topic:1",
                "source_id": "1",
                "topic_id": 1,
                "availability": "source_only",
            }
        ],
        root=vault.root,
    )
    return vault, course_dir


@pytest.fixture
def working_ocr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Only external executable discovery/recognition is replaced. The PDF parser, renderer,
    # image preparation, conversion, vault writes, and provenance checks stay real.
    executable = tmp_path / "tesseract"
    executable.touch()
    monkeypatch.setattr(convert.shutil, "which", lambda _name: str(executable))
    monkeypatch.setattr(convert.pytesseract.pytesseract, "tesseract_cmd", str(executable))
    monkeypatch.setattr(convert.pytesseract, "get_languages", lambda **_kwargs: ["eng"])
    monkeypatch.setattr(convert.pytesseract, "image_to_string", lambda *a, **k: "")


def _mapped_row(course_dir: Path) -> dict[str, object]:
    rows = course_index.read_content_map(course_dir)["topics"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    return row


@pytest.mark.usefixtures("working_ocr")
@pytest.mark.parametrize("previous_twin", [False, True])
@pytest.mark.parametrize("ocr_text", ["", " \t\r\n\f"])
def test_empty_ocr_keeps_gap_but_recommends_original_inspection(
    mapped_pdf: tuple[Vault, Path],
    monkeypatch: pytest.MonkeyPatch,
    previous_twin: bool,
    ocr_text: str,
) -> None:
    vault, course_dir = mapped_pdf
    if previous_twin:
        # The authored fixture is healthy at the default threshold. A different requested
        # threshold below forces a fresh real OCR attempt instead of accepting this cache.
        assert convert.convert_vault(vault).converted == 1
        assert len(verified_sources(vault, course_dir)) == 1
    prior = vault.entry("uwaterloo:111111:topic:1")
    assert prior is not None
    source = vault.materialized(prior)
    source_bytes, source_mtime = source.read_bytes(), source.stat().st_mtime_ns
    twin = source.with_suffix(".md")
    if previous_twin:
        twin = vault.root / prior.derived["markdown"].path
        twin_bytes, twin_mtime = twin.read_bytes(), twin.stat().st_mtime_ns
    monkeypatch.setattr(convert.pytesseract, "image_to_string", lambda *a, **k: ocr_text)

    report = convert.convert_vault(vault, ocr_words_per_page=10_000)

    assert report.gaps == 1 and report.converted == 0 and report.errors == ()
    row = _mapped_row(course_dir)
    assert row["availability"] == "conversion_gap"
    assert row["path"] is None and row["source_path"] == prior.path
    action = str(row["next_action"]).casefold()
    assert "install" not in action
    assert "inspect" in action and "original" in action
    assert "unrecognized" in action or "unresolved" in action
    assert course_index.reconcile_content_map(vault, [row]) == [row]
    assert verified_sources(vault, course_dir) == ()
    assert source.read_bytes() == source_bytes and source.stat().st_mtime_ns == source_mtime
    assert Vault(vault.root).entry("uwaterloo:111111:topic:1") == prior
    if previous_twin:
        assert twin.read_bytes() == twin_bytes and twin.stat().st_mtime_ns == twin_mtime
    else:
        assert not twin.exists() and not list(course_dir.rglob("*.md"))


@pytest.mark.usefixtures("working_ocr")
@pytest.mark.parametrize("injected_reader", [False, True])
@pytest.mark.parametrize("ocr_text", ["", " \t\r\n\f"])
def test_empty_ocr_stays_unresolved_without_claiming_unavailability_or_blankness(
    monkeypatch: pytest.MonkeyPatch, injected_reader: bool, ocr_text: str
) -> None:
    monkeypatch.setattr(convert.pytesseract, "image_to_string", lambda *a, **k: ocr_text)
    backend = convert.PdfOxideBackend(
        ocr_reader=(lambda _image: ocr_text) if injected_reader else None
    )

    result = convert.convert_pdf(
        FILES / "lecture01.pdf", backend=backend, ocr_words_per_page=10_000
    )

    assert result.backend == "pdf-oxide" and result.gap is True
    assert [page.mode for page in result.page_coverage] == ["unresolved", "unresolved"]
    assert [page.words for page in result.page_coverage] == [0, 0]
    assert tuple(page.warning for page in result.page_coverage) == result.warnings
    assert all("OCR returned no text" in warning for warning in result.warnings)
    assert "OCR unavailable" not in result.markdown
    assert "blank" not in result.markdown.casefold()
    assert "Introduction to Course Materials." not in result.markdown


@pytest.mark.usefixtures("working_ocr")
@pytest.mark.parametrize("failure", ["missing", "language", "process", "undecodable"])
def test_missing_or_unusable_ocr_still_recommends_setup_without_exception_text(
    mapped_pdf: tuple[Vault, Path], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    vault, course_dir = mapped_pdf
    if failure == "missing":
        monkeypatch.setattr(convert.shutil, "which", lambda _name: None)
        monkeypatch.delenv("PROGRAMFILES", raising=False)
    elif failure == "language":
        monkeypatch.setattr(convert.pytesseract, "get_languages", lambda **_kwargs: [])
    else:

        def unusable_ocr(*_args: object, **_kwargs: object) -> str:
            if failure == "undecodable":
                raise UnicodeDecodeError("utf-8", b"\x89", 0, 1, "synthetic-private-detail")
            # Matching words in a process error must not impersonate successful empty output.
            raise convert.pytesseract.TesseractError(
                1, "OCR returned no text on page 1: synthetic-private-detail"
            )

        monkeypatch.setattr(convert.pytesseract, "image_to_string", unusable_ocr)

    report = convert.convert_vault(vault, ocr_words_per_page=10_000)

    assert report.gaps == 1 and report.converted == 0
    row = _mapped_row(course_dir)
    assert row["availability"] == "conversion_gap" and row["path"] is None
    assert "install Tesseract" in str(row["next_action"])
    assert "eng" in str(row["next_action"]) and "a2l sync" in str(row["next_action"])
    assert all("OCR unavailable" in warning for warning in report.warnings)
    assert "synthetic-private-detail" not in str(row) + str(report)
    assert verified_sources(vault, course_dir) == ()


@pytest.mark.usefixtures("working_ocr")
@pytest.mark.parametrize("empty_first", [False, True])
def test_unusable_ocr_setup_takes_priority_when_another_page_returns_no_text(
    mapped_pdf: tuple[Vault, Path], monkeypatch: pytest.MonkeyPatch, empty_first: bool
) -> None:
    vault, course_dir = mapped_pdf
    empty_pages = iter((empty_first, not empty_first))

    def recognize(*_args: object, **_kwargs: object) -> str:
        if next(empty_pages):
            return ""
        raise convert.pytesseract.TesseractError(1, "synthetic-private-detail")

    monkeypatch.setattr(convert.pytesseract, "image_to_string", recognize)

    report = convert.convert_vault(vault, ocr_words_per_page=10_000)

    assert report.gaps == 1 and report.converted == 0
    assert "install Tesseract" in str(_mapped_row(course_dir)["next_action"])
    assert sum("OCR unavailable" in warning for warning in report.warnings) == 1
    assert sum("OCR returned no text" in warning for warning in report.warnings) == 1
    assert "synthetic-private-detail" not in str(report)
