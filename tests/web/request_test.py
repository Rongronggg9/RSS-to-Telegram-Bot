from __future__ import annotations

import aiohttp
import pytest

from tests.support.http import LocalFeedServer


@pytest.mark.http
async def test_permanent_redirect_result_preserves_basic_authentication(
    local_feed_server: LocalFeedServer,
) -> None:
    from src.web import get

    username = "fixture-user"
    password = "fixture-password"
    original_url = (
        f"http://{username}:{password}@127.0.0.1:{local_feed_server.port}/original"
    )
    redirected_url = f"http://127.0.0.1:{local_feed_server.port}/permanent"
    authenticated_redirected_url = (
        f"http://{username}:{password}@127.0.0.1:"
        f"{local_feed_server.port}/permanent"
    )
    local_feed_server.enqueue(status=301, headers={"Location": redirected_url})
    local_feed_server.enqueue(body=b"redirect target")

    result = await get(original_url, timeout=1)

    assert result.status == 200
    assert result.content == b"redirect target"
    assert result.ori_url == original_url
    assert result.url == authenticated_redirected_url
    assert [request.path_qs for request in local_feed_server.requests] == [
        "/original",
        "/permanent",
    ]
    assert local_feed_server.requests[-1].headers["Authorization"] == (
        aiohttp.BasicAuth(username, password).encode()
    )
