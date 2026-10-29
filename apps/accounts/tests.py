from django.test import TestCase
from django.urls import reverse

from .models import User

PASSWORD = "Str0ng-pass-123"


def make_user(username, role=User.Role.STUDENT, **kwargs):
    return User.objects.create_user(
        username, f"{username}@example.com", PASSWORD, role=role, **kwargs
    )


class UserModelTest(TestCase):
    def test_default_role_is_student(self):
        self.assertEqual(make_user("s1").role, User.Role.STUDENT)

    def test_password_is_hashed_with_pbkdf2(self):  # OEP-SR-002 / TC-Sec-03
        self.assertTrue(make_user("s2").password.startswith("pbkdf2_sha256$"))

    def test_email_is_stored_lower_case(self):
        user = User.objects.create_user("a", "Mixed@Example.COM", PASSWORD)
        self.assertEqual(user.email, "mixed@example.com")

    def test_superuser_is_administrator(self):
        admin = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        self.assertEqual(admin.role, User.Role.ADMINISTRATOR)


class HomePageTest(TestCase):
    def test_home_page_loads_for_anonymous_user(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_home_redirects_signed_in_user_to_dashboard(self):
        make_user("s3")
        self.client.login(username="s3@example.com", password=PASSWORD)
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("accounts:dashboard"), fetch_redirect_response=False)


class LoginTest(TestCase):  # OEP-F-001
    def setUp(self):
        self.user = make_user("alice")
        self.url = reverse("accounts:login")

    def post(self, identifier, password):
        return self.client.post(self.url, {"username": identifier, "password": password})

    def test_login_with_email(self):
        response = self.post("alice@example.com", PASSWORD)
        self.assertRedirects(response, reverse("accounts:dashboard"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_email_is_case_insensitive(self):
        self.post("ALICE@Example.com", PASSWORD)
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_password_is_rejected(self):
        response = self.post("alice@example.com", "wrong")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_email_is_rejected(self):
        self.post("nobody@example.com", PASSWORD)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivated_account_cannot_log_in(self):  # OEP-F-004
        self.user.is_active = False
        self.user.save()
        self.post("alice@example.com", PASSWORD)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_ends_session(self):
        self.post("alice@example.com", PASSWORD)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class RoleAccessTest(TestCase):  # OEP-F-002, OEP-SR-003
    URLS = {
        User.Role.STUDENT: "accounts:student_dashboard",
        User.Role.INSTRUCTOR: "accounts:instructor_dashboard",
        User.Role.ADMINISTRATOR: "accounts:admin_dashboard",
    }

    def setUp(self):
        self.users = {role: make_user(role, role=role) for role in self.URLS}

    def sign_in(self, role):
        self.client.login(username=self.users[role].email, password=PASSWORD)

    def test_anonymous_is_redirected_to_login(self):
        for name in self.URLS.values():
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("accounts:login"), response["Location"])

    def test_each_role_sees_only_its_own_dashboard(self):
        # AC-002, AC-SR-003 / TC-Auth-02, TC-Sec-04
        for role in self.URLS:
            self.client.logout()
            self.sign_in(role)
            for other_role, name in self.URLS.items():
                expected = 200 if other_role == role else 403
                with self.subTest(role=role, page=other_role):
                    self.assertEqual(self.client.get(reverse(name)).status_code, expected)

    def test_dashboard_redirects_by_role(self):
        for role, name in self.URLS.items():
            self.client.logout()
            self.sign_in(role)
            response = self.client.get(reverse("accounts:dashboard"))
            self.assertRedirects(response, reverse(name), fetch_redirect_response=False)
