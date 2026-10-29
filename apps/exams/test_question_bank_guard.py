"""TC-QB-05 / AC-014 (OEP-F-014, OEP-SR-003): Students get HTTP 403 on every exams page
that is not one of their own exam-attempt pages.

The URLs are read from apps/exams/urls.py when the test runs, so pages added later
(for example the question bank) are checked automatically.
"""
import uuid

from django.test import TestCase
from django.urls import URLPattern, URLResolver, reverse

from apps.accounts.models import User

from . import urls as exam_urls

# Exams pages a Student may open. Each of these must only ever show the student's
# OWN running attempt (see AttemptAccessTest in test_access.py). Only add a URL
# name here if it is a page for students taking an exam; never for question-bank
# or answer-key pages.
STUDENT_ALLOWED_EXAM_URLS = {
    "exams:start_attempt",
    "exams:take_attempt",
    "exams:save_answer",
    "exams:submit_attempt",
}

SAMPLE_VALUES = {"int": 1, "str": "x", "slug": "x", "path": "x", "uuid": uuid.uuid4()}

HOW_TO_FIX = (
    "If this page shows question-bank data or answer keys, protect it with "
    "QuestionBankAccessMixin or @question_bank_required from apps/exams/access.py. "
    "If it is a page for a student's own exam attempt, add {name!r} to "
    "STUDENT_ALLOWED_EXAM_URLS in apps/exams/test_question_bank_guard.py."
)


def exam_urls_to_check(patterns=exam_urls.urlpatterns, prefix=f"{exam_urls.app_name}:"):
    """Yield (url name, url) for every exams route, with sample values for URL parameters."""
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            namespace = f"{pattern.namespace}:" if pattern.namespace else ""
            yield from exam_urls_to_check(pattern.url_patterns, prefix + namespace)
        elif isinstance(pattern, URLPattern):
            name = f"{prefix}{pattern.name}" if pattern.name else None
            converters = getattr(pattern.pattern, "converters", {})
            kwargs = {
                key: SAMPLE_VALUES.get(type(conv).__name__.replace("Converter", "").lower(), 1)
                for key, conv in converters.items()
            }
            yield name, (reverse(name, kwargs=kwargs) if name else str(pattern.pattern))


class TCQB05StudentQuestionBankAccessTest(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            "student", "student@example.com", "Str0ng-pass-123", role=User.Role.STUDENT
        )

    def test_every_exams_url_has_a_name(self):
        for name, url in exam_urls_to_check():
            with self.subTest(url=url):
                self.assertIsNotNone(
                    name, f"The exams route {url!r} has no name=, so it cannot be checked."
                )

    def test_student_gets_403_on_every_non_student_exams_page(self):
        self.client.force_login(self.student)
        checked = 0
        for name, url in exam_urls_to_check():
            if name in STUDENT_ALLOWED_EXAM_URLS:
                continue
            checked += 1
            for method in ("get", "post"):
                with self.subTest(url=url, method=method):
                    status = getattr(self.client, method)(url).status_code
                    self.assertEqual(
                        status, 403,
                        f"Student got HTTP {status} on {method.upper()} {url} ({name}), "
                        f"expected 403. " + HOW_TO_FIX.format(name=name),
                    )
        self.assertGreater(checked, 0, "No exams pages were checked.")

    def test_anonymous_visitors_are_sent_to_login_on_every_exams_page(self):
        for name, url in exam_urls_to_check():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(
                    response.status_code, 302,
                    f"Anonymous GET {url} ({name}) returned {response.status_code}, "
                    "expected a redirect to the login page.",
                )
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_allowed_list_only_names_existing_urls(self):
        existing = {name for name, _ in exam_urls_to_check()}
        for name in STUDENT_ALLOWED_EXAM_URLS:
            with self.subTest(name=name):
                self.assertIn(
                    name, existing,
                    f"{name!r} is in STUDENT_ALLOWED_EXAM_URLS but no such exams URL exists; "
                    "remove it from the list.",
                )
