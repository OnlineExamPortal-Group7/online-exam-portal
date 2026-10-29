from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course

from .models import Exam, Question


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
                "questions": [
                    self.question1.pk,
                    self.question2.pk,
                ],
            },
        )

        self.assertEqual(response.status_code, 302)

        exam = Exam.objects.get(title="Computer Networks Test")

        self.assertEqual(exam.created_by, self.instructor)
        self.assertEqual(exam.total_marks, 5)
        self.assertEqual(exam.exam_questions.count(), 2)

        positions = list(
            exam.exam_questions.values_list("position", flat=True)
        )
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
        self.assertFalse(
            Exam.objects.filter(title="Invalid Exam").exists()
        )
        self.assertIn("end_time", response.context["form"].errors)
