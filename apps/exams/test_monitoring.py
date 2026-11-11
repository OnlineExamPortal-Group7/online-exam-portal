"""Live examination monitoring (OEP-F-040)."""
import re
from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course, Enrollment

from . import monitoring
from .models import Exam, ExamAttempt

PASSWORD = "TestPassword123!"


def data_queries(captured):
    """Queries that touch data; SAVEPOINT statements depend on the database and test wrapper."""
    return [
        query["sql"]
        for query in captured.captured_queries
        if "SAVEPOINT" not in query["sql"].upper()
    ]


class MonitoringTestBase(TestCase):
    """A live exam with three enrolled students. Defines no tests."""

    @classmethod
    def setUpTestData(cls):
        def user(username, role):
            return User.objects.create_user(
                username=username,
                email=f"{username}@example.com",
                password=PASSWORD,
                role=role,
            )

        cls.instructor = user("mon_instructor", User.Role.INSTRUCTOR)
        cls.other_instructor = user("mon_instructor2", User.Role.INSTRUCTOR)
        cls.admin = user("mon_admin", User.Role.ADMINISTRATOR)
        cls.students = [user(f"mon_student{n}", User.Role.STUDENT) for n in (1, 2, 3)]
        cls.outsider = user("mon_outsider", User.Role.STUDENT)

        cls.course = Course.objects.create(
            name="Software Engineering", code="SE501", instructor=cls.instructor
        )
        cls.other_course = Course.objects.create(
            name="Compilers", code="CD502", instructor=cls.other_instructor
        )
        for student in cls.students:
            Enrollment.objects.create(student=student, course=cls.course)

        now = timezone.now()
        cls.exam = cls.make_exam(cls.course, "Live Exam", now)
        cls.other_exam = cls.make_exam(cls.other_course, "Other Exam", now)

    @classmethod
    def make_exam(cls, course, title, now):
        return Exam.objects.create(
            course=course,
            title=title,
            created_by=course.instructor,
            start_time=now - timedelta(minutes=10),
            end_time=now + timedelta(hours=1),
            duration_minutes=30,
            status=Exam.Status.PUBLISHED,
        )

    def attempt(self, student, status=ExamAttempt.Status.IN_PROGRESS, deadline=None):
        return ExamAttempt.objects.create(
            exam=self.exam,
            student=student,
            deadline_at=deadline or timezone.now() + timedelta(minutes=20),
            status=status,
            submitted_at=(
                None if status == ExamAttempt.Status.IN_PROGRESS else timezone.now()
            ),
        )

    def status_by_username(self, snapshot):
        return {row["student"].username: row["status"] for row in snapshot["rows"]}


class MonitorableExamsTests(MonitoringTestBase):
    def test_administrator_can_monitor_every_exam(self):
        exams = monitoring.monitorable_exams(self.admin)
        self.assertCountEqual(exams, [self.exam, self.other_exam])

    def test_instructor_can_monitor_only_own_course_exams(self):
        self.assertCountEqual(monitoring.monitorable_exams(self.instructor), [self.exam])
        self.assertCountEqual(
            monitoring.monitorable_exams(self.other_instructor), [self.other_exam]
        )

    def test_students_and_anonymous_users_can_monitor_nothing(self):
        self.assertFalse(monitoring.monitorable_exams(self.students[0]).exists())
        self.assertFalse(monitoring.monitorable_exams(AnonymousUser()).exists())

    def test_inactive_instructor_can_monitor_nothing(self):
        self.instructor.is_active = False
        self.instructor.save(update_fields=["is_active"])

        self.assertFalse(monitoring.monitorable_exams(self.instructor).exists())


