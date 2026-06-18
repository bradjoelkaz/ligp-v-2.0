"""Slack Webhook notifier.

Events: viral detection / saga failure / revenue milestone / budget warning.
No-op (returns False) when no webhook is configured.
"""

from __future__ import annotations

import os
import time

from utils.logger import get_logger

logger = get_logger(__name__)

_COLORS = {
    "info": "#36a64f",
    "warning": "#ffcc00",
    "error": "#ff0000",
    "success": "#2eb886",
    "viral": "#7c3aed",
}


class SlackNotifier:
    """Slack Incoming Webhook client."""

    def __init__(
        self,
        webhook_url: str | None = None,
        channel: str = "#iigp-alerts",
    ) -> None:
        self._webhook = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
        self._channel = channel

    async def send(
        self,
        title: str,
        message: str,
        level: str = "info",
        fields: list[dict] | None = None,
    ) -> bool:
        """Send a Slack message. Returns True on HTTP 200."""
        if not self._webhook:
            logger.debug("slack_not_configured")
            return False

        color = _COLORS.get(level, _COLORS["info"])
        payload: dict = {
            "channel": self._channel,
            "attachments": [
                {
                    "color": color,
                    "title": title,
                    "text": message,
                    "fields": fields or [],
                    "footer": "IIGP v2.0",
                    "ts": time.time(),
                }
            ],
        }

        try:
            import httpx  # lazy

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self._webhook, json=payload)
                return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.warning("slack_send_failed", extra={"error": str(exc)})
            return False

    async def alert_viral(self, node: dict, velocity: float) -> None:
        """Viral trend detection alert."""
        await self.send(
            title="🔥 바이럴 트렌드 감지!",
            message=f"노드 `{node.get('label')}` 속도: {velocity:.1%}",
            level="viral",
            fields=[
                {"title": "Node ID", "value": node.get("node_id", ""), "short": True},
                {"title": "Velocity", "value": f"{velocity:.2%}", "short": True},
            ],
        )

    async def alert_saga_failure(self, saga_id: str, platform: str, error: str) -> None:
        """Publish Saga failure alert."""
        await self.send(
            title="❌ Saga 발행 실패",
            message=f"플랫폼: {platform}\n오류: {error[:200]}",
            level="error",
            fields=[{"title": "Saga ID", "value": saga_id, "short": True}],
        )

    async def alert_revenue_milestone(self, amount: float, period: str) -> None:
        """Revenue milestone alert."""
        await self.send(
            title="💰 수익 마일스톤 달성!",
            message=f"{period} 누적 수익: ₩{amount:,.0f}",
            level="success",
        )

    async def alert_budget_warning(self, spent: float, budget: float) -> None:
        """LLM budget 80% warning."""
        await self.send(
            title="⚠️ LLM 예산 경고",
            message=f"이번 달 사용: ${spent:.2f} / ${budget:.2f}",
            level="warning",
        )
