"""Answer auto-save and persistence (OEP-F-022, TC-Exam-03)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course, Enrollment

from .models import Answer, Choice, Exam, ExamAttempt, ExamQuestion, Question


class AutosaveTestBase(TestCase):
    """Published exam with two MCQs and an enrolled student. Defines no tests."""

    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            username="as_instructor",
            email="as_instructor@example.com",
            password="TestPassword123!",
            role=User.Role.INSTRUCTOR,
        )
        cls.student = User.objects.create_user(
            username="as_student",
            email="as_student@example.com",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )
        cls.other_student = User.objects.create_user(
            username="as_student2",
            email="as_student2@example.com",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )
        cls.course = Course.objects.create(
            name="Operating Systems", code="OS201", instructor=cls.instructor
        )
        Enrollment.objects.create(student=cls.student, course=cls.course)
        Enrollment.objects.create(student=cls.other_student, course=cls.course)

        now = timezone.now()
        cls.exam = Exam.objects.create(
            course=cls.course,
            title="Autosave Exam",
            created_by=cls.instructor,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=2),
            duration_minutes=30,
            total_marks=3,
            randomize_questions=False,
            status=Exam.Status.PUBLISHED,
        )
        cls.questions = []
        cls.correct = []
        cls.wrong = []
        for position in (1, 2):
            question = Question.objects.create(
                course=cls.course,
                text=f"Autosave question {position}?",
                marks=position,
                created_by=cls.instructor,
            )
            ExamQuestion.objects.create(exam=cls.exam, question=question, position=position)
            cls.correct.append(
                Choice.objects.create(question=question, text="Right", is_correct=True)
            )
            cls.wrong.append(
                Choice.objects.create(question=question, text="Wrong", is_correct=False)
            )
            cls.questions.append(question)

    def create_attempt(self, student=None, deadline=None, status=None):
        return ExamAttempt.objects.create(
            exam=self.exam,
            student=student or self.student,
            deadline_at=deadline or timezone.now() + timedelta(minutes=20),
            status=status or ExamAttempt.Status.IN_PROGRESS,
        )


class StoreAnswerValidationTests(AutosaveTestBase):
    """The shared answer-storing path used by navigation saves."""

    def post_save(self, attempt, question_id, choice_id, next_question="0"):
        return self.client.post(
            reverse("exams:save_answer", args=[attempt.pk]),
            {
                "question_id": question_id,
                "choice_id": choice_id,
                "next_question": next_question,
            },
        )

    def test_choice_from_another_question_is_rejected(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.post_save(attempt, self.questions[0].pk, self.correct[1].pk)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())

    def test_question_outside_the_exam_is_rejected(self):
        attempt = self.create_attempt()
        stray = Question.objects.create(
            course=self.course, text="Not in exam", created_by=self.instructor
        )
        self.client.force_login(self.student)

        response = self.post_save(attempt, stray.pk, "")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())

    def test_malformed_ids_are_rejected_without_server_error(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        self.assertEqual(self.post_save(attempt, "abc", "").status_code, 404)
        self.assertEqual(
            self.post_save(attempt, self.questions[0].pk, "xyz").status_code, 404
        )
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())

    def test_changing_and_clearing_an_answer_updates_one_row(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)
        question = self.questions[0]

        self.post_save(attempt, question.pk, self.wrong[0].pk)
        self.post_save(attempt, question.pk, self.correct[0].pk)
        answer = Answer.objects.get(attempt=attempt, question=question)
        self.assertEqual(answer.selected_choice_id, self.correct[0].pk)

        self.post_save(attempt, question.pk, "")
        answer.refresh_from_db()
        self.assertIsNone(answer.selected_choice_id)
        self.assertEqual(Answer.objects.filter(attempt=attempt).count(), 1)
