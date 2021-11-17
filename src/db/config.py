from src import env

TORTOISE_ORM = {
    "connections": {
        "default": env.DB_URL
    },
    "apps": {
        "models": {
            "models": ["aerich.models", "src.db.models"],
            "default_connection": "default",
        },
    },
}
