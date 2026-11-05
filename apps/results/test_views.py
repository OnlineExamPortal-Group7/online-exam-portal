
"""Instructor and student result pages (OEP-F-031 and Issue #19)."""
from django.test import TestCase
from django.urls import reverse

from apps.exams.models import ExamAttempt

from .models import ResultPublication
from .services import is_published, publish_results
from .test_services import ResultsTestData


class ExamResultListViewTest(ResultsTestData, TestCase):
    url = reverse("results:exam_list")

    def test_instructor_sees_own_exams_with_publication_status(self):
        publish_results(self.ended_exam, self.instructor)
        self.client.force_login(self.instructor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(
            response.context["exams"], [self.open_exam, self.ended_exam]
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
        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={self.url}"
        )


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
        attempt = self.make_attempt(
            self.ended_exam, self.student, self.correct, submitted=False
        )
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


class PublishResultsViewTest(ResultsTestData, TestCase):
    def publish_url(self, exam):
        return reverse("results:publish", args=[exam.pk])

    def test_instructor_publishes_after_exam_ends(self):
        self.client.force_login(self.instructor)

        response = self.client.post(
            self.publish_url(self.ended_exam), follow=True
        )

        self.assertRedirects(
            response,
            reverse("results:exam_review", args=[self.ended_exam.pk]),
        )
        self.assertTrue(is_published(self.ended_exam))
        self.assertContains(response, "Results published.")
        self.assertNotContains(response, "Publish results</button>")

    def test_review_page_shows_publish_button_only_when_allowed(self):
        self.client.force_login(self.instructor)
        button = "Publish results</button>"

        self.assertContains(
            self.client.get(
                reverse("results:exam_review", args=[self.ended_exam.pk])
            ),
            button,
        )
        self.assertNotContains(
            self.client.get(
                reverse("results:exam_review", args=[self.open_exam.pk])
            ),
            button,
        )

    def test_publishing_before_exam_ends_is_refused(self):
        self.client.force_login(self.instructor)

        response = self.client.post(
            self.publish_url(self.open_exam), follow=True
        )

        self.assertFalse(is_published(self.open_exam))
        self.assertContains(
            response, "only after the exam window has closed"
        )

    def test_publishing_twice_is_refused(self):
        self.client.force_login(self.instructor)
        self.client.post(self.publish_url(self.ended_exam))

        response = self.client.post(
            self.publish_url(self.ended_exam), follow=True
        )

        self.assertContains(response, "already published")
        self.assertEqual(ResultPublication.objects.count(), 1)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.instructor)

        response = self.client.get(self.publish_url(self.ended_exam))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(is_published(self.ended_exam))

    def test_other_instructor_gets_404(self):
        self.client.force_login(self.other_instructor)

        response = self.client.post(self.publish_url(self.ended_exam))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(is_published(self.ended_exam))

    def test_students_and_administrators_get_403(self):
        for user in (self.student, self.admin):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                response = self.client.post(
                    self.publish_url(self.ended_exam)
                )
                self.assertEqual(response.status_code, 403)
        self.assertFalse(is_published(self.ended_exam))


# Issue #19: Student results and examination history.


class StudentResultsListViewTest(ResultsTestData, TestCase):
    url = reverse("results:student_results")

    def test_student_sees_only_own_published_results(self):
        own_attempt = self.make_attempt(
            self.ended_exam, self.student, self.correct
        )
        self.make_attempt(
            self.ended_exam, self.student2, self.wrong
        )
        publish_results(self.ended_exam, self.instructor)

        self.client.force_login(self.student)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        results = list(response.context["results"])
        self.assertEqual(
            [result.pk for result in results],
            [own_attempt.result.pk],
        )
        self.assertContains(response, "Ended exam")
        self.assertContains(response, "2 / 2")
        self.assertNotContains(response, "0 / 2")

    def test_unpublished_results_are_not_visible(self):
        self.make_attempt(
            self.ended_exam, self.student, self.correct
        )

        self.client.force_login(self.student)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertContains(
            response, "You do not have any published results yet."
        )

    def test_instructors_and_administrators_get_403(self):
        for user in (self.instructor, self.admin):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(
                    self.client.get(self.url).status_code, 403
                )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={self.url}"
        )


class StudentExamHistoryViewTest(ResultsTestData, TestCase):
    url = reverse("results:student_history")

    def test_student_sees_only_own_exam_attempts(self):
        own_attempt = self.make_attempt(
            self.ended_exam, self.student, self.correct
        )
        in_progress_attempt = self.make_attempt(
            self.open_exam, self.student, submitted=False
        )
        self.make_attempt(
            self.ended_exam, self.student2, self.wrong
        )
        publish_results(self.ended_exam, self.instructor)

        self.client.force_login(self.student)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        attempts = list(response.context["attempts"])

        self.assertEqual(
            {attempt.pk for attempt in attempts},
            {own_attempt.pk, in_progress_attempt.pk},
        )

        attempts_by_id = {
            attempt.pk: attempt for attempt in attempts
        }
        self.assertEqual(
            attempts_by_id[own_attempt.pk].published_result.score, 2
        )
        self.assertIsNone(
            attempts_by_id[in_progress_attempt.pk].published_result
        )

    def test_unpublished_attempt_does_not_show_its_score(self):
        self.make_attempt(
            self.ended_exam, self.student, self.correct
        )

        self.client.force_login(self.student)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Not published")
        self.assertNotContains(response, "2 / 2")

    def test_instructors_and_administrators_get_403(self):
        for user in (self.instructor, self.admin):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                self.assertEqual(
                    self.client.get(self.url).status_code, 403
                )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={self.url}"
        )


class StudentResultDetailViewTest(ResultsTestData, TestCase):
    def detail_url(self, result):
        return reverse("results:student_result_detail", args=[result.pk])

    def test_student_can_view_own_published_result(self):
        attempt = self.make_attempt(
            self.ended_exam, self.student, self.correct
        )
        publish_results(self.ended_exam, self.instructor)

        self.client.force_login(self.student)
        response = self.client.get(self.detail_url(attempt.result))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 / 2")
        self.assertContains(response, "100.0%")

    def test_student_cannot_view_another_students_result(self):
        other_attempt = self.make_attempt(
            self.ended_exam, self.student2, self.correct
        )
        publish_results(self.ended_exam, self.instructor)

        self.client.force_login(self.student)
        response = self.client.get(
            self.detail_url(other_attempt.result)
        )

        self.assertEqual(response.status_code, 404)

    def test_student_cannot_view_unpublished_result(self):
        attempt = self.make_attempt(
            self.ended_exam, self.student, self.correct
        )

        self.client.force_login(self.student)
        response = self.client.get(self.detail_url(attempt.result))

        self.assertEqual(response.status_code, 404)

    def test_instructors_and_administrators_get_403(self):
        attempt = self.make_attempt(
            self.ended_exam, self.student, self.correct
        )
        publish_results(self.ended_exam, self.instructor)

        for user in (self.instructor, self.admin):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                response = self.client.get(
                    self.detail_url(attempt.result)
                )
                self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        attempt = self.make_attempt(
            self.ended_exam, self.student, self.correct
        )
        publish_results(self.ended_exam, self.instructor)

        url = self.detail_url(attempt.result)
        response = self.client.get(url)

        self.assertRedirects(
            response, f"{reverse('accounts:login')}?next={url}"
        )
