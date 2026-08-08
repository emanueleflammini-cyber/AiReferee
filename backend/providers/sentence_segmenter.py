"""Deterministic sentence segmentation for the Synthesizer sentence-index wire
contract (feature/deterministic-excerpt-sentence-index).

``split_sentences`` breaks a provider response into an ordered list of
sentence-like segments. Every segment is guaranteed to be a real, contiguous,
character-for-character substring of the input (surrounding whitespace
trimmed only) -- nothing is rewritten, translated, normalized or reordered.
Segmentation is pure split-point selection: no fuzzy or semantic matching is
involved anywhere in this module.
"""
from __future__ import annotations

import re

_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\]\)]+", re.IGNORECASE)
_DECIMAL_POINT_RE = re.compile(r"(?<=\d)\.(?=\d)")
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}'\"”’"

# '.', '!', '?', horizontal ellipsis -- require a following whitespace/EOL to
# count as a sentence boundary (guards against abbreviations, decimals, mid-
# sentence ellipses).
_WESTERN_TERMINATORS = ".!?…"
# CJK full-width terminators -- CJK prose is not space-separated, so these
# split immediately without a trailing-whitespace requirement.
_CJK_TERMINATORS = "。！？"
_ALL_TERMINATORS = _WESTERN_TERMINATORS + _CJK_TERMINATORS
# Closing punctuation that may trail a terminator before the real boundary
# (e.g. a period inside a closing quote: `He said "stop."`).
_CLOSERS = "\"')]”’»》】"

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc",
    "e.g", "i.e", "eg", "ie", "inc", "ltd", "co", "no", "fig", "approx",
    "sig", "dott", "sigg", "ecc", "u.s", "u.k", "vol", "pp", "cf",
}

# Lower-priority boundaries used only when a natural sentence exceeds the
# public excerpt limit. The boundary character remains in the preceding
# segment; only existing split points are selected.
_CHUNK_PUNCTUATION = ",;:—–"


def split_sentences(
    text: str,
    *,
    max_length: int | None = None,
) -> list[str]:
    """Split ``text`` deterministically into an ordered list of sentences.

    Each returned segment is a non-empty, contiguous substring of ``text``.
    When ``max_length`` is supplied, overlong natural sentences are split at
    existing punctuation, then whitespace, then a hard character boundary.
    Blank lines act only as separators between segments and never produce an
    empty segment themselves.
    """
    if not text:
        return []
    if max_length is not None and max_length < 1:
        raise ValueError("max_length must be a positive integer")
    segments: list[str] = []
    for line, _line_start in _iter_lines(text):
        if not line.strip():
            continue
        for start, end in _split_line_sentences(line):
            for chunk_start, chunk_end in _bound_span(
                line, start, end, max_length
            ):
                segment = line[chunk_start:chunk_end]
                if segment:
                    segments.append(segment)
    return segments


def _bound_span(
    line: str,
    start: int,
    end: int,
    max_length: int | None,
) -> list[tuple[int, int]]:
    """Split one sentence span without rewriting or overlapping its text."""
    if max_length is None or end - start <= max_length:
        return [(start, end)]

    spans: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > max_length:
        window_end = cursor + max_length
        split_at = _last_punctuation_boundary(line, cursor, window_end)
        if split_at is None:
            split_at = _last_whitespace_boundary(line, cursor, window_end)
        if split_at is None:
            split_at = window_end

        chunk_end = _last_non_space(line, cursor, split_at)
        if chunk_end <= cursor:
            chunk_end = window_end
        spans.append((cursor, chunk_end))
        cursor = _first_non_space(line, split_at)

    if cursor < end:
        spans.append((cursor, end))
    return spans


def _last_punctuation_boundary(
    line: str,
    start: int,
    window_end: int,
) -> int | None:
    for pos in range(window_end - 1, start, -1):
        if line[pos] in _CHUNK_PUNCTUATION:
            return pos + 1
    return None


def _last_whitespace_boundary(
    line: str,
    start: int,
    window_end: int,
) -> int | None:
    for pos in range(window_end - 1, start, -1):
        if line[pos].isspace():
            return pos
    return None


def _iter_lines(text: str) -> list[tuple[str, int]]:
    lines: list[tuple[str, int]] = []
    pos = 0
    for match in _LINE_BREAK_RE.finditer(text):
        lines.append((text[pos:match.start()], pos))
        pos = match.end()
    lines.append((text[pos:], pos))
    return lines


def _split_line_sentences(line: str) -> list[tuple[int, int]]:
    protected = _protected_ranges(line)

    def is_protected(pos: int) -> bool:
        return any(span_start <= pos < span_end for span_start, span_end in protected)

    n = len(line)
    spans: list[tuple[int, int]] = []
    start = _first_non_space(line, 0)
    i = start
    while i < n:
        ch = line[i]
        if ch in _ALL_TERMINATORS and not is_protected(i):
            if ch in _WESTERN_TERMINATORS:
                if ch == "." and (
                    _is_list_marker_period(line, i) or _is_abbreviation_before(line, i)
                ):
                    i += 1
                    continue
                j = _extend_terminator_run(line, i)
                if j >= n or line[j].isspace():
                    end = _last_non_space(line, start, j)
                    if end > start:
                        spans.append((start, end))
                    i = _first_non_space(line, j)
                    start = i
                    continue
                i += 1
                continue
            # CJK terminator: split immediately, no trailing-space requirement.
            j = _extend_terminator_run(line, i)
            end = _last_non_space(line, start, j)
            if end > start:
                spans.append((start, end))
            i = _first_non_space(line, j)
            start = i
            continue
        i += 1
    end = _last_non_space(line, start, n)
    if end > start:
        spans.append((start, end))
    return spans


def _first_non_space(line: str, pos: int) -> int:
    n = len(line)
    while pos < n and line[pos].isspace():
        pos += 1
    return pos


def _last_non_space(line: str, start: int, end: int) -> int:
    while end > start and line[end - 1].isspace():
        end -= 1
    return end


def _extend_terminator_run(line: str, i: int) -> int:
    n = len(line)
    j = i + 1
    while j < n and (line[j] in _ALL_TERMINATORS or line[j] in _CLOSERS):
        j += 1
    return j


def _protected_ranges(line: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in _URL_RE.finditer(line):
        url = match.group(0)
        trimmed = url.rstrip(_TRAILING_URL_PUNCTUATION)
        end = match.start() + len(trimmed)
        if end > match.start():
            ranges.append((match.start(), end))
    for match in _DECIMAL_POINT_RE.finditer(line):
        ranges.append((match.start(), match.end()))
    return ranges


def _is_abbreviation_before(line: str, i: int) -> bool:
    allowed = (
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ."
    )
    j = i
    while j > 0 and line[j - 1] in allowed:
        j -= 1
    token = line[j:i].strip(".").lower()
    return bool(token) and token in _ABBREVIATIONS


def _is_list_marker_period(line: str, i: int) -> bool:
    """True when ``.`` at ``i`` is a numbered-list marker ("1. Item")."""
    j = i
    while j > 0 and line[j - 1].isdigit():
        j -= 1
    if j == i:
        return False
    k = j
    while k > 0 and line[k - 1].isspace():
        k -= 1
    return k == 0
