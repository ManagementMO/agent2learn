#!/usr/bin/env python3
"""Deterministically generate the synthetic API fixture corpus.

Every fixture in this repository is **authored**, never captured. Nothing here is
transformed from a real student account: the shapes come from D2L's documented schemas
and the client contracts in the design spec, and every identifier, name, and timestamp
is an obvious invention.

Determinism is a hard requirement. Re-running this script must produce a clean Git
diff, which is what lets the golden-vault test detect a real change instead of noise.
That means: sorted JSON keys, UTF-8, LF only, exactly one trailing newline, fixed
timestamps, fixed archive member dates, and no PDF creation date.

Constraints, enforced by ``tests/test_fixture_contract.py``:
  * no network access and no environment or session reads;
  * only identity tokens from ``ALLOWED_IDENTITY_TOKENS`` appear in output;
  * no URL query strings and no high-entropy strings;
  * all timestamps are the fixed UTC values below.

Developer tool. Not shipped in the wheel, not imported by the package.

    uv run python tools/generate_fixtures.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "tests" / "fixtures" / "api"
FILES = ROOT / "tests" / "fixtures" / "files"
MANIFEST = ROOT / "tests" / "fixtures" / "SHA256SUMS"

# --------------------------------------------------------------------------------------
# Synthetic identities. The contract test asserts that no token outside this set appears.
# --------------------------------------------------------------------------------------
STUDENT_ID = "99999999"
STUDENT_FIRST = "Alex"
STUDENT_LAST = "Example"
STUDENT_USER = "aexample"

TERM_CODE = "1261"  # 1900 + 126 = 2026, season 1 = Winter
COURSE_A_OU = 111111
COURSE_B_OU = 222222
COURSE_A = "COURSE101"
COURSE_B = "COURSE202"

# One frozen instant, reused everywhere a time is needed.
T0 = "2026-01-05T14:00:00.000Z"
T1 = "2026-01-12T14:00:00.000Z"
T2 = "2026-01-19T14:00:00.000Z"
DUE_A = "2026-02-06T04:59:00.000Z"
DUE_B = "2026-03-13T03:59:00.000Z"

LE = "1.96"
LP = "1.62"

# --------------------------------------------------------------------------------------
# Adversarial names. These exist so path handling is exercised by the golden-vault test
# rather than only by unit tests of safe_name().
# --------------------------------------------------------------------------------------
LONG_TITLE = "Long title " + ("x" * (300 - len("Long title ")))
NFD_NAME = unicodedata.normalize("NFD", "Café Notes.pdf")  # decomposed on purpose


def _content_url(ou: int, name: str) -> str:
    """A first-party content path. No query string, by contract."""
    return f"/content/enforced/{ou}-{COURSE_A}/{name}"


# --------------------------------------------------------------------------------------
# Endpoint fixtures
# --------------------------------------------------------------------------------------
def versions() -> object:
    return [
        {"ProductCode": "le", "LatestVersion": LE, "SupportedVersions": ["1.94", "1.95", LE]},
        {"ProductCode": "lp", "LatestVersion": LP, "SupportedVersions": ["1.60", "1.61", LP]},
    ]


def whoami() -> object:
    return {
        "Identifier": STUDENT_ID,
        "FirstName": STUDENT_FIRST,
        "LastName": STUDENT_LAST,
        "UniqueName": STUDENT_USER,
        "ProfileIdentifier": "SYNTHETIC-PROFILE-0001",
    }


def _enrollment(ou: int, code: str, name: str, section: str) -> dict:
    return {
        "OrgUnit": {
            "Id": ou,
            "Type": {"Id": 3, "Code": "Course Offering", "Name": "Course Offering"},
            "Name": name,
            "Code": f"{code}_{section}_{TERM_CODE}",
        },
        "Access": {"IsActive": True, "StartDate": T0, "EndDate": None},
    }


def myenrollments_page1() -> object:
    """First page. HasMoreItems drives the pagination path in the client."""
    return {
        "PagingInfo": {"Bookmark": "SYNTHETIC-BOOKMARK-0001", "HasMoreItems": True},
        "Items": [_enrollment(COURSE_A_OU, COURSE_A, "Introduction to Example Studies", "sec01")],
    }


def myenrollments_page2() -> object:
    return {
        "PagingInfo": {"Bookmark": "SYNTHETIC-BOOKMARK-0002", "HasMoreItems": False},
        "Items": [
            _enrollment(COURSE_B_OU, COURSE_B, "Intermediate Example Methods", "sec02"),
            # A non-course org unit that the adapter must filter out.
            {
                "OrgUnit": {
                    "Id": 333333,
                    "Type": {"Id": 2, "Code": "Department", "Name": "Department"},
                    "Name": "Example Department",
                    "Code": "EXAMPLEDEPT",
                },
                "Access": {"IsActive": True, "StartDate": T0, "EndDate": None},
            },
        ],
    }


def _topic(tid: int, title: str, url: str, *, kind: str = "File", modified: str = T0) -> dict:
    return {
        "TopicId": tid,
        "Title": title,
        "TypeIdentifier": kind,
        "Url": url,
        "LastModifiedDate": modified,
        "IsBroken": False,
    }


def content_toc_a() -> object:
    """The adversarial TOC. Every path hazard the spec names appears here."""
    return {
        "Modules": [
            {
                "ModuleId": 900001,
                "Title": "Week 1 Introduction",
                "Modules": [],
                "Topics": [
                    _topic(800001, "Lecture Slides", _content_url(COURSE_A_OU, "lecture01.pdf")),
                    # Trailing dot: Win32 silently strips it.
                    _topic(800002, "Reading list.", _content_url(COURSE_A_OU, "reading.pdf")),
                    # NFD-decomposed accented name.
                    _topic(800003, NFD_NAME, _content_url(COURSE_A_OU, "cafe-notes.pdf")),
                ],
            },
            {
                # Reserved Windows device name as a directory.
                "ModuleId": 900002,
                "Title": "CON",
                "Modules": [
                    {
                        "ModuleId": 900003,
                        "Title": "Nested Submodule",
                        "Modules": [],
                        "Topics": [
                            _topic(
                                800004,
                                "Notebook",
                                _content_url(COURSE_A_OU, "analysis.ipynb"),
                                modified=T1,
                            )
                        ],
                    }
                ],
                "Topics": [],
            },
            {
                "ModuleId": 900004,
                "Title": "Week 2 Hazards",
                "Modules": [],
                "Topics": [
                    # Case-only collision: identical on Windows and default macOS.
                    _topic(800005, "Lab Notes", _content_url(COURSE_A_OU, "lab-notes-a.pdf")),
                    _topic(800006, "lab notes", _content_url(COURSE_A_OU, "lab-notes-b.pdf")),
                    # Over-length component.
                    _topic(800007, LONG_TITLE, _content_url(COURSE_A_OU, "long.pdf")),
                    # Licensed / third-party targets: recorded as stubs, never fetched.
                    _topic(
                        800008,
                        "Publisher eText",
                        "https://example-vitalsource.invalid/book/synthetic-0001",
                        kind="Link",
                    ),
                    _topic(
                        800009,
                        "External Tool",
                        "https://example-lti.invalid/launch/synthetic-0001",
                        kind="lti",
                    ),
                    _topic(
                        800010,
                        "Quicklink",
                        "https://quicklink.d2l.invalid/d2l/le/content/synthetic-0001",
                        kind="Link",
                    ),
                    # Archive + Rmd + plain HTML, for the converter paths.
                    _topic(
                        800011,
                        "Site Archive",
                        _content_url(COURSE_A_OU, "site.html.zip"),
                        modified=T2,
                    ),
                    _topic(800012, "R Notes", _content_url(COURSE_A_OU, "notes.Rmd"), modified=T2),
                ],
            },
            {
                # An empty module must still appear in the index.
                "ModuleId": 900005,
                "Title": "Week 3 Empty",
                "Modules": [],
                "Topics": [],
            },
        ]
    }


def content_toc_b() -> object:
    return {
        "Modules": [
            {
                "ModuleId": 910001,
                "Title": "Unit 1",
                "Modules": [],
                "Topics": [
                    _topic(
                        810001,
                        "Course Outline",
                        f"/content/enforced/{COURSE_B_OU}-{COURSE_B}/outline.pdf",
                    )
                ],
            }
        ]
    }


def dropbox_folders_a() -> object:
    return [
        {
            "Id": 700001,
            "Name": "Problem Set 1",
            "GradeItemId": 600001,
            "DueDate": DUE_A,
            "GroupTypeId": None,
            "Availability": {"StartDate": T0, "EndDate": None},
        },
        {
            # Non-graded: the only kind the supervised upload test may target.
            "Id": 700002,
            "Name": "Practice Upload",
            "GradeItemId": None,
            "DueDate": DUE_B,
            "GroupTypeId": None,
            "Availability": {"StartDate": T0, "EndDate": None},
        },
        {
            # Group folder: v0.1 previews then refuses.
            "Id": 700003,
            "Name": "Team Report",
            "GradeItemId": 600002,
            "DueDate": DUE_B,
            "GroupTypeId": 500001,
            "Availability": {"StartDate": T0, "EndDate": None},
        },
    ]


def submissions_readback() -> object:
    """Shape of the read-back that `submit` requires before reporting success."""
    return [
        {
            "Entity": {"EntityType": "User", "EntityId": int(STUDENT_ID), "Active": True},
            "Submissions": [
                {
                    "Id": 400001,
                    "SubmissionDate": T2,
                    "Comment": {"Text": "", "Html": ""},
                    "Files": [{"FileId": 300001, "FileName": "submission.txt", "Size": 307}],
                }
            ],
        }
    ]


def news_a() -> object:
    return [
        {
            "Id": 200001,
            "Title": "Welcome to the course",
            "Body": {"Text": "Office hours are listed in the outline.", "Html": None},
            "StartDate": T0,
            "EndDate": None,
            "IsPublished": True,
            "Attachments": [],
        },
        {
            "Id": 200002,
            "Title": "Reading posted",
            "Body": {"Text": "The Week 2 reading is now available.", "Html": None},
            "StartDate": T1,
            "EndDate": None,
            "IsPublished": True,
            "Attachments": [],
        },
        {
            # Removed in news_a_withdrawn.json to exercise merge-not-replace.
            "Id": 200003,
            "Title": "Temporary notice",
            "Body": {"Text": "This notice is withdrawn in a later sync.", "Html": None},
            "StartDate": T2,
            "EndDate": None,
            "IsPublished": True,
            "Attachments": [],
        },
    ]


def news_a_withdrawn() -> object:
    """Same feed with the middle item absent. Two consecutive absences mark it withdrawn."""
    return [item for item in news_a() if item["Id"] != 200002]


def quizzes_a() -> object:
    return {
        "Next": None,
        "Objects": [
            {
                "QuizId": 100001,
                "Name": "Quiz 1",
                "DueDate": DUE_A,
                "StartDate": T0,
                "EndDate": None,
                "IsActive": True,
            }
        ],
    }


def grades_myvalues_a() -> object:
    """Opt-in only. Never fetched unless the student enables grade sync."""
    return [
        {
            "GradeObjectIdentifier": "600001",
            "GradeObjectName": "Problem Set 1",
            "GradeObjectType": 1,
            "PointsNumerator": 17.0,
            "PointsDenominator": 20.0,
            "DisplayedGrade": "17/20",
        }
    ]


def discussions_forums_a() -> object:
    """Opt-in only. Author identities are pseudonymised by the ingest layer."""
    return [
        {
            "ForumId": 50001,
            "Name": "General Discussion",
            "Description": {"Text": "Ask questions here.", "Html": None},
            "StartDate": T0,
            "EndDate": None,
        }
    ]


JSON_FIXTURES: dict[str, object] = {
    "versions.json": versions(),
    "whoami.json": whoami(),
    "myenrollments_page1.json": myenrollments_page1(),
    "myenrollments_page2.json": myenrollments_page2(),
    "content_toc_course101.json": content_toc_a(),
    "content_toc_course202.json": content_toc_b(),
    "dropbox_folders_course101.json": dropbox_folders_a(),
    "submissions_readback_course101.json": submissions_readback(),
    "news_course101.json": news_a(),
    "news_course101_withdrawn.json": news_a_withdrawn(),
    "quizzes_course101.json": quizzes_a(),
    "grades_myvalues_course101.json": grades_myvalues_a(),
    "discussions_forums_course101.json": discussions_forums_a(),
}

# Non-JSON responses. Kept out of api/ so the JSON contract test can glob *.json safely.
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Sign In</title></head>
<body>
<h1>Sign in to continue</h1>
<form action="/d2l/lp/auth/login/login.d2l" method="post">
<input type="text" name="userName" />
<input type="password" name="password" />
</form>
</body>
</html>
"""

