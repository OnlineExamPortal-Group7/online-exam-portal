"""End-to-end acceptance tests for issue #5, using the real login page.

TC-Auth-02 (OEP-F-002 / AC-002), TC-Auth-04 (OEP-F-004 / AC-004),
TC-Sec-04 (OEP-SR-003 / AC-SR-003).
"""
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User

from . import urls as admin_urls

PASSWORD = "Str0ng-pass-123"


def make_user(username, role=User.Role.STUDENT):
    return User.objects.create_user(username, f"{username}@example.com", PASSWORD, role=role)


def log_in(user, password=PASSWORD):
    """Sign in through the login page; return the client, or None if login failed."""
    client = Client()
    client.post(reverse("accounts:login"), {"username": user.email, "password": password})
    return client if "_auth_user_id" in client.session else None


def management_urls(target):
    """Every route under /manage/, so new routes are covered automatically."""
    for pattern in admin_urls.urlpatterns:
        args = [target.pk] if "<int:pk>" in str(pattern.pattern) else []
        yield reverse(f"administration:{pattern.name}", args=args)


class TCAuth02RoleRestrictedScreensTest(TestCase):
    """AC-002: a Student cannot open a management screen restricted to another role."""

    def test_only_administrator_can_open_management_screens(self):
        admin = make_user("admin", User.Role.ADMINISTRATOR)
        screens = [reverse("administration:user_list"), reverse("administration:user_create")]
        for role, expected in [
            (User.Role.STUDENT, 403),
            (User.Role.INSTRUCTOR, 403),
            (User.Role.ADMINISTRATOR, 200),
        ]:
            client = log_in(admin if role == User.Role.ADMINISTRATOR else make_user(role, role))
            for url in screens:
                with self.subTest(role=role, url=url):
                    self.assertEqual(client.get(url).status_code, expected)


class TCAuth04AccountLifecycleTest(TestCase):
    """AC-004: a deactivated account cannot log in; a role change takes effect on next login."""

    def setUp(self):
        self.admin_client = log_in(make_user("admin", User.Role.ADMINISTRATOR))

    def act(self, name, user, data=None):
        url = reverse(f"administration:{name}", args=[user.pk])
        self.assertEqual(self.admin_client.post(url, data or {}).status_code, 302)

    def test_deactivated_account_cannot_log_in_until_reactivated(self):
        student = make_user("student")
        student_client = log_in(student)
        self.act("user_deactivate", student)

        dashboard = student_client.get(reverse("accounts:dashboard"))
        self.assertIn(reverse("accounts:login"), dashboard["Location"])
        self.assertIsNone(log_in(student))

        self.act("user_reactivate", student)
        self.assertIsNotNone(log_in(student))

    def test_role_change_takes_effect_on_next_login(self):
        student = make_user("student")
        student_client = log_in(student)
        self.act("user_role", student, {"role": User.Role.INSTRUCTOR})

        # The old session has ended, so the user must log in again.
        response = student_client.get(reverse("accounts:dashboard"))
        self.assertIn(reverse("accounts:login"), response["Location"])

        new_client = log_in(student)
        response = new_client.get(reverse("accounts:dashboard"))
        self.assertRedirects(
            response, reverse("accounts:instructor_dashboard"), fetch_redirect_response=False
        )
        self.assertEqual(new_client.get(reverse("accounts:instructor_dashboard")).status_code, 200)
        self.assertEqual(new_client.get(reverse("accounts:student_dashboard")).status_code, 403)

    def test_created_user_can_log_in_with_assigned_role(self):
        response = self.admin_client.post(reverse("administration:user_create"), {
            "username": "ivy", "email": "ivy@example.com", "first_name": "", "last_name": "",
            "role": User.Role.INSTRUCTOR, "password1": PASSWORD, "password2": PASSWORD,
        })
        self.assertEqual(response.status_code, 302)
        client = log_in(User.objects.get(username="ivy"))
        self.assertEqual(client.get(reverse("accounts:instructor_dashboard")).status_code, 200)


class TCSec04DenyWithoutPermissionTest(TestCase):
    """AC-SR-003: a role without explicit permission gets HTTP 403."""

    def test_student_calling_instructor_only_endpoint_gets_403(self):
        client = log_in(make_user("student"))
        self.assertEqual(client.get(reverse("accounts:instructor_dashboard")).status_code, 403)

    def test_non_administrators_get_403_on_every_management_route(self):
        target = make_user("target")
        for role in (User.Role.STUDENT, User.Role.INSTRUCTOR):
            client = log_in(make_user(role, role))
            for url in management_urls(target):
                with self.subTest(role=role, url=url):
                    self.assertEqual(client.post(url, {"role": role}).status_code, 403)
                    self.assertEqual(client.get(url).status_code, 403)
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertEqual(target.role, User.Role.STUDENT)
