"""Regression tests for deterministic, local-only source conversion."""

from __future__ import annotations

import socket
import subprocess
import sys
import zipfile
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

import pytest
from conftest import FILES, fixture_bytes

import agent2learn.convert as convert
from agent2learn.convert import (
    ConversionError,
    ConversionResult,
    PageCoverage,
    PdfOxideBackend,
    convert_pdf,
    convert_source,
    convert_vault,
)
from agent2learn.vault import ManifestEntry, Vault


def test_pdf_conversion_is_deterministic_and_page_marked() -> None:
    source = FILES / "lecture01.pdf"

    first = convert_source(source, ocr_words_per_page=1)
    second = convert_source(source, ocr_words_per_page=1)

    assert first.markdown == second.markdown
    assert "<!-- a2l:page 1 -->" in first.markdown
    assert "<!-- a2l:page 2 -->" in first.markdown
    assert "Example lecture page one." in first.markdown
    assert "Example lecture page two." in first.markdown
    assert [page.page for page in first.page_coverage] == [1, 2]
    assert all(page.mode == "markdown" for page in first.page_coverage)
    assert first.warnings == ()


def test_executed_notebook_output_reaches_twin() -> None:
    result = convert_source(FILES / "analysis.ipynb")

    assert "# Analysis" in result.markdown
    assert "data:image/png;base64," in result.markdown
    assert "hello" in result.markdown
    assert "col_a  col_b" in result.markdown
    assert "ValueError: example" in result.markdown
    assert "\\x1b" not in result.markdown
    assert "application/vnd.example.custom+json" in result.markdown
    assert "unsupported" in result.markdown.casefold()
    assert "````python" in result.markdown
    assert "# a fence in the body: ```" in result.markdown


def test_html_zip_picks_main_inner_html_without_remote_assets() -> None:
    result = convert_source(FILES / "site.html.zip")

    assert "# Example Site" in result.markdown
    assert "Repository-authored content for archive-extraction tests." in result.markdown
    assert "style.css" not in result.markdown
    assert result.warnings == ()


def test_missing_optional_office_dependency_is_a_conversion_gap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "worksheet.xlsx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    monkeypatch.setitem(sys.modules, "markitdown", None)

    result = convert_source(source)

    assert result.gap is True
    assert result.markdown == ""
    assert any("optional" in warning.casefold() for warning in result.warnings)


def test_conversion_ignores_an_invalid_utf8_content_map(tmp_path: Path) -> None:
    course_meta = tmp_path / "Term" / "COURSE101" / "_meta"
    course_meta.mkdir(parents=True)
    (course_meta / "content_map.json").write_bytes(b"{\xff")

    convert._update_content_map(Vault(tmp_path), "waterloo:1:topic:1", availability="integrity_gap")


def test_extension_alone_does_not_make_a_source_a_pdf(tmp_path: Path) -> None:
    source = tmp_path / "not-a-pdf.pdf"
    source.write_text("plain text", encoding="utf-8")

    result = convert_source(source)

    assert result.gap is True
    assert any("mismatched" in warning for warning in result.warnings)


@dataclass
class _FakePdf:
    pages: tuple[str, ...]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def extract_text_auto(self, page: int) -> str:
        return self.pages[page]

    def extract_text_ocr(self, page: int) -> str:
        del page
        raise AssertionError("pdf-oxide built-in OCR must never be called")

    def to_markdown(self, page: int) -> str:
        return f"# structured page {page + 1}\n"

    def to_markdown_all(self) -> str:
        return "\n---\n".join(self.to_markdown(page) for page in range(len(self.pages)))

    def render_page(self, page: int, dpi: int) -> bytes:
        del page, dpi
        return b"synthetic image"


def test_pdf_ocr_threshold_is_strict_and_uses_external_ocr_only(
    tmp_path: Path,
) -> None:
    eighty = " ".join(f"word{number}" for number in range(80))
    seventy_nine = " ".join(f"thin{number}" for number in range(79))
    document = _FakePdf((eighty, seventy_nine))
    ocr_calls: list[bytes] = []

    backend = PdfOxideBackend(
        document_factory=lambda _source: document,
        ocr_reader=lambda image: ocr_calls.append(image) or "OCR replacement",
    )
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")

    result = backend.convert_pdf(source, ocr_words_per_page=80)

    assert document.pages == (eighty, seventy_nine)
    assert len(ocr_calls) == 1
    assert "structured page 1" in result.markdown
    assert "OCR replacement" in result.markdown
    assert [page.mode for page in result.page_coverage] == ["markdown", "ocr"]


def test_unavailable_ocr_is_an_explicit_conversion_gap(tmp_path: Path) -> None:
    source = tmp_path / "thin.pdf"
    source.write_bytes(b"%PDF-synthetic")
    document = _FakePdf(("thin",))

    def no_ocr(_image: bytes) -> str:
        raise ConversionError("Tesseract is unavailable")

    result = PdfOxideBackend(
        document_factory=lambda _source: document, ocr_reader=no_ocr
    ).convert_pdf(source, ocr_words_per_page=80)

    assert result.gap is True
    assert result.page_coverage[0].mode == "unresolved"
    assert "conversion gap" in result.markdown


