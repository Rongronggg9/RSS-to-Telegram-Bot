#!/usr/bin/env python3

import re
from functools import partial
from setuptools import setup, find_packages
from pathlib import Path

version_info = re.search(r"""__version__ *= *['"]([^'"]+)['"]""", Path("src/version.py").read_text())[1]
version = {'__version__': version_info}

replacePackagePath = partial(re.compile(r'^src').sub, 'rsstt')

source_packages = find_packages(include=['src', 'src.*'])
proj_packages = [replacePackagePath(name) for name in source_packages]

setup(
    version=version['__version__'],
    packages=proj_packages,
    package_dir={'rsstt': 'src'},
)
