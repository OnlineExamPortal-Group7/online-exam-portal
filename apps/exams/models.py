# Models are added by later issues.
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Question(models.Model):
    class QuestionType(models.TextChoices):
        MCQ = "mcq", "Multiple Choice"

    class Difficulty(models.TextChoices):
        EASY = "easy", "Easy"
        MEDIUM = "medium", "Medium"
        HARD = "hard", "Hard"

    course = models.ForeignKey(
        "administration.Course",
        on_delete=models.PROTECT,
        related_name="questions",
    )
    text = models.TextField()
    question_type = models.CharField(
        max_length=10,
        choices=QuestionType.choices,
        default=QuestionType.MCQ,
    )
    difficulty = models.CharField(
        max_length=10,
        choices=Difficulty.choices,
        default=Difficulty.MEDIUM,
    )
    marks = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_questions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["course", "id"]

    def __str__(self):
        return f"Question {self.pk}: {self.text[:60]}"


class Choice(models.Model):
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="choices",
    )
    text = models.TextField()
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Choice {self.pk} for Question {self.question_id}"


class Exam(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        COMPLETED = "completed", "Completed"

    course = models.ForeignKey(
        "administration.Course",
        on_delete=models.PROTECT,
        related_name="exams",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_exams",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    total_marks = models.PositiveIntegerField(default=0)
    randomize_questions = models.BooleanField(default=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_time"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="exam_end_after_start",
            )
        ]

    def __str__(self):
        return self.title


class ExamQuestion(models.Model):
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name="exam_questions",
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT,
        related_name="exam_usages",
    )
    position = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["exam", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["exam", "question"],
                name="unique_question_per_exam",
            ),
            models.UniqueConstraint(
                fields=["exam", "position"],
                name="unique_exam_question_position",
            ),
        ]

    def __str__(self):
        return f"{self.exam}: Question {self.question_id}"


class ExamAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        SUBMITTED = "submitted", "Submitted"
        TIMED_OUT = "timed_out", "Timed Out"

    exam = models.ForeignKey(
        Exam,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="exam_attempts",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    deadline_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["exam", "student"]),
            models.Index(fields=["status", "deadline_at"]),
        ]

    def __str__(self):
        return f"{self.student} - {self.exam}"


class Answer(models.Model):
    attempt = models.ForeignKey(
        ExamAttempt,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT,
        related_name="submitted_answers",
    )
    selected_choice = models.ForeignKey(
        Choice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="selected_answers",
    )
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"],
                name="unique_answer_per_attempt_question",
            )
        ]

    def __str__(self):
        return f"Answer for attempt {self.attempt_id}"
