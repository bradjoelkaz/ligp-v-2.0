"""Visual asset generator (Phase 11): thumbnails / album covers.

Turns an image prompt (from trend analysis \u2014 ``image_prompt``) into a real image
via the Google Gemini image API (or a configured image endpoint), returning a
web URL or a saved local path. Resilient by design: with no API key or on any
failure it returns a deterministic per-category **default thumbnail** so the
pipeline never breaks.

The HTTP client and file writer are injectable, so generation is fully unit
testable offline with no network or disk side effects.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

# Gemini image-capable model endpoint (overridable).
_DEFAULT_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.0-flash-exp-image-generation")

# Per-category fallback thumbnails served from the app's static assets.
DEFAULT_IMAGE = "/static/defaults/trend.png"
CATEGORY_DEFAULTS: dict[str, str] = {
    "IT/테크": "/static/defaults/tech.png",
    "사회/종합": "/static/defaults/society.png",
    "비즈니스": "/static/defaults/business.png",
    "문화/라이프": "/static/defaults/culture.png",
}


def default_image(category: str = "") -> str:
    """Return the fallback thumbnail path for a category."""
    return CATEGORY_DEFAULTS.get(category, DEFAULT_IMAGE)


class VisualGenerator:
    """Generate a thumbnail/cover image from a prompt, with category fallback."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.model = model or _DEFAULT_MODEL

    def available(self) -> bool:
        return bool(self.api_key)

    def _fallback(self, category: str, reason: str) -> dict[str, Any]:
        return {"status": "fallback", "image_url": default_image(category), "reason": reason}

    @staticmethod
    def _extract_url(data: dict[str, Any]) -> str:
        """Best-effort extraction of a hosted image URL from a response."""
        if not isinstance(data, dict):
            return ""
        # OpenRouter / generic image-provider shape.
        for item in data.get("images", []) or []:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
        return str(data.get("url", "") or "")

    @staticmethod
    def _extract_b64(data: dict[str, Any]) -> str:
        """Extract inline base64 image data from a Gemini-style response."""
        for cand in data.get("candidates", []) or []:
            for part in cand.get("content", {}).get("parts", []) or []:
                inline = part.get("inline_data") or part.get("inlineData")
                if inline and inline.get("data"):
                    return str(inline["data"])
        return ""

    def generate_image(
        self,
        image_prompt: str,
        category: str = "",
        *,
        content_id: str = "",
        http: Any | None = None,
        writer: Callable[[str, str], str] | None = None,
    ) -> dict[str, Any]:
        """Generate an image; return ``{status, image_url, ...}`` (never raises)."""
        if not self.available():
            return self._fallback(category, "no_api_key")

        created = False
        try:
            if http is None:  # pragma: no cover - real network client
                import httpx

                http = httpx.Client(timeout=60.0)
                created = True

            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model}:generateContent?key={self.api_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": f"Generate an image: {image_prompt}"}]}],
                "generationConfig": {"responseModalities": ["IMAGE"]},
            }
            resp = http.post(url, json=payload, headers={"Content-Type": "application/json"})
            resp.raise_for_status()
            data = resp.json()

            hosted = self._extract_url(data)
            if hosted:
                return {"status": "complete", "image_url": hosted, "image_prompt": image_prompt}

            b64 = self._extract_b64(data)
            if b64:
                write = writer or _save_png
                path = write(b64, content_id or image_prompt)
                return {"status": "complete", "image_url": path, "image_prompt": image_prompt}

            return self._fallback(category, "no_image_in_response")
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            _log.warning("visual_generate_failed", extra={"error": str(exc)})
            return self._fallback(category, str(exc))
        finally:
            if created and http is not None:  # pragma: no cover - real network client
                try:
                    http.close()
                except Exception:  # noqa: BLE001
                    pass


def _save_png(b64_data: str, seed: str) -> str:  # pragma: no cover - real disk write
    """Persist base64 PNG data under data/images/ and return its path."""
    import base64

    name = hashlib.sha256((seed or b64_data[:32]).encode("utf-8")).hexdigest()[:16]
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "images")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.png")
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(b64_data))
    return f"/data/images/{name}.png"
