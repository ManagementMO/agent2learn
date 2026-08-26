"""Local, deterministic conversion of captured course sources into Markdown twins.

Conversion is deliberately downstream of ingestion.  It receives only a local source path, never
an API client or session, and it writes nothing until the caller has accepted the complete result.
PDFs use the pinned PDF Oxide backend by default; notebooks and HTML archives are handled by small
auditable renderers rather than an execution-capable exporter stack.
"""

from __future__ import annotations

import base64
import binascii
import importlib
import importlib.metadata
import io
import json
import os
import re
import shutil
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pytesseract  # type: ignore[import-untyped]
from pdf_oxide import PdfDocument
from PIL import Image

from agent2learn import clock, paths
from agent2learn import index as course_index
from agent2learn.errors import A2LError
from agent2learn.vault import DerivedArtifact, ManifestEntry, Vault

DEFAULT_OCR_WORDS_PER_PAGE = 80
OCR_DPI = 300
CONVERTER_VERSION = "1"
MAX_ZIP_MEMBERS = 1_000
MAX_ZIP_UNCOMPRESSED = 64 * 1024 * 1024
MAX_ZIP_MEMBER = 32 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 1_000

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_BACKTICKS = re.compile(r"`+")
_ATTACHMENT = re.compile(r"attachment:([^\s)\"'>]+)", re.IGNORECASE)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_FORBIDDEN_ARCHIVE_PARTS = frozenset({"", ".", ".."})
_SAFE_IMAGE_MIME = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})
_HTML_SKIP = frozenset({"script", "style", "form", "iframe", "object", "embed", "template"})
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "dt",
        "dd",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }
)


class ConversionError(A2LError):
    """A source could not be converted by the selected backend."""


@dataclass(frozen=True)
class PageCoverage:
    """Deterministic coverage information for one one-based source page."""

    page: int
    mode: str
    words: int
    warning: str | None = None

    @property
    def word_count(self) -> int:
        """Alias used by audit/report consumers that spell out the measurement."""

        return self.words


@dataclass(frozen=True)
class ConversionResult:
    """Pure conversion output; no filesystem installation occurs here."""

    markdown: str
    page_coverage: tuple[PageCoverage, ...] = ()
    warnings: tuple[str, ...] = ()
    backend: str = "agent2learn"
    tool_version: str = CONVERTER_VERSION
    gap: bool = False

    @property
    def coverage(self) -> tuple[PageCoverage, ...]:
        """Short alias for callers rendering an audit summary."""

        return self.page_coverage


@dataclass(frozen=True)
class ConversionReport:
    """Summary of a vault conversion pass."""

    converted: int = 0
    skipped: int = 0
    gaps: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class ConverterBackend(Protocol):
    """The narrow PDF backend boundary shared by the default and degraded implementations."""

    name: str
    version: str

    def convert_pdf(self, source: Path, *, ocr_words_per_page: int) -> ConversionResult:
        """Convert one local PDF without accessing network or session state."""


