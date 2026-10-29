from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .sessions import end_sessions


@receiver(user_logged_in)
def keep_only_the_new_session(sender, request, user, **kwargs):
    """A new login signs the user out of every other session (OEP-F-005)."""
    end_sessions(user, keep_session_key=request.session.session_key)
