#  RSS to Telegram Bot
#  Copyright (C) 2022-2024  Rongrong <i@rong.moe>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

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
