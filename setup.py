#!/usr/bin/env python3

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
