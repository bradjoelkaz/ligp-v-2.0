"""robots.txt compliance (QA-021).

Wraps the stdlib ``urllib.robotparser`` and caches parsed robots per domain.
Network fetch is lazy and guarded; offline, ``refresh`` can be fed raw robots
text directly for testing.
"""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from utils.logger import get_logger

_log = get_logger(__name__)


class RobotsChecker:
    """Per-domain robots.txt evaluation with caching."""

    def __init__(self, default_crawl_delay: float = 1.0) -> None:
        self._cache: dict[str, RobotFileParser] = {}
        self.default_crawl_delay = default_crawl_delay

    @staticmethod
    def _domain(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme or 'https'}://{parsed.netloc}"

    def _get_parser(self, domain: str) -> RobotFileParser | None:
        return self._cache.get(domain)

    def refresh(self, domain: str, robots_text: str | None = None) -> None:
        """(Re)load robots.txt for a domain. If ``robots_text`` is given, parse
        it directly (offline); otherwise fetch over the network (lazy)."""
        domain = self._domain(domain) if "://" not in domain else domain
        rp = RobotFileParser()
        if robots_text is not None:
            rp.parse(robots_text.splitlines())
            self._cache[domain] = rp
            return
        try:  # pragma: no cover - network path
            rp.set_url(f"{domain}/robots.txt")
            rp.read()
            self._cache[domain] = rp
        except Exception as exc:  # pragma: no cover
            _log.warning("robots_fetch_failed", extra={"domain": domain, "error": str(exc)})

    def is_allowed(self, url: str, user_agent: str = "iigp-bot") -> bool:
        """Return True if ``user_agent`` may crawl ``url`` (default allow)."""
        domain = self._domain(url)
        rp = self._get_parser(domain)
        if rp is None:
            self.refresh(domain)
            rp = self._get_parser(domain)
        if rp is None:
            return True  # fail-open when robots is unavailable
        return rp.can_fetch(user_agent, url)

    def get_crawl_delay(self, domain: str) -> float:
        """Return the crawl-delay for a domain, or the configured default."""
        domain = self._domain(domain) if "://" not in domain else domain
        rp = self._get_parser(domain)
        if rp is None:
            return self.default_crawl_delay
        delay = rp.crawl_delay("iigp-bot")
        return float(delay) if delay is not None else self.default_crawl_delay
