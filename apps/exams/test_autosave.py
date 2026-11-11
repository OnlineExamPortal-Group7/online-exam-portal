"""Answer auto-save and persistence (OEP-F-022, TC-Exam-03)."""
import re
from datetime import timedelta

from django.test import Client, TestCase
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


class AutosaveEndpointTests(AutosaveTestBase):
    """POST exams/attempt/<id>/autosave/ returns a JSON acknowledgement."""

    def autosave(self, attempt, question_id, choice_id=""):
        return self.client.post(
            reverse("exams:autosave_answer", args=[attempt.pk]),
            {"question_id": question_id, "choice_id": choice_id},
        )

    def test_autosave_stores_answer_and_acknowledges(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.autosave(attempt, self.questions[0].pk, self.correct[0].pk)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["saved"])
        self.assertEqual(data["question_id"], self.questions[0].pk)
        self.assertEqual(data["choice_id"], self.correct[0].pk)
        self.assertIn("saved_at", data)
        answer = Answer.objects.get(attempt=attempt, question=self.questions[0])
        self.assertEqual(answer.selected_choice_id, self.correct[0].pk)

    def test_autosave_overwrites_and_clears_the_same_answer(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)
        question = self.questions[1]

        self.autosave(attempt, question.pk, self.wrong[1].pk)
        self.autosave(attempt, question.pk, self.correct[1].pk)
        answer = Answer.objects.get(attempt=attempt, question=question)
        self.assertEqual(answer.selected_choice_id, self.correct[1].pk)

        response = self.autosave(attempt, question.pk, "")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["choice_id"])
        answer.refresh_from_db()
        self.assertIsNone(answer.selected_choice_id)
        self.assertEqual(Answer.objects.filter(attempt=attempt).count(), 1)

    def test_invalid_question_or_choice_returns_400(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        for question_id, choice_id in (
            ("", ""),
            ("abc", ""),
            (self.questions[0].pk, self.correct[1].pk),
            (self.questions[0].pk, "999999"),
        ):
            response = self.autosave(attempt, question_id, choice_id)
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json()["saved"])

        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())

    def test_get_is_not_allowed(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.client.get(reverse("exams:autosave_answer", args=[attempt.pk]))

        self.assertEqual(response.status_code, 405)

    def test_submitted_attempt_cannot_autosave(self):
        attempt = self.create_attempt(status=ExamAttempt.Status.SUBMITTED)
        self.client.force_login(self.student)

        response = self.autosave(attempt, self.questions[0].pk, self.correct[0].pk)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["saved"])
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())

    def test_expired_attempt_is_timed_out_scored_and_rejected(self):
        attempt = self.create_attempt(deadline=timezone.now() - timedelta(seconds=1))
        self.client.force_login(self.student)

        response = self.autosave(attempt, self.questions[0].pk, self.correct[0].pk)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["saved"])
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)
        self.assertTrue(hasattr(attempt, "result"))
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())

    def test_student_cannot_autosave_into_another_students_attempt(self):
        attempt = self.create_attempt(student=self.other_student)
        self.client.force_login(self.student)

        response = self.autosave(attempt, self.questions[0].pk, self.correct[0].pk)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())

    def test_instructor_cannot_autosave(self):
        attempt = self.create_attempt()
        self.client.force_login(self.instructor)

        response = self.autosave(attempt, self.questions[0].pk, self.correct[0].pk)

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        attempt = self.create_attempt()

        response = self.autosave(attempt, self.questions[0].pk, self.correct[0].pk)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())


class AutosavePageTests(AutosaveTestBase):
    """The exam page wires choice changes to the autosave endpoint."""

    def test_page_exposes_autosave_url_and_status_region(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.client.get(reverse("exams:take_attempt", args=[attempt.pk]))

        autosave_url = reverse("exams:autosave_answer", args=[attempt.pk])
        self.assertContains(response, f'data-autosave-url="{autosave_url}"')
        self.assertContains(response, 'id="autosave-status"')
        self.assertContains(response, 'role="status"')
        self.assertContains(response, "autosaveAnswer(choiceId)")

    def test_no_js_navigation_form_is_unchanged(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.client.get(reverse("exams:take_attempt", args=[attempt.pk]))

        save_url = reverse("exams:save_answer", args=[attempt.pk])
        self.assertContains(response, f'action="{save_url}"')
        self.assertContains(response, 'name="question_id"')
        self.assertContains(response, 'name="choice_id"')
        self.assertContains(response, 'name="next_question"')

    def test_autosave_accepts_csrf_token_from_the_page(self):
        attempt = self.create_attempt()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)

        page = client.get(reverse("exams:take_attempt", args=[attempt.pk]))
        token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()
        ).group(1)
        url = reverse("exams:autosave_answer", args=[attempt.pk])
        data = {"question_id": self.questions[0].pk, "choice_id": self.correct[0].pk}

        self.assertEqual(client.post(url, data).status_code, 403)
        response = client.post(url, data, HTTP_X_CSRFTOKEN=token)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["saved"])
        self.assertTrue(
            Answer.objects.filter(
                attempt=attempt, selected_choice=self.correct[0]
            ).exists()
        )


