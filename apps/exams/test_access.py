from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.views import View

from apps.accounts.models import User
from apps.administration.models import Course

from .access import QuestionBankAccessMixin, question_bank_required, questions_for
from .models import Question

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
