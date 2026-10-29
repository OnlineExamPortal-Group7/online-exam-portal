from unittest import mock

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase

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

    @mock.patch.object(services, "audit_hook")
    def test_audit_hook_is_called_for_each_change(self, hook):
        services.deactivate(self.admin, self.student)
        services.change_role(self.admin, self.student, User.Role.INSTRUCTOR)
        hook.assert_any_call("user_deactivated", self.admin, self.student)
        hook.assert_any_call(
            "role_changed", self.admin, self.student,
            old_role=User.Role.STUDENT, new_role=User.Role.INSTRUCTOR,
        )
