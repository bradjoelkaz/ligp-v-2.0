"""Naver collector unit tests (httpx mocked)."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
def test_naver_collector_no_keys():
    """No API keys -> empty list (no network)."""
    os.environ.pop("NAVER_CLIENT_ID", None)
    os.environ.pop("NAVER_CLIENT_SECRET", None)
    from ingestion.collectors.naver import NaverBlogCollector

    collector = NaverBlogCollector()
    assert asyncio.run(collector.collect("테스트")) == []


@pytest.mark.unit
def test_naver_collector_parses_response():
    """A well-formed API response is parsed into RawDocuments."""
    mock_response = {
        "items": [
            {
                "title": "<b>테스트</b> 제목",
                "link": "https://blog.naver.com/test",
                "description": "설명 <b>텍스트</b>",
                "bloggername": "테스터",
                "postdate": "20240101",
            }
        ]
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.get = AsyncMock(return_value=mock_resp)

        os.environ["NAVER_CLIENT_ID"] = "test_id"
        os.environ["NAVER_CLIENT_SECRET"] = "test_secret"
        from ingestion.collectors.naver import NaverBlogCollector

        collector = NaverBlogCollector()
        result = asyncio.run(collector.collect("테스트"))

    assert len(result) == 1
    assert result[0].title == "테스트 제목"  # HTML stripped
    assert result[0].source == "naver_blog"
    assert result[0].lang == "ko"
