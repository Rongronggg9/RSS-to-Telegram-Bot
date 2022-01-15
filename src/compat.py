"""Containing something make the bot compatible with Python 3.7 ~ 3.10"""

import sys

_version_info = sys.version_info
if not (_version_info[0] == 3 and _version_info[1] >= 7):
    raise RuntimeError("This bot requires Python 3.7 or later")

from contextlib import AbstractContextManager, AbstractAsyncContextManager
from typing import Any

# add a false `Final` for Python 3.7
try:
    from typing import Final
except ImportError:
    Final = Any

# backport `contextlib.nullcontext` for Python 3.7 ~ 3.9
if _version_info[1] >= 10:
    # noinspection PyUnresolvedReferences
    from contextlib import nullcontext
else:
    # noinspection SpellCheckingInspection
    class nullcontext(AbstractContextManager, AbstractAsyncContextManager):
        """Backported `contextlib.nullcontext` from Python 3.10"""

        def __init__(self, enter_result=None):
            self.enter_result = enter_result

        def __enter__(self):
            return self.enter_result

        def __exit__(self, *excinfo):
            pass

        async def __aenter__(self):
            return self.enter_result

        async def __aexit__(self, *excinfo):
            pass
