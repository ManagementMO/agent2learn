"""An experimental lexical evidence scan over the student's own course material.

``a2l check`` answers one narrow question per claim: *what matching or related text did a
deterministic lexical retrieval find in this course's verified material, and where is it?*  It
does not grade, prove, rewrite, or answer.  Every human-readable report opens with the disclosure
in :data:`DISCLOSURE`, and no status in this module means correct, incorrect, policy-compliant, or
academically acceptable.  The semantic judgement belongs to the person or agent reading the
citations.

Three decisions keep it honest.

**It cannot manufacture its own evidence.**  The source set comes from ``ground.py``, so a
candidate must trace to a LEARN source ID with an archived original and a markdown twin that both
still hash to their recorded digests.  A student's own draft, a downloaded solution, an untracked
sibling, and every Agent2Learn-generated report are therefore unreachable — otherwise a claim
could cite an answer back to itself.

**It is exactly reproducible.**  Scores are computed with :class:`fractions.Fraction` and
serialised as floored integer basis points, so no platform can disagree through floating-point
rounding or JSON formatting.  Candidates are ordered by ``(-score_bp, path, line)``.  There are no
embeddings and no model calls.

**``possible_conflict`` is deliberately weak.**  It fires only for two allowlisted surface forms
whose token sequences are otherwise identical: opposite comparison operators, or opposite
``is``/``is not`` polarity.  A differing number never qualifies, because the lecture's ``n = 10``
and the lab's ``n = 20`` are usually both correct.  A false contradiction is worse than no tool at
all: it would lead a student to "fix" a right answer using the authority of their own course
notes.  The status is rendered as an invitation to compare, never as a claim that the student is
wrong.

``CANDIDATE_FLOOR_BP``, ``STRONG_MATCH_FLOOR_BP``, the tokeniser, the ``GENERIC`` stopwords, and
the segmentation heuristic together define :data:`CHECK_ALGORITHM_VERSION`.  Changing any of them
requires a version bump and fixture review.
"""

from __future__ import annotations

import heapq
import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Literal

from agent2learn import ground, paths
from agent2learn import index as course_index
from agent2learn.errors import A2LError
from agent2learn.ground import GENERIC, tok
from agent2learn.vault import Vault

CHECK_ALGORITHM_VERSION = 1
CANDIDATE_FLOOR_BP = 3_500
STRONG_MATCH_FLOOR_BP = 7_500
NOTATION_FLOOR_BP = 7_200
TOP_CITATIONS = 5
DISCLOSURE = "Experimental lexical evidence scan — review the cited sources yourself."

SUPPORTED_SUFFIXES = frozenset({".md", ".txt", ".ipynb", ".py", ".r", ".rmd", ".tex"})

ClaimKind = Literal["prose", "code", "formula", "step"]
Status = Literal[
    "evidence_found",
    "related_evidence",
    "no_matching_evidence",
    "possible_conflict",
    "skipped",
]

_FETCHABLE = frozenset({"metadata_only", "source_only", "integrity_gap"})
_AVAILABILITY_NOTES = {
    "metadata_only": "known from metadata but never fetched",
    "source_only": "fetched, but it has no markdown twin yet",
    "integrity_gap": "on-disk bytes no longer match the manifest",
    "conversion_gap": "fetched, but conversion produced no markdown twin",
    "unsupported_format": "no converter handles this format",
    "external_link": "external or licensed link, deliberately not fetched",
}