class PdfOxideBackend:
    """The pinned PDF Oxide backend with explicit external-Tesseract OCR."""

    name = "pdf-oxide"

    def __init__(
        self,
        *,
        document_factory: Callable[[Path], object] | None = None,
        ocr_reader: Callable[[bytes], str] | None = None,
        ocr_language: str = "eng",
        dpi: int = OCR_DPI,
    ) -> None:
        if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
            raise ValueError("dpi must be a positive integer")
        if not isinstance(ocr_language, str) or not ocr_language:
            raise ValueError("ocr_language must be a non-empty string")
        self.version = _package_version("pdf-oxide", "unknown")
        self._document_factory = document_factory or self._open_document
        self._ocr_reader = ocr_reader
        self._ocr_language = ocr_language
        self._dpi = dpi

    @staticmethod
    def _open_document(source: Path) -> object:
        return PdfDocument(os.fspath(paths.long_path(source)))

    def convert_pdf(self, source: Path, *, ocr_words_per_page: int) -> ConversionResult:
        _validate_threshold(ocr_words_per_page)
        document = self._document_factory(Path(source))
        try:
            page_count = _pdf_oxide_page_count(document)
            if page_count < 1:
                raise ConversionError("PDF has no pages")
            extracted = [
                _text_value(_call_method(document, "extract_text_auto", page))
                for page in range(page_count)
            ]
            healthy = [len(text.split()) >= ocr_words_per_page for text in extracted]
            page_markdown: list[str] = []
            coverage: list[PageCoverage] = []
            warnings: list[str] = []

            all_markdown: list[str] | None = None
            if all(healthy) and hasattr(document, "to_markdown_all"):
                try:
                    all_value = _call_method(document, "to_markdown_all")
                    all_markdown = _split_all_markdown(_text_value(all_value), page_count)
                except Exception as exc:
                    warnings.append(f"whole-document Markdown unavailable: {type(exc).__name__}")
                else:
                    if all_markdown is None:
                        warnings.append("whole-document Markdown had no stable page split")

            for page, text in enumerate(extracted):
                if healthy[page]:
                    if all_markdown is not None:
                        markdown = all_markdown[page]
                    else:
                        markdown = _text_value(_call_method(document, "to_markdown", page))
                    mode = "markdown"
                    warning = None
                    words = len(text.split())
                else:
                    try:
                        image_bytes = _text_image_bytes(
                            _call_method(document, "render_page", page, dpi=self._dpi)
                        )
                        ocr_text = self._read_ocr(image_bytes)
                    except (ConversionError, OSError, RuntimeError) as exc:
                        warning = f"OCR unavailable on page {page + 1}: {type(exc).__name__}"
                        warnings.append(warning)
                        markdown = f"[a2l conversion gap: {warning}]"
                        mode = "unresolved"
                        words = 0
                    else:
                        markdown = ocr_text
                        mode = "ocr"
                        warning = None
                        words = len(ocr_text.split())
                page_markdown.append(_page_block(page + 1, markdown))
                coverage.append(PageCoverage(page + 1, mode, words, warning))

            return ConversionResult(
                markdown=_normalise_markdown("\n\n".join(page_markdown)),
                page_coverage=tuple(coverage),
                warnings=tuple(warnings),
                backend=self.name,
                tool_version=self.version,
                gap=any(page.mode == "unresolved" for page in coverage),
            )
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"pdf-oxide could not convert {source.name}") from exc
        finally:
            _close_quietly(document)

    def _read_ocr(self, image_bytes: bytes) -> str:
        if self._ocr_reader is not None:
            normalized = _normalise_markdown(self._ocr_reader(image_bytes))
            if not normalized:
                raise ConversionError("OCR returned no text")
            return normalized
        if not _configure_tesseract(self._ocr_language):
            raise ConversionError("Tesseract is unavailable or lacks the requested language")
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                text = pytesseract.image_to_string(image, lang=self._ocr_language)
        except pytesseract.TesseractError as exc:
            raise ConversionError("Tesseract could not OCR the rendered page") from exc
        normalized = _normalise_markdown(text)
        if not normalized:
            raise ConversionError("Tesseract returned no text")
        return normalized


class PdfiumBackend:
    """Named degraded PDFium fallback; it never silently replaces a successful default result."""

    name = "pypdfium2"

    def __init__(self) -> None:
        self.version = _package_version("pypdfium2", "unknown")

    def convert_pdf(self, source: Path, *, ocr_words_per_page: int) -> ConversionResult:
        _validate_threshold(ocr_words_per_page)
        try:
            document = pdfium.PdfDocument(os.fspath(paths.long_path(source)))
        except Exception as exc:
            raise ConversionError(f"pypdfium2 could not open {source.name}") from exc

        blocks: list[str] = []
        coverage: list[PageCoverage] = []
        try:
            for index in range(len(document)):
                page = document[index]
                textpage = page.get_textpage()
                try:
                    text = _normalise_markdown(textpage.get_text_bounded())
                finally:
                    _close_quietly(textpage)
                    _close_quietly(page)
                blocks.append(_page_block(index + 1, text))
                coverage.append(PageCoverage(index + 1, "fallback", len(text.split())))
            if not coverage:
                raise ConversionError("PDF has no pages")
            empty_page = any(page.words == 0 for page in coverage)
            return ConversionResult(
                markdown=_normalise_markdown("\n\n".join(blocks)),
                page_coverage=tuple(coverage),
                backend=self.name,
                tool_version=self.version,
                warnings=("fallback contains an empty page",) if empty_page else (),
                gap=empty_page,
            )
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"pypdfium2 could not convert {source.name}") from exc
        finally:
            _close_quietly(document)


