"""Newsletter publishing client (Phase 12).

Publishes an assembled newsletter to an external channel (Substack / Mailchimp)
when credentials are configured, and otherwise records a deterministic **mock**
success so the pipeline keeps working offline. Every attempt is logged to the
``deployments`` ledger with platform ``newsletter``.

Honors the Phase 9 production no-mock switch: in production with no credentials,
it records a real ``failed`` status instead of fabricating success (unless
``IIGP_ALLOW_MOCK=1``). HTTP client + store are injectable for offline tests.
"""

from __future__ import annotations

import os
from typing import Any

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)

PLATFORM = "newsletter"


def _content_id(newsletter: dict[str, Any]) -> str:
    return str(
        newsletter.get("content_id")
        or f"newsletter:{abs(hash(newsletter.get('title', '') + newsletter.get('subject', '')))}"
    )


def _credentials() -> tuple[str, str]:
    """Return (provider, token) for whichever newsletter channel is configured."""
    if os.getenv("SUBSTACK_API_KEY"):
        return "substack", os.environ["SUBSTACK_API_KEY"]
    if os.getenv("MAILCHIMP_API_KEY"):
        return "mailchimp", os.environ["MAILCHIMP_API_KEY"]
    return "", ""


def _mock_result(content_id: str) -> dict[str, Any]:
    return {
        "status": "mock",
        "url": f"https://mock.local/newsletter/{content_id}",
        "published_at": utcnow_iso(),
    }


def _unavailable(content_id: str, reason: str) -> dict[str, Any]:
    from utils.runtime import mock_allowed

    if mock_allowed():
        return _mock_result(content_id)
    _log.error("newsletter_publish_failed_production", extra={"reason": reason})
    return {"status": "failed", "url": "", "error": reason, "published_at": utcnow_iso()}


def publish(
    newsletter: dict[str, Any],
    *,
    http: Any | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Publish ``newsletter`` to the configured channel (or mock); record it."""
    if store is None:
        from database import db_store as store

        store.init_db()

    content_id = _content_id(newsletter)
    provider, token = _credentials()

    if not provider:
        result = _unavailable(content_id, "no_newsletter_credentials")
    else:
        try:
            result = _publish_remote(provider, token, newsletter, http)
        except Exception as exc:  # noqa: BLE001 - publish failed
            _log.warning(
                "newsletter_publish_failed", extra={"provider": provider, "error": str(exc)}
            )
            result = _unavailable(content_id, str(exc))

    store.record_deployment(content_id, PLATFORM, result.get("url", ""), result["status"])
    out = {"content_id": content_id, "platform": PLATFORM, "provider": provider, **result}
    _log.info("newsletter_published", extra={"content_id": content_id, "status": result["status"]})
    return out


def _publish_remote(
    provider: str, token: str, newsletter: dict[str, Any], http: Any | None
) -> dict[str, Any]:  # pragma: no cover - exercised via injected http in tests
    """POST the newsletter to the provider; returns a published result."""
    created = False
    if http is None:  # pragma: no cover - real network client
        import httpx

        http = httpx.Client(timeout=30.0)
        created = True
    try:
        url = (
            "https://api.substack.com/v1/posts"
            if provider == "substack"
            else "https://us1.api.mailchimp.com/3.0/campaigns"
        )
        resp = http.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "title": newsletter.get("title", ""),
                "subject": newsletter.get("subject", ""),
                "body_html": newsletter.get("html", ""),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": "published",
            "url": data.get("url", "") or data.get("archive_url", ""),
            "post_id": data.get("id", ""),
            "published_at": utcnow_iso(),
        }
    finally:
        if created and http is not None:  # pragma: no cover - real network client
            try:
                http.close()
            except Exception:  # noqa: BLE001
                pass
