
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .lockout import (
    clear_failed_attempts,
    is_locked,
    record_failed_attempt,
)

UserModel = get_user_model()


def find_user(identifier):
    """Find a user by email (preferred) or username, ignoring case."""
    if not identifier:
        return None

    identifier = identifier.strip()

    user = UserModel.objects.filter(email__iexact=identifier).first()

    if user is None:
        user = UserModel.objects.filter(username__iexact=identifier).first()

    return user


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate using email or username with temporary account lockout."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)

        if not username or password is None:
            return None

        identifier = username.strip()
        user = find_user(identifier)

        if user is None:
            # Hash a password to reduce timing differences for unknown accounts.
            UserModel().set_password(password)
            return None

        # Track attempts by user ID so email and username share the same lockout.
        lockout_key = f"user:{user.pk}"

        if is_locked(lockout_key):
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            clear_failed_attempts(lockout_key)
            return user

        record_failed_attempt(lockout_key)
        return None
