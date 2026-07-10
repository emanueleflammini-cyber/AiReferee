"""Local language detection — no API cost."""
from __future__ import annotations
import re
from typing import Optional

try:
    from langdetect import detect, DetectorFactory, LangDetectException
    DetectorFactory.seed = 0
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False

SUPPORTED = {"en", "it", "es", "fr", "de"}
DEFAULT_LANG = "en"


def detect_language(text: str) -> str:
    """Return an ISO-639-1 code. Falls back to English if detection fails.
    Very short text (< 10 chars) defaults to English — langdetect is unreliable
    below that length.
    """
    if not text or len(text.strip()) < 10:
        return DEFAULT_LANG
    if not _AVAILABLE:
        return DEFAULT_LANG
    try:
        code = detect(text).lower()
        return code if code in SUPPORTED else code  # keep the code even if unsupported for logging
    except LangDetectException:
        return DEFAULT_LANG


def normalize_prompt(p: str) -> str:
    p = (p or "").lower()
    p = re.sub(r"[^\w\s]", " ", p, flags=re.UNICODE)
    p = re.sub(r"\s+", " ", p).strip()
    return p
