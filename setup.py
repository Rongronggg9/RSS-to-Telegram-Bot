#!/usr/bin/env python3

#  RSS to Telegram Bot
#  Copyright (C) 2024  Rongrong <i@rong.moe>
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

import re
from functools import partial
from setuptools import setup, find_packages
from pathlib import Path

PROJ_ROOT = Path(__file__).parent

version = re.search(r"""__version__ *= *['"]([^'"]+)['"]""", (PROJ_ROOT / "src/version.py").read_text())[1]

replacePackagePath = partial(re.compile(r'^src').sub, 'rsstt')

# DB migrations are not Python packages, but they should also be included in the package
source_packages = find_packages(PROJ_ROOT, include=['src', 'src.*'])
db_migrations_dirs = [
    str(path.relative_to(PROJ_ROOT)).replace('/', '.')
    for path in (PROJ_ROOT / 'src' / 'db').glob('migrations_*/**')
    if path.is_dir()
]
proj_packages = [replacePackagePath(name) for name in source_packages + db_migrations_dirs]

setup(
    version=version,
    packages=proj_packages,
    package_dir={'rsstt': 'src'},
)