def convert_pdf(
    source: Path,
    *,
    backend: ConverterBackend | None = None,
    fallback: ConverterBackend | None = None,
    ocr_words_per_page: int = DEFAULT_OCR_WORDS_PER_PAGE,
) -> ConversionResult:
    """Use the default PDF backend, falling back only when it cannot convert at all."""

    selected = backend or PdfOxideBackend()
    degraded = fallback or PdfiumBackend()
    try:
        return selected.convert_pdf(source, ocr_words_per_page=ocr_words_per_page)
    except Exception:
        try:
            result = degraded.convert_pdf(source, ocr_words_per_page=ocr_words_per_page)
        except Exception as fallback_error:
            raise ConversionError("both PDF backends failed") from fallback_error
        warning = f"default PDF backend failed; accepted {degraded.name} fallback"
        return replace(result, warnings=(warning, *result.warnings))


def convert_source(
    source: Path,
    *,
    backend: ConverterBackend | None = None,
    fallback: ConverterBackend | None = None,
    ocr_words_per_page: int = DEFAULT_OCR_WORDS_PER_PAGE,
    content_type: str | None = None,
) -> ConversionResult:
    """Convert one local source based on magic bytes plus extension, never executing it."""

    del content_type  # Server metadata is advisory; local bytes and the extension decide dispatch.
    source = Path(source)
    if not source.is_file():
        raise ConversionError(f"source is not a regular file: {source.name}")
    kind = _classify_source(source)
    if kind == "pdf":
        return convert_pdf(
            source,
            backend=backend,
            fallback=fallback,
            ocr_words_per_page=ocr_words_per_page,
        )
    if kind == "notebook":
        return render_notebook(source)
    if kind == "html_zip":
        return convert_html_zip(source)
    if kind == "html":
        return _convert_html_file(source)
    if kind == "text":
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ConversionError(f"text source could not be read: {source.name}") from exc
        return ConversionResult(
            markdown=_normalise_markdown(text),
            page_coverage=(PageCoverage(1, "text", len(text.split())),),
            backend="agent2learn-text",
            tool_version=CONVERTER_VERSION,
        )
    if kind == "office":
        return _convert_office(source)
    return ConversionResult(
        markdown="",
        warnings=(f"unsupported or mismatched source format: {source.suffix or source.name}",),
        backend="agent2learn",
        tool_version=CONVERTER_VERSION,
        gap=True,
    )


def render_notebook(source: Path) -> ConversionResult:
    """Render a v4 notebook without importing or executing any cell code."""

    try:
        nbformat = importlib.import_module("nbformat")
    except ImportError:
        return ConversionResult(
            markdown="",
            warnings=("optional notebook dependency nbformat is not installed",),
            backend="nbformat",
            tool_version="missing",
            gap=True,
        )
    try:
        notebook = nbformat.read(os.fspath(paths.long_path(source)), as_version=4)
    except Exception as exc:
        raise ConversionError(f"notebook could not be parsed: {source.name}") from exc

    metadata = notebook.get("metadata", {})
    language = "text"
    if isinstance(metadata, Mapping):
        language_info = metadata.get("language_info", {})
        if isinstance(language_info, Mapping) and isinstance(language_info.get("name"), str):
            language = cast(str, language_info["name"]).strip() or "text"

    blocks: list[str] = []
    warnings: list[str] = []
    cells = notebook.get("cells", [])
    if not isinstance(cells, Sequence) or isinstance(cells, (str, bytes)):
        raise ConversionError("notebook cells must be an array")
    for number, cell in enumerate(cells, start=1):
        if not isinstance(cell, Mapping):
            warnings.append(f"cell {number} is not an object")
            continue
        cell_type = cell.get("cell_type")
        source_text = _cell_text(cell.get("source"))
        if cell_type == "markdown":
            attachments = cell.get("attachments", {})
            blocks.append(_replace_attachments(source_text, attachments))
        elif cell_type == "code":
            blocks.append(_fenced(source_text, language))
            outputs = cell.get("outputs", [])
            if isinstance(outputs, Sequence) and not isinstance(outputs, (str, bytes)):
                for output in outputs:
                    rendered, output_warning = _render_notebook_output(output)
                    if rendered:
                        blocks.append(rendered)
                    if output_warning is not None:
                        warnings.append(f"cell {number}: {output_warning}")
        else:
            warnings.append(f"cell {number}: unsupported cell type {cell_type!r}")

    markdown = _normalise_markdown("\n\n".join(blocks))
    return ConversionResult(
        markdown=markdown,
        page_coverage=(PageCoverage(1, "notebook", len(markdown.split())),),
        warnings=tuple(warnings),
        backend="nbformat",
        tool_version=_package_version("nbformat", "unknown"),
        gap=False,
    )


