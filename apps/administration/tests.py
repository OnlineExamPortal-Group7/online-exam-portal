from unittest import mock

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.sessions.models import Session
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User

from . import services

PASSWORD = "Str0ng-pass-123"


def make_user(username, role=User.Role.STUDENT, **kwargs):
    return User.objects.create_user(
        username, f"{username}@example.com", PASSWORD, role=role, **kwargs
    )


class AdministrationAppSmokeTest(SimpleTestCase):
    def test_app_is_installed(self):
        self.assertTrue(apps.is_installed("apps.administration"))


class UserServiceTest(TestCase):  # OEP-F-004
    def setUp(self):
        self.admin = make_user("admin", role=User.Role.ADMINISTRATOR)
        self.student = make_user("student")

    def test_create_user_with_role(self):
        user = services.create_user(
            self.admin, username="ivy", email="Ivy@Example.com",
            password=PASSWORD, role=User.Role.INSTRUCTOR,
        )
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.INSTRUCTOR)
        self.assertEqual(user.email, "ivy@example.com")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertTrue(user.is_active)

    def test_create_user_rejects_unknown_role(self):
        with self.assertRaises(ValidationError):
            services.create_user(
                self.admin, username="x", email="x@example.com", password=PASSWORD, role="admin"
            )
        self.assertFalse(User.objects.filter(username="x").exists())

    def test_deactivate_and_reactivate(self):
        services.deactivate(self.admin, self.student)
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)
        services.reactivate(self.admin, self.student)
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

    def test_change_role(self):
        services.change_role(self.admin, self.student, User.Role.INSTRUCTOR)
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.INSTRUCTOR)

    def test_change_role_rejects_unknown_role(self):
        with self.assertRaises(ValidationError):
            services.change_role(self.admin, self.student, "superuser")
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.STUDENT)

    def test_only_administrators_can_make_changes(self):  # OEP-SR-003
        instructor = make_user("teacher", role=User.Role.INSTRUCTOR)
        calls = [
            lambda: services.create_user(
                instructor, username="y", email="y@example.com",
                password=PASSWORD, role=User.Role.STUDENT,
            ),
            lambda: services.deactivate(instructor, self.student),
            lambda: services.reactivate(instructor, self.student),
            lambda: services.change_role(instructor, self.student, User.Role.ADMINISTRATOR),
        ]
        for call in calls:
            with self.assertRaises(PermissionDenied):
                call()
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)
        self.assertEqual(self.student.role, User.Role.STUDENT)

    def test_admin_cannot_deactivate_self(self):
        with self.assertRaisesMessage(ValidationError, "deactivate your own account"):
            services.deactivate(self.admin, self.admin)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_cannot_demote_self(self):
        for role in (User.Role.STUDENT, User.Role.INSTRUCTOR):
            with self.subTest(role=role):
                with self.assertRaisesMessage(ValidationError, "own Administrator role"):
                    services.change_role(self.admin, self.admin, role)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMINISTRATOR)

    def test_admin_can_deactivate_and_demote_another_admin(self):
        other = make_user("admin2", role=User.Role.ADMINISTRATOR)
        services.change_role(self.admin, other, User.Role.INSTRUCTOR)
        services.deactivate(self.admin, other)
        other.refresh_from_db()
        self.assertEqual(other.role, User.Role.INSTRUCTOR)
        self.assertFalse(other.is_active)

    @mock.patch.object(services, "audit_hook")
    def test_refused_change_is_not_audited(self, hook):
        with self.assertRaises(ValidationError):
            services.deactivate(self.admin, self.admin)
        hook.assert_not_called()

    @mock.patch.object(services, "audit_hook")
    def test_audit_hook_is_called_for_each_change(self, hook):
        services.deactivate(self.admin, self.student)
        services.change_role(self.admin, self.student, User.Role.INSTRUCTOR)
        hook.assert_any_call("user_deactivated", self.admin, self.student)
        hook.assert_any_call(
            "role_changed", self.admin, self.student,
            old_role=User.Role.STUDENT, new_role=User.Role.INSTRUCTOR,
        )


class EndSessionsTest(TestCase):  # OEP-F-004 / AC-004
    def setUp(self):
        self.admin = make_user("admin", role=User.Role.ADMINISTRATOR)
        self.student = make_user("student")
        self.other = make_user("other")
        self.student_client = self.signed_in(self.student)
        self.other_client = self.signed_in(self.other)

    def signed_in(self, user):
        client = Client()
        self.assertTrue(client.login(username=user.email, password=PASSWORD))
        return client

    def assertSignedOut(self, client):
        response = client.get(reverse("accounts:student_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def assertStillSignedIn(self, client):
        self.assertEqual(client.get(reverse("accounts:student_dashboard")).status_code, 200)

    def test_deactivation_ends_the_users_sessions(self):
        services.deactivate(self.admin, self.student)
        self.assertSignedOut(self.student_client)
        self.assertStillSignedIn(self.other_client)

    def test_role_change_ends_the_users_sessions(self):
        services.change_role(self.admin, self.student, User.Role.INSTRUCTOR)
        self.assertSignedOut(self.student_client)
        self.assertStillSignedIn(self.other_client)

    def test_new_role_applies_on_next_login(self):
        services.change_role(self.admin, self.student, User.Role.INSTRUCTOR)
        client = self.signed_in(self.student)
        response = client.get(reverse("accounts:dashboard"))
        self.assertRedirects(
            response, reverse("accounts:instructor_dashboard"), fetch_redirect_response=False
        )

    def test_setting_the_same_role_keeps_the_session(self):
        services.change_role(self.admin, self.student, User.Role.STUDENT)
        self.assertStillSignedIn(self.student_client)

    def test_only_the_target_users_session_rows_are_deleted(self):
        before = Session.objects.count()
        services.deactivate(self.admin, self.student)
        self.assertEqual(Session.objects.count(), before - 1)
