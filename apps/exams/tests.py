from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course, Enrollment

from .models import Answer, Choice, Exam, ExamAttempt, ExamQuestion, Question


class ExamCreationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = User.objects.create_user(
            username="instructor1",
            email="instructor1@example.com",
            password="TestPassword123!",
            role=User.Role.INSTRUCTOR,
        )
        cls.student = User.objects.create_user(
            username="student1",
            email="student1@example.com",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )
        cls.course = Course.objects.create(
            name="Computer Networks",
            code="CN101",
            instructor=cls.instructor,
        )
        Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.question1 = Question.objects.create(
            course=cls.course,
            text="What is a computer network?",
            marks=2,
            created_by=cls.instructor,
        )
        cls.question2 = Question.objects.create(
            course=cls.course,
            text="What is an IP address?",
            marks=3,
            created_by=cls.instructor,
        )

    def test_instructor_can_open_exam_creation_page(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("exams:create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Exam")

    def test_student_cannot_create_exam(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("exams:create"))
        self.assertEqual(response.status_code, 403)

    def test_exam_creation_saves_questions_and_total_marks(self):
        self.client.force_login(self.instructor)
        start_time = timezone.now() + timedelta(days=1)
        end_time = start_time + timedelta(hours=2)
        response = self.client.post(
            reverse("exams:create"),
            {
                "course": self.course.pk,
                "title": "Computer Networks Test",
                "description": "Unit test exam",
                "start_time": start_time.strftime("%Y-%m-%dT%H:%M"),
                "end_time": end_time.strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 60,
                "randomize_questions": "on",
                "questions": [self.question1.pk, self.question2.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        exam = Exam.objects.get(title="Computer Networks Test")
        self.assertEqual(exam.created_by, self.instructor)
        self.assertEqual(exam.total_marks, 5)
        self.assertEqual(exam.exam_questions.count(), 2)
        positions = list(exam.exam_questions.values_list("position", flat=True))
        self.assertEqual(sorted(positions), [1, 2])

    def test_exam_with_invalid_dates_is_rejected(self):
        self.client.force_login(self.instructor)
        start_time = timezone.now() + timedelta(days=2)
        end_time = start_time - timedelta(hours=1)
        response = self.client.post(
            reverse("exams:create"),
            {
                "course": self.course.pk,
                "title": "Invalid Exam",
                "description": "",
                "start_time": start_time.strftime("%Y-%m-%dT%H:%M"),
                "end_time": end_time.strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": 60,
                "randomize_questions": "on",
                "questions": [self.question1.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Exam.objects.filter(title="Invalid Exam").exists())
        self.assertIn("end_time", response.context["form"].errors)


class ServerAuthoritativeTimerTests(ExamCreationTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        now = timezone.now()
        cls.exam = Exam.objects.create(
            course=cls.course,
            title="Timer Test Exam",
            description="Testing the server-side timer",
            created_by=cls.instructor,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=2),
            duration_minutes=30,
            total_marks=5,
            randomize_questions=False,
            status=Exam.Status.PUBLISHED,
        )
        ExamQuestion.objects.create(exam=cls.exam, question=cls.question1, position=1)
        ExamQuestion.objects.create(exam=cls.exam, question=cls.question2, position=2)
        cls.choice = Choice.objects.create(
            question=cls.question1,
            text="A sample choice",
            is_correct=True,
        )
        cls.choice2 = Choice.objects.create(
            question=cls.question2,
            text="Another sample choice",
            is_correct=False,
        )

    def create_attempt(self, deadline=None, status=None):
        now = timezone.now()
        return ExamAttempt.objects.create(
            exam=self.exam,
            student=self.student,
            deadline_at=deadline or now + timedelta(minutes=20),
            status=status or ExamAttempt.Status.IN_PROGRESS,
        )

    def test_start_attempt_creates_server_calculated_deadline(self):
        self.client.force_login(self.student)
        before = timezone.now()
        response = self.client.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        after = timezone.now()
        self.assertEqual(response.status_code, 302)
        attempt = ExamAttempt.objects.get(exam=self.exam, student=self.student)
        self.assertGreaterEqual(attempt.deadline_at, before + timedelta(minutes=30))
        self.assertLessEqual(attempt.deadline_at, after + timedelta(minutes=30))
        self.assertEqual(response.url, reverse("exams:take_attempt", args=[attempt.pk]))

    def test_student_not_enrolled_cannot_start_exam(self):
        outsider = User.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )
        self.client.force_login(outsider)
        response = self.client.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ExamAttempt.objects.filter(exam=self.exam, student=outsider).exists())

    def test_deadline_never_exceeds_exam_end_time(self):
        self.client.force_login(self.student)
        with patch(
            "apps.exams.views.timezone.now",
            return_value=self.exam.end_time - timedelta(minutes=5),
        ):
            response = self.client.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        self.assertEqual(response.status_code, 302)
        attempt = ExamAttempt.objects.get(exam=self.exam, student=self.student)
        self.assertEqual(attempt.deadline_at, self.exam.end_time)

    def test_restarting_exam_does_not_reset_deadline(self):
        original_deadline = timezone.now() + timedelta(minutes=10)
        attempt = self.create_attempt(deadline=original_deadline)
        self.client.force_login(self.student)
        response = self.client.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.deadline_at, original_deadline)
        self.assertEqual(
            ExamAttempt.objects.filter(exam=self.exam, student=self.student).count(),
            1,
        )

    def test_attempt_page_displays_countdown_and_navigation(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)
        response = self.client.get(reverse("exams:take_attempt", args=[attempt.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("remaining_seconds", response.context)
        self.assertContains(response, "Time remaining")
        self.assertContains(response, "Question 1 of 2")
        self.assertContains(response, "Save &amp; Next")

    def test_answer_is_saved_when_navigating_to_next_question(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("exams:save_answer", args=[attempt.pk]),
            {
                "question_id": self.question1.pk,
                "choice_id": self.choice.pk,
                "next_question": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("?q=1"))
        answer = Answer.objects.get(attempt=attempt, question=self.question1)
        self.assertEqual(answer.selected_choice_id, self.choice.pk)
        next_response = self.client.get(reverse("exams:take_attempt", args=[attempt.pk]) + "?q=1")
        self.assertContains(next_response, self.question2.text)

    def test_saved_answer_is_preselected_when_revisiting_question(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt,
            question=self.question1,
            selected_choice=self.choice,
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse("exams:take_attempt", args=[attempt.pk]) + "?q=0")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{self.choice.pk}"')
        self.assertContains(response, "checked")

    def test_manual_submission_marks_attempt_as_submitted(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.client.post(
            reverse("exams:submit_attempt", args=[attempt.pk])
        )

        self.assertEqual(response.status_code, 302)

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.SUBMITTED)
        self.assertIsNotNone(attempt.submitted_at)

    def test_submitted_attempt_cannot_save_or_change_answers(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt,
            question=self.question1,
            selected_choice=self.choice,
        )
        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])

        self.client.force_login(self.student)

        response = self.client.post(
            reverse("exams:save_answer", args=[attempt.pk]),
            {
                "question_id": self.question1.pk,
                "choice_id": self.choice2.pk,
            },
        )

        self.assertEqual(response.status_code, 403)

        answer = Answer.objects.get(
            attempt=attempt,
            question=self.question1,
        )
        self.assertEqual(answer.selected_choice_id, self.choice.pk)

    def test_submit_confirmation_is_present_on_exam_page(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.client.get(
            reverse("exams:take_attempt", args=[attempt.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Are you sure you want to submit the exam?",
        )

    def test_expired_attempt_cannot_save_answer(self):
        attempt = self.create_attempt(deadline=timezone.now() - timedelta(seconds=1))
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("exams:save_answer", args=[attempt.pk]),
            {"question_id": self.question1.pk, "choice_id": self.choice.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)

    def test_expired_attempt_cannot_be_submitted_as_active(self):
        attempt = self.create_attempt(deadline=timezone.now() - timedelta(seconds=1))
        self.client.force_login(self.student)
        response = self.client.post(reverse("exams:submit_attempt", args=[attempt.pk]))
        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)

    def test_student_cannot_access_another_students_attempt(self):
        another_student = User.objects.create_user(
            username="student2",
            email="student2@example.com",
            password="TestPassword123!",
            role=User.Role.STUDENT,
        )
        attempt = self.create_attempt()
        self.client.force_login(another_student)
        response = self.client.get(reverse("exams:take_attempt", args=[attempt.pk]))
        self.assertEqual(response.status_code, 404)

    def test_expired_attempt_is_not_displayed_as_active(self):
        attempt = self.create_attempt(deadline=timezone.now() - timedelta(seconds=1))
        self.client.force_login(self.student)
        response = self.client.get(reverse("exams:take_attempt", args=[attempt.pk]))
        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)

    def test_instructor_cannot_start_student_attempt(self):
        self.client.force_login(self.instructor)
        response = self.client.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        self.assertEqual(response.status_code, 403)
