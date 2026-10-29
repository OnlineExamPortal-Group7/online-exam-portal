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


class UserListViewTest(TestCase):  # OEP-F-002, OEP-SR-003
    def setUp(self):
        self.url = reverse("administration:user_list")
        self.admin = make_user("admin", role=User.Role.ADMINISTRATOR)
        self.inactive = make_user("gone", is_active=False)

    def test_administrator_sees_all_users_with_role_and_status(self):
        self.client.login(username=self.admin.email, password=PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "administration/user_list.html")
        self.assertContains(response, "admin@example.com")
        self.assertContains(response, "gone@example.com")
        self.assertContains(response, "Administrator")
        self.assertContains(response, "Deactivated")

    def test_other_roles_get_403(self):
        for role in (User.Role.STUDENT, User.Role.INSTRUCTOR):
            user = make_user(role, role=role)
            self.client.login(username=user.email, password=PASSWORD)
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])


class UserCreateViewTest(TestCase):  # OEP-F-004
    def setUp(self):
        self.url = reverse("administration:user_create")
        self.admin = make_user("admin", role=User.Role.ADMINISTRATOR)

    def form_data(self, **overrides):
        data = {
            "username": "newbie", "email": "Newbie@Example.com",
            "first_name": "New", "last_name": "User", "role": User.Role.INSTRUCTOR,
            "password1": PASSWORD, "password2": PASSWORD,
        }
        return {**data, **overrides}

    def sign_in(self, user):
        self.client.login(username=user.email, password=PASSWORD)

    def test_administrator_sees_the_form(self):
        self.sign_in(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="role"')

    def test_administrator_creates_user_with_role(self):
        self.sign_in(self.admin)
        response = self.client.post(self.url, self.form_data(), follow=True)
        self.assertRedirects(response, reverse("administration:user_list"))
        self.assertContains(response, "Created newbie (Instructor).")
        user = User.objects.get(username="newbie")
        self.assertEqual(user.role, User.Role.INSTRUCTOR)
        self.assertEqual(user.email, "newbie@example.com")
        self.assertTrue(user.check_password(PASSWORD))

    def test_duplicate_email_is_rejected_ignoring_case(self):
        self.sign_in(self.admin)
        response = self.client.post(self.url, self.form_data(email="ADMIN@example.com"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_weak_or_mismatched_password_is_rejected(self):
        self.sign_in(self.admin)
        for passwords in (("12345678", "12345678"), (PASSWORD, PASSWORD + "x")):
            with self.subTest(passwords=passwords):
                data = self.form_data(password1=passwords[0], password2=passwords[1])
                self.assertEqual(self.client.post(self.url, data).status_code, 200)
                self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_other_roles_get_403_and_nothing_is_created(self):
        for role in (User.Role.STUDENT, User.Role.INSTRUCTOR):
            self.sign_in(make_user(role, role=role))
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.post(self.url, self.form_data()).status_code, 403)
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(self.url, self.form_data())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
        self.assertFalse(User.objects.filter(username="newbie").exists())


class UserActionViewTest(TestCase):  # OEP-F-004
    def setUp(self):
        self.admin = make_user("admin", role=User.Role.ADMINISTRATOR)
        self.student = make_user("student")
        self.client.login(username=self.admin.email, password=PASSWORD)

    def url(self, name, user):
        return reverse(f"administration:{name}", args=[user.pk])

    def test_deactivate_and_reactivate(self):
        response = self.client.post(self.url("user_deactivate", self.student), follow=True)
        self.assertRedirects(response, reverse("administration:user_list"))
        self.assertContains(response, "Deactivated student.")
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)

        response = self.client.post(self.url("user_reactivate", self.student), follow=True)
        self.assertContains(response, "Reactivated student.")
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

    def test_change_role(self):
        response = self.client.post(
            self.url("user_role", self.student), {"role": User.Role.INSTRUCTOR}, follow=True
        )
        self.assertContains(response, "student is now Instructor.")
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.INSTRUCTOR)

    def test_invalid_role_shows_error(self):
        response = self.client.post(
            self.url("user_role", self.student), {"role": "superuser"}, follow=True
        )
        self.assertContains(response, "Choose a valid role.")
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.STUDENT)

    def test_self_deactivate_and_self_demote_show_errors(self):
        response = self.client.post(self.url("user_deactivate", self.admin), follow=True)
        self.assertContains(response, "You cannot deactivate your own account.")
        response = self.client.post(
            self.url("user_role", self.admin), {"role": User.Role.STUDENT}, follow=True
        )
        self.assertContains(response, "You cannot remove your own Administrator role.")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertEqual(self.admin.role, User.Role.ADMINISTRATOR)

    def test_get_is_not_allowed(self):
        for name in ("user_deactivate", "user_reactivate", "user_role"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name, self.student)).status_code, 405)
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

    def test_unknown_user_is_404(self):
        response = self.client.post(reverse("administration:user_deactivate", args=[9999]))
        self.assertEqual(response.status_code, 404)

    def test_post_without_csrf_token_is_rejected(self):  # OEP-SR-005
        client = Client(enforce_csrf_checks=True)
        client.login(username=self.admin.email, password=PASSWORD)
        self.assertEqual(client.post(self.url("user_deactivate", self.student)).status_code, 403)
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)

    def test_other_roles_get_403_and_nothing_changes(self):
        instructor = make_user("teacher", role=User.Role.INSTRUCTOR)
        for user in (self.student, instructor):
            client = Client()
            client.login(username=user.email, password=PASSWORD)
            target = self.admin
            with self.subTest(role=user.role):
                self.assertEqual(client.post(self.url("user_deactivate", target)).status_code, 403)
                response = client.post(self.url("user_role", target), {"role": User.Role.STUDENT})
                self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertEqual(self.admin.role, User.Role.ADMINISTRATOR)

    def test_list_page_shows_action_buttons(self):
        response = self.client.get(reverse("administration:user_list"))
        self.assertContains(response, self.url("user_deactivate", self.student))
        self.assertContains(response, self.url("user_role", self.student))


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