class _Backend:
    name = "fake"
    version = "1"

    def __init__(
        self,
        *,
        error: Exception | None = None,
        text: str = "fallback",
        name: str = "fake",
    ) -> None:
        self.error = error
        self.text = text
        self.name = name
        self.calls = 0

    def convert_pdf(self, source: Path, *, ocr_words_per_page: int) -> ConversionResult:
        del source, ocr_words_per_page
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ConversionResult(
            markdown=self.text,
            page_coverage=(PageCoverage(1, "markdown", 1),),
            backend=self.name,
            tool_version=self.version,
        )


def test_default_pdf_failure_uses_named_fallback_and_warns(tmp_path: Path) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"broken")
    default = _Backend(error=ConversionError("default failed"))
    fallback = _Backend(name="pypdfium2", text="degraded")

    result = convert_pdf(source, backend=default, fallback=fallback)

    assert result.markdown == "degraded"
    assert result.backend == "pypdfium2"
    assert any("fallback" in warning.casefold() for warning in result.warnings)
    assert default.calls == 1
    assert fallback.calls == 1


def test_both_pdf_backends_fail_as_a_scoped_conversion_error(tmp_path: Path) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"broken")

    with pytest.raises(ConversionError, match="both PDF backends"):
        convert_pdf(
            source,
            backend=_Backend(error=ConversionError("default failed")),
            fallback=_Backend(error=ConversionError("fallback failed")),
        )