class MonitorSnapshotTests(MonitoringTestBase):
    def test_every_enrolled_student_is_listed_as_not_started(self):
        snapshot = monitoring.monitor_snapshot(self.exam)

        self.assertEqual(snapshot["total"], 3)
        self.assertEqual(
            set(self.status_by_username(snapshot).values()), {monitoring.NOT_STARTED}
        )
        self.assertEqual(snapshot["counts"][monitoring.NOT_STARTED], 3)
        self.assertTrue(snapshot["is_live"])
        self.assertTrue(all(row["enrolled"] for row in snapshot["rows"]))

    def test_each_attempt_status_is_reported(self):
        self.attempt(self.students[0])
        self.attempt(self.students[1], status=ExamAttempt.Status.SUBMITTED)
        self.attempt(self.students[2], status=ExamAttempt.Status.TIMED_OUT)

        snapshot = monitoring.monitor_snapshot(self.exam)

        self.assertEqual(
            self.status_by_username(snapshot),
            {
                "mon_student1": monitoring.IN_PROGRESS,
                "mon_student2": monitoring.SUBMITTED,
                "mon_student3": monitoring.TIMED_OUT,
            },
        )
        self.assertEqual(
            snapshot["counts"],
            {
                monitoring.NOT_STARTED: 0,
                monitoring.IN_PROGRESS: 1,
                monitoring.SUBMITTED: 1,
                monitoring.TIMED_OUT: 1,
            },
        )
        row = snapshot["rows"][1]
        self.assertEqual(row["status_label"], "Submitted")
        self.assertIsNotNone(row["started_at"])
        self.assertIsNotNone(row["submitted_at"])

    def test_overdue_attempt_is_shown_timed_out_without_writing(self):
        attempt = self.attempt(
            self.students[0], deadline=timezone.now() - timedelta(seconds=1)
        )

        with CaptureQueriesContext(connection) as captured:
            snapshot = monitoring.monitor_snapshot(self.exam)

        self.assertEqual(
            self.status_by_username(snapshot)["mon_student1"], monitoring.TIMED_OUT
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.IN_PROGRESS)
        self.assertTrue(
            all(sql.lstrip().upper().startswith("SELECT") for sql in data_queries(captured))
        )

    def test_unenrolled_student_with_attempt_is_still_listed(self):
        self.attempt(self.outsider, status=ExamAttempt.Status.SUBMITTED)

        snapshot = monitoring.monitor_snapshot(self.exam)

        self.assertEqual(snapshot["total"], 4)
        row = next(r for r in snapshot["rows"] if r["student"] == self.outsider)
        self.assertFalse(row["enrolled"])
        self.assertEqual(row["status"], monitoring.SUBMITTED)

    def test_other_exams_attempts_are_ignored(self):
        ExamAttempt.objects.create(
            exam=self.other_exam,
            student=self.students[0],
            deadline_at=timezone.now() + timedelta(minutes=20),
        )

        snapshot = monitoring.monitor_snapshot(self.exam)

        self.assertEqual(
            self.status_by_username(snapshot)["mon_student1"], monitoring.NOT_STARTED
        )

    def test_rows_are_sorted_by_username(self):
        snapshot = monitoring.monitor_snapshot(self.exam)

        usernames = [row["student"].username for row in snapshot["rows"]]
        self.assertEqual(usernames, sorted(usernames))

    def test_ended_exam_is_not_live(self):
        later = self.exam.end_time + timedelta(seconds=1)

        snapshot = monitoring.monitor_snapshot(self.exam, now=later)

        self.assertFalse(snapshot["is_live"])

    def test_query_count_does_not_grow_with_class_size(self):
        self.attempt(self.students[0])

        with CaptureQueriesContext(connection) as small:
            monitoring.monitor_snapshot(self.exam)

        for n in range(20):
            student = User.objects.create_user(
                username=f"mon_extra{n}",
                email=f"mon_extra{n}@example.com",
                password=PASSWORD,
                role=User.Role.STUDENT,
            )
            Enrollment.objects.create(student=student, course=self.course)
            if n % 2:
                self.attempt(student)

        with CaptureQueriesContext(connection) as large:
            snapshot = monitoring.monitor_snapshot(self.exam)

        self.assertEqual(snapshot["total"], 23)
        self.assertEqual(len(data_queries(small)), 2)
        self.assertEqual(len(data_queries(large)), 2)


