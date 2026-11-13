import os
import sys
import tempfile

# src.env reads the environment and parses the command line as soon as it is imported. Give it what a real run would
# have, and a throwaway config folder, before any test module imports src.
_config_dir = tempfile.mkdtemp(prefix='rsstt-test-')
os.environ.setdefault('TOKEN', 'test')
os.environ.setdefault('MANAGER', '-1')
sys.argv = [sys.argv[0], '--config', _config_dir]
