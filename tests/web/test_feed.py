from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.support.http import LocalFeedServer


_FEED_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "feeds"


@pytest.mark.http
async def test_feed_get_parses_local_rss_and_preserves_response_metadata(
    local_feed_server: LocalFeedServer,
) -> None:
    from src.web import feed_get

    body = (_FEED_FIXTURES / "baseline.xml").read_bytes()
    local_feed_server.enqueue(
        headers={
            "Content-Type": "application/rss+xml; charset=utf-8",
            "ETag": '"fixture-v1"',
            "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT",
        },
        body=body,
    )

    result = await feed_get(local_feed_server.feed_url, timeout=1)

    assert result.status == 200
    assert result.url == local_feed_server.feed_url
    assert result.ori_url == local_feed_server.feed_url
    assert result.content == body
    assert result.headers["ETag"] == '"fixture-v1"'
    assert result.error is None
    assert result.web_response is not None
    assert result.web_response.etag == '"fixture-v1"'
    assert result.web_response.last_modified == datetime(
        2025,
        1,
        1,
        tzinfo=timezone.utc,
    )
    assert result.rss_d is not None
    assert result.rss_d.feed.title == "Fixture Feed"
    assert [
        (entry.id, entry.title, entry.link, entry.summary)
        for entry in result.rss_d.entries
    ] == [
        (
            "urn:fixture:old-2",
            "old-2",
            "https://example.test/old-2",
            "Description for old-2.",
        ),
        (
            "urn:fixture:old-1",
            "old-1",
            "https://example.test/old-1",
            "Description for old-1.",
        ),
    ]


@pytest.mark.http
async def test_feed_get_returns_cached_result_for_http_304(
    local_feed_server: LocalFeedServer,
) -> None:
    from src.web import feed_get

    local_feed_server.enqueue(status=304, headers={"ETag": '"fixture-v1"'})

    result = await feed_get(local_feed_server.feed_url, timeout=1)

    assert result.status == 304
    assert result.content is None
    assert result.rss_d is None
    assert result.error is None
    assert result.headers["ETag"] == '"fixture-v1"'
    assert result.web_response is not None
    assert result.web_response.status == 304


@pytest.mark.http
async def test_feed_get_treats_empty_200_response_as_cached(
    local_feed_server: LocalFeedServer,
) -> None:
    from src.web import feed_get

    local_feed_server.enqueue(
        headers={"Content-Length": "0", "ETag": '"fixture-empty"'},
        body=b"",
    )

    result = await feed_get(local_feed_server.feed_url, timeout=1)

    assert result.status == 304
    assert result.content == b""
    assert result.rss_d is None
    assert result.error is None
    assert result.headers["ETag"] == '"fixture-empty"'
    assert result.web_response is not None
    assert result.web_response.status == 200


@pytest.mark.http
async def test_feed_get_converts_local_timeout_to_network_error(
    local_feed_server: LocalFeedServer,
) -> None:
    from src.web import feed_get

    response_gate = asyncio.Event()
    local_feed_server.enqueue(wait_for=response_gate)
    local_feed_server.enqueue(wait_for=response_gate)

    try:
        result = await feed_get(
            local_feed_server.feed_url,
            timeout=0.01,
            verbose=False,
        )
    finally:
        response_gate.set()

    assert result.status == -1
    assert result.rss_d is None
    assert result.error is not None
    assert result.error.error_name == "network error"
    assert result.error.url == local_feed_server.feed_url
    assert isinstance(result.error.base_error, TimeoutError)