class MonitorPageAccessTests(MonitoringTestBase):
    """Who may open the monitoring list and detail pages."""

    def detail_url(self, exam=None):
        return reverse("exams:monitor_detail", args=[(exam or self.exam).pk])

    def test_course_instructor_can_open_detail(self):
        self.client.force_login(self.instructor)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 200)

    def test_administrator_can_open_any_exam(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 200)
        self.assertEqual(
            self.client.get(self.detail_url(self.other_exam)).status_code, 200
        )

    def test_other_instructor_gets_404(self):
        self.client.force_login(self.other_instructor)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_student_gets_403(self):
        self.client.force_login(self.students[0])
        self.assertEqual(self.client.get(self.detail_url()).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("exams:monitor_list")).status_code, 403
        )

    def test_anonymous_user_is_redirected_to_login(self):
        for url in (reverse("exams:monitor_list"), self.detail_url()):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("accounts:login"), response.url)

    def test_dashboard_links_to_monitoring_for_staff_only(self):
        link = reverse("exams:monitor_list")
        for user, visible in (
            (self.instructor, True),
            (self.admin, True),
            (self.students[0], False),
        ):
            self.client.force_login(user)
            response = self.client.get(reverse("accounts:dashboard"), follow=True)
            if visible:
                self.assertContains(response, f'href="{link}"')
            else:
                self.assertNotContains(response, f'href="{link}"')


class MonitorPageContentTests(MonitoringTestBase):
    """What the monitoring pages show."""

    def test_list_groups_live_upcoming_and_ended_exams(self):
        now = timezone.now()
        upcoming = Exam.objects.create(
            course=self.course,
            title="Upcoming Exam",
            created_by=self.instructor,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            duration_minutes=30,
            status=Exam.Status.PUBLISHED,
        )
        ended = Exam.objects.create(
            course=self.course,
            title="Ended Exam",
            created_by=self.instructor,
            start_time=now - timedelta(days=1),
            end_time=now - timedelta(days=1) + timedelta(hours=1),
            duration_minutes=30,
            status=Exam.Status.PUBLISHED,
        )
        Exam.objects.create(
            course=self.course,
            title="Draft Exam",
            created_by=self.instructor,
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            duration_minutes=30,
        )
        self.client.force_login(self.instructor)

        response = self.client.get(reverse("exams:monitor_list"))

        self.assertEqual(response.context["live_exams"], [self.exam])
        self.assertEqual(response.context["upcoming_exams"], [upcoming])
        self.assertEqual(response.context["ended_exams"], [ended])
        self.assertNotContains(response, "Draft Exam")
        self.assertNotContains(response, "Other Exam")
        self.assertContains(
            response, reverse("exams:monitor_detail", args=[self.exam.pk])
        )

    def test_detail_shows_counts_and_student_statuses(self):
        self.attempt(self.students[0])
        self.attempt(self.students[1], status=ExamAttempt.Status.SUBMITTED)
        self.client.force_login(self.instructor)

        response = self.client.get(
            reverse("exams:monitor_detail", args=[self.exam.pk])
        )

        self.assertContains(response, "Monitor: Live Exam")
        self.assertContains(response, '<span id="monitor-live">Live</span>')
        self.assertContains(response, '<strong id="count-not_started">1</strong>')
        self.assertContains(response, '<strong id="count-in_progress">1</strong>')
        self.assertContains(response, '<strong id="count-submitted">1</strong>')
        self.assertContains(response, '<strong id="count-timed_out">0</strong>')
        self.assertContains(response, '<strong id="count-total">3</strong>')
        self.assertContains(response, '<tr data-status="in_progress">')
        self.assertContains(response, '<tr data-status="submitted">')
        self.assertContains(response, '<tr data-status="not_started">')
        for student in self.students:
            self.assertContains(response, student.username)

    def test_detail_marks_unenrolled_attempting_student(self):
        self.attempt(self.outsider, status=ExamAttempt.Status.SUBMITTED)
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("exams:monitor_detail", args=[self.exam.pk])
        )

        self.assertContains(response, "mon_outsider (not enrolled)")

    def test_viewing_detail_does_not_change_overdue_attempt(self):
        attempt = self.attempt(
            self.students[0], deadline=timezone.now() - timedelta(seconds=1)
        )
        self.client.force_login(self.instructor)

        response = self.client.get(
            reverse("exams:monitor_detail", args=[self.exam.pk])
        )

        self.assertContains(response, '<tr data-status="timed_out">')
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.IN_PROGRESS)