class SubmitCarriesCurrentAnswerTests(AutosaveTestBase):
    """Submitting keeps the choice on the question the student was viewing."""

    def submit(self, attempt, data):
        return self.client.post(
            reverse("exams:submit_attempt", args=[attempt.pk]), data
        )

    def test_manual_submit_stores_and_scores_current_choice(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        response = self.submit(
            attempt,
            {"question_id": self.questions[1].pk, "choice_id": self.correct[1].pk},
        )

        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.SUBMITTED)
        self.assertTrue(
            Answer.objects.filter(
                attempt=attempt, selected_choice=self.correct[1]
            ).exists()
        )
        self.assertEqual(attempt.result.score, self.questions[1].marks)

    def test_empty_choice_on_submit_does_not_clear_saved_answer(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt, question=self.questions[0], selected_choice=self.correct[0]
        )
        self.client.force_login(self.student)

        self.submit(attempt, {"question_id": self.questions[0].pk, "choice_id": ""})

        answer = Answer.objects.get(attempt=attempt, question=self.questions[0])
        self.assertEqual(answer.selected_choice_id, self.correct[0].pk)

    def test_invalid_choice_on_submit_still_submits(self):
        attempt = self.create_attempt()
        self.client.force_login(self.student)

        self.submit(
            attempt,
            {"question_id": self.questions[0].pk, "choice_id": self.correct[1].pk},
        )

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.SUBMITTED)
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())
        self.assertEqual(attempt.result.score, 0)

    def test_submit_after_deadline_ignores_carried_choice(self):
        attempt = self.create_attempt(deadline=timezone.now() - timedelta(seconds=1))
        self.client.force_login(self.student)

        self.submit(
            attempt,
            {"question_id": self.questions[0].pk, "choice_id": self.correct[0].pk},
        )

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, ExamAttempt.Status.TIMED_OUT)
        self.assertFalse(Answer.objects.filter(attempt=attempt).exists())
        self.assertEqual(attempt.result.score, 0)

    def test_submit_form_carries_current_question_and_saved_choice(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt, question=self.questions[0], selected_choice=self.wrong[0]
        )
        self.client.force_login(self.student)

        response = self.client.get(
            reverse("exams:take_attempt", args=[attempt.pk]) + "?q=0"
        )

        content = response.content.decode()
        submit_form = content[content.index('id="submit-form"'):]
        self.assertIn(f'name="question_id" value="{self.questions[0].pk}"', submit_form)
        self.assertRegex(
            submit_form,
            rf'id="submit-choice-id"\s+value="{self.wrong[0].pk}"',
        )


class ResumeAttemptTests(AutosaveTestBase):
    """Reopening an attempt resumes where the student left off."""

    def open_attempt(self, attempt, query=""):
        self.client.force_login(self.student)
        return self.client.get(
            reverse("exams:take_attempt", args=[attempt.pk]) + query
        )

    def test_reopening_resumes_at_first_unanswered_question(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt, question=self.questions[0], selected_choice=self.correct[0]
        )

        response = self.open_attempt(attempt)

        self.assertEqual(response.context["question_index"], 1)
        self.assertContains(response, self.questions[1].text)

    def test_answer_row_without_choice_counts_as_unanswered(self):
        attempt = self.create_attempt()
        Answer.objects.create(attempt=attempt, question=self.questions[0])

        response = self.open_attempt(attempt)

        self.assertEqual(response.context["question_index"], 0)
        self.assertEqual(response.context["answered_count"], 0)

    def test_fully_answered_attempt_opens_at_first_question(self):
        attempt = self.create_attempt()
        for question, choice in zip(self.questions, self.correct):
            Answer.objects.create(attempt=attempt, question=question, selected_choice=choice)

        response = self.open_attempt(attempt)

        self.assertEqual(response.context["question_index"], 0)

    def test_explicit_question_parameter_is_respected(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt, question=self.questions[0], selected_choice=self.correct[0]
        )

        response = self.open_attempt(attempt, "?q=0")

        self.assertEqual(response.context["question_index"], 0)

    def test_start_attempt_resumes_existing_attempt_at_unanswered_question(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt, question=self.questions[0], selected_choice=self.correct[0]
        )
        self.client.force_login(self.student)

        response = self.client.get(
            reverse("exams:start_attempt", args=[self.exam.pk]), follow=True
        )

        self.assertEqual(response.context["attempt"].pk, attempt.pk)
        self.assertEqual(response.context["question_index"], 1)

    def test_answered_questions_are_marked_in_navigation(self):
        attempt = self.create_attempt()
        Answer.objects.create(
            attempt=attempt, question=self.questions[0], selected_choice=self.correct[0]
        )

        response = self.open_attempt(attempt)

        self.assertEqual(response.context["answered_count"], 1)
        self.assertContains(response, 'aria-label="Go to question 1 (answered)"')
        self.assertContains(response, 'aria-label="Go to question 2"')
        self.assertContains(response, 'class=" answered"')
        self.assertRegex(
            response.content.decode(),
            r'<span id="answered-count">1</span>\s+of 2 answered',
        )
