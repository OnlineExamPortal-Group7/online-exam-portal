from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User

from . import services
from .models import AuditLog


PASSWORD = "Str0ng-pass-123"


def make_user(username, role=User.Role.STUDENT, **kwargs):
    return User.objects.create_user(
        username, f"{username}@example.com", PASSWORD, role=role, **kwargs
    )


class AuditLogServiceTest(TestCase):
    def test_successful_user_deactivation_creates_audit_record(self):
        administrator = make_user("audit_admin", role=User.Role.ADMINISTRATOR)
        student = make_user("audit_student")

        services.deactivate(administrator, student)

        log = AuditLog.objects.get(action="user_deactivated")
        self.assertEqual(log.actor, administrator)
        self.assertEqual(log.actor_name, administrator.username)
        self.assertEqual(log.target_type, "User")
        self.assertEqual(log.target_id, str(student.pk))
        self.assertEqual(log.target_name, str(student))
        self.assertEqual(log.details, {})


class AuditLogListViewTest(TestCase):
    def setUp(self):
        self.url = reverse("administration:audit_log_list")
        self.administrator = make_user("audit_view_admin", role=User.Role.ADMINISTRATOR)
        self.actor = make_user("audit_actor")
        self.log = AuditLog.objects.create(
            actor=self.actor,
            actor_name=self.actor.username,
            action="sample_action",
            target_type="User",
            target_id="42",
            target_name="sample-user",
            details={"reason": "test"},
        )

    def test_administrator_can_view_audit_history(self):
        self.client.login(username=self.administrator.email, password=PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "administration/audit_log_list.html")
        self.assertContains(response, "sample_action")
        self.assertContains(response, "sample-user")
        self.assertContains(response, "audit_actor")

    def test_student_and_instructor_are_forbidden(self):
        for role in (User.Role.STUDENT, User.Role.INSTRUCTOR):
            user = make_user(f"audit_{role}", role=role)
            self.client.force_login(user)
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_newest_audit_records_are_shown_first(self):
        AuditLog.objects.create(
            actor=self.actor,
            actor_name=self.actor.username,
            action="newer_action",
            target_type="User",
            target_id="43",
            target_name="newer-user",
        )
        self.client.force_login(self.administrator)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            response.content.index(b"newer_action"),
            response.content.index(b"sample_action"),
        )
