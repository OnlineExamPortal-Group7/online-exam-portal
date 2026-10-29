"""Production settings: PostgreSQL, TLS enforcement (OEP-SR-001).

Startup fails with ImproperlyConfigured if a required variable is missing or blank.
"""
from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = require_env("DJANGO_SECRET_KEY")  # noqa: F405
ALLOWED_HOSTS = [
    h.strip() for h in require_env("DJANGO_ALLOWED_HOSTS").split(",") if h.strip()  # noqa: F405
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": require_env("POSTGRES_DB"),  # noqa: F405
        "USER": require_env("POSTGRES_USER"),  # noqa: F405
        "PASSWORD": require_env("POSTGRES_PASSWORD"),  # noqa: F405
        "HOST": require_env("POSTGRES_HOST"),  # noqa: F405
        "PORT": env("POSTGRES_PORT", "5432"),  # noqa: F405
    }
}

# Nginx terminates TLS and forwards this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", "localhost")  # noqa: F405
EMAIL_PORT = int(env("EMAIL_PORT", "587"))  # noqa: F405
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")  # noqa: F405
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")  # noqa: F405
EMAIL_USE_TLS = True
