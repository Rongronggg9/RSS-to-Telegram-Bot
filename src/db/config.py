from __future__ import annotations

from .. import env

TORTOISE_ORM = {
    "connections": {
        "default": env.DATABASE_URL
    },
    "apps": {
        "models": {
            "models": ["aerich.models", f"{env.self_module_name}.db.models"],
            "default_connection": "default",
        },
    },
}