def convert_html_zip(source: Path) -> ConversionResult:
    """Extract only a safe main HTML member from a bounded archive in memory."""

    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            html_info = _validate_archive(infos)
            if html_info is None:
                return ConversionResult(
                    markdown="",
                    warnings=("HTML archive has no main HTML member",),
                    backend="html-archive",
                    tool_version=CONVERTER_VERSION,
                    gap=True,
                )
            html_bytes = archive.read(html_info)
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ConversionError(f"HTML archive rejected: {source.name}") from exc
    try:
        text = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConversionError("HTML archive main member is not UTF-8") from exc
    return _html_result(text)


def convert_vault(
    vault: Vault,
    *,
    backend: ConverterBackend | None = None,
    fallback: ConverterBackend | None = None,
    ocr_words_per_page: int = DEFAULT_OCR_WORDS_PER_PAGE,
) -> ConversionReport:
    """Install current, hash-linked twins for manifest sources without losing revisions."""

    _validate_threshold(ocr_words_per_page)
    entries = vault.manifest()
    selected_backend = backend or PdfOxideBackend()
    selected_fallback = fallback or PdfiumBackend()
    converted = skipped = gaps = 0
    warnings: list[str] = []
    errors: list[str] = []
    for key, entry in sorted(entries.items()):
        source = vault.materialized(entry)
        if not source.is_file():
            gaps += 1
            message = f"{key}: source is missing"
            errors.append(message)
            _update_content_map(vault, key, availability="integrity_gap", next_action=message)
            continue
        source_hash, source_size = _hash_file(source)
        if source_hash != entry.sha256 or source_size != entry.size:
            gaps += 1
            message = f"{key}: source hash does not match manifest"
            errors.append(message)
            _update_content_map(
                vault,
                key,
                availability="integrity_gap",
                source_path=entry.path,
                path=None,
                sha256=entry.sha256,
                source_sha256=entry.sha256,
                size=entry.size,
                next_action=message,
            )
            continue

        artifact = entry.derived.get("markdown")
        expected_tool, expected_version = _expected_tool(source, selected_backend)
        expected_threshold = ocr_words_per_page if _classify_source(source) == "pdf" else None
        if artifact is not None and _artifact_is_current(
            vault,
            artifact,
            entry,
            expected_tool,
            expected_version,
            expected_threshold,
        ):
            skipped += 1
            continue

        try:
            result = convert_source(
                source,
                backend=selected_backend,
                fallback=selected_fallback,
                ocr_words_per_page=ocr_words_per_page,
            )
        except Exception as exc:
            gaps += 1
            message = f"{key}: {type(exc).__name__}"
            errors.append(message)
            _update_content_map(
                vault,
                key,
                availability="integrity_gap",
                source_path=entry.path,
                path=None,
                sha256=entry.sha256,
                source_sha256=entry.sha256,
                size=entry.size,
                next_action=message,
            )
            continue
        warnings.extend(f"{key}: {warning}" for warning in result.warnings)
        if result.gap or not result.markdown:
            gaps += 1
            availability = (
                "unsupported_format"
                if any(
                    "unsupported" in warning.casefold() or "optional" in warning.casefold()
                    for warning in result.warnings
                )
                else "integrity_gap"
            )
            next_action = result.warnings[0] if result.warnings else "conversion gap"
            _update_content_map(
                vault,
                key,
                availability=availability,
                source_path=entry.path,
                path=None,
                sha256=entry.sha256,
                source_sha256=entry.sha256,
                size=entry.size,
                next_action=next_action,
            )
            continue

        destination = source.with_suffix(".md")
        prior_artifact = entry.derived.get("markdown")
        local_modification = False
        if prior_artifact is not None:
            prior_path = _artifact_path(vault, prior_artifact)
            if prior_path.is_file() and _hash_file(prior_path)[0] != prior_artifact.sha256:
                vault.preserve_revision(key, changed_at=clock.now())
                local_modification = True
        destination.parent.mkdir(parents=True, exist_ok=True)
        paths.atomic_write_text(paths.long_path(destination), result.markdown)
        source_kind = _classify_source(source)
        derived = DerivedArtifact(
            path=paths.rel_posix(destination, vault.root),
            sha256=_hash_file(destination)[0],
            source_sha256=entry.sha256,
            tool=result.backend,
            tool_version=result.tool_version,
            created_at=_now(),
            ocr_words_per_page=(ocr_words_per_page if source_kind == "pdf" else None),
            page_coverage=tuple(
                {
                    "page": page.page,
                    "mode": page.mode,
                    "words": page.words,
                    "warning": page.warning,
                }
                for page in result.page_coverage
            ),
        )
        updated = replace(entry, derived={"markdown": derived})
        vault.mark(key, updated)
        vault.save_manifest()
        _update_content_map(
            vault,
            key,
            availability="markdown_ready",
            source_path=updated.path,
            path=derived.path,
            sha256=updated.sha256,
            source_sha256=updated.sha256,
            size=updated.size,
            next_action="ready for citation",
        )
        if local_modification:
            warnings.append(f"{key}: preserved locally modified markdown twin")
        converted += 1
    return ConversionReport(converted, skipped, gaps, tuple(warnings), tuple(errors))


