"""Result publication services (OEP-F-031)."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course, Enrollment
from apps.exams.models import Answer, Choice, Exam, ExamAttempt, ExamQuestion, Question

from . import services
from .models import Result, ResultPublication
from .signals import results_published

PASSWORD = "Str0ng-pass-123"


def make_user(username, role=User.Role.STUDENT):
    return User.objects.create_user(username, f"{username}@example.com", PASSWORD, role=role)


class ResultsTestData:
    """Shared data: one course with two enrolled students, an ended exam and an open exam."""

    @classmethod
    def setUpTestData(cls):
        cls.instructor = make_user("instructor", User.Role.INSTRUCTOR)
        cls.other_instructor = make_user("other_instructor", User.Role.INSTRUCTOR)
        cls.admin = make_user("admin", User.Role.ADMINISTRATOR)
        cls.student = make_user("student")
        cls.student2 = make_user("student2")
        cls.course = Course.objects.create(name="Networks", code="CN101", instructor=cls.instructor)
        for student in (cls.student, cls.student2):
            Enrollment.objects.create(student=student, course=cls.course)

        cls.question = Question.objects.create(
            course=cls.course, text="What is TCP?", topic="Transport", marks=2,
            created_by=cls.instructor,
        )
        cls.correct = Choice.objects.create(
            question=cls.question, text="A protocol", is_correct=True
        )
        cls.wrong = Choice.objects.create(question=cls.question, text="A cable")

        now = timezone.now()
        hour = timedelta(hours=1)
        cls.ended_exam = cls.make_exam("Ended exam", now - 3 * hour, now - hour)
        cls.open_exam = cls.make_exam("Open exam", now - hour, now + hour)

    @classmethod
    def make_exam(cls, title, start, end):
        exam = Exam.objects.create(
            course=cls.course, title=title, created_by=cls.instructor, start_time=start,
            end_time=end, duration_minutes=60, total_marks=2, status=Exam.Status.PUBLISHED,
        )
        ExamQuestion.objects.create(exam=exam, question=cls.question, position=1)
        return exam

    def make_attempt(self, exam, student, choice=None, submitted=True):
        attempt = ExamAttempt.objects.create(
            exam=exam, student=student, deadline_at=exam.start_time + timedelta(minutes=60),
        )
        if choice is not None:
            Answer.objects.create(attempt=attempt, question=self.question, selected_choice=choice)
        if submitted:
            attempt.status = ExamAttempt.Status.SUBMITTED
            attempt.submitted_at = attempt.deadline_at
            attempt.save()
            Result.objects.create(
                attempt=attempt, score=2 if choice == self.correct else 0, total_marks=2,
            )
        return attempt


class PublishResultsTest(ResultsTestData, TestCase):
    def test_course_instructor_publishes_after_exam_ends(self):
        publication = services.publish_results(self.ended_exam, self.instructor)

        self.assertEqual(publication.exam, self.ended_exam)
        self.assertEqual(publication.published_by, self.instructor)
        self.assertTrue(services.is_published(self.ended_exam))

    def test_cannot_publish_before_exam_window_closes(self):
        self.assertFalse(services.can_publish(self.open_exam))
        with self.assertRaises(ValidationError):
            services.publish_results(self.open_exam, self.instructor)
        self.assertFalse(services.is_published(self.open_exam))

    def test_cannot_publish_twice(self):
        services.publish_results(self.ended_exam, self.instructor)

        self.assertFalse(services.can_publish(self.ended_exam))
        with self.assertRaises(ValidationError):
            services.publish_results(self.ended_exam, self.instructor)
        self.assertEqual(ResultPublication.objects.count(), 1)

    def test_only_the_course_instructor_may_publish(self):
        for user in (self.other_instructor, self.admin, self.student):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                services.publish_results(self.ended_exam, user)
        self.assertFalse(services.is_published(self.ended_exam))

    def test_publishing_scores_attempts_left_in_progress(self):
        attempt = self.make_attempt(self.ended_exam, self.student, self.correct, submitted=False)

        services.publish_results(self.ended_exam, self.instructor)

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)
        self.assertEqual(attempt.result.score, 2)

    def test_signal_is_sent_once_after_commit(self):
        received = []

        def receiver(sender, exam, published_by, **kwargs):
            received.append((exam, published_by))

        results_published.connect(receiver)
        self.addCleanup(results_published.disconnect, receiver)

        with self.captureOnCommitCallbacks(execute=True):
            services.publish_results(self.ended_exam, self.instructor)

        self.assertEqual(received, [(self.ended_exam, self.instructor)])


class FinalizeOverdueAttemptsTest(ResultsTestData, TestCase):
    def test_overdue_attempt_is_timed_out_and_scored(self):
        attempt = self.make_attempt(self.ended_exam, self.student, self.wrong, submitted=False)

        services.finalize_overdue_attempts(self.ended_exam)

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)
        self.assertEqual(attempt.result.score, 0)

    def test_running_attempt_is_left_alone(self):
        attempt = ExamAttempt.objects.create(
            exam=self.open_exam, student=self.student,
            deadline_at=timezone.now() + timedelta(minutes=30),
        )

        services.finalize_overdue_attempts(self.open_exam)

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.IN_PROGRESS)
        self.assertFalse(Result.objects.filter(attempt=attempt).exists())

    def test_closed_attempt_without_result_is_scored(self):
        attempt = self.make_attempt(self.ended_exam, self.student, self.correct, submitted=False)
        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.save()

        services.finalize_overdue_attempts(self.ended_exam)

        self.assertEqual(Result.objects.get(attempt=attempt).score, 2)


class ResultQueriesTest(ResultsTestData, TestCase):
    def test_student_sees_results_only_after_publication(self):
        self.make_attempt(self.ended_exam, self.student, self.correct)
        self.make_attempt(self.ended_exam, self.student2, self.wrong)
        self.assertFalse(services.published_results_for(self.student).exists())

        services.publish_results(self.ended_exam, self.instructor)

        results = list(services.published_results_for(self.student))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].attempt.student, self.student)
        self.assertEqual(results[0].score, 2)

    def test_results_for_exam_includes_unpublished_results(self):
        self.make_attempt(self.ended_exam, self.student, self.correct)
        self.make_attempt(self.ended_exam, self.student2, self.wrong)

        scores = [r.score for r in services.results_for_exam(self.ended_exam)]
        self.assertEqual(scores, [2, 0])

    def test_exams_for_review_lists_only_own_course_exams(self):
        self.assertEqual(
            set(services.exams_for_review(self.instructor)), {self.ended_exam, self.open_exam}
        )
        for user in (self.other_instructor, self.admin, self.student):
            with self.subTest(user=user.username):
                self.assertFalse(services.exams_for_review(user).exists())
