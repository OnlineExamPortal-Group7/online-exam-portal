from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User
from .sessions import end_sessions

PASSWORD = "Str0ng-pass-123"


def make_user(username, role=User.Role.STUDENT):
    return User.objects.create_user(username, f"{username}@example.com", PASSWORD, role=role)


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


def is_signed_in(client):
    return client.get(reverse("accounts:student_dashboard")).status_code == 200


class EndSessionsTest(TestCase):  # OEP-F-004, OEP-F-005
    def setUp(self):
        self.user = make_user("alice")
        self.other = make_user("bob")

    def test_ends_all_of_the_users_sessions(self):
        first, second = signed_in(self.user), signed_in(self.user)
        end_sessions(self.user)
        self.assertFalse(is_signed_in(first))
        self.assertFalse(is_signed_in(second))

    def test_keeps_the_given_session(self):
        old, current = signed_in(self.user), signed_in(self.user)
        end_sessions(self.user, keep_session_key=current.session.session_key)
        self.assertFalse(is_signed_in(old))
        self.assertTrue(is_signed_in(current))

    def test_other_users_are_not_affected(self):
        other_client = signed_in(self.other)
        signed_in(self.user)
        end_sessions(self.user)
        self.assertTrue(is_signed_in(other_client))

    def test_expired_sessions_are_left_for_cleanup(self):
        client = signed_in(self.user)
        Session.objects.filter(session_key=client.session.session_key).update(
            expire_date=timezone.now() - timedelta(days=1)
        )
        end_sessions(self.user)
        self.assertTrue(Session.objects.filter(session_key=client.session.session_key).exists())


class SingleSessionOnLoginTest(TestCase):  # OEP-F-005
    def setUp(self):
        self.user = make_user("alice")

    def logged_in(self, user):
        client = Client()
        self.assertTrue(client.login(username=user.email, password=PASSWORD))
        return client

    def test_new_login_ends_the_previous_session(self):
        first = self.logged_in(self.user)
        second = self.logged_in(self.user)
        self.assertFalse(is_signed_in(first))
        self.assertTrue(is_signed_in(second))

    def test_user_has_exactly_one_session_after_login(self):
        for _ in range(3):
            client = self.logged_in(self.user)
        sessions = [s for s in Session.objects.all() if s.get_decoded().get("_auth_user_id")]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].session_key, client.session.session_key)

    def test_other_users_stay_signed_in(self):
        other_client = self.logged_in(make_user("bob"))
        self.logged_in(self.user)
        self.assertTrue(is_signed_in(other_client))

    def test_logout_still_works(self):
        client = self.logged_in(self.user)
        client.post(reverse("accounts:logout"))
        self.assertFalse(is_signed_in(client))

    def test_admin_site_login_also_ends_the_previous_session(self):
        admin = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        portal = self.logged_in(admin)
        site = Client()
        site.post(reverse("admin:login"), {"username": "root", "password": PASSWORD})
        self.assertEqual(site.get(reverse("admin:index")).status_code, 200)
        response = portal.get(reverse("accounts:admin_dashboard"))
        self.assertIn(reverse("accounts:login"), response["Location"])