# Function and discourse words. Distinct from GENERIC, which removes coursework-title noise from
# retrieval scoring: this set decides whether a sentence carries any checkable content at all.
_FUNCTION = frozenset(
    {
        "a", "about", "above", "after", "again", "all", "also", "although", "am", "an", "and",
        "another", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
        "both", "but", "by", "can", "could", "did", "do", "does", "during", "each", "else",
        "finally", "first", "following", "for", "from", "further", "had", "has", "have", "he",
        "hence", "her", "here", "him", "his", "how", "however", "i", "if", "in", "into", "is",
        "it", "its", "just", "least", "less", "many", "may", "me", "might", "more", "most",
        "must", "my", "never", "next", "no", "not", "now", "of", "on", "one", "only", "or",
        "other", "our", "over", "per", "quite", "rather", "same", "second", "shall", "she",
        "should", "since", "so", "some", "still", "such", "than", "that", "the", "their", "them",
        "then", "there", "therefore", "these", "they", "third", "this", "those", "though",
        "thus", "to", "under", "until", "up", "us", "very", "via", "was", "we", "were", "what",
        "when", "where", "which", "while", "who", "whom", "whose", "why", "will", "with",
        "within", "without", "would", "yet", "you", "your",
    }
)  # fmt: skip

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_STEP = re.compile(r"^\s*\d+\s*[.)]\s+")
_NUMBER_OR_MATH = re.compile(r"\d|[=<>≤≥≠∈∉∑∏∫√±×÷^{}]")
_DEFINITION_CUE = re.compile(
    r"\b(?:is|are)\s+defined\b|\bwe\s+(?:define|denote|let)\b|\bdenotes?\b|\bmeans\b|"
    r"\brefers?\s+to\b|\blet\s+\w+\s+be\b",
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(
    r"`[^`]+`|[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|"
    r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)+|[a-z]+[A-Z][A-Za-z0-9]*"
)
_NAMED_METHOD = re.compile(
    r"\b[A-Z][a-z]+(?:['\u2019]s)?\s+(?:algorithm|method|decomposition|theorem|lemma|rule|"
    r"criterion|transform|test|inequality|bound|relaxation)\b"
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NEGATION = re.compile(r"\b(?:not|no|never|cannot|without)\b|n['\u2019]t\b", re.IGNORECASE)
_IS_POLARITY = re.compile(r"\bis(?P<not>\s+not)?\b", re.IGNORECASE)
_RUN = re.compile(r"[a-z0-9]+")

# Longest first: "greater than or equal to" must not be consumed as "greater than".
_WORD_OPERATORS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in (
        (r"\bgreater\s+than\s+or\s+equal\s+to\b", ">="),
        (r"\bless\s+than\s+or\s+equal\s+to\b", "<="),
        (r"\bno\s+more\s+than\b", "<="),
        (r"\bno\s+less\s+than\b", ">="),
        (r"\bat\s+most\b", "<="),
        (r"\bat\s+least\b", ">="),
        (r"\bstrictly\s+greater\s+than\b", ">"),
        (r"\bstrictly\s+less\s+than\b", "<"),
        (r"\bgreater\s+than\b", ">"),
        (r"\bless\s+than\b", "<"),
    )
)
_SYMBOL_OPERATORS = ("<=", ">=", "!=", "==", "≤", "≥", "≠", "∈", "<", ">", "=")
_CANONICAL_OPERATOR = {"≤": "<=", "≥": ">=", "≠": "!=", "==": "="}
_OPPOSITES = {
    "<": frozenset({">", ">="}),
    ">": frozenset({"<", "<="}),
    "<=": frozenset({">", ">="}),
    ">=": frozenset({"<", "<="}),
    "=": frozenset({"!="}),
    "!=": frozenset({"="}),
}


@dataclass(frozen=True)
class Claim:
    """One checkable unit of the draft, located by its starting line."""

    line: int
    text: str
    kind: ClaimKind


@dataclass(frozen=True)
class Citation:
    """One retrieved course span, pinned to the revision that was scanned."""

    path: str
    line: int
    excerpt: str
    source_sha256: str
    derived_sha256: str
    retrieval_score_bp: int


@dataclass(frozen=True)
class Finding:
    """What retrieval found for one claim, and nothing more."""

    claim: Claim
    status: Status
    citations: list[Citation] = field(default_factory=list)
    note: str | None = None


@dataclass(frozen=True)
class CoverageGap:
    """Course material that could not be scanned, with its honest availability state."""

    source_key: str
    source_id: str
    title: str
    availability: str
    note: str
    fetch_command: str | None


@dataclass(frozen=True)
class NotationCandidate:
    """A draft term absent from the scanned material, with a candidate — never a correction."""

    term: str
    candidate: str | None
    citation: Citation | None


@dataclass(frozen=True)
class CheckReport:
    """Everything one scan computed, plus the revisions it computed it from."""

    draft: str
    course: str
    course_code: str
    scope: str
    findings: tuple[Finding, ...]
    coverage_gaps: tuple[CoverageGap, ...]
    notation: tuple[NotationCandidate, ...]
    revisions: dict[str, dict[str, str]]
    algorithm_version: int = CHECK_ALGORITHM_VERSION

    @property
    def review_required(self) -> bool:
        """Whether ``--strict`` should exit non-zero, as a review reminder only."""
        return any(
            finding.status in {"no_matching_evidence", "possible_conflict"}
            for finding in self.findings
        )


