from __future__ import annotations
from typing import Optional

from aiohttp import web

from . import log

logger = log.getLogger('RSStT.redirect_server')


async def redirect(_):
    return web.HTTPFound('https://github.com/Rongronggg9/RSS-to-Telegram-Bot')


app = web.Application()
app.add_routes([web.route('*', '/{tail:.*}', redirect)])


async def run(port: Optional[int] = 5000):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, port=port)
    await site.start()
    logger.info(f'Redirect server listening on port {port}')


if __name__ == '__main__':
    web.run_app(app)
