import re
from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.models import User
from apps.administration.models import Course

from .access import QuestionBankAccessMixin, question_bank_required, questions_for
from .models import Choice, Exam, ExamAttempt, ExamQuestion, Question

PASSWORD = "Str0ng-pass-123"


def make_user(username, role, **kwargs):
    email = f"{username}@example.com"
    return User.objects.create_user(username, email, PASSWORD, role=role, **kwargs)


@question_bank_required
def bank_function_view(request):
    return HttpResponse("question bank")


class BankClassView(QuestionBankAccessMixin, View):
    def get(self, request):
        return HttpResponse("question bank")


class QuestionBankGuardTest(TestCase):  # OEP-F-014, OEP-SR-003
    VIEWS = {"function view": bank_function_view, "class view": BankClassView.as_view()}

    def setUp(self):
        self.users = {role: make_user(role, role) for role in User.Role.values}

    def call(self, view, user):
        request = RequestFactory().get("/exams/questions/")
        request.user = user
        return view(request)

    def test_instructor_and_administrator_are_allowed(self):
        for name, view in self.VIEWS.items():
            for role in (User.Role.INSTRUCTOR, User.Role.ADMINISTRATOR):
                with self.subTest(view=name, role=role):
                    response = self.call(view, self.users[role])
                    self.assertEqual(response.status_code, 200)

    def test_student_gets_403(self):
        for name, view in self.VIEWS.items():
            with self.subTest(view=name):
                with self.assertRaises(PermissionDenied):
                    self.call(view, self.users[User.Role.STUDENT])

    def test_anonymous_is_sent_to_login(self):
        for name, view in self.VIEWS.items():
            with self.subTest(view=name):
                response = self.call(view, AnonymousUser())
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/login/", response["Location"])


class QuestionsForTest(TestCase):  # OEP-F-014
    def setUp(self):
        self.teacher = make_user("teacher", User.Role.INSTRUCTOR)
        other_teacher = make_user("other", User.Role.INSTRUCTOR)
        self.admin = make_user("admin", User.Role.ADMINISTRATOR)
        own_course = Course.objects.create(name="Own", code="OWN1", instructor=self.teacher)
        other_course = Course.objects.create(name="Other", code="OTH1", instructor=other_teacher)
        self.own = Question.objects.create(
            course=own_course, text="Own question?", created_by=self.teacher
        )
        self.other = Question.objects.create(
            course=other_course, text="Other question?", created_by=other_teacher
        )

    def test_instructor_sees_only_own_course_questions(self):
        self.assertQuerySetEqual(questions_for(self.teacher), [self.own])

    def test_administrator_sees_all_questions(self):
        self.assertQuerySetEqual(
            questions_for(self.admin).order_by("pk"), [self.own, self.other]
        )

    def test_students_anonymous_and_inactive_users_see_nothing(self):
        inactive_admin = make_user("gone", User.Role.ADMINISTRATOR, is_active=False)
        for user in (make_user("student", User.Role.STUDENT), AnonymousUser(), inactive_admin):
            with self.subTest(user=str(user)):
                self.assertFalse(questions_for(user).exists())


class AttemptAccessTest(TestCase):  # OEP-F-014, OEP-SR-004
    def setUp(self):
        self.teacher = make_user("teacher", User.Role.INSTRUCTOR)
        self.student = make_user("student", User.Role.STUDENT)
        self.other_student = make_user("other", User.Role.STUDENT)
        course = Course.objects.create(name="Programming", code="CS101", instructor=self.teacher)
        now = timezone.now()
        self.exam = Exam.objects.create(
            course=course, title="Quiz", created_by=self.teacher,
            start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1),
            duration_minutes=30, status=Exam.Status.PUBLISHED,
        )
        self.question = Question.objects.create(
            course=course, text="Secret question text?", created_by=self.teacher
        )
        self.right = Choice.objects.create(question=self.question, text="Alpha", is_correct=True)
        self.wrong = Choice.objects.create(question=self.question, text="Beta")
        ExamQuestion.objects.create(exam=self.exam, question=self.question, position=1)
        self.deadline = now + timedelta(minutes=30)

    def attempt_for(self, student, **kwargs):
        return ExamAttempt.objects.create(
            exam=self.exam, student=student, deadline_at=kwargs.pop("deadline", self.deadline),
            **kwargs,
        )

    def urls(self, attempt):
        return {
            "take": ("get", reverse("exams:take_attempt", args=[attempt.pk])),
            "save": ("post", reverse("exams:save_answer", args=[attempt.pk])),
            "submit": ("post", reverse("exams:submit_attempt", args=[attempt.pk])),
        }

    def test_student_cannot_open_another_students_attempt(self):  # OEP-SR-004
        attempt = self.attempt_for(self.other_student)
        self.client.force_login(self.student)
        data = {"question_id": self.question.pk, "choice_id": self.wrong.pk}
        for name, (method, url) in self.urls(attempt).items():
            with self.subTest(page=name):
                response = getattr(self.client, method)(url, data)
                self.assertEqual(response.status_code, 404)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.IN_PROGRESS)
        self.assertFalse(attempt.answers.exists())

    def test_no_question_content_before_the_attempt_starts(self):  # OEP-F-014
        self.exam.start_time += timedelta(hours=2)
        self.exam.end_time += timedelta(hours=2)
        self.exam.save()
        self.client.force_login(self.student)
        response = self.client.get(
            reverse("exams:start_attempt", args=[self.exam.pk]), follow=True
        )
        self.assertNotContains(response, "Secret question text?")
        self.assertFalse(ExamAttempt.objects.filter(student=self.student).exists())

    def test_unpublished_exam_cannot_be_started(self):  # OEP-F-014
        self.exam.status = self.exam.Status.DRAFT
        self.exam.save()
        self.client.force_login(self.student)
        response = self.client.get(reverse("exams:start_attempt", args=[self.exam.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExamAttempt.objects.exists())

    def test_no_question_content_after_submit_or_timeout(self):  # OEP-F-014
        submitted = self.attempt_for(self.student, status=ExamAttempt.Status.SUBMITTED)
        expired = self.attempt_for(self.student, deadline=timezone.now() - timedelta(seconds=1))
        self.client.force_login(self.student)
        for attempt in (submitted, expired):
            with self.subTest(attempt=attempt.pk):
                url = reverse("exams:take_attempt", args=[attempt.pk])
                response = self.client.get(url, follow=True)
                self.assertNotContains(response, "Secret question text?")

    def test_attempt_page_does_not_reveal_the_answer_key(self):  # OEP-F-014
        attempt = self.attempt_for(self.student)
        self.client.force_login(self.student)
        url = reverse("exams:take_attempt", args=[attempt.pk])

        def page():
            html = self.client.get(url).content.decode()
            return re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', "", html)

        before = page()
        self.assertContains(self.client.get(url), "Secret question text?")
        self.assertNotIn("is_correct", before)
        # Swap which choice is correct: the student's page must not change at all.
        self.right.is_correct, self.wrong.is_correct = False, True
        self.right.save()
        self.wrong.save()
        self.assertEqual(page(), before)

    def test_staff_roles_cannot_use_student_attempt_pages(self):  # OEP-SR-003
        attempt = self.attempt_for(self.student)
        admin = make_user("admin", User.Role.ADMINISTRATOR)
        start = ("get", reverse("exams:start_attempt", args=[self.exam.pk]))
        for user in (self.teacher, admin):
            self.client.force_login(user)
            for name, (method, url) in {"start": start, **self.urls(attempt)}.items():
                with self.subTest(role=user.role, page=name):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 403)
