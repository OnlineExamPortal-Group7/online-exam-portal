"""Out-of-order autosave requests are rejected on the server (OEP-F-022)."""
from django.urls import reverse

from .models import Answer, ExamAttempt
from .test_autosave import AutosaveTestBase


class AutosaveOrderingTestBase(AutosaveTestBase):
    """Helpers for posting versioned autosaves. Defines no tests."""

    def setUp(self):
        self.attempt = self.create_attempt()
        self.client.force_login(self.student)
        self.question = self.questions[0]
        self.option_a = self.wrong[0]
        self.option_b = self.correct[0]

    def autosave(self, choice, seq=None):
        data = {
            "question_id": self.question.pk,
            "choice_id": choice.pk if choice else "",
        }
        if seq is not None:
            data["seq"] = seq
        return self.client.post(
            reverse("exams:autosave_answer", args=[self.attempt.pk]), data
        )

    def stored(self):
        return Answer.objects.get(attempt=self.attempt, question=self.question)

    def assert_stale(self, response, stored_seq):
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "stale")
        self.assertFalse(data["saved"])
        self.assertEqual(data["seq"], stored_seq)


class OutOfOrderAutosaveTests(AutosaveOrderingTestBase):
    """Only a request with a higher sequence number than the stored one is saved."""

    def test_first_save_with_no_stored_answer_creates_the_row(self):
        response = self.autosave(self.option_a, seq=1)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["saved"])
        self.assertEqual(data["status"], "saved")
        self.assertEqual(data["seq"], 1)
        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_a.pk)
        self.assertEqual(answer.autosave_seq, 1)

    def test_requests_in_order_are_all_saved(self):
        self.autosave(self.option_a, seq=1)
        response = self.autosave(self.option_b, seq=2)

        self.assertEqual(response.json()["status"], "saved")
        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 2)

    def test_older_request_arriving_late_does_not_overwrite_newer_answer(self):
        # The student changed A to B quickly and the server got B first.
        self.assertEqual(self.autosave(self.option_b, seq=2).json()["status"], "saved")

        response = self.autosave(self.option_a, seq=1)

        self.assert_stale(response, stored_seq=2)
        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 2)
        self.assertEqual(Answer.objects.filter(attempt=self.attempt).count(), 1)

    def test_equal_sequence_number_is_stale(self):
        self.autosave(self.option_b, seq=2)

        response = self.autosave(self.option_a, seq=2)

        self.assert_stale(response, stored_seq=2)
        self.assertEqual(self.stored().selected_choice_id, self.option_b.pk)

    def test_late_request_cannot_undo_a_cleared_answer(self):
        self.autosave(self.option_a, seq=1)
        self.autosave(None, seq=3)

        response = self.autosave(self.option_b, seq=2)

        self.assert_stale(response, stored_seq=3)
        self.assertIsNone(self.stored().selected_choice_id)

    def test_sequence_is_per_question(self):
        self.autosave(self.option_b, seq=5)
        other = self.questions[1]

        response = self.client.post(
            reverse("exams:autosave_answer", args=[self.attempt.pk]),
            {"question_id": other.pk, "choice_id": self.correct[1].pk, "seq": 1},
        )

        self.assertEqual(response.json()["status"], "saved")
        self.assertEqual(
            Answer.objects.get(attempt=self.attempt, question=other).autosave_seq, 1
        )

    def test_malformed_sequence_number_is_rejected(self):
        for seq in ("abc", "0", "-1", "1.5", str(2 ** 31)):
            response = self.autosave(self.option_a, seq=seq)
            self.assertEqual(response.status_code, 400, seq)
            self.assertFalse(response.json()["saved"])

        self.assertFalse(Answer.objects.filter(attempt=self.attempt).exists())

    def test_unversioned_save_does_not_lower_the_stored_number(self):
        self.autosave(self.option_a, seq=3)

        response = self.autosave(self.option_b)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "saved")
        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 3)


class ReloadContinuityTests(AutosaveOrderingTestBase):
    """After a reload the page continues numbering from the stored sequence."""

    def open_question(self, index=0):
        return self.client.get(
            reverse("exams:take_attempt", args=[self.attempt.pk]) + f"?q={index}"
        )

    def test_page_renders_stored_sequence_number(self):
        for seq in (1, 2, 3):
            self.autosave(self.option_a if seq % 2 else self.option_b, seq=seq)

        page = self.open_question(0)

        self.assertEqual(page.context["current_question"].autosave_seq, 3)
        self.assertContains(page, 'data-autosave-seq="3"')
        self.assertContains(page, 'name="autosave_seq"', count=2)

    def test_unanswered_question_renders_zero(self):
        page = self.open_question(1)

        self.assertEqual(page.context["current_question"].autosave_seq, 0)
        self.assertContains(page, 'data-autosave-seq="0"')

    def test_saves_after_reload_continue_from_stored_number(self):
        for seq in (1, 2, 3):
            self.autosave(self.option_a, seq=seq)

        # Reload: the page starts its counter at the rendered number.
        rendered = self.open_question(0).context["current_question"].autosave_seq

        response = self.autosave(self.option_b, seq=rendered + 1)

        self.assertEqual(response.json()["status"], "saved")
        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 4)

        # A request from before the reload that arrives now is still rejected.
        self.assert_stale(self.autosave(self.option_a, seq=3), stored_seq=4)
        self.assertEqual(self.stored().selected_choice_id, self.option_b.pk)


class FormSaveOrderingTests(AutosaveOrderingTestBase):
    """Save & Next and Submit raise the stored number so late autosaves lose."""

    def save_and_next(self, choice, seq=None):
        data = {
            "question_id": self.question.pk,
            "choice_id": choice.pk,
            "next_question": "1",
        }
        if seq is not None:
            data["autosave_seq"] = seq
        return self.client.post(
            reverse("exams:save_answer", args=[self.attempt.pk]), data
        )

    def test_late_autosave_after_save_and_next_does_not_change_answer(self):
        # A (seq 1) and B (seq 2) are still in flight when the student clicks
        # Save & Next with B selected; the form carries seq 2.
        response = self.save_and_next(self.option_b, seq=2)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.stored().autosave_seq, 2)

        self.assert_stale(self.autosave(self.option_a, seq=1), stored_seq=2)
        self.assertEqual(self.stored().selected_choice_id, self.option_b.pk)

    def test_form_save_never_lowers_the_stored_number(self):
        self.autosave(self.option_a, seq=5)

        self.save_and_next(self.option_b, seq=2)

        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 5)

    def test_form_save_without_sequence_keeps_stored_number(self):
        self.autosave(self.option_a, seq=4)

        self.save_and_next(self.option_b)

        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 4)

    def test_form_save_with_malformed_sequence_still_saves(self):
        self.autosave(self.option_a, seq=4)

        response = self.save_and_next(self.option_b, seq="abc")

        self.assertEqual(response.status_code, 302)
        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 4)

    def test_submit_stores_current_choice_with_its_sequence(self):
        self.autosave(self.option_a, seq=1)

        self.client.post(
            reverse("exams:submit_attempt", args=[self.attempt.pk]),
            {
                "question_id": self.question.pk,
                "choice_id": self.option_b.pk,
                "autosave_seq": 2,
            },
        )

        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, ExamAttempt.Status.SUBMITTED)
        answer = self.stored()
        self.assertEqual(answer.selected_choice_id, self.option_b.pk)
        self.assertEqual(answer.autosave_seq, 2)
