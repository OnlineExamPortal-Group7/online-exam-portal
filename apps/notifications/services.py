
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.administration.models import Enrollment
from apps.results.models import Result

from .models import EmailNotification


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BASE_RETRY_DELAY_MINUTES = 5
PROCESSING_TIMEOUT_MINUTES = 15


def queue_exam_scheduled_notifications(exam):
    """Queue exam notifications for enrolled students."""
    student_ids = (
        Enrollment.objects.filter(course=exam.course)
        .values_list("student_id", flat=True)
        .distinct()
    )

    return _create_notifications(
        exam=exam,
        student_ids=student_ids,
        notification_type=EmailNotification.NotificationType.EXAM_SCHEDULED,
    )


def queue_results_published_notifications(exam):
    """Queue result notifications for students with saved results."""
    student_ids = (
        Result.objects.filter(attempt__exam=exam)
        .values_list("attempt__student_id", flat=True)
        .distinct()
    )

    return _create_notifications(
        exam=exam,
        student_ids=student_ids,
        notification_type=EmailNotification.NotificationType.RESULTS_PUBLISHED,
    )


def _create_notifications(exam, student_ids, notification_type):
    """Create one pending notification per eligible student."""
    notifications = []

    with transaction.atomic():
        for student_id in student_ids:
            notification, created = EmailNotification.objects.get_or_create(
                exam=exam,
                recipient_id=student_id,
                notification_type=notification_type,
            )

            if created:
                notifications.append(notification)

    return notifications


def _email_content(notification):
    """Build the subject and message for an email."""
    exam = notification.exam
    recipient = notification.recipient

    if notification.notification_type == (
        EmailNotification.NotificationType.EXAM_SCHEDULED
    ):
        subject = f"Exam Published: {exam.title}"

        message = (
            f"Hello {recipient.username},\n\n"
            f"The exam '{exam.title}' has been published.\n"
            f"Course: {exam.course}\n"
            f"Start time: {exam.start_time}\n"
            f"End time: {exam.end_time}\n"
            f"Duration: {exam.duration_minutes} minutes\n\n"
            "Please log in to the Online Examination Portal "
            "to view the exam details.\n"
        )

    elif notification.notification_type == (
        EmailNotification.NotificationType.RESULTS_PUBLISHED
    ):
        result = Result.objects.filter(
            attempt__exam=exam,
            attempt__student=recipient,
            attempt__exam__result_publication__isnull=False,
        ).first()

        if result is None:
            raise ValueError(
                "No published result exists for this student."
            )

        subject = f"Results Published: {exam.title}"

        message = (
            f"Hello {recipient.username},\n\n"
            f"The results for '{exam.title}' have been published.\n"
            f"Your score: {result.score}/{result.total_marks}\n"
            f"Percentage: {result.percentage}%\n\n"
            "Please log in to the Online Examination Portal "
            "to view your result.\n"
        )

    else:
        raise ValueError("Unsupported notification type.")

    return subject, message


def _claim_notification(notification_id):
    """Claim a notification before sending, using a short transaction."""
    now = timezone.now()

    with transaction.atomic():
        notification = (
            EmailNotification.objects.select_for_update()
            .filter(pk=notification_id)
            .first()
        )

        if notification is None:
            return None

        if notification.status in (
            EmailNotification.Status.SENT,
            EmailNotification.Status.FAILED,
        ):
            return None

        if notification.status == EmailNotification.Status.PROCESSING:
            timeout = now - timedelta(
                minutes=PROCESSING_TIMEOUT_MINUTES
            )

            if (
                notification.processing_started_at is not None
                and notification.processing_started_at > timeout
            ):
                return None

        elif notification.next_attempt_at > now:
            return None

        if notification.attempt_count >= MAX_ATTEMPTS:
            notification.status = EmailNotification.Status.FAILED
            notification.processing_started_at = None
            notification.last_error = (
                notification.last_error
                or "Maximum email attempts reached."
            )
            notification.save(
                update_fields=[
                    "status",
                    "processing_started_at",
                    "last_error",
                    "updated_at",
                ]
            )
            return None

        notification.status = EmailNotification.Status.PROCESSING
        notification.attempt_count += 1
        notification.last_attempt_at = now
        notification.processing_started_at = now

        notification.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_attempt_at",
                "processing_started_at",
                "updated_at",
            ]
        )

        return notification


def _record_failure(notification_id, error):
    """Record a failed attempt and schedule its retry."""
    now = timezone.now()

    with transaction.atomic():
        notification = (
            EmailNotification.objects.select_for_update()
            .filter(pk=notification_id)
            .first()
        )

        if notification is None:
            return

        if notification.status != EmailNotification.Status.PROCESSING:
            return

        notification.last_error = str(error)
        notification.processing_started_at = None

        if notification.attempt_count >= MAX_ATTEMPTS:
            notification.status = EmailNotification.Status.FAILED
        else:
            delay = BASE_RETRY_DELAY_MINUTES * (
                2 ** (notification.attempt_count - 1)
            )

            notification.status = EmailNotification.Status.PENDING
            notification.next_attempt_at = (
                now + timedelta(minutes=delay)
            )

        notification.save(
            update_fields=[
                "status",
                "last_error",
                "processing_started_at",
                "next_attempt_at",
                "updated_at",
            ]
        )


def _record_success(notification_id):
    """Record successful email delivery."""
    with transaction.atomic():
        notification = (
            EmailNotification.objects.select_for_update()
            .filter(pk=notification_id)
            .first()
        )

        if notification is None:
            return

        if notification.status != EmailNotification.Status.PROCESSING:
            return

        notification.status = EmailNotification.Status.SENT
        notification.sent_at = timezone.now()
        notification.processing_started_at = None
        notification.last_error = ""

        notification.save(
            update_fields=[
                "status",
                "sent_at",
                "processing_started_at",
                "last_error",
                "updated_at",
            ]
        )


def send_notification(notification):
    """Claim, send and record one notification."""
    claimed = _claim_notification(notification.pk)

    if claimed is None:
        return False

    try:
        claimed = (
            EmailNotification.objects.select_related(
                "exam",
                "recipient",
                "exam__course",
            )
            .get(pk=claimed.pk)
        )

        if not claimed.recipient.email:
            raise ValueError("Recipient has no email address.")

        subject, message = _email_content(claimed)

        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[claimed.recipient.email],
            fail_silently=False,
        )

        if sent_count != 1:
            raise RuntimeError(
                "Email backend did not confirm delivery."
            )

    except Exception as exc:
        logger.exception(
            "Failed to send notification %s",
            notification.pk,
        )
        _record_failure(notification.pk, exc)
        return False

    _record_success(notification.pk)
    return True


def recover_stale_notifications():
    """Return notifications abandoned by a stopped worker to pending."""
    timeout = timezone.now() - timedelta(
        minutes=PROCESSING_TIMEOUT_MINUTES
    )

    return EmailNotification.objects.filter(
        status=EmailNotification.Status.PROCESSING,
        processing_started_at__lte=timeout,
    ).update(
        status=EmailNotification.Status.PENDING,
        processing_started_at=None,
        next_attempt_at=timezone.now(),
    )


def process_pending_notifications(batch_size=100):
    """Process ready notifications in creation order."""
    recover_stale_notifications()

    notification_ids = list(
        EmailNotification.objects.filter(
            status=EmailNotification.Status.PENDING,
            next_attempt_at__lte=timezone.now(),
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:batch_size]
    )

    sent_count = 0

    for notification_id in notification_ids:
        notification = EmailNotification(pk=notification_id)

        if send_notification(notification):
            sent_count += 1

    return sent_count
