from types import SimpleNamespace

from django.test import SimpleTestCase

from .question_import import MAX_ROWS, parse_questions

HEADER = "course,topic,difficulty,question,option_1,option_2,option_3,option_4,correct,marks"
VALID_ROW = "CS101,Loops,easy,What does a for loop do?,Repeats code,Ends a program,,,1,2"
COURSES = {"CS101": SimpleNamespace(pk=1, code="CS101")}


def parse(*rows, header=HEADER, courses=COURSES):
    return parse_questions("\n".join([header, *rows]).encode("utf-8"), courses)


def messages(result):
    return [str(error) for error in result.errors]


class ParseValidFileTest(SimpleTestCase):  # OEP-F-011
    def test_valid_row_is_parsed(self):
        result = parse(VALID_ROW)
        self.assertTrue(result.is_valid)
        question = result.questions[0]
        self.assertEqual(question.row, 2)
        self.assertEqual(question.course, COURSES["CS101"])
        self.assertEqual(question.topic, "Loops")
        self.assertEqual(question.difficulty, "easy")
        self.assertEqual(question.options, ["Repeats code", "Ends a program"])
        self.assertEqual(question.correct_index, 0)
        self.assertEqual(question.marks, 2)

    def test_header_and_values_are_trimmed_and_case_insensitive(self):
        header = " Course ,TOPIC,Difficulty,Question,Option_1,Option_2,Correct"
        result = parse(" cs101 , Loops , MEDIUM ,Q?, A , B ,2", header=header)
        self.assertTrue(result.is_valid, messages(result))
        self.assertEqual(result.questions[0].difficulty, "medium")
        self.assertEqual(result.questions[0].options, ["A", "B"])

    def test_marks_default_to_one_and_six_options_are_allowed(self):
        header = "course,topic,difficulty,question," + ",".join(
            f"option_{n}" for n in range(1, 7)
        ) + ",correct"
        result = parse("CS101,T,hard,Q?,a,b,c,d,e,f,6", header=header)
        self.assertTrue(result.is_valid, messages(result))
        self.assertEqual(result.questions[0].marks, 1)
        self.assertEqual(result.questions[0].correct_index, 5)

    def test_excel_utf8_bom_and_quoted_commas_are_handled(self):
        data = ("﻿" + HEADER + '\nCS101,Loops,easy,"Pick one, please",A,B,,,2,1').encode()
        result = parse_questions(data, COURSES)
        self.assertTrue(result.is_valid, messages(result))
        self.assertEqual(result.questions[0].text, "Pick one, please")

    def test_blank_lines_are_ignored(self):
        result = parse(VALID_ROW, "", ",,,,,,,,,", VALID_ROW.replace("What", "Why"))
        self.assertTrue(result.is_valid, messages(result))
        self.assertEqual([q.row for q in result.questions], [2, 5])


class RowErrorTest(SimpleTestCase):  # AC-011: bad rows are reported with row number + reason
    def assertRowError(self, row, expected):
        result = parse(row)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.questions, [])
        found = [m for m in messages(result) if m.startswith("Row 2: ") and expected in m]
        self.assertTrue(found, messages(result))

    def test_each_rule_is_reported(self):
        cases = {
            ",Loops,easy,Q?,A,B,,,1,1": "course is empty",
            "XX999,Loops,easy,Q?,A,B,,,1,1": "course 'XX999' is not one of your active courses",
            "CS101,,easy,Q?,A,B,,,1,1": "topic is empty",
            f"CS101,{'t' * 101},easy,Q?,A,B,,,1,1": "topic is longer than 100",
            "CS101,Loops,tricky,Q?,A,B,,,1,1": "difficulty must be one of: easy, medium, hard",
            "CS101,Loops,easy,,A,B,,,1,1": "question is empty",
            "CS101,Loops,easy,Q?,A,,,,1,1": "needs at least 2 options",
            "CS101,Loops,easy,Q?,A,,C,,1,1": "option_2 is empty but a later option is filled",
            "CS101,Loops,easy,Q?,A,a,,,1,1": "two options have the same text",
            "CS101,Loops,easy,Q?,A,B,,,,1": "correct must be the number of the one correct",
            "CS101,Loops,easy,Q?,A,B,,,\"1,2\",1": "correct must be the number of the one correct",
            "CS101,Loops,easy,Q?,A,B,,,3,1": "correct is 3 but there is no option_3",
            "CS101,Loops,easy,Q?,A,B,,,0,1": "correct is 0 but there is no option_0",
            "CS101,Loops,easy,Q?,A,B,,,1,0": "marks must be a whole number of at least 1",
            "CS101,Loops,easy,Q?,A,B,,,1,1,extra": "has more values than columns",
        }
        for row, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertRowError(row, expected)

    def test_all_problems_in_a_row_are_listed(self):
        result = parse("CS101,,tricky,,A,,,,5,0")
        self.assertEqual(messages(result), [
            "Row 2: topic is empty.",
            "Row 2: difficulty must be one of: easy, medium, hard.",
            "Row 2: question is empty.",
            "Row 2: needs at least 2 options.",
            "Row 2: correct is 5 but there is no option_5.",
            "Row 2: marks must be a whole number of at least 1.",
        ])

    def test_every_bad_row_is_reported_and_nothing_is_kept(self):
        result = parse(VALID_ROW, "CS101,,easy,Q?,A,B,,,1,1", VALID_ROW.replace("What", "How"),
                       "CS101,Loops,easy,Q?,A,B,,,9,1")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.questions, [])
        self.assertEqual([error.row for error in result.errors], [3, 5])

    def test_duplicate_question_in_the_file_is_reported(self):
        result = parse(VALID_ROW, VALID_ROW.replace("What", "what"))
        self.assertEqual(messages(result), ["Row 3: same question as row 2."])


class FileErrorTest(SimpleTestCase):
    def assertFileError(self, data, expected):
        result = parse_questions(data, COURSES)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.questions, [])
        self.assertTrue(any(expected in message for message in messages(result)), messages(result))

    def test_file_problems_are_reported(self):
        cases = [
            (b"", "The file is empty"),
            (HEADER.encode(), "The file has no questions"),
            ("course,topic\n".encode(), "Missing columns: difficulty, question"),
            ((HEADER + ",colour\n" + VALID_ROW + ",red").encode(), "Unknown columns: colour"),
            ((HEADER + ",topic\n").encode(), "appears more than once"),
            ("é".encode("latin-1"), "must be saved as UTF-8 CSV"),
            (b"x" * (1024 * 1024 + 1), "larger than 1024 KB"),
        ]
        for data, expected in cases:
            with self.subTest(expected=expected):
                self.assertFileError(data, expected)

    def test_too_many_rows(self):
        rows = [VALID_ROW.replace("What", f"Q{n}") for n in range(MAX_ROWS + 1)]
        self.assertFileError("\n".join([HEADER, *rows]).encode(), f"more than {MAX_ROWS} questions")

    def test_exactly_the_maximum_is_allowed(self):
        rows = [VALID_ROW.replace("What", f"Q{n}") for n in range(MAX_ROWS)]
        result = parse(*rows)
        self.assertTrue(result.is_valid, messages(result)[:3])
        self.assertEqual(len(result.questions), MAX_ROWS)
