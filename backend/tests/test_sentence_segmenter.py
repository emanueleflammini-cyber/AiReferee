"""Tests for the deterministic sentence segmenter (PATCH D1: sentence-index
wire-only contract, feature/deterministic-excerpt-sentence-index).

Covers the segmenter's contract: every returned segment is a real,
contiguous substring of the input, segments are ordered exactly as they
appear in the source text, and no text is rewritten, translated or
normalized -- only split points are chosen.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from providers.sentence_segmenter import split_sentences  # noqa: E402
from providers.synthesizer import RESPONSE_EXCERPT_MAX_LENGTH  # noqa: E402


def assert_contiguous_and_ordered(text: str, segments: list[str]) -> None:
    """Shared invariant check used by tests I and J below."""
    cursor = 0
    for segment in segments:
        assert segment, "segments must never be empty"
        found = text.find(segment, cursor)
        assert found != -1, f"{segment!r} is not a substring of the original at/after {cursor}"
        cursor = found + len(segment)


# --- A: normal sentences with . ! ? ----------------------------------------


def test_a_splits_on_period_exclamation_question_mark():
    text = "Caching helps. Does it always help? Yes it does!"
    assert split_sentences(text) == [
        "Caching helps.",
        "Does it always help?",
        "Yes it does!",
    ]


# --- B: newline --------------------------------------------------------


def test_b_newline_is_a_hard_boundary():
    text = "First paragraph line.\nSecond paragraph line."
    assert split_sentences(text) == [
        "First paragraph line.",
        "Second paragraph line.",
    ]


def test_b_blank_lines_are_separators_not_empty_segments():
    text = "First line.\n\n\nSecond line."
    assert split_sentences(text) == ["First line.", "Second line."]


# --- C: bullet list items ----------------------------------------------


def test_c_bullet_items_stay_on_separate_segments():
    text = "- First bullet point.\n- Second bullet point.\n- Third."
    assert split_sentences(text) == [
        "- First bullet point.",
        "- Second bullet point.",
        "- Third.",
    ]


# --- D: CRLF -------------------------------------------------------------


def test_d_crlf_line_endings_are_handled():
    text = "Windows line one.\r\nWindows line two.\r\n"
    assert split_sentences(text) == [
        "Windows line one.",
        "Windows line two.",
    ]


def test_d_mixed_crlf_and_lf_are_handled():
    text = "One.\r\nTwo.\nThree.\r\n"
    assert split_sentences(text) == ["One.", "Two.", "Three."]


# --- E: Unicode punctuation / CJK ----------------------------------------


def test_e_cjk_terminators_split_without_spaces():
    text = "这是第一句。这是第二句！第三句吗？"
    assert split_sentences(text) == [
        "这是第一句。",
        "这是第二句！",
        "第三句吗？",
    ]


def test_e_curly_quotes_and_em_dash_are_preserved_verbatim():
    text = "She said “this works”—and it does. Good."
    segments = split_sentences(text)
    assert segments[0] == "She said “this works”—and it does."
    assert segments[1] == "Good."


# --- F: decimal numbers ----------------------------------------------------


def test_f_decimal_point_is_not_a_sentence_boundary():
    text = "The result is 3.14 exactly. Next fact."
    assert split_sentences(text) == [
        "The result is 3.14 exactly.",
        "Next fact.",
    ]


def test_f_decimal_at_end_of_clause_still_splits_on_the_real_period():
    text = "Pi is about 3.14. Next fact."
    assert split_sentences(text) == ["Pi is about 3.14.", "Next fact."]


# --- G: abbreviations -------------------------------------------------


def test_g_common_abbreviation_is_not_a_sentence_boundary():
    text = "Dr. Smith won the trial. The verdict stands."
    assert split_sentences(text) == [
        "Dr. Smith won the trial.",
        "The verdict stands.",
    ]


def test_g_etc_abbreviation_is_not_a_sentence_boundary():
    text = "Bring pens, paper, etc. to the meeting. Be on time."
    assert split_sentences(text) == [
        "Bring pens, paper, etc. to the meeting.",
        "Be on time.",
    ]


# --- H: markdown --------------------------------------------------------


def test_h_markdown_emphasis_markers_are_kept_verbatim():
    text = "**Bold text.** Normal text."
    segments = split_sentences(text)
    assert segments == ["**Bold text.** Normal text."]
    assert "**" in segments[0]


def test_h_markdown_heading_line_is_not_destructively_altered():
    text = "# Heading Title\nBody sentence follows."
    assert split_sentences(text) == [
        "# Heading Title",
        "Body sentence follows.",
    ]


# --- I: segments are real contiguous substrings of the original -----------


def test_i_every_segment_is_a_contiguous_substring():
    text = (
        "Dr. Smith reported a 3.14 percent gain. Visit https://example.com/a.b "
        "for details.\n- Then this bullet.\n这是句子。"
    )
    segments = split_sentences(text)
    assert_contiguous_and_ordered(text, segments)


# --- J: concatenation preserves original order ------------------------


def test_j_concatenation_order_matches_the_original_text():
    text = "Alpha sentence one. Beta sentence two! Gamma sentence three?"
    segments = split_sentences(text)
    assert_contiguous_and_ordered(text, segments)
    # Reconstructing with single-space separators reproduces the source
    # exactly for this space-separated, ASCII-punctuation fixture.
    assert " ".join(segments) == text


def test_j_multiline_concatenation_preserves_relative_order():
    text = "First.\nSecond.\nThird."
    segments = split_sentences(text)
    assert_contiguous_and_ordered(text, segments)
    assert segments == ["First.", "Second.", "Third."]


# --- misc: empty / falsy input ---------------------------------------------


def test_empty_and_none_like_input_returns_empty_list():
    assert split_sentences("") == []


def test_whitespace_only_input_returns_empty_list():
    assert split_sentences("   \n\n  \r\n  ") == []


# --- D1.1: every model-selectable segment fits the public excerpt contract -


def bounded(text: str) -> list[str]:
    return split_sentences(text, max_length=RESPONSE_EXCERPT_MAX_LENGTH)


def test_bounded_sentence_below_limit_is_unchanged():
    text = "A short sentence."
    assert bounded(text) == [text]


def test_bounded_sentence_exactly_at_limit_is_unchanged():
    text = "x" * (RESPONSE_EXCERPT_MAX_LENGTH - 1) + "."
    assert len(text) == RESPONSE_EXCERPT_MAX_LENGTH
    assert bounded(text) == [text]


def test_overlong_sentence_is_split_and_every_chunk_is_bounded():
    text = "word " * 150 + "done."
    segments = bounded(text)
    assert len(segments) > 1
    assert all(0 < len(item) <= RESPONSE_EXCERPT_MAX_LENGTH for item in segments)
    assert_contiguous_and_ordered(text, segments)


def test_bounded_split_prefers_existing_punctuation():
    text = "a" * 300 + "; " + "b" * 300 + "."
    segments = bounded(text)
    assert segments == ["a" * 300 + ";", "b" * 300 + "."]


def test_bounded_split_uses_whitespace_without_punctuation():
    text = "a" * 400 + " " + "b" * 200
    assert bounded(text) == ["a" * 400, "b" * 200]


def test_pathological_single_token_uses_deterministic_hard_split():
    text = "z" * (RESPONSE_EXCERPT_MAX_LENGTH + 17)
    assert bounded(text) == [
        "z" * RESPONSE_EXCERPT_MAX_LENGTH,
        "z" * 17,
    ]


def test_long_unicode_chunks_remain_exact_substrings():
    text = "é界🙂" * 220
    segments = bounded(text)
    assert all(0 < len(item) <= RESPONSE_EXCERPT_MAX_LENGTH for item in segments)
    assert_contiguous_and_ordered(text, segments)
    assert "".join(segments) == text


def test_long_markdown_list_remains_verbatim_inside_chunks():
    text = "- **important item** " * 40 + "done"
    segments = bounded(text)
    assert all(0 < len(item) <= RESPONSE_EXCERPT_MAX_LENGTH for item in segments)
    assert_contiguous_and_ordered(text, segments)
    assert segments[0].startswith("- **important item**")
    assert "**" in segments[0]


def test_bounded_crlf_and_newline_behavior_is_unchanged():
    text = ("a" * 510) + "\r\n" + ("b" * 510) + "\nTail."
    segments = bounded(text)
    assert [len(item) for item in segments] == [500, 10, 500, 10, 5]
    assert_contiguous_and_ordered(text, segments)
