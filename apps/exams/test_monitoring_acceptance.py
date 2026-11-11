"""Acceptance tests for live examination monitoring (OEP-F-040 / TC-Admin-01).

AC-040: the monitoring view updates within 30 seconds of a student's status change.
The page polls every 10 seconds (checked in test_monitoring.py); here each real
status change, made through the student's own exam views, must be visible on the
very next poll.
"""
import re
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course, Enrollment

from .models import Choice, Exam, ExamAttempt, ExamQuestion, Question

PASSWORD = "TestPassword123!"
AC_040_SECONDS = 30


class TCAdmin01LiveMonitoringTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        def user(username, role):
            return User.objects.create_user(
                username=username,
                email=f"{username}@example.com",
                password=PASSWORD,
                role=role,
            )

        cls.instructor = user("tca_instructor", User.Role.INSTRUCTOR)
        cls.admin = user("tca_admin", User.Role.ADMINISTRATOR)
        cls.alice = user("tca_alice", User.Role.STUDENT)
        cls.bob = user("tca_bob", User.Role.STUDENT)
        cls.carol = user("tca_carol", User.Role.STUDENT)

        course = Course.objects.create(
            name="Computer Architecture", code="CA601", instructor=cls.instructor
        )
        for student in (cls.alice, cls.bob, cls.carol):
            Enrollment.objects.create(student=student, course=course)

        now = timezone.now()
        cls.exam = Exam.objects.create(
            course=course,
            title="Monitored Exam",
            created_by=cls.instructor,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=2),
            duration_minutes=45,
            total_marks=1,
            randomize_questions=False,
            status=Exam.Status.PUBLISHED,
        )
        question = Question.objects.create(
            course=course, text="Which unit decodes instructions?", created_by=cls.instructor
        )
        ExamQuestion.objects.create(exam=cls.exam, question=question, position=1)
        Choice.objects.create(question=question, text="Control unit", is_correct=True)

    def login(self, user):
        client = Client()
        self.assertTrue(client.login(username=user.username, password=PASSWORD))
        return client

    def poll(self, client):
        response = client.get(reverse("exams:monitor_status", args=[self.exam.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        return data["counts"], {row["username"]: row["status"] for row in data["rows"]}

    def test_monitor_reflects_each_student_status_change_on_next_poll(self):
        instructor = self.login(self.instructor)
        admin = self.login(self.admin)

        # The detail page refreshes far inside the 30 second target.
        page = instructor.get(reverse("exams:monitor_detail", args=[self.exam.pk]))
        poll_ms = int(re.search(r'data-poll-ms="(\d+)"', page.content.decode()).group(1))
        self.assertLess(poll_ms / 1000, AC_040_SECONDS)

        counts, statuses = self.poll(instructor)
        self.assertEqual(
            statuses,
            {"tca_alice": "not_started", "tca_bob": "not_started", "tca_carol": "not_started"},
        )
        self.assertEqual(counts["not_started"], 3)

        # Alice starts the exam.
        alice = self.login(self.alice)
        alice.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        _, statuses = self.poll(instructor)
        self.assertEqual(statuses["tca_alice"], "in_progress")

        # Bob starts and submits.
        bob = self.login(self.bob)
        bob.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        bob_attempt = ExamAttempt.objects.get(exam=self.exam, student=self.bob)
        bob.post(reverse("exams:submit_attempt", args=[bob_attempt.pk]))
        _, statuses = self.poll(instructor)
        self.assertEqual(statuses["tca_bob"], "submitted")

        # Carol starts, then her deadline passes with her browser closed.
        carol = self.login(self.carol)
        carol.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        ExamAttempt.objects.filter(exam=self.exam, student=self.carol).update(
            deadline_at=timezone.now() - timedelta(seconds=1)
        )
        counts, statuses = self.poll(instructor)
        self.assertEqual(
            statuses,
            {"tca_alice": "in_progress", "tca_bob": "submitted", "tca_carol": "timed_out"},
        )
        self.assertEqual(
            counts,
            {"not_started": 0, "in_progress": 1, "submitted": 1, "timed_out": 1},
        )

        # The administrator sees the same picture.
        self.assertEqual(self.poll(admin), (counts, statuses))

        # Monitoring is read-only: Carol's row is still in progress in the database
        # until the normal timeout path (#15/#18) closes it.
        carol_attempt = ExamAttempt.objects.get(exam=self.exam, student=self.carol)
        self.assertEqual(carol_attempt.status, ExamAttempt.Status.IN_PROGRESS)
        instructor.get(reverse("results:exam_review", args=[self.exam.pk]))
        carol_attempt.refresh_from_db()
        self.assertEqual(carol_attempt.status, ExamAttempt.Status.TIMED_OUT)
        self.assertEqual(self.poll(instructor)[1]["tca_carol"], "timed_out")

    def test_students_cannot_monitor_the_exam(self):
        alice = self.login(self.alice)

        for name in ("exams:monitor_detail", "exams:monitor_status"):
            response = alice.get(reverse(name, args=[self.exam.pk]))
            self.assertEqual(response.status_code, 403, name)
        self.assertEqual(alice.get(reverse("exams:monitor_list")).status_code, 403)
