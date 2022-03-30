import re
from functools import partial
from setuptools import setup, find_packages
from distutils.util import convert_path

version = {}
with open(convert_path('src/version.py')) as f:
    exec(f.read(), version)

replacePackagePath = partial(re.compile(rf'^src').sub, 'rsstt')

source_packages = find_packages(include=['src', f'src.*'])
proj_packages = [replacePackagePath(name) for name in source_packages]

setup(
    version=version['__version__'],
    packages=proj_packages,
    package_dir={'rsstt': 'src'},
)
