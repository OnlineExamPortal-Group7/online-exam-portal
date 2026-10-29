"""Session helpers shared by login (OEP-F-005) and user administration (OEP-F-004)."""
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone


def end_sessions(user, keep_session_key=None):
    """Sign the user out everywhere, except the session given in keep_session_key."""
    sessions = Session.objects.filter(expire_date__gt=timezone.now())
    if keep_session_key:
        sessions = sessions.exclude(session_key=keep_session_key)
    for session in sessions:
        if session.get_decoded().get(SESSION_KEY) == str(user.pk):
            session.delete()