# Deliberately invalid JSON: the client must fail cleanly, not crash.
MALFORMED_BODY = '{"Items": [{"OrgUnit": {"Id": 111111,\n'

RATE_LIMITED_BODY = """<!DOCTYPE html>
<html lang="en"><head><title>Too Many Requests</title></head>
<body><p>Please slow down and retry later.</p></body>
</html>
"""


# --------------------------------------------------------------------------------------
# Deterministic binary fixtures
# --------------------------------------------------------------------------------------
def build_pdf(pages: list[str]) -> bytes:
    """A minimal, valid, reproducible PDF.

    Written by hand rather than with a library so there is no creation date, no
    producer string, and no run-to-run variation. Offsets are computed, so the xref
    table is correct and real parsers accept it.
    """
    objects: list[bytes] = []
    n_pages = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def build_notebook() -> str:
    """An *executed* notebook. Its outputs are grounding evidence and must survive
    conversion, so the fixture carries stream, execute_result, and error outputs plus a
    markdown attachment and a code body containing backticks."""
    nb = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Analysis\n", "\n", "Inline image: ![tiny](attachment:tiny.png)\n"],
                "attachments": {
                    "tiny.png": {
                        # 1x1 transparent PNG, the smallest valid image.
                        "image/png": (
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP"
                            "6DwABBQEBzOSxNgAAAABJRU5ErkJggg=="
                        )
                    }
                },
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "source": ["print('hello')\n", "# a fence in the body: ```\n"],
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": ["hello\n"]},
                    {
                        "output_type": "execute_result",
                        "execution_count": 1,
                        "metadata": {},
                        "data": {"text/plain": ["   col_a  col_b\n", "0      1      2\n"]},
                    },
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "metadata": {},
                "source": ["raise ValueError('example')\n"],
                "outputs": [
                    {
                        "output_type": "error",
                        "ename": "ValueError",
                        "evalue": "example",
                        "traceback": [
                            "\u001b[0;31mValueError\u001b[0m: example",
                        ],
                    }
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 3,
                "metadata": {},
                "source": ["display_unsupported()\n"],
                "outputs": [
                    {
                        "output_type": "display_data",
                        "metadata": {},
                        # No safe textual representation: the converter must emit an
                        # explicit marker rather than dropping the cell silently.
                        "data": {"application/vnd.example.custom+json": {"value": 1}},
                    }
                ],
            },
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(nb, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


RMD_SOURCE = """---
title: "Example R Notes"
output: html_document
---

## Setup

```{r}
summary(cars)
```

Repository-authored text. No course material appears in this file.
"""

HTML_INDEX = """<!DOCTYPE html>
<html lang="en">
<head><title>Example Site</title><link rel="stylesheet" href="style.css" /></head>
<body>
<h1>Example Site</h1>
<p>Repository-authored content for archive-extraction tests.</p>
</body>
</html>
"""

HTML_STYLE = "body { font-family: sans-serif; }\n"


def build_html_zip(path: Path) -> None:
    """Zip with fixed member timestamps and no extra metadata, so bytes are stable."""
    fixed = (2026, 1, 5, 14, 0, 0)
    if path.exists():
        path.unlink()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in (("index.html", HTML_INDEX), ("style.css", HTML_STYLE)):
            info = zipfile.ZipInfo(name, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 0  # always report DOS, never the build host
            zf.writestr(info, text)


# --------------------------------------------------------------------------------------
def dump_json(value: object) -> str:
    """The single canonical serialisation. Matches spec C7."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def generate() -> dict[str, str]:
    """Write every fixture; return {relative path: sha256}."""
    written: dict[str, bytes] = {}

    for name, value in JSON_FIXTURES.items():
        written[f"api/{name}"] = dump_json(value).encode("utf-8")

    written["api/nonjson/login.html"] = LOGIN_HTML.encode("utf-8")
    written["api/nonjson/malformed_body.txt"] = MALFORMED_BODY.encode("utf-8")
    written["api/nonjson/rate_limited.html"] = RATE_LIMITED_BODY.encode("utf-8")

    written["files/lecture01.pdf"] = build_pdf(
        ["Example lecture page one.", "Example lecture page two."]
    )
    written["files/analysis.ipynb"] = build_notebook().encode("utf-8")
    written["files/notes.Rmd"] = RMD_SOURCE.encode("utf-8")

    base = ROOT / "tests" / "fixtures"
    for rel, data in written.items():
        write(base / rel, data)

    # The zip is written directly because ZipFile owns the file handle.
    build_html_zip(FILES / "site.html.zip")
    written["files/site.html.zip"] = (FILES / "site.html.zip").read_bytes()

    return {rel: hashlib.sha256(data).hexdigest() for rel, data in sorted(written.items())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate and fail if any fixture or hash would change",
    )
    args = ap.parse_args()

    before = MANIFEST.read_text(encoding="utf-8") if MANIFEST.exists() else ""
    sums = generate()
    body = "".join(f"{digest}  {rel}\n" for rel, digest in sums.items())

    if args.check:
        if body != before:
            print("FAIL  fixture output is not reproducible; regenerate and inspect the diff")
            return 1
        print(f"ok    {len(sums)} fixtures reproduce byte-for-byte")
        return 0

    MANIFEST.write_text(body, encoding="utf-8")
    print(f"wrote {len(sums)} fixtures and {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