def _convert_html_file(source: Path) -> ConversionResult:
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConversionError(f"HTML source could not be read: {source.name}") from exc
    return _html_result(text)


def _html_result(text: str) -> ConversionResult:
    parser = _SafeHtmlMarkdown()
    parser.feed(text)
    parser.close()
    markdown = _normalise_markdown(parser.markdown())
    return ConversionResult(
        markdown=markdown,
        page_coverage=(PageCoverage(1, "html", len(markdown.split())),),
        warnings=(),
        backend="html-sanitizer",
        tool_version=CONVERTER_VERSION,
    )


def _convert_office(source: Path) -> ConversionResult:
    try:
        module = importlib.import_module("markitdown")
        converter_type = module.MarkItDown
        converted = converter_type().convert(os.fspath(paths.long_path(source)))
        text = getattr(converted, "text_content", None)
        if not isinstance(text, str):
            raise ConversionError("MarkItDown returned no text content")
    except ImportError:
        return ConversionResult(
            markdown="",
            warnings=("optional office dependency markitdown is not installed",),
            backend="markitdown",
            tool_version="missing",
            gap=True,
        )
    except Exception as exc:
        return ConversionResult(
            markdown="",
            warnings=(f"office conversion failed: {type(exc).__name__}",),
            backend="markitdown",
            tool_version=_package_version("markitdown", "unknown"),
            gap=True,
        )
    markdown = _normalise_markdown(text)
    return ConversionResult(
        markdown=markdown,
        page_coverage=(PageCoverage(1, "office", len(markdown.split())),),
        backend="markitdown",
        tool_version=_package_version("markitdown", "unknown"),
    )


def _classify_source(source: Path) -> str:
    suffixes = [suffix.casefold() for suffix in source.suffixes]
    suffix = source.suffix.casefold()
    try:
        magic = source.read_bytes()[:16]
    except OSError as exc:
        raise ConversionError(f"source could not be inspected: {source.name}") from exc
    if magic.startswith(b"%PDF"):
        return "pdf"
    if suffix == ".pdf":
        return "unsupported"
    if suffix == ".ipynb" or (magic.lstrip().startswith(b"{") and _looks_like_notebook(source)):
        return "notebook"
    if suffix in {".docx", ".pptx", ".xlsx"}:
        return "office" if _looks_like_office(source, suffix) else "unsupported"
    if suffix in {".doc", ".ppt", ".xls"}:
        return "office" if magic.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") else "unsupported"
    if zipfile.is_zipfile(source):
        if suffix == ".zip" and ".html" in suffixes:
            return "html_zip"
        try:
            with zipfile.ZipFile(source) as archive:
                if any(_is_html_name(info.filename) for info in archive.infolist()):
                    return "html_zip"
        except (OSError, zipfile.BadZipFile):
            return "html_zip"
    if suffix in {".html", ".htm"} or magic.lstrip().lower().startswith(
        (b"<!doctype html", b"<html")
    ):
        return "html"
    if suffix in {".md", ".markdown", ".rmd", ".txt", ".csv", ".tsv"}:
        return "text"
    return "unsupported"