class MonitorStatusEndpointTests(MonitoringTestBase):
    """GET exams/monitor/<id>/status/ returns the snapshot as JSON."""

    def status_url(self, exam=None):
        return reverse("exams:monitor_status", args=[(exam or self.exam).pk])

    def get_status(self, user, exam=None):
        self.client.force_login(user)
        return self.client.get(self.status_url(exam))

    def test_returns_counts_and_rows_as_json(self):
        self.attempt(self.students[1], status=ExamAttempt.Status.SUBMITTED)

        response = self.get_status(self.instructor)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertEqual(data["exam_id"], self.exam.pk)
        self.assertTrue(data["is_live"])
        self.assertEqual(data["total"], 3)
        self.assertEqual(
            data["counts"],
            {"not_started": 2, "in_progress": 0, "submitted": 1, "timed_out": 0},
        )
        self.assertIn("generated_at", data)
        self.assertRegex(data["generated_display"], r"^\d{2}:\d{2}:\d{2}$")
        row = data["rows"][1]
        self.assertEqual(row["username"], "mon_student2")
        self.assertEqual(row["status"], "submitted")
        self.assertEqual(row["status_label"], "Submitted")
        self.assertTrue(row["enrolled"])
        self.assertIsNotNone(row["started_at"])
        self.assertIsNotNone(row["submitted_display"])
        self.assertIsNone(data["rows"][0]["started_at"])

    def test_response_is_not_cached(self):
        response = self.get_status(self.instructor)

        self.assertIn("no-cache", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_each_status_change_shows_on_the_next_request(self):
        student = self.students[0]

        def status_of_student():
            rows = self.get_status(self.instructor).json()["rows"]
            return next(r["status"] for r in rows if r["username"] == student.username)

        self.assertEqual(status_of_student(), "not_started")
        attempt = self.attempt(student)
        self.assertEqual(status_of_student(), "in_progress")
        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])
        self.assertEqual(status_of_student(), "submitted")

    def test_access_rules_match_the_detail_page(self):
        self.assertEqual(self.get_status(self.admin).status_code, 200)
        self.assertEqual(self.get_status(self.admin, self.other_exam).status_code, 200)
        self.assertEqual(self.get_status(self.other_instructor).status_code, 404)
        self.assertEqual(self.get_status(self.students[0]).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.status_url()).status_code, 302)

    def test_only_get_is_allowed(self):
        self.client.force_login(self.instructor)

        self.assertEqual(self.client.post(self.status_url()).status_code, 405)

    def test_endpoint_is_read_only_and_query_count_is_fixed(self):
        attempt = self.attempt(
            self.students[0], deadline=timezone.now() - timedelta(seconds=1)
        )
        self.client.force_login(self.instructor)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(self.status_url())

        self.assertEqual(response.json()["counts"]["timed_out"], 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.IN_PROGRESS)
        queries = data_queries(captured)
        # Session, user, exam, enrolled students, attempts.
        self.assertEqual(len(queries), 5, "\n".join(queries))
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in queries))


class MonitorAutoRefreshTests(MonitoringTestBase):
    """The detail page refreshes itself well within 30 seconds (AC-040)."""

    def get_detail(self):
        self.client.force_login(self.instructor)
        return self.client.get(reverse("exams:monitor_detail", args=[self.exam.pk]))

    def test_page_polls_status_endpoint_within_30_seconds(self):
        content = self.get_detail().content.decode()

        status_url = reverse("exams:monitor_status", args=[self.exam.pk])
        self.assertIn(f'data-status-url="{status_url}"', content)
        poll_ms = int(re.search(r'data-poll-ms="(\d+)"', content).group(1))
        self.assertLessEqual(poll_ms, 15000)
        self.assertGreater(poll_ms, 0)
        self.assertIn('id="monitor-connection" role="status"', content)
        self.assertIn("fetch(statusUrl", content)

    def test_noscript_refresh_is_in_head_and_within_30_seconds(self):
        content = self.get_detail().content.decode()

        head = content[:content.index("</head>")]
        match = re.search(
            r'<noscript><meta http-equiv="refresh" content="(\d+)"></noscript>', head
        )
        self.assertIsNotNone(match, "noscript refresh must be inside <head>")
        self.assertLessEqual(int(match.group(1)), 30)

    def test_other_pages_do_not_auto_refresh(self):
        self.client.force_login(self.instructor)

        for url in (reverse("exams:monitor_list"), reverse("accounts:login")):
            response = self.client.get(url, follow=True)
            self.assertNotContains(response, 'http-equiv="refresh"')
