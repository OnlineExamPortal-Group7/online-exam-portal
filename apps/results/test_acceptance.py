
"""TC-Eval-02 / AC-031 (OEP-F-031): results are visible to students only after the
instructor publishes them.

The test drives the real pages with real logins: the student takes and submits
the exam, cannot see a score, the instructor reviews and publishes, then the
student sees it.
"""
import re
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from apps.accounts.models import User
from apps.administration.models import Course, Enrollment
from apps.administration.test_acceptance import log_in, make_user
from apps.exams.models import (
    Choice,
    Exam,
    ExamAttempt,
    ExamQuestion,
    Question,
)

from .models import ResultPublication


STUDENT_DASHBOARD = reverse("accounts:student_dashboard")


def normalized_text(response):
    """Remove HTML tags and normalize whitespace for score assertions."""
    return re.sub(r"\s+", " ", strip_tags(response.content.decode()))


class TCEval02ResultPublicationTest(TestCase):
    """AC-031: a student sees their result only after the instructor publishes it."""

    def setUp(self):
        self.teacher = make_user("teacher", User.Role.INSTRUCTOR)
        self.student = make_user("student")

        course = Course.objects.create(
            code="CN101",
            name="Networks",
            instructor=self.teacher,
        )
        Enrollment.objects.create(
            student=self.student,
            course=course,
        )

        self.question = Question.objects.create(
            course=course,
            text="What is TCP?",
            topic="Transport",
            marks=4,
            created_by=self.teacher,
        )

        self.correct = Choice.objects.create(
            question=self.question,
            text="A protocol",
            is_correct=True,
        )
        Choice.objects.create(
            question=self.question,
            text="A cable",
        )

        now = timezone.now()

        self.exam = Exam.objects.create(
            course=course,
            title="Networks quiz",
            created_by=self.teacher,
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(minutes=50),
            duration_minutes=30,
            total_marks=4,
            status=Exam.Status.PUBLISHED,
        )

        ExamQuestion.objects.create(
            exam=self.exam,
            question=self.question,
            position=1,
        )

    def take_and_submit_exam(self, client):
        client.post(
            reverse("exams:start_attempt", args=[self.exam.pk])
        )

        attempt = ExamAttempt.objects.get(
            exam=self.exam,
            student=self.student,
        )

        client.post(
            reverse("exams:save_answer", args=[attempt.pk]),
            {
                "question_id": self.question.pk,
                "choice_id": self.correct.pk,
            },
        )

        client.post(
            reverse("exams:submit_attempt", args=[attempt.pk])
        )

        attempt.refresh_from_db()

        self.assertEqual(
            attempt.status,
            ExamAttempt.Status.SUBMITTED,
        )

    def test_result_is_visible_only_after_instructor_publishes(self):
        student_client = log_in(self.student)
        teacher_client = log_in(self.teacher)

        review_url = reverse(
            "results:exam_review",
            args=[self.exam.pk],
        )
        publish_url = reverse(
            "results:publish",
            args=[self.exam.pk],
        )

        self.take_and_submit_exam(student_client)

        # The result exists, but the student cannot see it before publication.
        dashboard = student_client.get(STUDENT_DASHBOARD)

        self.assertContains(
            dashboard,
            "Result: Not published yet",
        )
        self.assertNotIn("4 / 4", normalized_text(dashboard))

        # The instructor can review the score while the exam is open.
        teacher_dashboard = teacher_client.get(review_url)
        self.assertIn("4 / 4", normalized_text(teacher_dashboard))

        # Publishing before the exam ends must fail.
        teacher_client.post(publish_url)

        self.assertFalse(
            ResultPublication.objects.filter(exam=self.exam).exists()
        )

        dashboard = student_client.get(STUDENT_DASHBOARD)
        self.assertNotIn("4 / 4", normalized_text(dashboard))

        # After the exam window closes, the instructor can publish.
        later = self.exam.end_time + timedelta(minutes=1)

        with patch("django.utils.timezone.now", return_value=later):
            response = teacher_client.post(
                publish_url,
                follow=True,
            )

            self.assertContains(response, "Results published.")

            dashboard = student_client.get(STUDENT_DASHBOARD)
            dashboard_text = normalized_text(dashboard)

            self.assertIn("4 / 4", dashboard_text)
            self.assertIn("(100.0%)", dashboard_text)
            self.assertNotContains(
                dashboard,
                "Result: Not published yet",
            )

    def test_only_the_instructor_can_use_instructor_results_pages(self):
        """Student and admin users cannot access instructor-only pages."""

        closed = timezone.now() - timedelta(minutes=1)

        Exam.objects.filter(pk=self.exam.pk).update(
            start_time=closed - timedelta(hours=1),
            end_time=closed,
        )

        admin = make_user(
            "admin",
            User.Role.ADMINISTRATOR,
        )

        instructor_urls = (
            reverse("results:exam_list"),
            reverse("results:exam_review", args=[self.exam.pk]),
            reverse("results:publish", args=[self.exam.pk]),
        )

        for user in (self.student, admin):
            client = log_in(user)

            for url in instructor_urls:
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(
                        client.get(url).status_code,
                        403,
                    )
                    self.assertEqual(
                        client.post(url).status_code,
                        403,
                    )

        self.assertFalse(
            ResultPublication.objects.filter(exam=self.exam).exists()
        )

    def test_student_can_access_own_results_and_history_pages(self):
        """Issue #19: students can access their own results and history."""

        client = log_in(self.student)

        student_urls = (
            reverse("results:student_results"),
            reverse("results:student_history"),
        )

        for url in student_urls:
            with self.subTest(url=url):
                self.assertEqual(
                    client.get(url).status_code,
                    200,
                )

    def test_administrator_cannot_access_student_results_pages(self):
        """Only students can access the student-facing results pages."""

        admin = make_user(
            "admin",
            User.Role.ADMINISTRATOR,
        )
        client = log_in(admin)

        student_urls = (
            reverse("results:student_results"),
            reverse("results:student_history"),
            reverse("results:student_result_detail", args=[1]),
        )

        for url in student_urls:
            with self.subTest(url=url):
                self.assertEqual(
                    client.get(url).status_code,
                    403,
                )
