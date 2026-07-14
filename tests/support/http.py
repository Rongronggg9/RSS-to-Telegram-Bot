from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

import pytest_asyncio
from aiohttp import web


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path_qs: str
    headers: Mapping[str, str]


@dataclass(frozen=True)
class QueuedResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    wait_for: asyncio.Event | None = None


class LocalFeedServer:
    def __init__(self, port: int) -> None:
        self.port = port
        self.requests: list[RecordedRequest] = []
        self._responses: list[QueuedResponse] = []

    def enqueue(
        self,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
        wait_for: asyncio.Event | None = None,
    ) -> None:
        self._responses.append(
            QueuedResponse(
                status=status,
                headers=headers or {},
                body=body,
                wait_for=wait_for,
            )
        )

    @property
    def feed_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/feed"

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path_qs=request.path_qs,
                headers=dict(request.headers),
            )
        )
        if not self._responses:
            raise RuntimeError("No local feed response was queued")
        response = self._responses.pop(0)
        if response.wait_for is not None:
            await response.wait_for.wait()
        return web.Response(
            status=response.status,
            headers=response.headers,
            body=response.body,
        )


@pytest_asyncio.fixture
async def local_feed_server() -> AsyncIterator[LocalFeedServer]:
    server = LocalFeedServer(port=0)
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", server.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    try:
        await site.start()
        addresses = runner.addresses
        if len(addresses) != 1:
            raise RuntimeError(f"Expected one local server address, got {addresses!r}")
        server.port = addresses[0][1]
        yield server
    finally:
        await runner.cleanup()
