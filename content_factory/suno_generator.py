"""Suno Pro session-cookie music generator (Phase 10, zero-cost).

Uses an existing Suno Pro browser session (``SUNO_COOKIE``) to talk to the Suno
studio API directly \u2014 submit a generation, poll the feed, and return the final
MP3 + cover-art URLs. No paid relay/API: it rides the user's existing
subscription.

Resilience is first-class: a missing/expired cookie or any HTTP failure never
raises \u2014 it returns a *fallback* card (``status="fallback"``) carrying the text
music + image prompts so the dashboard can offer manual copy instead.

The HTTP client and ``sleep`` are injectable, so the polling loop is fully unit
testable offline with no network.
"""

from __future__ import annotations

import os
import time
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

STUDIO_BASE = "https://studio-api.suno.ai"
FALLBACK_MESSAGE = "수노 자동 생성 대기 및 수동 복사 지원"


class SunoGenerator:
    """Generate music via a Suno Pro cookie session (with text fallback)."""

    def __init__(self, cookie: str | None = None) -> None:
        self.cookie = cookie if cookie is not None else os.getenv("SUNO_COOKIE", "")
        self.model = os.getenv("SUNO_MODEL", "chirp-v3-5")

    def available(self) -> bool:
        """True when a session cookie is configured."""
        return bool(self.cookie)

    def _headers(self) -> dict[str, str]:
        return {
            "Cookie": self.cookie,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; IIGP/2.0)",
            "Accept": "application/json",
        }

    def _fallback(self, suno_prompt: str, image_prompt: str, reason: str) -> dict[str, Any]:
        return {
            "status": "fallback",
            "audio_url": "",
            "image_url": "",
            "suno_prompt": suno_prompt,
            "image_prompt": image_prompt,
            "message": FALLBACK_MESSAGE,
            "reason": reason,
        }

    def generate(
        self,
        suno_prompt: str,
        image_prompt: str = "",
        *,
        instrumental: bool = True,
        title: str = "",
        http: Any | None = None,
        sleep: Any | None = None,
        max_polls: int = 12,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Submit a generation and poll until complete.

        Returns ``{status: "complete", audio_url, image_url, clip_id, ...}`` on
        success, or a ``status="fallback"`` text card on any miss/failure.
        """
        if not self.available():
            return self._fallback(suno_prompt, image_prompt, "no_cookie")

        sleep = sleep or time.sleep
        created = False
        try:
            if http is None:  # pragma: no cover - real network client
                import httpx

                http = httpx.Client(timeout=30.0)
                created = True

            payload = {
                "gpt_description_prompt": suno_prompt,
                "prompt": "" if instrumental else suno_prompt,
                "tags": "",
                "make_instrumental": bool(instrumental),
                "mv": self.model,
                "title": title,
            }
            resp = http.post(
                f"{STUDIO_BASE}/api/generate/v2/", json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            clips = resp.json().get("clips", [])
            ids = [c.get("id") for c in clips if c.get("id")]
            if not ids:
                return self._fallback(suno_prompt, image_prompt, "no_clip_ids")

            for _ in range(max_polls):
                feed = http.get(
                    f"{STUDIO_BASE}/api/feed/",
                    params={"ids": ",".join(ids)},
                    headers=self._headers(),
                )
                feed.raise_for_status()
                for item in feed.json() or []:
                    if item.get("status") in ("complete", "streaming") and item.get("audio_url"):
                        return {
                            "status": "complete",
                            "audio_url": item.get("audio_url", ""),
                            "image_url": item.get("image_large_url") or item.get("image_url", ""),
                            "clip_id": item.get("id", ""),
                            "suno_prompt": suno_prompt,
                            "image_prompt": image_prompt,
                        }
                sleep(poll_interval)
            return self._fallback(suno_prompt, image_prompt, "timeout")
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            _log.warning("suno_generate_failed", extra={"error": str(exc)})
            return self._fallback(suno_prompt, image_prompt, str(exc))
        finally:
            if created and http is not None:  # pragma: no cover - real network client
                try:
                    http.close()
                except Exception:  # noqa: BLE001
                    pass
