"""Parse and validate a CSV file of MCQ questions (OEP-F-011, rules from OEP-F-010).

This module only reads the file. It does not touch the database, so every row
can be checked and reported before anything is saved.

CSV columns (first row is the header, names are case-insensitive):
    course, topic, difficulty, question, option_1 ... option_6, correct, marks
`option_3` to `option_6` and `marks` are optional. `correct` is the number of
the one correct option. Row numbers in errors match the spreadsheet row
(the header is row 1).
"""
import csv
import io
from dataclasses import dataclass, field

from .models import Question

MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 500
MIN_OPTIONS, MAX_OPTIONS = 2, 6
MAX_TOPIC_LENGTH = 100

OPTION_COLUMNS = [f"option_{n}" for n in range(1, MAX_OPTIONS + 1)]
REQUIRED_COLUMNS = ["course", "topic", "difficulty", "question", "option_1", "option_2", "correct"]
ALLOWED_COLUMNS = set(REQUIRED_COLUMNS + OPTION_COLUMNS + ["marks"])


@dataclass
class ParsedQuestion:
    row: int
    course: object
    topic: str
    difficulty: str
    text: str
    options: list
    correct_index: int  # position in `options`, starting at 0
    marks: int


@dataclass
class RowError:
    row: int | None  # None for problems with the whole file
    message: str

    def __str__(self):
        return f"Row {self.row}: {self.message}" if self.row else self.message


@dataclass
class ParseResult:
    questions: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def is_valid(self):
        return bool(self.questions) and not self.errors


def parse_questions(data, courses):
    """Check every row of `data` (bytes) and return the questions and all errors.

    `courses` maps a course code to the Course the user may import into.
    """
    result = ParseResult()

    def file_error(message):
        result.errors.append(RowError(None, message))
        return result

    if len(data) > MAX_FILE_BYTES:
        return file_error(f"The file is larger than {MAX_FILE_BYTES // 1024} KB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return file_error("The file must be saved as UTF-8 CSV.")

    reader = csv.reader(io.StringIO(text))
    header = [name.strip().lower() for name in next(reader, [])]
    if not any(header):
        return file_error("The file is empty.")
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    unknown = [name for name in header if name not in ALLOWED_COLUMNS]
    if missing:
        file_error(f"Missing columns: {', '.join(missing)}.")
    if unknown:
        file_error(f"Unknown columns: {', '.join(unknown)}.")
    if len(set(header)) != len(header):
        file_error("A column name appears more than once.")
    if result.errors:
        return result

    courses = {code.lower(): course for code, course in courses.items()}
    seen = {}
    row_count = 0
    for row_number, values in enumerate(reader, start=2):
        if not any(value.strip() for value in values):
            continue  # blank line
        row_count += 1
        if row_count > MAX_ROWS:
            result.questions = []
            return file_error(f"The file has more than {MAX_ROWS} questions.")
        if len(values) > len(header):
            result.errors.append(RowError(row_number, "has more values than columns."))
            continue
        row = {name: value.strip() for name, value in zip(header, values)}
        question, problems = _parse_row(row_number, row, courses)
        result.errors += [RowError(row_number, problem) for problem in problems]
        if question is None:
            continue
        key = (question.course.pk, question.text.lower())
        if key in seen:
            result.errors.append(
                RowError(row_number, f"same question as row {seen[key]}.")
            )
            continue
        seen[key] = row_number
        result.questions.append(question)

    if not result.questions and not result.errors:
        file_error("The file has no questions.")
    if result.errors:
        result.questions = []
    return result


def _parse_row(row_number, row, courses):
    problems = []

    course = courses.get(row.get("course", "").lower())
    if not row.get("course"):
        problems.append("course is empty.")
    elif course is None:
        problems.append(f"course '{row['course']}' is not one of your active courses.")

    topic, topic_problem = _clean_topic(row.get("topic", ""))
    if topic_problem:
        problems.append(topic_problem)

    difficulty = row.get("difficulty", "").lower()
    if difficulty not in Question.Difficulty.values:
        allowed = ", ".join(Question.Difficulty.values)
        problems.append(f"difficulty must be one of: {allowed}.")

    text = row.get("question", "")
    if not text:
        problems.append("question is empty.")

    values = [row.get(name, "") for name in OPTION_COLUMNS]
    last_filled = max((n for n, value in enumerate(values) if value), default=-1)
    options = values[: last_filled + 1]
    if "" in options:
        problems.append(f"option_{options.index('') + 1} is empty but a later option is filled.")
    elif len(options) < MIN_OPTIONS:
        problems.append(f"needs at least {MIN_OPTIONS} options.")
    elif len({option.lower() for option in options}) != len(options):
        problems.append("two options have the same text.")

    correct_index = None
    correct = row.get("correct", "")
    if not correct.isdigit():
        problems.append("correct must be the number of the one correct option (e.g. 2).")
    elif not 1 <= int(correct) <= len(options):
        problems.append(f"correct is {correct} but there is no option_{correct}.")
    else:
        correct_index = int(correct) - 1

    marks = row.get("marks", "") or "1"
    if not marks.isdigit() or int(marks) < 1:
        problems.append("marks must be a whole number of at least 1.")

    if problems:
        return None, problems
    question = ParsedQuestion(
        row=row_number, course=course, topic=topic, difficulty=difficulty, text=text,
        options=options, correct_index=correct_index, marks=int(marks),
    )
    return question, []


def _clean_topic(value):
    """Topic / subject tag (OEP-F-010). Kept separate until the Question model has a topic field."""
    if not value:
        return value, "topic is empty."
    if len(value) > MAX_TOPIC_LENGTH:
        return value, f"topic is longer than {MAX_TOPIC_LENGTH} characters."
    return value, None
