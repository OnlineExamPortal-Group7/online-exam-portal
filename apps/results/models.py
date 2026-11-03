from django.conf import settings
from django.db import models


class Result(models.Model):
    attempt = models.OneToOneField(
        "exams.ExamAttempt",
        on_delete=models.CASCADE,
        related_name="result",
    )
    score = models.PositiveIntegerField(default=0)
    total_marks = models.PositiveIntegerField(default=0)
    evaluated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-evaluated_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score__lte=models.F("total_marks")),
                name="result_score_not_above_total",
            )
        ]

    @property
    def percentage(self):
        if self.total_marks == 0:
            return 0
        return round((self.score / self.total_marks) * 100, 2)

    def __str__(self):
        return f"Result for attempt {self.attempt_id}: {self.score}/{self.total_marks}"


class ResultPublication(models.Model):
    """An exam's results are visible to students once this row exists (OEP-F-031)."""

    exam = models.OneToOneField(
        "exams.Exam",
        on_delete=models.CASCADE,
        related_name="result_publication",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_results",
    )
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return f"Results published for {self.exam}"
