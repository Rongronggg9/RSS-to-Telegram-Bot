#!/usr/bin/env python3

#  RSS to Telegram Bot
#  Copyright (C) 2025  Rongrong <i@rong.moe>
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

import asyncio
import os
import sys

import aiohttp

port = os.environ.get('PORT')
if not port:
    # This script is only used for the health check in the Docker container,
    # skip it if PORT is not set.
    print('Skipping health check as PORT is not set')
    sys.exit(0)


async def check_health():
    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=3.0, connect=1.5),
            raise_for_status=False
    ) as session:
        try:
            async with session.get(f'http://127.0.0.1:{port}', allow_redirects=False) as response:
                status = response.status
        except aiohttp.ClientError as e:
            print(f'Health check failed: Connection error: {e}')
            sys.exit(1)
        if status < 400:
            # RSStT only returns 302 currently, but it should be OK to loosen the requirement in health check.
            print(f'Health check passed with status {status}')
            sys.exit(0)
        else:
            print(f'Health check failed with status {status}')
            sys.exit(1)


if __name__ == '__main__':
    asyncio.run(check_health())
