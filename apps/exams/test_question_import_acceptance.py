"""TC-QB-02 / AC-011 (OEP-F-011): bulk CSV import through the real login and upload pages."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.administration.models import Course

from .models import Choice, Question

PASSWORD = "Str0ng-pass-123"
HEADER = "course,topic,difficulty,question,option_1,option_2,option_3,option_4,correct,marks"
DIFFICULTIES = ["easy", "medium", "hard"]


def valid_row(n):
    options = 2 + n % 3  # 2, 3 or 4 options
    values = [f"Answer {n}.{k}" for k in range(1, options + 1)] + [""] * (4 - options)
    correct = 1 + n % options
    return ",".join(
        ["CS101", f"Topic {n % 5}", DIFFICULTIES[n % 3], f"Question number {n}?",
         *values, str(correct), str(1 + n % 4)]
    )


class TCQB02BulkCsvImportTest(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            "teacher", "teacher@example.com", PASSWORD, role=User.Role.INSTRUCTOR
        )
        Course.objects.create(name="Programming", code="CS101", instructor=self.teacher)
        self.client = Client()
        self.client.post(
            reverse("accounts:login"), {"username": "teacher@example.com", "password": PASSWORD}
        )
        self.url = reverse("exams:question_import")

    def upload(self, rows):
        data = "\n".join([HEADER, *rows]).encode()
        csv_file = SimpleUploadedFile("questions.csv", data, content_type="text/csv")
        return self.client.post(self.url, {"file": csv_file}, follow=True)

    def test_valid_csv_of_50_questions_creates_50_entries(self):
        response = self.upload([valid_row(n) for n in range(50)])

        self.assertContains(response, "Imported 50 questions.")
        self.assertEqual(Question.objects.count(), 50)
        for question in Question.objects.prefetch_related("choices"):
            n = int(question.text.split()[-1].rstrip("?"))
            with self.subTest(question=n):
                self.assertEqual(question.created_by, self.teacher)
                self.assertEqual(question.topic, f"Topic {n % 5}")
                self.assertEqual(question.difficulty, DIFFICULTIES[n % 3])
                self.assertEqual(question.choices.count(), 2 + n % 3)
                correct = [c.text for c in question.choices.all() if c.is_correct]
                self.assertEqual(correct, [f"Answer {n}.{1 + n % (2 + n % 3)}"])

    def test_malformed_rows_are_reported_not_silently_dropped(self):
        rows = [valid_row(n) for n in range(50)]
        rows[4] = "CS101,,easy,No topic?,A,B,,,1,1"           # spreadsheet row 6
        rows[19] = "CS101,Loops,easy,Two answers?,A,B,,,\"1,2\",1"  # row 21
        rows[48] = "CS101,Loops,impossible,Bad level?,A,B,,,1,1"  # row 50

        response = self.upload(rows)

        self.assertContains(response, "Nothing was imported.")
        self.assertContains(response, "Row 6: topic is empty.")
        self.assertContains(response, "Row 21: correct must be the number of the one correct")
        self.assertContains(response, "Row 50: difficulty must be one of: easy, medium, hard.")
        self.assertEqual(Question.objects.count(), 0)
        self.assertEqual(Choice.objects.count(), 0)

    def test_fixed_file_can_be_uploaded_again_without_duplicates(self):
        rows = [valid_row(n) for n in range(50)]
        good_row = rows[10]
        rows[10] = "CS101,Loops,easy,Broken?,A,B,,,9,1"
        self.upload(rows)
        self.assertEqual(Question.objects.count(), 0)

        rows[10] = good_row
        response = self.upload(rows)
        self.assertContains(response, "Imported 50 questions.")
        self.assertEqual(Question.objects.count(), 50)
