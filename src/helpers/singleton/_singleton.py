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

from __future__ import annotations

from typing import ClassVar


class Singleton:
    _singleton: ClassVar = None

    def __new__(cls, *args, **kwargs):
        if cls._singleton is None:
            return object.__new__(cls)
        raise RuntimeError('A singleton instance already exists, use get_instance() instead.')

    @classmethod
    def get_instance(cls) -> 'Singleton':
        if cls._singleton is None:
            cls._singleton = cls()  # implicitly calls __new__ then __init__
        return cls._singleton