def test_convert_vault_installs_hash_linked_twin_and_is_idempotent(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    source = vault.root / "Winter 2026" / "COURSE101" / "content" / "lecture01.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(fixture_bytes("lecture01.pdf"))
    entry = ManifestEntry(
        path="Winter 2026/COURSE101/content/lecture01.pdf",
        sha256=_sha256(source.read_bytes()),
        source_id="1",
        etag=None,
        last_modified=None,
        size=source.stat().st_size,
        fetched_at="2026-08-25T12:00:00Z",
    )
    vault.manifest()
    vault.mark("uwaterloo:111111:topic:1", entry)
    vault.save_manifest()

    pdf_backend = PdfOxideBackend(
        document_factory=lambda _source: _FakePdf(("one", "two")),
        ocr_reader=lambda _image: "OCR replacement",
    )
    first = convert_vault(vault, backend=pdf_backend, fallback=_Backend())
    twin = source.with_suffix(".md")
    first_bytes = twin.read_bytes()
    second = convert_vault(vault, backend=pdf_backend, fallback=_Backend())

    assert first.converted == 1
    assert second.skipped == 1
    assert twin.read_bytes() == first_bytes
    artifact = Vault(vault.root).entry("uwaterloo:111111:topic:1")
    assert artifact is not None
    assert artifact.derived["markdown"].source_sha256 == entry.sha256
    assert artifact.derived["markdown"].ocr_words_per_page == 80
    assert artifact.derived["markdown"].page_coverage[0]["page"] == 1


def test_changing_pdf_threshold_invalidates_the_derived_twin(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    source = vault.root / "Winter 2026" / "COURSE101" / "content" / "lecture01.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(fixture_bytes("lecture01.pdf"))
    entry = ManifestEntry(
        path="Winter 2026/COURSE101/content/lecture01.pdf",
        sha256=_sha256(source.read_bytes()),
        source_id="1",
        etag=None,
        last_modified=None,
        size=source.stat().st_size,
        fetched_at="2026-08-25T12:00:00Z",
    )
    vault.mark("uwaterloo:111111:topic:1", entry)
    vault.save_manifest()

    pdf_backend = PdfOxideBackend(
        document_factory=lambda _source: _FakePdf(("one", "two")),
        ocr_reader=lambda _image: "OCR replacement",
    )
    first = convert_vault(vault, backend=pdf_backend, fallback=_Backend(), ocr_words_per_page=80)
    second = convert_vault(vault, backend=pdf_backend, fallback=_Backend(), ocr_words_per_page=1)

    assert first.converted == 1
    assert second.converted == 1
    assert second.skipped == 0
    refreshed = vault.entry("uwaterloo:111111:topic:1")
    assert refreshed is not None
    assert refreshed.derived["markdown"].ocr_words_per_page == 1


def test_source_revision_invalidates_the_derived_twin(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    source = vault.root / "Winter 2026" / "COURSE101" / "content" / "revision.pdf"
    source.parent.mkdir(parents=True)
    original = b"%PDF-original"
    source.write_bytes(original)
    entry = ManifestEntry(
        path="Winter 2026/COURSE101/content/revision.pdf",
        sha256=_sha256(original),
        source_id="3",
        etag=None,
        last_modified=None,
        size=len(original),
        fetched_at="2026-08-25T12:00:00Z",
    )
    vault.mark("uwaterloo:111111:topic:3", entry)
    vault.save_manifest()
    backend = _Backend(name="synthetic", text="first twin")

    assert convert_vault(vault, backend=backend, fallback=backend).converted == 1
    revised = b"%PDF-revised"
    source.write_bytes(revised)
    vault.mark(
        "uwaterloo:111111:topic:3",
        replace(entry, sha256=_sha256(revised), size=len(revised)),
    )
    vault.save_manifest()

    report = convert_vault(vault, backend=_Backend(name="synthetic", text="second twin"))

    assert report.converted == 1
    refreshed = vault.entry("uwaterloo:111111:topic:3")
    assert refreshed is not None
    assert refreshed.derived["markdown"].source_sha256 == _sha256(revised)


def test_locally_modified_twin_is_preserved_before_regeneration(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    source = vault.root / "Winter 2026" / "COURSE101" / "content" / "notes.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-synthetic")
    entry = ManifestEntry(
        path="Winter 2026/COURSE101/content/notes.pdf",
        sha256=_sha256(source.read_bytes()),
        source_id="2",
        etag=None,
        last_modified=None,
        size=source.stat().st_size,
        fetched_at="2026-08-25T12:00:00Z",
    )
    vault.mark("uwaterloo:111111:topic:2", entry)
    vault.save_manifest()

    backend = _Backend(name="synthetic", text="generated v1")
    assert convert_vault(vault, backend=backend, fallback=backend).converted == 1
    twin = source.with_suffix(".md")
    twin.write_text("student annotation\n", encoding="utf-8")

    report = convert_vault(
        vault,
        backend=_Backend(name="synthetic", text="generated v2"),
        fallback=_Backend(name="synthetic", text="generated v2"),
    )

    assert report.converted == 1
    assert any("locally modified" in warning for warning in report.warnings)
    assert twin.read_text(encoding="utf-8") == "generated v2"
    history = vault.state() / "history" / sha256(b"uwaterloo:111111:topic:2").hexdigest()
    metadata = next(history.rglob("revision.json"))
    assert "local-modification" in metadata.read_text(encoding="utf-8")


def test_html_sanitizer_removes_active_content_and_remote_images(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.html"
    source.write_text(
        """
        <h1 onclick="bad()">Keep</h1>
        <script>do_not_keep()</script>
        <form action="/submit"><input value="secret">hidden form</form>
        <p><a href="https://example.test/path?x=1#fragment">safe link</a>
        <a href="javascript:alert(1)">bad link</a></p>
        <img src="https://example.test/image.png"><img src="data:image/png;base64,AAAA">
        """,
        encoding="utf-8",
    )

    result = convert.convert_source(source)

    assert "Keep" in result.markdown
    assert "do_not_keep" not in result.markdown
    assert "hidden form" not in result.markdown
    assert "onclick" not in result.markdown
    assert "javascript:" not in result.markdown
    assert "https://example.test/path" in result.markdown
    assert "?x=1" not in result.markdown
    assert "#fragment" not in result.markdown
    assert "image.png" not in result.markdown
    assert "data:image/png;base64,AAAA" in result.markdown


@pytest.mark.parametrize("member_name", ["../escape.html", "/absolute.html", r"C:\\escape.html"])
def test_html_archive_rejects_unsafe_member_paths(tmp_path: Path, member_name: str) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member_name, "<h1>unsafe</h1>")

    with pytest.raises(ConversionError, match="HTML archive rejected"):
        convert.convert_html_zip(archive_path)


def test_html_archive_rejects_device_name_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "device.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("CON/index.html", "<h1>unsafe</h1>")

    with pytest.raises(ConversionError, match="HTML archive rejected"):
        convert.convert_html_zip(archive_path)


def test_html_archive_rejects_encrypted_and_symlink_members() -> None:
    encrypted = zipfile.ZipInfo("index.html")
    encrypted.flag_bits = 0x1
    with pytest.raises(ValueError, match="encrypted"):
        convert._validate_archive([encrypted])

    symlink = zipfile.ZipInfo("index.html")
    symlink.external_attr = 0o120777 << 16
    with pytest.raises(ValueError, match="symlink"):
        convert._validate_archive([symlink])


def test_html_archive_enforces_member_and_ratio_caps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive_path = tmp_path / "large.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "A" * 100)

    monkeypatch.setattr(convert, "MAX_ZIP_MEMBER", 99)
    with pytest.raises(ConversionError, match="HTML archive rejected"):
        convert.convert_html_zip(archive_path)

    monkeypatch.setattr(convert, "MAX_ZIP_MEMBER", 1_000)
    monkeypatch.setattr(convert, "MAX_ZIP_COMPRESSION_RATIO", 1)
    with pytest.raises(ConversionError, match="HTML archive rejected"):
        convert.convert_html_zip(archive_path)


def test_conversion_does_not_use_network_or_spawn_processes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "notes.md"
    source.write_text("local notes", encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("conversion attempted external I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    assert convert.convert_source(source).markdown == "local notes\n"


def _sha256(data: bytes) -> str:
    return sha256(data).hexdigest()
