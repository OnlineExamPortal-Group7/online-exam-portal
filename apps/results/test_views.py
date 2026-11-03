"""Instructor result review pages (OEP-F-031)."""
from django.test import TestCase
from django.urls import reverse

from apps.exams.models import ExamAttempt

from .services import publish_results
from .test_services import ResultsTestData


class ExamResultListViewTest(ResultsTestData, TestCase):
    url = reverse("results:exam_list")

    def test_instructor_sees_own_exams_with_publication_status(self):
        publish_results(self.ended_exam, self.instructor)
        self.client.force_login(self.instructor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["exams"]), [self.open_exam, self.ended_exam]
        )
        self.assertContains(response, "Published")
        self.assertContains(response, "Exam still open")

    def test_other_instructor_sees_no_exams(self):
        self.client.force_login(self.other_instructor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.ended_exam.title)

    def test_students_and_administrators_get_403(self):
        for user in (self.student, self.admin):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}")


class ExamResultReviewViewTest(ResultsTestData, TestCase):
    def review_url(self, exam):
        return reverse("results:exam_review", args=[exam.pk])

    def test_review_lists_every_enrolled_student_with_score(self):
        self.make_attempt(self.ended_exam, self.student, self.correct)
        self.client.force_login(self.instructor)

        response = self.client.get(self.review_url(self.ended_exam))

        self.assertEqual(response.status_code, 200)
        rows = {row["student"]: row for row in response.context["rows"]}
        self.assertEqual(set(rows), {self.student, self.student2})
        self.assertEqual(rows[self.student]["result"].score, 2)
        self.assertIsNone(rows[self.student2]["attempt"])
        self.assertContains(response, "2 / 2")
        self.assertContains(response, "Not attempted")
        self.assertContains(response, "Not published")
        self.assertEqual(response.context["average_percentage"], 100.0)

    def test_review_scores_attempts_left_in_progress(self):
        attempt = self.make_attempt(self.ended_exam, self.student, self.correct, submitted=False)
        self.client.force_login(self.instructor)

        response = self.client.get(self.review_url(self.ended_exam))

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)
        self.assertContains(response, "Timed Out")
        self.assertContains(response, "2 / 2")

    def test_review_shows_open_exam_cannot_be_published_yet(self):
        self.client.force_login(self.instructor)

        response = self.client.get(self.review_url(self.open_exam))

        self.assertContains(response, "The exam is still open.")

    def test_review_shows_publication(self):
        publish_results(self.ended_exam, self.instructor)
        self.client.force_login(self.instructor)

        response = self.client.get(self.review_url(self.ended_exam))

        self.assertContains(response, "Students can see their scores.")

    def test_other_instructor_gets_404(self):
        self.client.force_login(self.other_instructor)
        response = self.client.get(self.review_url(self.ended_exam))
        self.assertEqual(response.status_code, 404)

    def test_students_and_administrators_get_403(self):
        for user in (self.student, self.admin):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                response = self.client.get(self.review_url(self.ended_exam))
                self.assertEqual(response.status_code, 403)
