
from django.core.cache import cache

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60
CACHE_PREFIX = "accounts:login-lockout:"


def _key(identifier):
    return f"{CACHE_PREFIX}{identifier.strip().lower()}"


def is_locked(identifier):
    if not identifier:
        return False

    return cache.get(_key(identifier), 0) >= MAX_FAILED_ATTEMPTS


def record_failed_attempt(identifier):
    if not identifier:
        return

    key = _key(identifier)
    attempts = cache.get(key, 0) + 1

    cache.set(key, attempts, timeout=LOCKOUT_SECONDS)


def clear_failed_attempts(identifier):
    if identifier:
        cache.delete(_key(identifier))
