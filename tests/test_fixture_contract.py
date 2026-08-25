"""Contract tests for the synthetic fixture corpus.

These guard three separate things, and each has bitten a real project:

1. **Shape.** Every fixture matches an explicit per-endpoint key/type contract, and
   unknown keys are rejected. Fixtures otherwise grow field by field until nobody knows
   which parts the adapters actually rely on.
2. **Privacy.** Only the approved synthetic identity tokens may appear. A fixture is the
   easiest place for real student data to reach a public repository.
3. **Determinism.** Fixed UTC timestamps, no query strings, no high-entropy strings,
   canonical JSON formatting. Non-determinism here makes the golden-vault test useless.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
API = FIXTURES / "api"
NONJSON = API / "nonjson"
FILES = FIXTURES / "files"

JSON_FILES = sorted(API.glob("*.json"))

# --------------------------------------------------------------------------------------
# Approved synthetic vocabulary
# --------------------------------------------------------------------------------------
ALLOWED_IDENTITY_TOKENS = {
    "Alex",
    "Example",
    "aexample",
    "99999999",
    "COURSE101",
    "COURSE202",
    "EXAMPLEDEPT",
    "SYNTHETIC-PROFILE-0001",
    "SYNTHETIC-BOOKMARK-0001",
    "SYNTHETIC-BOOKMARK-0002",
}

# Anything that looks like a person, a real institution, or a real course code.
FORBIDDEN_PATTERNS = [
    (re.compile(r"\buwaterloo\b", re.I), "real institution hostname"),
    (re.compile(r"\bd2lSessionVal\b|\bd2lSecureSessionVal\b"), "session cookie name"),
    (re.compile(r"\bMSISAuth\w*\b"), "SSO cookie name"),
    (re.compile(r"\b(?:MSE|MSCI|PSYCH|ECE|CS|MATH)\s?\d{3}\b", re.I), "real course code"),
    (re.compile(r"\b2[01]\d{6}\b"), "student-number-shaped value"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email address"),
]

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
ALLOWED_TIMESTAMPS = {
    "2026-01-05T14:00:00.000Z",
    "2026-01-12T14:00:00.000Z",
    "2026-01-19T14:00:00.000Z",
    "2026-02-06T04:59:00.000Z",
    "2026-03-13T03:59:00.000Z",
}


def _walk(node: Any, path: str = "$"):
    """Yield (json-path, value) for every scalar in a decoded document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def _strings(node: Any):
    for p, v in _walk(node):
        if isinstance(v, str):
            yield p, v


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


# --------------------------------------------------------------------------------------
# Per-endpoint key contracts. Unknown keys fail: schema drift must be a review, not an
# accident.
# --------------------------------------------------------------------------------------
def _keys(obj: dict) -> set[str]:
    return set(obj.keys())


SCHEMAS: dict[str, dict[str, set[str]]] = {
    "versions.json": {"*": {"ProductCode", "LatestVersion", "SupportedVersions"}},
    "whoami.json": {
        "$": {"Identifier", "FirstName", "LastName", "UniqueName", "ProfileIdentifier"}
    },
    "myenrollments_page1.json": {"$": {"PagingInfo", "Items"}},
    "myenrollments_page2.json": {"$": {"PagingInfo", "Items"}},
    "content_toc_course101.json": {"$": {"Modules"}},
    "content_toc_course202.json": {"$": {"Modules"}},
    "dropbox_folders_course101.json": {
        "*": {"Id", "Name", "GradeItemId", "DueDate", "GroupTypeId", "Availability"}
    },
    "submissions_readback_course101.json": {"*": {"Entity", "Submissions"}},
    "news_course101.json": {
        "*": {"Id", "Title", "Body", "StartDate", "EndDate", "IsPublished", "Attachments"}
    },
    "news_course101_withdrawn.json": {
        "*": {"Id", "Title", "Body", "StartDate", "EndDate", "IsPublished", "Attachments"}
    },
    "quizzes_course101.json": {"$": {"Next", "Objects"}},
    "grades_myvalues_course101.json": {
        "*": {
            "GradeObjectIdentifier",
            "GradeObjectName",
            "GradeObjectType",
            "PointsNumerator",
            "PointsDenominator",
            "DisplayedGrade",
        }
    },
    "discussions_forums_course101.json": {
        "*": {"ForumId", "Name", "Description", "StartDate", "EndDate"}
    },
}