def _looks_like_notebook(source: Path) -> bool:
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(raw, dict) and isinstance(raw.get("cells"), list)


def _looks_like_office(source: Path, suffix: str) -> bool:
    required_member = {
        ".docx": "word/document.xml",
        ".pptx": "ppt/presentation.xml",
        ".xlsx": "xl/workbook.xml",
    }[suffix]
    try:
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False
    return "[Content_Types].xml" in names and required_member in names


def _validate_archive(infos: Sequence[zipfile.ZipInfo]) -> zipfile.ZipInfo | None:
    if len(infos) > MAX_ZIP_MEMBERS:
        raise ValueError("archive member-count limit exceeded")
    total = 0
    html_members: list[zipfile.ZipInfo] = []
    for info in infos:
        name = info.filename
        if not name or "\\" in name or _WINDOWS_ABSOLUTE.match(name):
            raise ValueError("archive member path is unsafe")
        pure = PurePosixPath(name)
        if pure.is_absolute() or any(part in _FORBIDDEN_ARCHIVE_PARTS for part in pure.parts):
            raise ValueError("archive member path escapes extraction root")
        if any(paths.safe_name(part) != part for part in pure.parts):
            raise ValueError("archive member contains an unsafe filename component")
        if info.flag_bits & 0x1:
            raise ValueError("encrypted archive members are unsupported")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError("archive symlinks are unsupported")
        if info.file_size > MAX_ZIP_MEMBER:
            raise ValueError("archive member-size limit exceeded")
        if info.file_size and info.compress_size == 0:
            raise ValueError("archive compression ratio is unsafe")
        if info.file_size / max(info.compress_size, 1) > MAX_ZIP_COMPRESSION_RATIO:
            raise ValueError("archive compression ratio is unsafe")
        total += info.file_size
        if total > MAX_ZIP_UNCOMPRESSED:
            raise ValueError("archive uncompressed-size limit exceeded")
        if _is_html_name(name):
            html_members.append(info)
    if not html_members:
        return None
    return sorted(
        html_members,
        key=lambda item: (
            0 if PurePosixPath(item.filename).name.casefold() == "index.html" else 1,
            len(PurePosixPath(item.filename).parts),
            item.filename.casefold(),
        ),
    )[0]


def _is_html_name(name: str) -> bool:
    return PurePosixPath(name).suffix.casefold() in {".html", ".htm"}


