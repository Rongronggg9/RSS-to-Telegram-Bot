from __future__ import annotations

from src import env

TORTOISE_ORM = {
    "connections": {
        "default": env.DATABASE_URL
    },
    "apps": {
        "models": {
            "models": ["aerich.models", "src.db.models"],
            "default_connection": "default",
        },
    },
}
