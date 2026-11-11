"""Acceptance tests for answer auto-save (OEP-F-022 / TC-Exam-03, OEP-NF-001)."""
from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course, Enrollment

from .models import Answer, Choice, Exam, ExamAttempt, ExamQuestion, Question

PASSWORD = "TestPassword123!"
QUESTION_COUNT = 10
ANSWERED = 5

# Data queries for one autosave: session, user, attempt lock, question lookup, choice
# lookup, answer lookup and answer insert/update. SAVEPOINT/RELEASE statements are not
# counted because how many appear depends on the database and the test wrapper.
AUTOSAVE_QUERY_BUDGET = 7


class AutosaveAcceptanceBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            username="acc_instructor",
            email="acc_instructor@example.com",
            password=PASSWORD,
            role=User.Role.INSTRUCTOR,
        )
        cls.student = User.objects.create_user(
            username="acc_student",
            email="acc_student@example.com",
            password=PASSWORD,
            role=User.Role.STUDENT,
        )
        cls.course = Course.objects.create(
            name="Databases", code="DB301", instructor=cls.instructor
        )
        Enrollment.objects.create(student=cls.student, course=cls.course)

        now = timezone.now()
        cls.exam = Exam.objects.create(
            course=cls.course,
            title="Crash Recovery Exam",
            created_by=cls.instructor,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=2),
            duration_minutes=60,
            total_marks=QUESTION_COUNT,
            randomize_questions=False,
            status=Exam.Status.PUBLISHED,
        )
        cls.questions = []
        cls.correct = []
        for position in range(1, QUESTION_COUNT + 1):
            question = Question.objects.create(
                course=cls.course,
                text=f"Recovery question {position}?",
                marks=1,
                created_by=cls.instructor,
            )
            ExamQuestion.objects.create(exam=cls.exam, question=question, position=position)
            cls.correct.append(
                Choice.objects.create(question=question, text="Right", is_correct=True)
            )
            Choice.objects.create(question=question, text="Wrong", is_correct=False)
            cls.questions.append(question)

    def login(self):
        client = Client()
        self.assertTrue(client.login(username=self.student.username, password=PASSWORD))
        return client

    def start(self, client):
        response = client.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        self.assertEqual(response.status_code, 302)
        return ExamAttempt.objects.get(exam=self.exam, student=self.student)

    def assert_autosave_within_budget(self, client, attempt, index):
        with CaptureQueriesContext(connection) as captured:
            response = self.autosave(client, attempt, index)
        data_queries = [
            query["sql"]
            for query in captured.captured_queries
            if "SAVEPOINT" not in query["sql"].upper()
        ]
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(data_queries), AUTOSAVE_QUERY_BUDGET, "\n".join(data_queries)
        )
        return response

    def autosave(self, client, attempt, index):
        return client.post(
            reverse("exams:autosave_answer", args=[attempt.pk]),
            {
                "question_id": self.questions[index].pk,
                "choice_id": self.correct[index].pk,
            },
        )


class TCExam03CrashRecoveryTest(AutosaveAcceptanceBase):
    """TC-Exam-03: a crash after answering 5 of 10 questions keeps those 5 on reload."""

    def test_answers_survive_browser_crash_and_new_login(self):
        before_crash = self.login()
        attempt = self.start(before_crash)
        for index in range(ANSWERED):
            response = self.autosave(before_crash, attempt, index)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["saved"])

        # Browser crash: the old client and its session are gone, nothing was
        # submitted. The student logs in again and reopens the exam.
        del before_crash
        after_crash = self.login()
        response = after_crash.get(
            reverse("exams:start_attempt", args=[self.exam.pk]), follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["attempt"].pk, attempt.pk)
        self.assertEqual(response.context["answered_count"], ANSWERED)
        self.assertEqual(response.context["question_index"], ANSWERED)

        for index, question in enumerate(self.questions):
            page = after_crash.get(
                reverse("exams:take_attempt", args=[attempt.pk]) + f"?q={index}"
            )
            selected = page.context["current_question"].selected_choice_id
            if index < ANSWERED:
                self.assertEqual(selected, self.correct[index].pk, question.text)
            else:
                self.assertIsNone(selected, question.text)

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.IN_PROGRESS)
        self.assertEqual(
            Answer.objects.filter(attempt=attempt, selected_choice__isnull=False).count(),
            ANSWERED,
        )

        after_crash.post(reverse("exams:submit_attempt", args=[attempt.pk]))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.SUBMITTED)
        self.assertEqual(attempt.result.score, ANSWERED)
        self.assertEqual(attempt.result.total_marks, QUESTION_COUNT)


class OEPNF001AutosaveCostTest(AutosaveAcceptanceBase):
    """OEP-NF-001: answer saves must be acknowledged quickly.

    Wall-clock timing is unreliable on shared CI runners, so the guard is a fixed,
    small number of queries per save that does not grow with the exam size.
    """

    def test_autosave_uses_a_fixed_small_number_of_queries(self):
        client = self.login()
        attempt = self.start(client)

        # First save inserts the answer row, later saves update it.
        self.assert_autosave_within_budget(client, attempt, 0)
        self.assert_autosave_within_budget(client, attempt, 0)

    def test_autosave_cost_does_not_grow_with_answers_saved(self):
        client = self.login()
        attempt = self.start(client)
        for index in range(QUESTION_COUNT - 1):
            self.autosave(client, attempt, index)

        self.assert_autosave_within_budget(client, attempt, QUESTION_COUNT - 1)

        self.assertEqual(
            Answer.objects.filter(attempt=attempt).count(), QUESTION_COUNT
        )
