
"""Dashboards show scores only after publication, and link instructors to results (OEP-F-031)."""
import re

from django.test import TestCase
from django.urls import reverse
from django.utils.html import strip_tags

from .services import publish_results
from .test_services import ResultsTestData


STUDENT_DASHBOARD = reverse("accounts:student_dashboard")


def normalized_text(response):
    """Remove HTML tags and normalize whitespace for score assertions."""
    return re.sub(r"\s+", " ", strip_tags(response.content.decode()))


class StudentDashboardResultTest(ResultsTestData, TestCase):

    def test_score_is_hidden_until_results_are_published(self):
        self.make_attempt(
            self.ended_exam,
            self.student,
            self.correct,
        )

        self.client.force_login(self.student)

        response = self.client.get(STUDENT_DASHBOARD)

        self.assertContains(
            response,
            "Result: Not published yet",
        )
        self.assertNotIn(
            "Score:",
            normalized_text(response),
        )

    def test_score_is_shown_after_results_are_published(self):
        self.make_attempt(
            self.ended_exam,
            self.student,
            self.correct,
        )

        publish_results(
            self.ended_exam,
            self.instructor,
        )

        self.client.force_login(self.student)

        response = self.client.get(STUDENT_DASHBOARD)
        response_text = normalized_text(response)

        self.assertIn("2 / 2", response_text)
        self.assertIn("(100.0%)", response_text)
        self.assertNotContains(
            response,
            "Result: Not published yet",
        )

    def test_student_sees_only_own_score(self):
        self.make_attempt(
            self.ended_exam,
            self.student,
            self.wrong,
        )

        self.make_attempt(
            self.ended_exam,
            self.student2,
            self.correct,
        )

        publish_results(
            self.ended_exam,
            self.instructor,
        )

        self.client.force_login(self.student)

        response = self.client.get(STUDENT_DASHBOARD)
        response_text = normalized_text(response)

        self.assertIn("0 / 2", response_text)
        self.assertNotIn("2 / 2", response_text)

    def test_no_result_line_without_an_attempt(self):
        self.client.force_login(self.student)

        response = self.client.get(STUDENT_DASHBOARD)
        response_text = normalized_text(response)

        self.assertNotIn(
            "Result: Not published yet",
            response_text,
        )
        self.assertNotIn(
            "Score:",
            response_text,
        )


class InstructorDashboardLinkTest(ResultsTestData, TestCase):

    def test_instructor_dashboard_links_to_exam_results(self):
        self.client.force_login(self.instructor)

        response = self.client.get(
            reverse("accounts:instructor_dashboard")
        )

        self.assertContains(
            response,
            reverse("results:exam_list"),
        )

    def test_other_dashboards_do_not_link_to_exam_results(self):
        for user, url in (
            (self.student, STUDENT_DASHBOARD),
            (
                self.admin,
                reverse("accounts:admin_dashboard"),
            ),
        ):
            self.client.force_login(user)

            with self.subTest(user=user.username):
                self.assertNotContains(
                    self.client.get(url),
                    reverse("results:exam_list"),
                )