MODULE_KEYS = {"ModuleId", "Title", "Modules", "Topics"}
TOPIC_KEYS = {"TopicId", "Title", "TypeIdentifier", "Url", "LastModifiedDate", "IsBroken"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------------------
def test_every_json_fixture_has_a_declared_schema() -> None:
    """A new fixture must arrive with a contract, not slip in unchecked."""
    undeclared = {p.name for p in JSON_FILES} - set(SCHEMAS)
    assert not undeclared, f"fixtures without a declared schema: {sorted(undeclared)}"


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_top_level_keys_match_contract(path: Path) -> None:
    doc = load(path)
    schema = SCHEMAS[path.name]
    if "$" in schema:
        assert isinstance(doc, dict), f"{path.name}: expected an object"
        unknown = _keys(doc) - schema["$"]
        assert not unknown, f"{path.name}: unknown top-level keys {sorted(unknown)}"
    if "*" in schema:
        assert isinstance(doc, list), f"{path.name}: expected an array"
        for i, item in enumerate(doc):
            unknown = _keys(item) - schema["*"]
            assert not unknown, f"{path.name}[{i}]: unknown keys {sorted(unknown)}"


@pytest.mark.parametrize(
    "path", [p for p in JSON_FILES if p.name.startswith("content_toc")], ids=lambda p: p.name
)
def test_toc_modules_and_topics_match_contract(path: Path) -> None:
    def check_module(m: dict, where: str) -> None:
        unknown = _keys(m) - MODULE_KEYS
        assert not unknown, f"{where}: unknown module keys {sorted(unknown)}"
        assert isinstance(m["ModuleId"], int)
        assert isinstance(m["Title"], str)
        for i, t in enumerate(m["Topics"]):
            tu = _keys(t) - TOPIC_KEYS
            assert not tu, f"{where}.Topics[{i}]: unknown topic keys {sorted(tu)}"
            assert isinstance(t["TopicId"], int)
            assert isinstance(t["IsBroken"], bool)
        for i, sub in enumerate(m["Modules"]):
            check_module(sub, f"{where}.Modules[{i}]")

    for i, mod in enumerate(load(path)["Modules"]):
        check_module(mod, f"$.Modules[{i}]")


def test_topic_ids_are_unique_across_the_corpus() -> None:
    """Stable IDs define identity; a duplicate would make the manifest ambiguous."""
    seen: dict[int, str] = {}
    for path in JSON_FILES:
        if not path.name.startswith("content_toc"):
            continue

        def collect(m: dict, src: str = path.name) -> None:
            for t in m["Topics"]:
                assert t["TopicId"] not in seen, (
                    f"TopicId {t['TopicId']} appears in both {seen.get(t['TopicId'])} and {src}"
                )
                seen[t["TopicId"]] = src
            for sub in m["Modules"]:
                collect(sub, src)

        for mod in load(path)["Modules"]:
            collect(mod)
    assert seen, "no topics found"


# --------------------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------------------
ALL_TEXT_FILES = JSON_FILES + sorted(NONJSON.iterdir()) + [FILES / "notes.Rmd"]


@pytest.mark.parametrize("path", ALL_TEXT_FILES, ids=lambda p: p.name)
def test_no_forbidden_identity_patterns(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pattern, label in FORBIDDEN_PATTERNS:
        m = pattern.search(text)
        assert m is None, f"{path.name}: {label} present -> {m.group(0)!r}"


def test_identity_bearing_fields_use_only_approved_values() -> None:
    """Check the fields that actually carry identity, rather than guessing at prose.

    An earlier version flagged any two capitalised words, which reported "The Week" from
    the sentence "The Week 2 reading is now available." Capitalisation is not a signal in
    authored prose. Personal data in a D2L payload lives in known keys, so those are
    enumerated and their values constrained.
    """
    identity_keys = {
        "FirstName",
        "LastName",
        "UniqueName",
        "Identifier",
        "ProfileIdentifier",
        "DisplayName",
        "UserName",
        "EmailAddress",
        "OrgDefinedId",
    }
    approved = ALLOWED_IDENTITY_TOKENS | {None}
    for path in JSON_FILES:
        for jpath, value in _walk(load(path)):
            key = jpath.rsplit(".", 1)[-1].split("[")[0]
            if key in identity_keys:
                assert value in approved or str(value) in approved, (
                    f"{path.name} {jpath}: identity field carries unapproved value {value!r}"
                )


def test_no_identity_key_is_silently_absent_from_the_corpus() -> None:
    """The check above is only meaningful if identity fields actually appear somewhere."""
    seen = set()
    for path in JSON_FILES:
        for jpath, _ in _walk(load(path)):
            seen.add(jpath.rsplit(".", 1)[-1].split("[")[0])
    assert {"FirstName", "LastName", "UniqueName", "Identifier"} <= seen, (
        "whoami-style identity fields are missing; the identity assertion would be vacuous"
    )


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_timestamps_are_fixed_and_utc(path: Path) -> None:
    for jpath, value in _strings(load(path)):
        if TIMESTAMP.match(value):
            assert value in ALLOWED_TIMESTAMPS, f"{path.name} {jpath}: unfixed timestamp {value}"


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_no_url_query_strings(path: Path) -> None:
    """A query string is where signed tokens and launch data hide."""
    for jpath, value in _strings(load(path)):
        if value.startswith(("http://", "https://", "/")):
            assert "?" not in value, f"{path.name} {jpath}: URL carries a query string"
            assert "#" not in value, f"{path.name} {jpath}: URL carries a fragment"


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_no_high_entropy_strings(path: Path) -> None:
    """Approximates "this looks like a credential".

    Thresholds are calibrated against measurements rather than guessed. English prose
    ("Introduction to Example Studies") scores 4.07 and a content path scores 4.14, so a
    4.0 cut-off produces nothing but false positives. Real credentials score higher and
    never contain whitespace: a JWT header scores 4.36 and a random 32-character token
    4.81. Prose is therefore excluded by its whitespace, URLs and paths are excluded
    because query strings and fragments are checked separately, and what remains is
    tested at 4.2.
    """
    for jpath, value in _strings(load(path)):
        if len(value) < 24 or " " in value:
            continue
        if value.startswith(("http://", "https://", "/")):
            continue
        assert _shannon(value) <= 4.2, (
            f"{path.name} {jpath}: credential-shaped string {value[:40]!r} "
            f"(entropy {_shannon(value):.2f})"
        )


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_canonical_json_formatting(path: Path) -> None:
    raw = path.read_bytes()
    assert b"\r\n" not in raw, f"{path.name}: CRLF line ending"
    assert raw.endswith(b"\n"), f"{path.name}: missing trailing newline"
    assert not raw.endswith(b"\n\n"), f"{path.name}: more than one trailing newline"
    expected = (
        json.dumps(
            json.loads(raw.decode("utf-8")),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    )
    assert raw.decode("utf-8") == expected, f"{path.name}: not canonical (sorted/indent=2)"


def test_generator_reproduces_every_fixture_byte_for_byte() -> None:
    """The determinism guarantee, enforced rather than asserted in prose."""
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent.parent / "tools" / "generate_fixtures.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"fixtures are not reproducible:\n{result.stdout}{result.stderr}"


def test_generator_has_no_network_or_environment_access() -> None:
    source = (Path(__file__).parent.parent / "tools" / "generate_fixtures.py").read_text(
        encoding="utf-8"
    )
    for banned in ("import requests", "import socket", "urllib.request", "os.environ", "getenv"):
        assert banned not in source, f"generator must not use {banned}"


# --------------------------------------------------------------------------------------
# Adversarial coverage — the cases exist, so later path tests cannot silently lose them
# --------------------------------------------------------------------------------------
def test_toc_contains_every_required_adversarial_case() -> None:
    import unicodedata

    doc = load(API / "content_toc_course101.json")
    titles: list[str] = []
    urls: list[str] = []
    kinds: list[str] = []

    def collect(m: dict) -> None:
        titles.append(m["Title"])
        for t in m["Topics"]:
            titles.append(t["Title"])
            urls.append(t["Url"])
            kinds.append(t["TypeIdentifier"])
        for sub in m["Modules"]:
            collect(sub)

    for mod in doc["Modules"]:
        collect(mod)

    assert "CON" in titles, "missing reserved-device-name module"
    assert any(t.endswith(".") for t in titles), "missing trailing-dot title"
    assert any(len(t) >= 300 for t in titles), "missing over-length title"

    lowered = [t.lower() for t in titles]
    assert any(c > 1 for c in Counter(lowered).values()), "missing case-only collision"

    assert any(unicodedata.normalize("NFC", t) != t for t in titles), "missing NFD-encoded title"

    assert any("vitalsource" in u for u in urls), "missing vitalsource exclusion"
    assert any("quicklink.d2l" in u for u in urls), "missing quicklink.d2l exclusion"
    assert any(k.lower() == "lti" for k in kinds), "missing type=lti exclusion"

    assert any(m["Topics"] == [] and m["Modules"] == [] for m in doc["Modules"]), (
        "missing empty module"
    )


def test_binary_fixtures_exist_and_are_well_formed() -> None:
    pdf = (FILES / "lecture01.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-"), "PDF fixture lacks a PDF header"
    assert pdf.rstrip().endswith(b"%%EOF"), "PDF fixture is truncated"
    assert b"/CreationDate" not in pdf, "PDF carries a creation date; output is not reproducible"

    nb = json.loads((FILES / "analysis.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    outputs = [o["output_type"] for c in nb["cells"] for o in c.get("outputs", [])]
    # Executed-cell output is grounding evidence; the fixture must carry every kind the
    # notebook renderer has to preserve.
    for required in ("stream", "execute_result", "error", "display_data"):
        assert required in outputs, f"notebook fixture lacks a {required} output"
    assert any("attachments" in c for c in nb["cells"]), "notebook fixture lacks an attachment"


def test_html_zip_is_reproducible_and_safe() -> None:
    import zipfile

    with zipfile.ZipFile(FILES / "site.html.zip") as zf:
        names = zf.namelist()
        assert names == ["index.html", "style.css"], names
        for info in zf.infolist():
            assert info.date_time == (2026, 1, 5, 14, 0, 0), "archive timestamp is not fixed"
            assert not info.filename.startswith(("/", "..")), "archive member escapes its root"


def test_binary_fixtures_are_marked_binary_in_gitattributes() -> None:
    """Regression guard for a Windows-only corruption.

    The hand-built PDF is 100% printable ASCII with no NUL bytes, so git's ``text=auto``
    heuristic classifies it as *text*. Combined with the repository-wide ``eol=lf`` rule,
    a Windows checkout would rewrite its line endings and silently corrupt a byte-exact
    fixture, breaking both SHA256SUMS and the golden-vault test. ``-text`` prevents that.
    """
    attrs = (Path(__file__).parent.parent / ".gitattributes").read_text(encoding="utf-8")
    assert "tests/fixtures/files/** -text" in attrs, (
        "binary fixtures must be marked -text or Windows checkouts will corrupt them"
    )
    pdf = (FILES / "lecture01.pdf").read_bytes()
    assert b"\x00" not in pdf, (
        "this guard exists because the PDF has no NUL bytes; if that changed, "
        "re-evaluate whether the -text attribute is still required"
    )


def test_archive_fixture_is_uncompressed_for_cross_platform_reproducibility() -> None:
    """Deflate output depends on the zlib build linked into the interpreter, so a
    compressed archive is not byte-reproducible across platforms. CI caught this as a
    Windows/Python 3.14 determinism failure while every other matrix entry passed."""
    import zipfile

    with zipfile.ZipFile(FILES / "site.html.zip") as zf:
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED, (
                f"{info.filename} is compressed; deflate bytes vary by zlib build and "
                "break cross-platform fixture reproducibility"
            )
