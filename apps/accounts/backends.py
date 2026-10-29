from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


def find_user(identifier):
    """Find a user by e-mail (preferred) or username, ignoring case."""
    if not identifier:
        return None
    identifier = identifier.strip()
    user = UserModel.objects.filter(email__iexact=identifier).first()
    if user is None:
        user = UserModel.objects.filter(username__iexact=identifier).first()
    return user


class EmailOrUsernameBackend(ModelBackend):
    """Log in with e-mail and password (OEP-F-001); username still works for /admin/."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None
        user = find_user(username)
        if user is None:
            # Hash anyway so response time does not reveal whether the account exists.
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