@dataclass(frozen=True)
class ScanSource:
    """A verified twin on disk, carrying the digests a citation must record."""

    path: Path
    citation_path: str
    source_sha256: str
    derived_sha256: str


class LineIndex:
    """One in-memory inverted line index per run, so claims do not rescan every file."""

    def __init__(self, sources: Sequence[ScanSource]) -> None:
        self._lines: list[tuple[ScanSource, int, str, frozenset[str], frozenset[str]]] = []
        self._postings: dict[str, list[int]] = {}
        self.vocabulary: dict[str, tuple[str, int]] = {}
        for source in sources:
            text = _read_text(source.path)
            if text is None:
                continue
            for number, raw in enumerate(text.splitlines(), start=1):
                terms = frozenset(term for term in tok(raw) if term not in GENERIC)
                if not terms:
                    continue
                position = len(self._lines)
                self._lines.append((source, number, raw.strip(), terms, frozenset(values(raw))))
                for term in terms:
                    self._postings.setdefault(term, []).append(position)
                    self.vocabulary.setdefault(term, (source.citation_path, number))

    def __len__(self) -> int:
        return len(self._lines)

    def retrieve(self, claim: Claim, *, top: int = TOP_CITATIONS) -> list[Citation]:
        """Score only the lines that share a term with the claim, then rank deterministically.

        Term overlap is counted straight off the postings lists rather than by intersecting a set
        per line, and only the surviving spans become :class:`Citation` objects.  On a corpus where
        a common term appears on every line, materialising a citation per scored line dominated
        everything else.
        """

        claim_terms = frozenset(term for term in tok(claim.text) if term not in GENERIC)
        if not claim_terms:
            return []
        claim_values = values(claim.text)
        total_terms = len(claim_terms)
        total_values = len(claim_values)

        matches: dict[int, int] = {}
        for term in claim_terms:
            for position in self._postings.get(term, ()):
                matches[position] = matches.get(position, 0) + 1
        if not matches:
            return []

        def ranked() -> Iterator[tuple[int, str, int, int]]:
            for position, matched in matches.items():
                source, number, _excerpt, _terms, line_values = self._lines[position]
                matched_values = len(claim_values & line_values) if total_values else 0
                points = score_bp(matched, total_terms, matched_values, total_values)
                if points > 0:
                    yield (-points, source.citation_path, number, position)

        return [
            self._citation(position, -negated)
            for negated, _path, _line, position in heapq.nsmallest(top, ranked())
        ]

    def _citation(self, position: int, points: int) -> Citation:
        source, number, excerpt, _terms, _line_values = self._lines[position]
        return Citation(
            path=source.citation_path,
            line=number,
            excerpt=excerpt,
            source_sha256=source.source_sha256,
            derived_sha256=source.derived_sha256,
            retrieval_score_bp=points,
        )


def score_bp(matched_terms: int, total_terms: int, matched_values: int, total_values: int) -> int:
    """Return ``floor(score * 10_000)`` using integer arithmetic only.

    ``score = 4/5 * a/b + 1/5 * c/d`` is ``(4ad + cb) / (5bd)``, so one integer floor division
    gives the identical result the rational form would, without constructing a
    :class:`~fractions.Fraction` per scored line.  ``exact_score`` keeps the rational definition
    available, and a test pins the two together across a grid of inputs.
    """

    terms = max(1, total_terms)
    if total_values:
        numerator = 10_000 * (4 * matched_terms * total_values + matched_values * terms)
        return numerator // (5 * terms * total_values)
    return (10_000 * matched_terms) // terms


def exact_score(
    matched_terms: int, total_terms: int, matched_values: int, total_values: int
) -> Fraction:
    """The rational definition of the score, kept as the reference for :func:`score_bp`."""

    term_coverage = Fraction(matched_terms, max(1, total_terms))
    if not total_values:
        return term_coverage
    value_coverage = Fraction(matched_values, total_values)
    return Fraction(4, 5) * term_coverage + Fraction(1, 5) * value_coverage


