
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User

PASSWORD = "Str0ng-pass-123"


def make_user(username, role=User.Role.STUDENT, **kwargs):
    return User.objects.create_user(
        username,
        f"{username}@example.com",
        PASSWORD,
        role=role,
        **kwargs,
    )


class UserModelTest(TestCase):
    def test_default_role_is_student(self):
        self.assertEqual(make_user("s1").role, User.Role.STUDENT)

    def test_password_is_hashed_with_pbkdf2(self):
        self.assertTrue(
            make_user("s2").password.startswith("pbkdf2_sha256$")
        )

    def test_email_is_stored_lower_case(self):
        user = User.objects.create_user(
            "a", "Mixed@Example.COM", PASSWORD
        )
        self.assertEqual(user.email, "mixed@example.com")

    def test_superuser_is_administrator(self):
        admin = User.objects.create_superuser(
            "root", "root@example.com", PASSWORD
        )
        self.assertEqual(admin.role, User.Role.ADMINISTRATOR)


class HomePageTest(TestCase):
    def test_home_page_loads_for_anonymous_user(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_home_redirects_signed_in_user_to_dashboard(self):
        make_user("s3")
        self.client.login(username="s3@example.com", password=PASSWORD)
        response = self.client.get(reverse("home"))
        self.assertRedirects(
            response,
            reverse("accounts:dashboard"),
            fetch_redirect_response=False,
        )


class LoginTest(TestCase):
    def setUp(self):
        self.user = make_user("alice")
        self.url = reverse("accounts:login")

    def post(self, identifier, password):
        return self.client.post(
            self.url,
            {"username": identifier, "password": password},
        )

    def test_login_with_email(self):
        response = self.post("alice@example.com", PASSWORD)
        self.assertRedirects(
            response,
            reverse("accounts:dashboard"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            int(self.client.session["_auth_user_id"]), self.user.pk
        )

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

    def test_deactivated_account_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.post("alice@example.com", PASSWORD)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_ends_session(self):
        self.post("alice@example.com", PASSWORD)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class RoleAccessTest(TestCase):
    URLS = {
        User.Role.STUDENT: "accounts:student_dashboard",
        User.Role.INSTRUCTOR: "accounts:instructor_dashboard",
        User.Role.ADMINISTRATOR: "accounts:admin_dashboard",
    }

    def setUp(self):
        self.users = {
            role: make_user(role, role=role) for role in self.URLS
        }

    def sign_in(self, role):
        self.client.login(
            username=self.users[role].email,
            password=PASSWORD,
        )

    def test_anonymous_is_redirected_to_login(self):
        for name in self.URLS.values():
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(
                reverse("accounts:login"), response["Location"]
            )

    def test_each_role_sees_only_its_own_dashboard(self):
        for role in self.URLS:
            self.client.logout()
            self.sign_in(role)
            for other_role, name in self.URLS.items():
                expected = 200 if other_role == role else 403
                with self.subTest(role=role, page=other_role):
                    self.assertEqual(
                        self.client.get(reverse(name)).status_code,
                        expected,
                    )

    def test_dashboard_redirects_by_role(self):
        for role, name in self.URLS.items():
            self.client.logout()
            self.sign_in(role)
            response = self.client.get(
                reverse("accounts:dashboard")
            )
            self.assertRedirects(
                response,
                reverse(name),
                fetch_redirect_response=False,
            )


class PasswordResetTest(TestCase):
    def setUp(self):
        self.user = make_user("resetuser")
        self.url = reverse("accounts:password_reset")

    def test_password_reset_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_password_reset_sends_email(self):
        response = self.client.post(
            self.url, {"email": self.user.email}
        )
        self.assertRedirects(
            response, reverse("accounts:password_reset_done")
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)

    def test_valid_reset_link_allows_password_change(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": uid, "token": token},
        )

        # Follow Django's redirect from the original token URL to
        # the URL containing its temporary token.
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)

        # Use the final redirected URL for the password-change POST.
        response = self.client.post(
            response.request["PATH_INFO"],
            {
                "new_password1": "New-Strong-pass-456!",
                "new_password2": "New-Strong-pass-456!",
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.check_password("New-Strong-pass-456!")
        )
        self.assertEqual(response.status_code, 200)

    def test_unknown_email_does_not_reveal_account_existence(self):
        response = self.client.post(
            self.url, {"email": "unknown@example.com"}
        )
        self.assertRedirects(
            response, reverse("accounts:password_reset_done")
        )
        self.assertEqual(len(mail.outbox), 0)

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import User


class AccountLockoutTest(TestCase):
    def setUp(self):
        cache.clear()
        self.password = "StrongTestPass123!"
        self.user = User.objects.create_user(
            username="lockoutstudent",
            email="lockoutstudent@example.com",
            password=self.password,
        )
        self.login_url = reverse("accounts:login")

    def tearDown(self):
        cache.clear()

    def test_failed_attempts_are_recorded(self):
        for _ in range(3):
            self.client.post(
                self.login_url,
                {
                    "username": self.user.email,
                    "password": "WrongPassword123!",
                },
            )

        self.assertEqual(cache.get(f"accounts:login-lockout:user:{self.user.pk}"), 3)

    def test_account_is_locked_after_five_failed_attempts(self):
        for _ in range(5):
            self.client.post(
                self.login_url,
                {
                    "username": self.user.email,
                    "password": "WrongPassword123!",
                },
            )

        self.assertGreaterEqual(
            cache.get(f"accounts:login-lockout:user:{self.user.pk}", 0),
            5,
        )

        response = self.client.post(
            self.login_url,
            {
                "username": self.user.email,
                "password": self.password,
            },
        )

        self.assertNotEqual(response.status_code, 302)

    def test_successful_login_clears_failed_attempts(self):
        cache.set(
            f"accounts:login-lockout:user:{self.user.pk}",
            2,
            timeout=900,
        )

        response = self.client.post(
            self.login_url,
            {
                "username": self.user.email,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(
            cache.get(f"accounts:login-lockout:user:{self.user.pk}")
        )
