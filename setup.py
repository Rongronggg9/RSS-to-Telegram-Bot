#!/usr/bin/env python3

import re
from functools import partial
from setuptools import setup, find_packages
from pathlib import Path

PROJ_ROOT = Path(__file__).parent

version = re.search(r"""__version__ *= *['"]([^'"]+)['"]""", (PROJ_ROOT / "src/version.py").read_text())[1]

replacePackagePath = partial(re.compile(r'^src').sub, 'rsstt')

source_packages = find_packages(include=['src', 'src.*'])
proj_packages = [replacePackagePath(name) for name in source_packages]

setup(
    version=version,
    packages=proj_packages,
    package_dir={'rsstt': 'src'},
)