def values(text: str) -> frozenset[str]:
    """Extract the numbers, comparison operators, and identifiers a claim commits to."""

    found: set[str] = set(_NUMBER.findall(text))
    remaining = text
    for symbol in _SYMBOL_OPERATORS:
        if symbol in remaining:
            found.add(_CANONICAL_OPERATOR.get(symbol, symbol))
            remaining = remaining.replace(symbol, " ")
    found.update(match.group(0).strip("`").casefold() for match in _IDENTIFIER.finditer(text))
    return frozenset(found)


def segment(draft_text: str, suffix: str) -> list[Claim]:
    """Split a draft into located claims, marking connective prose ``skipped`` later.

    Markdown and text become sentences with their starting line numbers; fenced blocks become one
    code claim each; display math becomes a formula claim; numbered list items become steps.  A
    notebook contributes one claim per code cell and its markdown cells segmented as prose, with
    line numbers running over the concatenated cell sources so a citation still locates the text.
    """

    if suffix.casefold() == ".ipynb":
        return _segment_notebook(draft_text)
    return _segment_text(draft_text)


def retrieve(
    claim: Claim,
    sources: Sequence[ScanSource] | LineIndex,
    top: int = TOP_CITATIONS,
) -> list[Citation]:
    """Return the top course spans for one claim, highest score first."""

    index = sources if isinstance(sources, LineIndex) else LineIndex(sources)
    return index.retrieve(claim, top=top)


def classify(claim: Claim, candidates: Sequence[Citation]) -> Finding:
    """Assign exactly one evidence status, deterministically and lexically."""

    if not _is_checkable(claim):
        return Finding(claim, "skipped", [], "connective prose, not a checkable claim")

    above = [item for item in candidates if item.retrieval_score_bp >= CANDIDATE_FLOOR_BP]
    if not above:
        nearest = candidates[0] if candidates else None
        note = "no matching evidence was found in the scanned course material"
        if nearest is not None:
            note = (
                f"{note}; nearest below-threshold span (not evidence): "
                f"{nearest.path}:{nearest.line}"
            )
        return Finding(claim, "no_matching_evidence", [], note)

    best = above[0]
    if best.retrieval_score_bp >= STRONG_MATCH_FLOOR_BP:
        if _possible_conflict(claim.text, best.excerpt):
            return Finding(
                claim,
                "possible_conflict",
                above,
                "your materials may say something different — compare both spans yourself",
            )
        claim_values = values(claim.text)
        if not claim_values or claim_values <= values(best.excerpt):
            return Finding(claim, "evidence_found", above, None)
        missing = ", ".join(sorted(claim_values - values(best.excerpt)))
        return Finding(
            claim,
            "related_evidence",
            above,
            f"related, not asserted; not found in the cited span: {missing}",
        )
    return Finding(
        claim,
        "related_evidence",
        above,
        "related, not asserted; it does not establish this specific claim",
    )


def check(draft: Path, course_dir: Path, *, assignment: str | None = None) -> CheckReport:
    """Scan one draft against one course's verified material.

    An empty source set is an error rather than a clean bill of health: a scan that found nothing
    to read has not checked anything.
    """

    draft_path = Path(draft)
    text = _read_text(draft_path)
    if text is None:
        raise A2LError("draft file is unreadable")
    suffix = draft_path.suffix.casefold()
    if suffix and suffix not in SUPPORTED_SUFFIXES:
        raise A2LError(f"check does not read {suffix} drafts")

    vault = _vault_for(course_dir)
    scope, sources = _scan_sources(vault, course_dir, draft_path, assignment)
    if not sources:
        raise A2LError("no verified course material was found to scan; run: a2l sync")

    index = LineIndex(sources)
    if not len(index):
        raise A2LError("the verified course material contains no readable lines; run: a2l sync")

    findings = tuple(classify(claim, index.retrieve(claim)) for claim in segment(text, suffix))
    code, _name = _course_identity(course_dir)
    return CheckReport(
        draft=_display(draft_path, vault.root),
        course=paths.rel_posix(course_dir, vault.root),
        course_code=code,
        scope=scope,
        findings=findings,
        coverage_gaps=_coverage_gaps(course_dir, findings),
        notation=_notation(findings, index),
        revisions={
            source.citation_path: {
                "source_sha256": source.source_sha256,
                "derived_sha256": source.derived_sha256,
            }
            for source in sources
        },
    )


