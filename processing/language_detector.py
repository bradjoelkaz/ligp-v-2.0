"""Language detection (QA-007, DD-004 routing input).

Primary backend is fastText (``lid.176``); ``langdetect`` is the secondary.
When neither is installed (e.g. offline sandbox) a Unicode-script heuristic
provides a coarse ko/en/ja/zh/other classification good enough for NER routing
and unit testing.
"""

from __future__ import annotations

import os
import unicodedata
from functools import lru_cache

from utils.logger import get_logger

_log = get_logger(__name__)

SUPPORTED = ("ko", "en", "ja", "zh", "other")


@lru_cache(maxsize=1)
def _load_fasttext():
    """Load the fastText model once if the lib + model file are available."""
    model_path = os.environ.get("FASTTEXT_LID_PATH", "")
    if not model_path or not os.path.exists(model_path):
        return None
    try:
        import fasttext  # type: ignore

        return fasttext.load_model(model_path)
    except Exception:  # pragma: no cover - optional dependency
        return None


def _script_heuristic(text: str) -> str:
    """Coarse classification by dominant Unicode script."""
    counts = {"ko": 0, "ja": 0, "zh": 0, "latin": 0}
    for ch in text:
        if not ch.strip():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        if "HANGUL" in name:
            counts["ko"] += 1
        elif "HIRAGANA" in name or "KATAKANA" in name:
            counts["ja"] += 1
        elif "CJK" in name:
            counts["zh"] += 1
        elif "LATIN" in name:
            counts["latin"] += 1

    if not any(counts.values()):
        return "other"
    # Japanese kana is the strongest signal; CJK without kana -> zh.
    if counts["ko"] and counts["ko"] >= max(counts["ja"], counts["zh"]):
        return "ko"
    if counts["ja"]:
        return "ja"
    if counts["zh"]:
        return "zh"
    if counts["latin"]:
        return "en"
    return "other"


def detect_language(text: str) -> str:
    """Return one of SUPPORTED language codes."""
    text = (text or "").strip()
    if not text:
        return "other"

    model = _load_fasttext()
    if model is not None:  # pragma: no cover - requires model file
        labels, _ = model.predict(text.replace("\n", " "), k=1)
        code = labels[0].replace("__label__", "")
        return code if code in SUPPORTED else _map_to_supported(code)

    try:
        from langdetect import detect  # type: ignore

        return _map_to_supported(detect(text))
    except Exception:
        return _script_heuristic(text)


def _map_to_supported(code: str) -> str:
    code = (code or "").lower()
    if code.startswith("zh"):
        return "zh"
    if code in ("ko", "en", "ja"):
        return code
    return "other"
