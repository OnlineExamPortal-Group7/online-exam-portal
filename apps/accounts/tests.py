from django.test import TestCase
from django.urls import reverse

from .models import User


class UserModelTest(TestCase):
    def test_default_role_is_student(self):
        user = User.objects.create_user("s1", "s1@example.com", "pw-12345-Aa")
        self.assertEqual(user.role, User.Role.STUDENT)

    def test_password_is_hashed_with_pbkdf2(self):  # OEP-SR-002
        user = User.objects.create_user("s2", "s2@example.com", "pw-12345-Aa")
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))


class HomePageTest(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
