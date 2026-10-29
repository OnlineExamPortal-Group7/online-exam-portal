"""Development / test settings: SQLite, DEBUG on."""
from .base import *  # noqa: F401,F403

# Development only. Production (prod.py) requires DJANGO_SECRET_KEY and never uses this.
SECRET_KEY = env(  # noqa: F405
    "DJANGO_SECRET_KEY", "dev-only-insecure-key-do-not-use-in-production"
)
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}
