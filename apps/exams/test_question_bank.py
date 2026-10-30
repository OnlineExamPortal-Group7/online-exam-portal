"""Issue #7: MCQ question-bank management (OEP-F-010, OEP-F-014).

TC-QB-01  a saved question stores all fields and appears in the question-bank list.
TC-QB-05  a student request to any question-bank page gets HTTP 403.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.models import Course

from .models import Answer, Choice, Exam, ExamAttempt, ExamQuestion, Question

PASSWORD = "Str0ng-pass-123"
MAX_FORMS = 6


def make_user(username, role):
    return User.objects.create_user(username, f"{username}@example.com", PASSWORD, role=role)


def make_question(course, creator, text="What is 2 + 2?", choices=None, **fields):
    question = Question.objects.create(course=course, created_by=creator, text=text, **fields)
    for choice_text, correct in choices or [("4", True), ("5", False)]:
        Choice.objects.create(question=question, text=choice_text, is_correct=correct)
    return question


def create_data(course, choices, **overrides):
    """POST data for the create form with up to six (text, is_correct) choices."""
    data = {
        "course": course.pk,
        "text": "Which planet is closest to the Sun?",
        "difficulty": "easy",
        "marks": 2,
        "choices-TOTAL_FORMS": MAX_FORMS,
        "choices-INITIAL_FORMS": 0,
        "choices-MIN_NUM_FORMS": 0,
        "choices-MAX_NUM_FORMS": MAX_FORMS,
    }
    for index in range(MAX_FORMS):
        text, correct = choices[index] if index < len(choices) else ("", False)
        data[f"choices-{index}-text"] = text
        if correct:
            data[f"choices-{index}-is_correct"] = "on"
    data.update(overrides)
    return data


def edit_data(question, choices=None, **overrides):
    """POST data for the edit form; `choices` is (text, is_correct, remove) per existing row."""
    existing = list(question.choices.all())
    data = {
        "course": question.course_id,
        "text": question.text,
        "difficulty": question.difficulty,
        "marks": question.marks,
        "choices-TOTAL_FORMS": MAX_FORMS,
        "choices-INITIAL_FORMS": len(existing),
        "choices-MIN_NUM_FORMS": 0,
        "choices-MAX_NUM_FORMS": MAX_FORMS,
    }
    for index in range(MAX_FORMS):
        if index < len(existing):
            choice = existing[index]
            text, correct, remove = (choices or {}).get(
                index, (choice.text, choice.is_correct, False)
            )
            data[f"choices-{index}-id"] = choice.pk
            data[f"choices-{index}-question"] = question.pk
            if remove:
                data[f"choices-{index}-DELETE"] = "on"
        else:
            text, correct = (choices or {}).get(index, ("", False))[:2]
        data[f"choices-{index}-text"] = text
        if correct:
            data[f"choices-{index}-is_correct"] = "on"
    data.update(overrides)
    return data


class QuestionBankTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.instructor = make_user("inst1", User.Role.INSTRUCTOR)
        cls.other_instructor = make_user("inst2", User.Role.INSTRUCTOR)
        cls.admin = make_user("boss", User.Role.ADMINISTRATOR)
        cls.student = make_user("stud", User.Role.STUDENT)
        cls.course = Course.objects.create(name="Maths", code="MA101", instructor=cls.instructor)
        cls.other_course = Course.objects.create(
            name="Physics", code="PH101", instructor=cls.other_instructor
        )
        cls.question = make_question(cls.course, cls.instructor)
        cls.other_question = make_question(
            cls.other_course, cls.other_instructor, text="What is the speed of light?"
        )

    def sign_in(self, user):
        self.client.login(username=user.email, password=PASSWORD)


class AccessTest(QuestionBankTestCase):
    """TC-QB-05 / AC-014 / OEP-SR-003: nobody but instructors and administrators gets in."""

    def pages(self):
        pk = self.question.pk
        return [
            reverse("exams:question_list"),
            reverse("exams:question_create"),
            reverse("exams:question_detail", args=[pk]),
            reverse("exams:question_update", args=[pk]),
            reverse("exams:question_delete", args=[pk]),
        ]

    def test_student_gets_403_on_every_page_and_method(self):
        self.sign_in(self.student)
        for url in self.pages():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_anonymous_user_is_sent_to_login(self):
        for url in self.pages():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_student_cannot_change_data_with_post(self):
        self.sign_in(self.student)
        self.client.post(reverse("exams:question_delete", args=[self.question.pk]))
        self.assertTrue(Question.objects.filter(pk=self.question.pk).exists())


class ListTest(QuestionBankTestCase):
    def test_instructor_sees_only_own_course_questions(self):
        self.sign_in(self.instructor)
        response = self.client.get(reverse("exams:question_list"))
        self.assertEqual(list(response.context["questions"]), [self.question])

    def test_administrator_sees_all_questions(self):
        self.sign_in(self.admin)
        response = self.client.get(reverse("exams:question_list"))
        self.assertCountEqual(
            response.context["questions"], [self.question, self.other_question]
        )

    def test_filters_by_difficulty_course_and_text(self):
        hard = make_question(self.course, self.instructor, "Prove it", difficulty="hard")
        self.sign_in(self.admin)
        url = reverse("exams:question_list")
        by_difficulty = self.client.get(url, {"difficulty": "hard"})
        self.assertEqual(list(by_difficulty.context["questions"]), [hard])
        by_course = self.client.get(url, {"course": self.other_course.pk})
        self.assertEqual(list(by_course.context["questions"]), [self.other_question])
        by_text = self.client.get(url, {"q": "speed"})
        self.assertEqual(list(by_text.context["questions"]), [self.other_question])

    def test_instructor_cannot_filter_by_someone_elses_course(self):
        self.sign_in(self.instructor)
        response = self.client.get(
            reverse("exams:question_list"), {"course": self.other_course.pk}
        )
        self.assertNotIn(self.other_question, response.context["questions"])

    def test_list_is_paginated(self):
        for number in range(25):
            make_question(self.course, self.instructor, f"Extra {number}")
        self.sign_in(self.instructor)
        response = self.client.get(reverse("exams:question_list"))
        self.assertEqual(len(response.context["questions"]), 20)
        self.assertTrue(response.context["is_paginated"])
        second = self.client.get(reverse("exams:question_list"), {"page": 2})
        self.assertEqual(second.status_code, 200)


class DetailTest(QuestionBankTestCase):
    def test_detail_shows_correct_answer_to_instructor(self):
        self.sign_in(self.instructor)
        response = self.client.get(reverse("exams:question_detail", args=[self.question.pk]))
        self.assertContains(response, "(correct)")

    def test_other_instructors_question_is_not_found(self):  # OEP-SR-004 style isolation
        self.sign_in(self.instructor)
        url = reverse("exams:question_detail", args=[self.other_question.pk])
        self.assertEqual(self.client.get(url).status_code, 404)


class CreateTest(QuestionBankTestCase):
    url = None

    def setUp(self):
        self.url = reverse("exams:question_create")
        self.sign_in(self.instructor)

    def test_form_page_loads(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_valid_question_is_saved_and_listed(self):  # TC-QB-01 / AC-010
        data = create_data(
            self.course,
            [("Mercury", True), ("Venus", False), ("Earth", False), ("Mars", False)],
        )
        response = self.client.post(self.url, data)
        question = Question.objects.get(text=data["text"])
        self.assertRedirects(
            response, reverse("exams:question_detail", args=[question.pk])
        )
        self.assertEqual(question.created_by, self.instructor)
        self.assertEqual(question.course, self.course)
        self.assertEqual(question.difficulty, "easy")
        self.assertEqual(question.marks, 2)
        self.assertEqual(question.question_type, Question.QuestionType.MCQ)
        self.assertEqual(
            [(c.text, c.is_correct) for c in question.choices.all()],
            [("Mercury", True), ("Venus", False), ("Earth", False), ("Mars", False)],
        )
        listing = self.client.get(reverse("exams:question_list"))
        self.assertIn(question, listing.context["questions"])

    def test_two_and_six_choices_are_accepted(self):
        for count in (2, 6):
            with self.subTest(choices=count):
                choices = [(f"Option {i}", i == 0) for i in range(count)]
                data = create_data(self.course, choices, text=f"Question with {count}")
                self.client.post(self.url, data)
                self.assertEqual(
                    Question.objects.get(text=f"Question with {count}").choices.count(), count
                )

    def assert_rejected(self, data, message=None):
        before = Question.objects.count()
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Question.objects.count(), before)
        self.assertEqual(Choice.objects.filter(question__text=data["text"]).count(), 0)
        if message:
            self.assertContains(response, message)

    def test_fewer_than_two_choices_is_rejected(self):
        self.assert_rejected(create_data(self.course, [("Only one", True)]), "between 2 and 6")

    def test_no_choices_is_rejected(self):
        self.assert_rejected(create_data(self.course, []), "between 2 and 6")

    def test_more_than_six_choices_is_rejected(self):
        data = create_data(self.course, [(f"Opt {i}", i == 0) for i in range(6)])
        data["choices-TOTAL_FORMS"] = 7
        data["choices-6-text"] = "Seventh"
        self.assert_rejected(data, "between 2 and 6")

    def test_no_correct_choice_is_rejected(self):
        self.assert_rejected(
            create_data(self.course, [("A", False), ("B", False)]), "exactly one"
        )

    def test_two_correct_choices_is_rejected(self):
        self.assert_rejected(create_data(self.course, [("A", True), ("B", True)]), "exactly one")

    def test_duplicate_choices_are_rejected(self):
        self.assert_rejected(
            create_data(self.course, [("Same", True), ("  same ", False)]), "different"
        )

    def test_correct_flag_on_blank_choice_is_rejected(self):
        data = create_data(self.course, [("A", True), ("B", False)])
        data["choices-3-is_correct"] = "on"
        self.assert_rejected(data)

    def test_whitespace_only_choice_counts_as_empty(self):
        data = create_data(self.course, [("A", True), ("   ", False)])
        self.assert_rejected(data, "between 2 and 6")

    def test_blank_question_text_is_rejected(self):
        self.assert_rejected(
            create_data(self.course, [("A", True), ("B", False)], text="   ")
        )

    def test_marks_must_be_at_least_one(self):
        self.assert_rejected(create_data(self.course, [("A", True), ("B", False)], marks=0))

    def test_invalid_difficulty_is_rejected(self):
        self.assert_rejected(
            create_data(self.course, [("A", True), ("B", False)], difficulty="impossible")
        )

    def test_instructor_cannot_use_another_instructors_course(self):
        data = create_data(self.other_course, [("A", True), ("B", False)])
        self.assert_rejected(data)

    def test_administrator_can_use_any_course(self):
        self.client.logout()
        self.sign_in(self.admin)
        data = create_data(self.other_course, [("A", True), ("B", False)], text="Admin made")
        self.client.post(self.url, data)
        self.assertEqual(Question.objects.get(text="Admin made").created_by, self.admin)

    def test_inactive_course_cannot_be_chosen(self):
        self.course.is_active = False
        self.course.save()
        self.assert_rejected(create_data(self.course, [("A", True), ("B", False)]))

    def test_nothing_is_saved_when_choices_are_invalid(self):
        before_choices = Choice.objects.count()
        self.client.post(self.url, create_data(self.course, [("A", True), ("B", True)]))
        self.assertEqual(Choice.objects.count(), before_choices)


class UpdateTest(QuestionBankTestCase):
    def setUp(self):
        self.url = reverse("exams:question_update", args=[self.question.pk])
        self.sign_in(self.instructor)

    def test_form_page_shows_existing_values(self):
        response = self.client.get(self.url)
        self.assertContains(response, "What is 2 + 2?")
        self.assertEqual(len(response.context["formset"].forms), MAX_FORMS)

    def test_edit_text_marks_and_difficulty(self):
        data = edit_data(self.question, text="What is 3 + 3?", marks=5, difficulty="hard")
        response = self.client.post(self.url, data)
        self.assertRedirects(
            response, reverse("exams:question_detail", args=[self.question.pk])
        )
        self.question.refresh_from_db()
        self.assertEqual(
            (self.question.text, self.question.marks, self.question.difficulty),
            ("What is 3 + 3?", 5, "hard"),
        )

    def test_change_which_choice_is_correct(self):
        data = edit_data(self.question, {0: ("4", False, False), 1: ("5", True, False)})
        self.client.post(self.url, data)
        self.assertEqual(
            [c.is_correct for c in self.question.choices.all()], [False, True]
        )

    def test_add_a_new_choice(self):
        data = edit_data(self.question, {2: ("6", False)})
        self.client.post(self.url, data)
        self.assertEqual(self.question.choices.count(), 3)

    def test_remove_a_choice_keeping_two(self):
        Choice.objects.create(question=self.question, text="6", is_correct=False)
        data = edit_data(self.question, {2: ("6", False, True)})
        self.client.post(self.url, data)
        self.assertEqual(self.question.choices.count(), 2)

    def test_removing_down_to_one_choice_is_rejected(self):
        data = edit_data(self.question, {1: ("5", False, True)})
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.question.choices.count(), 2)

    def test_removing_the_correct_choice_is_rejected(self):
        data = edit_data(self.question, {0: ("4", True, True)})
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.assertEqual(self.question.choices.count(), 2)

    def test_other_instructors_question_cannot_be_edited(self):
        url = reverse("exams:question_update", args=[self.other_question.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        data = edit_data(self.other_question, text="Hijacked")
        self.assertEqual(self.client.post(url, data).status_code, 404)
        self.other_question.refresh_from_db()
        self.assertNotEqual(self.other_question.text, "Hijacked")

    def test_cannot_move_question_to_another_instructors_course(self):
        data = edit_data(self.question, course=self.other_course.pk)
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.question.refresh_from_db()
        self.assertEqual(self.question.course, self.course)

    def test_answered_question_cannot_be_edited(self):
        make_answered(self.question, self.student)
        self.assertRedirects(
            self.client.get(self.url),
            reverse("exams:question_detail", args=[self.question.pk]),
        )
        response = self.client.post(self.url, edit_data(self.question, text="Changed"))
        self.assertEqual(response.status_code, 302)
        self.question.refresh_from_db()
        self.assertEqual(self.question.text, "What is 2 + 2?")


def make_exam(course, creator, **fields):
    now = timezone.now()
    defaults = {
        "title": "Midterm",
        "start_time": now,
        "end_time": now + timezone.timedelta(hours=2),
        "duration_minutes": 60,
    }
    defaults.update(fields)
    return Exam.objects.create(course=course, created_by=creator, **defaults)


def make_answered(question, student):
    exam = make_exam(question.course, question.created_by)
    ExamQuestion.objects.create(exam=exam, question=question, position=1)
    attempt = ExamAttempt.objects.create(
        exam=exam, student=student, deadline_at=exam.end_time
    )
    Answer.objects.create(
        attempt=attempt, question=question, selected_choice=question.choices.first()
    )


class DeleteTest(QuestionBankTestCase):
    def setUp(self):
        self.url = reverse("exams:question_delete", args=[self.question.pk])
        self.sign_in(self.instructor)

    def test_confirmation_page_does_not_delete(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Question.objects.filter(pk=self.question.pk).exists())

    def test_post_deletes_question_and_its_choices(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("exams:question_list"))
        self.assertFalse(Question.objects.filter(pk=self.question.pk).exists())
        self.assertFalse(Choice.objects.filter(question_id=self.question.pk).exists())

    def test_question_used_in_an_exam_is_not_deleted(self):
        exam = make_exam(self.course, self.instructor)
        ExamQuestion.objects.create(exam=exam, question=self.question, position=1)
        response = self.client.post(self.url)
        self.assertRedirects(
            response, reverse("exams:question_detail", args=[self.question.pk])
        )
        self.assertTrue(Question.objects.filter(pk=self.question.pk).exists())

    def test_answered_question_is_not_deleted(self):
        make_answered(self.question, self.student)
        self.client.post(self.url)
        self.assertTrue(Question.objects.filter(pk=self.question.pk).exists())
        self.assertEqual(Answer.objects.count(), 1)

    def test_other_instructors_question_cannot_be_deleted(self):
        url = reverse("exams:question_delete", args=[self.other_question.pk])
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(Question.objects.filter(pk=self.other_question.pk).exists())

    def test_administrator_can_delete_any_unused_question(self):
        self.client.logout()
        self.sign_in(self.admin)
        url = reverse("exams:question_delete", args=[self.other_question.pk])
        self.client.post(url)
        self.assertFalse(Question.objects.filter(pk=self.other_question.pk).exists())
