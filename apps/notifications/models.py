
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class EmailNotification(models.Model):
    class NotificationType(models.TextChoices):
        EXAM_SCHEDULED = "exam_scheduled", "Exam Scheduled"
        RESULTS_PUBLISHED = "results_published", "Results Published"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    exam = models.ForeignKey(
        "exams.Exam",
        on_delete=models.CASCADE,
        related_name="email_notifications",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_notifications",
    )
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["exam", "recipient", "notification_type"],
                name="unique_exam_recipient_notification",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__gte=0),
                name="notification_attempt_count_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at"],
                name="notification_retry_idx",
            ),
            models.Index(
                fields=["status", "processing_started_at"],
                name="notification_processing_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.get_notification_type_display()} - "
            f"{self.recipient} - {self.get_status_display()}"
        )