def render(report: CheckReport) -> str:
    """Render the report for a human, leading with the experimental disclosure."""

    counts = _counts(report)
    lines = [
        DISCLOSURE,
        "",
        f"{report.course_code} · {report.scope} · {report.draft}",
        (
            f"{len(report.findings)} claims · {counts['evidence_found']} with matching evidence · "
            f"{counts['related_evidence']} related · {counts['no_matching_evidence']} no match · "
            f"{counts['possible_conflict']} to compare · {counts['skipped']} skipped"
        ),
        "",
    ]
    marks = {
        "evidence_found": "+",
        "related_evidence": "~",
        "no_matching_evidence": "x",
        "possible_conflict": "?",
        "skipped": "-",
    }
    for finding in report.findings:
        if finding.status == "skipped":
            continue
        lines.append(f"{marks[finding.status]} L{finding.claim.line}  {finding.claim.text}")
        if finding.note:
            lines.append(f"      {finding.note}")
        for citation in finding.citations:
            lines.append(f"      {citation.path}:{citation.line}")
            lines.append(f"        source excerpt: {citation.excerpt}")
        lines.append("")

    if report.notation:
        lines.extend(["NOTATION", ""])
        for item in report.notation:
            if item.candidate and item.citation is not None:
                lines.append(
                    f'· you write "{item.term}"; nearest course wording candidate: '
                    f'"{item.candidate}" ({item.citation.path}:{item.citation.line})'
                )
            else:
                lines.append(f'· you write "{item.term}"; no close course wording was found')
        lines.append("")

    if report.coverage_gaps:
        lines.extend(["COVERAGE", ""])
        for gap in report.coverage_gaps:
            action = f" → {gap.fetch_command}" if gap.fetch_command else ""
            lines.append(f"· {gap.title}: {gap.note}{action}")
        lines.append("")

    lines.extend(
        [
            "─" * 53,
            (
                "A status here describes what a lexical scan matched. It is not proof that your "
                "work is right or wrong, and it says nothing about grading or academic policy. "
                "Read the cited sources yourself."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def render_json(report: CheckReport) -> str:
    """Render the same content as stable machine-readable JSON."""

    payload = {
        "check_algorithm_version": report.algorithm_version,
        "disclosure": DISCLOSURE,
        "not_proof": (
            "A status describes a lexical match only. It is not proof of correctness, "
            "incorrectness, policy compliance, or academic integrity."
        ),
        "draft": report.draft,
        "course": report.course,
        "course_code": report.course_code,
        "scope": report.scope,
        "candidate_floor_bp": CANDIDATE_FLOOR_BP,
        "strong_match_floor_bp": STRONG_MATCH_FLOOR_BP,
        "findings": [
            {
                "line": finding.claim.line,
                "text": finding.claim.text,
                "kind": finding.claim.kind,
                "status": finding.status,
                "score_bp": (finding.citations[0].retrieval_score_bp if finding.citations else 0),
                "citations": [
                    {
                        "path": citation.path,
                        "line": citation.line,
                        "excerpt": citation.excerpt,
                        "source_sha256": citation.source_sha256,
                        "derived_sha256": citation.derived_sha256,
                        "retrieval_score_bp": citation.retrieval_score_bp,
                    }
                    for citation in finding.citations
                ],
                "note": finding.note,
            }
            for finding in report.findings
        ],
        "coverage_gaps": [
            {
                "source_key": gap.source_key,
                "source_id": gap.source_id,
                "title": gap.title,
                "availability": gap.availability,
                "note": gap.note,
                "fetch_command": gap.fetch_command,
            }
            for gap in report.coverage_gaps
        ],
        "notation": [
            {
                "term": item.term,
                "candidate": item.candidate,
                "citation": None
                if item.citation is None
                else {"path": item.citation.path, "line": item.citation.line},
            }
            for item in report.notation
        ],
        "revisions": report.revisions,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _segment_text(text: str) -> list[Claim]:
    claims: list[Claim] = []
    block: list[tuple[int, str]] = []
    fence: list[str] = []
    fence_line = 0
    fence_kind: ClaimKind = "code"
    inside = False

    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        opener = _fence_kind(stripped)
        if inside:
            if _closes_fence(stripped, fence_kind):
                claims.append(Claim(fence_line, "\n".join(fence).strip(), fence_kind))
                inside = False
                fence = []
                continue
            fence.append(raw)
            continue
        if opener is not None:
            _emit_block(block, claims)
            block = []
            inside = True
            fence_line = number
            fence_kind = opener
            fence = []
            continue
        if not stripped or stripped.startswith("<!--"):
            _emit_block(block, claims)
            block = []
            continue
        block.append((number, stripped.lstrip("#").strip()))

    if inside and fence:
        claims.append(Claim(fence_line, "\n".join(fence).strip(), fence_kind))
    _emit_block(block, claims)
    return claims


def _emit_block(block: Sequence[tuple[int, str]], claims: list[Claim]) -> None:
    """Emit one block, keeping an enumerated derivation step intact.

    A numbered item is one checkable unit, so it is never sentence-split: splitting after the
    enumerator would leave ``1.`` as its own meaningless claim.
    """

    if not block:
        return
    segments: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for number, text in block:
        if _STEP.match(text) and current:
            segments.append(current)
            current = []
        current.append((number, text))
    if current:
        segments.append(current)

    for segment_lines in segments:
        start, first = segment_lines[0]
        if _STEP.match(first):
            joined = " ".join(value for _number, value in segment_lines)
            claims.append(Claim(start, joined, "step"))
            continue
        _flush(segment_lines, claims)


def _segment_notebook(text: str) -> list[Claim]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise A2LError("notebook draft is not valid JSON") from exc
    cells = raw.get("cells") if isinstance(raw, Mapping) else None
    if not isinstance(cells, list):
        raise A2LError("notebook draft has no cells")
    claims: list[Claim] = []
    line = 1
    for cell in cells:
        if not isinstance(cell, Mapping):
            continue
        body = _cell_source(cell.get("source"))
        height = max(1, len(body.splitlines()))
        if cell.get("cell_type") == "code":
            if body.strip():
                claims.append(Claim(line, body.strip(), "code"))
        else:
            for claim in _segment_text(body):
                claims.append(Claim(line + claim.line - 1, claim.text, claim.kind))
        line += height
    return claims


def _cell_source(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return ""


def _fence_kind(stripped: str) -> ClaimKind | None:
    if stripped.startswith("```") or stripped.startswith("~~~"):
        return "code"
    if stripped == "$$" or stripped.startswith("\\["):
        return "formula"
    return None


def _closes_fence(stripped: str, kind: ClaimKind) -> bool:
    if kind == "code":
        return stripped.startswith("```") or stripped.startswith("~~~")
    return stripped == "$$" or stripped.startswith("\\]")


def _flush(paragraph: Sequence[tuple[int, str]], claims: list[Claim]) -> None:
    if not paragraph:
        return
    joined = ""
    offsets: list[tuple[int, int]] = []
    for number, piece in paragraph:
        if joined:
            joined += " "
        offsets.append((len(joined), number))
        joined += piece
    cursor = 0
    for sentence in _SENTENCE_SPLIT.split(joined):
        text = sentence.strip()
        if not text:
            continue
        start = joined.find(text, cursor)
        if start < 0:
            start = cursor
        cursor = start + len(text)
        claims.append(Claim(_line_for(start, offsets), text, _kind(text)))


def _line_for(offset: int, offsets: Sequence[tuple[int, int]]) -> int:
    number = offsets[0][1] if offsets else 1
    for start, candidate in offsets:
        if start <= offset:
            number = candidate
        else:
            break
    return number


def _kind(text: str) -> ClaimKind:
    if _STEP.match(text):
        return "step"
    words = [token for token in _RUN.findall(text.casefold()) if not token.isdigit()]
    if _NUMBER_OR_MATH.search(text) and len(words) < 6:
        return "formula"
    return "prose"


def _is_checkable(claim: Claim) -> bool:
    """Return whether a claim commits to something a lexical scan can look for.

    Explicit and versioned on purpose: this does not parse noun phrases or judge meaning.  A claim
    counts as checkable when it carries a number or math symbol, a definition cue, a code or API
    identifier, a named-method cue, or at least three content tokens once function and coursework
    words are removed.
    """

    if claim.kind in {"code", "formula", "step"}:
        return True
    text = claim.text
    if _NUMBER_OR_MATH.search(text):
        return True
    if _DEFINITION_CUE.search(text):
        return True
    if _IDENTIFIER.search(text):
        return True
    if _NAMED_METHOD.search(text):
        return True
    return len(_content_tokens(text)) >= 3


def _content_tokens(text: str) -> list[str]:
    return [token for token in tok(text) if token not in GENERIC and token not in _FUNCTION]


def _possible_conflict(claim_text: str, source_text: str) -> bool:
    """Return whether two spans match one of exactly two allowlisted conflict templates.

    Both templates require the token sequences to be otherwise identical, which is what keeps the
    status narrow.  A differing number changes the token sequence, so it can never qualify.
    """

    claim_ops, claim_core = _relation_signature(claim_text)
    source_ops, source_core = _relation_signature(source_text)
    if (
        claim_core
        and claim_core == source_core
        and len(claim_ops) == len(source_ops) >= 1
        and all(
            other in _OPPOSITES.get(mine, frozenset())
            for mine, other in zip(claim_ops, source_ops, strict=True)
        )
    ):
        return True

    claim_negated, claim_tokens = _polarity(claim_text)
    source_negated, source_tokens = _polarity(source_text)
    return bool(claim_tokens) and claim_tokens == source_tokens and claim_negated != source_negated


def _relation_signature(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a span into its ordered comparison operators and the tokens around them.

    Scanning left to right, longest operator first, keeps ``<=`` from being read as ``<`` and
    keeps the operator order faithful to the sentence.
    """

    normalized = text
    for pattern, replacement in _WORD_OPERATORS:
        normalized = pattern.sub(f" {replacement} ", normalized)
    operators: list[str] = []
    remainder: list[str] = []
    position = 0
    while position < len(normalized):
        for symbol in _SYMBOL_OPERATORS:
            if normalized.startswith(symbol, position):
                operators.append(_CANONICAL_OPERATOR.get(symbol, symbol))
                remainder.append(" ")
                position += len(symbol)
                break
        else:
            remainder.append(normalized[position])
            position += 1
    return tuple(operators), tuple(tok("".join(remainder)))


def _polarity(text: str) -> tuple[bool, tuple[str, ...]]:
    """Return the narrow ``is``/``is not`` predicate polarity template.

    Broad lexical negation (``never``, ``cannot``, ``without``, and friends) is deliberately not a
    conflict signal.  The design allowlist only treats a single explicit ``is`` predicate and its
    immediately following ``not`` as opposite polarity; any other negation or multiple predicates
    makes the template inapplicable.
    """

    matches = tuple(_IS_POLARITY.finditer(text))
    if len(matches) != 1:
        return False, ()
    match = matches[0]
    stripped = text[: match.start()] + " " + text[match.end() :]
    if _NEGATION.search(stripped) is not None:
        return False, ()
    return bool(match.group("not")), tuple(tok(stripped))


def _vault_for(course_dir: Path) -> Vault:
    candidate = Path(course_dir).expanduser()
    for parent in (candidate, *candidate.parents):
        try:
            if Vault.is_vault(parent):
                return Vault(parent)
        except (OSError, ValueError):
            continue
    raise A2LError("this course is not inside an Agent2Learn vault; run: a2l init")


def _scan_sources(
    vault: Vault,
    course_dir: Path,
    draft: Path,
    assignment: str | None,
) -> tuple[str, tuple[ScanSource, ...]]:
    item = assignment or _assignment_for(course_dir, draft)
    if item is not None:
        selected = ground.select_sources(vault, course_dir, item)
        scope = item
    else:
        selected = ground.verified_sources(vault, course_dir)
        scope = "whole course"
    excluded = _same_file_key(draft)
    sources = tuple(
        ScanSource(
            path=vault.root / PurePosixPath(source.citation_path),
            citation_path=source.citation_path,
            source_sha256=source.source_sha256,
            derived_sha256=source.derived_sha256,
        )
        for source in selected
        if _same_file_key(vault.root / PurePosixPath(source.citation_path)) != excluded
    )
    return scope, sources


def _assignment_for(course_dir: Path, draft: Path) -> str | None:
    """Return the assignment folder name when the draft sits inside one."""

    assignments = _same_file_key(course_dir / "assignments")
    previous: Path | None = None
    for parent in Path(draft).expanduser().parents:
        if _same_file_key(parent) == assignments and previous is not None:
            return previous.name
        previous = parent
    return None


def _coverage_gaps(course_dir: Path, findings: Sequence[Finding]) -> tuple[CoverageGap, ...]:
    """Report unscannable material whose title shares a term with an unresolved claim.

    Reported before a reader treats ``no_matching_evidence`` as absence: the material may simply
    not be on disk yet.
    """

    wanted: set[str] = set()
    for finding in findings:
        if finding.status in {"no_matching_evidence", "related_evidence"}:
            wanted.update(ground.distinguishing_terms(finding.claim.text))
    if not wanted:
        return ()
    rows = course_index.read_content_map(course_dir)["topics"]
    if not isinstance(rows, list):
        return ()
    gaps: dict[str, CoverageGap] = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("path"):
            continue
        source_key = row.get("source_key")
        source_id = row.get("source_id")
        if not isinstance(source_key, str) or not isinstance(source_id, str):
            continue
        title = str(row.get("title") or source_key)
        if not ground.distinguishing_terms(title) & wanted:
            continue
        availability = str(row.get("availability") or "metadata_only")
        gaps[source_key] = CoverageGap(
            source_key=source_key,
            source_id=source_id,
            title=title,
            availability=availability,
            note=_AVAILABILITY_NOTES.get(availability, "unavailable locally"),
            fetch_command=(f"a2l fetch {source_id}" if availability in _FETCHABLE else None),
        )
    return tuple(gaps[key] for key in sorted(gaps))


def _notation(findings: Sequence[Finding], index: LineIndex) -> tuple[NotationCandidate, ...]:
    """Flag draft terms absent from the scanned material, with a candidate, never a correction."""

    missing: dict[str, None] = {}
    for finding in findings:
        if finding.status == "skipped":
            continue
        for token in _content_tokens(finding.claim.text):
            if len(token) < 4 or token.isdigit() or token in index.vocabulary:
                continue
            missing.setdefault(token, None)
    candidates: list[NotationCandidate] = []
    for term in sorted(missing):
        best_term: str | None = None
        best_ratio = 0
        for known in sorted(index.vocabulary):
            ratio = int(SequenceMatcher(None, term, known).ratio() * 10_000)
            if ratio > best_ratio:
                best_ratio, best_term = ratio, known
        if best_term is None or best_ratio < NOTATION_FLOOR_BP:
            candidates.append(NotationCandidate(term, None, None))
            continue
        path, line = index.vocabulary[best_term]
        candidates.append(
            NotationCandidate(
                term,
                best_term,
                Citation(
                    path=path,
                    line=line,
                    excerpt=best_term,
                    source_sha256="",
                    derived_sha256="",
                    retrieval_score_bp=best_ratio,
                ),
            )
        )
    return tuple(candidates)


def _counts(report: CheckReport) -> dict[str, int]:
    counts = dict.fromkeys(
        (
            "evidence_found",
            "related_evidence",
            "no_matching_evidence",
            "possible_conflict",
            "skipped",
        ),
        0,
    )
    for finding in report.findings:
        counts[finding.status] += 1
    return counts


def _course_identity(course_dir: Path) -> tuple[str, str]:
    rows = course_index.read_content_map(course_dir)["topics"]
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            code = row.get("course_code")
            name = row.get("course_name")
            if isinstance(code, str) and code:
                return code, name if isinstance(name, str) and name else code
    return course_dir.name, course_dir.name


def _display(path: Path, root: Path) -> str:
    try:
        return paths.rel_posix(path, root)
    except (ValueError, OSError):
        return path.name


def _same_file_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(paths.plain_path(path)))


def _read_text(path: Path) -> str | None:
    try:
        with open(
            os.fspath(paths.long_path(path)), encoding="utf-8", errors="ignore", newline=""
        ) as handle:
            return handle.read()
    except (FileNotFoundError, IsADirectoryError, OSError, UnicodeError):
        return None


__all__ = [
    "CANDIDATE_FLOOR_BP",
    "CHECK_ALGORITHM_VERSION",
    "DISCLOSURE",
    "NOTATION_FLOOR_BP",
    "STRONG_MATCH_FLOOR_BP",
    "SUPPORTED_SUFFIXES",
    "TOP_CITATIONS",
    "CheckReport",
    "Citation",
    "Claim",
    "CoverageGap",
    "Finding",
    "LineIndex",
    "NotationCandidate",
    "ScanSource",
    "check",
    "classify",
    "render",
    "render_json",
    "retrieve",
    "exact_score",
    "score_bp",
    "segment",
    "values",
]
