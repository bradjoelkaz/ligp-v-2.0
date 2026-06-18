"""Small shared helpers (utils/helpers.py)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime

_WS_RE = re.compile(r"\s+")


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(tz=UTC)


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp string."""
    return utcnow().isoformat()


def normalize_text(text: str) -> str:
    """Unicode-normalize (NFKC), strip, and collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return _WS_RE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    """Stable SHA-256 hex digest of normalized text (for exact-dup checks)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def make_node_id(node_type: str, name: str) -> str:
    """Deterministic node id, e.g. ``topic:artificial_intelligence``."""
    slug = _WS_RE.sub("_", normalize_text(name).lower())
    slug = re.sub(r"[^a-z0-9_\-:]", "", slug)
    return f"{node_type}:{slug}"


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the inclusive range [low, high]."""
    return max(low, min(high, value))
