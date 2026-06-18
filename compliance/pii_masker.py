"""PII masking (QA-022).

Detects and masks emails, phone numbers (KR/intl), Korean resident registration
numbers (RRN), and credit-card-like sequences. Pure-regex, multilingual-safe.
``mask`` returns the redacted text plus a list of detections (with positions).
"""

from __future__ import annotations

import re
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

# Order matters: more specific patterns first so they win the position.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("krrn", re.compile(r"\b\d{6}[-\s]?\d{7}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("phone_kr", re.compile(r"\b01[016789][-\s]?\d{3,4}[-\s]?\d{4}\b")),
    ("phone_intl", re.compile(r"\+?\d{1,3}[-\s]?\(?\d{2,4}\)?[-\s]?\d{3,4}[-\s]?\d{4}\b")),
]

_MASK = {
    "email": "[EMAIL]",
    "krrn": "[RRN]",
    "credit_card": "[CARD]",
    "phone_kr": "[PHONE]",
    "phone_intl": "[PHONE]",
}


class PIIMasker:
    """Detect and redact personally identifiable information."""

    def detect_only(self, text: str) -> list[dict[str, Any]]:
        """Return non-overlapping detections sorted by position."""
        if not text:
            return []
        detections: list[dict[str, Any]] = []
        claimed: list[tuple[int, int]] = []

        def _overlaps(s: int, e: int) -> bool:
            return any(s < ce and e > cs for cs, ce in claimed)

        for ptype, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                s, e = m.start(), m.end()
                if _overlaps(s, e):
                    continue
                claimed.append((s, e))
                detections.append({"type": ptype, "original": m.group(), "start": s, "end": e})
        detections.sort(key=lambda d: d["start"])
        return detections

    def mask(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        """Return (masked_text, detections). Original text is not mutated."""
        detections = self.detect_only(text)
        # Replace from the end so earlier offsets stay valid.
        out = text
        for det in sorted(detections, key=lambda d: d["start"], reverse=True):
            token = _MASK.get(det["type"], "[PII]")
            out = out[: det["start"]] + token + out[det["end"] :]
        return out, detections