class _SafeHtmlMarkdown(HTMLParser):
    """Small inert HTML-to-Markdown parser with no URL fetching."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._pre_depth = 0
        self._links: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if self._skip_depth:
            if tag in _HTML_SKIP:
                self._skip_depth += 1
            return
        if tag in _HTML_SKIP:
            self._skip_depth = 1
            return
        if tag in {f"h{level}" for level in range(1, 7)}:
            self._block()
            self._parts.append("#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "section", "article", "main", "header", "footer", "figure"}:
            self._block()
        elif tag == "li":
            self._block()
            self._parts.append("- ")
        elif tag == "pre":
            self._block()
            self._pre_depth += 1
        elif tag == "code" and not self._pre_depth:
            self._parts.append("`")
        elif tag == "br":
            self._parts.append("\n")
        elif tag == "a":
            href = next((value for name, value in attrs if name.casefold() == "href"), None)
            self._parts.append("[")
            self._links.append(_safe_href(href))
        elif tag == "img":
            src = next((value for name, value in attrs if name.casefold() == "src"), None)
            if isinstance(src, str):
                image_uri = _safe_image_uri(src)
                if image_uri is not None:
                    self._parts.append(f"![image]({image_uri})")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._skip_depth:
            if tag in _HTML_SKIP:
                self._skip_depth -= 1
            return
        if tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
            self._block()
        elif tag == "code" and not self._pre_depth:
            self._parts.append("`")
        elif tag == "a" and self._links:
            href = self._links.pop()
            self._parts.append(f"]({href})" if href else "]")
        elif tag in _BLOCK_TAGS:
            self._block()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        safe_data = escape(data, quote=False)
        if self._pre_depth:
            self._parts.append(safe_data)
        else:
            self._parts.append(re.sub(r"\s+", " ", safe_data))

    def markdown(self) -> str:
        return "".join(self._parts)

    def _block(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n\n"):
            self._parts.append("\n\n")


def _safe_href(value: str | None) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.scheme.casefold() not in {"", "http", "https"}:
        return None
    if parsed.scheme and not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_image_uri(value: str) -> str | None:
    header, separator, payload = value.partition(",")
    if not separator or not header.casefold().startswith("data:"):
        return None
    mime, separator, encoding = header[5:].partition(";")
    if not separator or encoding.casefold() != "base64":
        return None
    mime = mime.casefold()
    if mime not in _SAFE_IMAGE_MIME:
        return None
    encoded = "".join(payload.split())
    if not encoded:
        return None
    try:
        base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    return f"data:{mime};base64,{encoded}"


def _render_notebook_output(output: object) -> tuple[str, str | None]:
    if not isinstance(output, Mapping):
        return "", "output is not an object"
    output_type = output.get("output_type")
    if output_type == "stream":
        name = output.get("name") if isinstance(output.get("name"), str) else "output"
        return f"### {name}\n\n{_fenced(_cell_text(output.get('text')), 'text')}", None
    if output_type == "error":
        traceback = _cell_text(output.get("traceback"))
        if not traceback:
            traceback = f"{output.get('ename', 'Error')}: {output.get('evalue', '')}"
        return f"### Error\n\n{_fenced(_ANSI.sub('', traceback), 'text')}", None
    if output_type in {"display_data", "execute_result"}:
        data = output.get("data")
        if not isinstance(data, Mapping):
            return "", "output data is not an object"
        markdown = data.get("text/markdown")
        if markdown is not None:
            return f"### Output\n\n{_cell_text(markdown)}", None
        plain = data.get("text/plain")
        if plain is not None:
            return f"### Output\n\n{_fenced(_cell_text(plain), 'text')}", None
        for mime, value in sorted(data.items(), key=lambda item: str(item[0])):
            if isinstance(mime, str) and mime.startswith("image/") and isinstance(value, str):
                image_uri = _safe_image_uri(f"data:{mime};base64,{value}")
                if image_uri is not None:
                    return f"### Output\n\n![output]({image_uri})", None
        mime_names = ", ".join(sorted(str(name) for name in data))
        marker = f"[a2l unsupported notebook output MIME: {mime_names}]"
        return marker, f"unsupported output MIME: {mime_names}"
    return f"[a2l unsupported notebook output type: {output_type!r}]", "unsupported output type"


def _replace_attachments(text: str, attachments: object) -> str:
    if not isinstance(attachments, Mapping):
        return text

    def replacement(match: re.Match[str]) -> str:
        name = match.group(1)
        payloads = attachments.get(name)
        if not isinstance(payloads, Mapping):
            return match.group(0)
        for mime, value in sorted(payloads.items(), key=lambda item: str(item[0])):
            if isinstance(mime, str) and isinstance(value, str):
                image_uri = _safe_image_uri(f"data:{mime};base64,{value}")
                if image_uri is not None:
                    return image_uri
        return match.group(0)

    return _ATTACHMENT.sub(replacement, text)


def _fenced(text: str, language: str) -> str:
    longest = max((len(match.group(0)) for match in _BACKTICKS.finditer(text)), default=0)
    fence = "`" * max(3, longest + 1)
    body = text.rstrip("\n")
    return f"{fence}{language}\n{body}\n{fence}"


def _cell_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "".join(cast(list[str], value))
    return ""


def _split_all_markdown(text: str, pages: int) -> list[str] | None:
    if pages == 1:
        return [text]
    pieces = re.split(r"\n\s*---\s*\n", text.strip())
    return pieces if len(pieces) == pages else None


def _page_block(page: int, text: str) -> str:
    return f"<!-- a2l:page {page} -->\n{_normalise_markdown(text).rstrip()}"


def _normalise_markdown(text: str) -> str:
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip() + "\n" if text.strip() else ""


def _text_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _text_image_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    raise ConversionError("PDF renderer returned a non-byte image")


def _pdf_oxide_page_count(document: object) -> int:
    value = getattr(document, "page_count", None)
    if callable(value):
        value = value()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConversionError("PDF backend returned an invalid page count")
    return value


def _call_method(value: object, name: str, *args: object, **kwargs: object) -> object:
    method = getattr(value, name, None)
    if not callable(method):
        raise ConversionError(f"PDF backend does not provide {name}")
    return method(*args, **kwargs)


def _close_quietly(value: object) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            return


def _configure_tesseract(language: str) -> bool:
    candidates: list[Path] = []
    found = shutil.which("tesseract")
    if found:
        candidates.append(Path(found))
    if os.name == "nt":
        program_files = os.environ.get("PROGRAMFILES")
        if program_files:
            candidates.append(Path(program_files) / "Tesseract-OCR" / "tesseract.exe")
        candidates.append(Path.home() / "AppData" / "Local" / "Tesseract-OCR" / "tesseract.exe")
    executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None:
        return False
    pytesseract.pytesseract.tesseract_cmd = os.fspath(executable)
    try:
        languages = pytesseract.get_languages(config="")
    except (OSError, pytesseract.TesseractError):
        return False
    return language in languages


def _validate_threshold(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("ocr_words_per_page must be a positive integer")


def _package_version(distribution: str, default: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return default


def _expected_tool(source: Path, backend: ConverterBackend) -> tuple[str, str]:
    kind = _classify_source(source)
    if kind == "pdf":
        return backend.name, backend.version
    if kind == "notebook":
        return "nbformat", _package_version("nbformat", "missing")
    if kind == "html_zip":
        return "html-archive", CONVERTER_VERSION
    if kind == "html":
        return "html-sanitizer", CONVERTER_VERSION
    if kind == "office":
        return "markitdown", _package_version("markitdown", "missing")
    return "agent2learn-text", CONVERTER_VERSION


def _artifact_is_current(
    vault: Vault,
    artifact: DerivedArtifact,
    entry: ManifestEntry,
    expected_tool: str,
    expected_version: str,
    expected_threshold: int | None,
) -> bool:
    if (
        artifact.source_sha256 != entry.sha256
        or artifact.tool != expected_tool
        or artifact.tool_version != expected_version
        or artifact.ocr_words_per_page != expected_threshold
    ):
        return False
    path = _artifact_path(vault, artifact)
    return path.is_file() and _hash_file(path)[0] == artifact.sha256


def _artifact_path(vault: Vault, artifact: DerivedArtifact) -> Path:
    return vault.materialized(
        ManifestEntry(
            path=artifact.path,
            sha256=artifact.sha256,
            source_id="derived",
            etag=None,
            last_modified=None,
            size=0,
            fetched_at="2026-01-01T00:00:00Z",
        )
    )


def _hash_file(source: Path) -> tuple[str, int]:
    from hashlib import sha256

    digest = sha256()
    size = 0
    try:
        with open(os.fspath(paths.long_path(source)), "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except (FileNotFoundError, IsADirectoryError):
        return "", -1
    return digest.hexdigest(), size


def _update_content_map(vault: Vault, key: str, **updates: object) -> None:
    for destination in sorted(vault.root.rglob("content_map.json")):
        try:
            raw = course_index.read_content_map(destination.parent.parent)
        except (A2LError, UnicodeError):
            continue
        changed = False
        raw_rows = raw.get("topics")
        if not isinstance(raw_rows, list):
            continue
        rows: list[object] = raw_rows
        for row in rows:
            if isinstance(row, dict) and row.get("source_key") == key:
                row.update(updates)
                changed = True
        if changed:
            checked = course_index.reconcile_content_map(vault, rows)
            course_index.write_content_map(destination.parent.parent, checked)


def _now() -> str:
    return clock.stamp()


__all__ = [
    "CONVERTER_VERSION",
    "DEFAULT_OCR_WORDS_PER_PAGE",
    "ConversionError",
    "ConversionReport",
    "ConversionResult",
    "ConverterBackend",
    "PageCoverage",
    "PdfOxideBackend",
    "PdfiumBackend",
    "convert_html_zip",
    "convert_pdf",
    "convert_source",
    "convert_vault",
    "render_notebook",
]
