
import logging
import threading
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.administration.models import Enrollment
from apps.results.models import Result

from .models import EmailNotification


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BASE_RETRY_DELAY_MINUTES = 5
PROCESSING_TIMEOUT_MINUTES = 15
# Renew well before the lease expires so slow email backends remain owned.
LEASE_RENEWAL_INTERVAL_SECONDS = 60


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
    """Claim a notification and assign a unique ownership token."""
    now = timezone.now()
    lease_expires_at = now + timedelta(
        minutes=PROCESSING_TIMEOUT_MINUTES
    )

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
            # New claims use lease_expires_at. The timestamp fallback keeps
            # Legacy rows without a lease use the original timestamp timeout.
            if (
                notification.lease_expires_at is not None
                and notification.lease_expires_at > now
            ):
                return None

            if (
                notification.lease_expires_at is None
                and notification.processing_started_at is not None
                and notification.processing_started_at
                > now - timedelta(minutes=PROCESSING_TIMEOUT_MINUTES)
            ):
                return None

        elif notification.next_attempt_at > now:
            return None

        if notification.attempt_count >= MAX_ATTEMPTS:
            notification.status = EmailNotification.Status.FAILED
            notification.processing_started_at = None
            notification.claim_token = None
            notification.lease_expires_at = None
            notification.last_error = (
                notification.last_error
                or "Maximum email attempts reached."
            )
            notification.save(
                update_fields=[
                    "status",
                    "processing_started_at",
                    "claim_token",
                    "lease_expires_at",
                    "last_error",
                    "updated_at",
                ]
            )
            return None

        notification.status = EmailNotification.Status.PROCESSING
        notification.attempt_count += 1
        notification.last_attempt_at = now
        notification.processing_started_at = now
        notification.claim_token = uuid.uuid4()
        notification.lease_expires_at = lease_expires_at

        notification.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_attempt_at",
                "processing_started_at",
                "claim_token",
                "lease_expires_at",
                "updated_at",
            ]
        )

        return notification


def _renew_claim(notification_id, claim_token):
    """Extend an active worker's lease without changing its ownership token."""
    now = timezone.now()
    updated = EmailNotification.objects.filter(
        pk=notification_id,
        status=EmailNotification.Status.PROCESSING,
        claim_token=claim_token,
        lease_expires_at__gt=now,
    ).update(
        lease_expires_at=now + timedelta(
            minutes=PROCESSING_TIMEOUT_MINUTES
        ),
        updated_at=now,
    )
    return updated == 1


def _record_failure(notification_id, claim_token, error):
    """Record failure only if this worker still owns the notification."""
    now = timezone.now()

    with transaction.atomic():
        notification = (
            EmailNotification.objects.select_for_update()
            .filter(
                pk=notification_id,
                status=EmailNotification.Status.PROCESSING,
                claim_token=claim_token,
            )
            .first()
        )

        if notification is None:
            return

        notification.last_error = str(error)
        notification.processing_started_at = None
        notification.claim_token = None
        notification.lease_expires_at = None

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
                "claim_token",
                "lease_expires_at",
                "next_attempt_at",
                "updated_at",
            ]
        )


def _record_success(notification_id, claim_token):
    """Record successful delivery only if this worker still owns the claim."""
    now = timezone.now()

    with transaction.atomic():
        notification = (
            EmailNotification.objects.select_for_update()
            .filter(
                pk=notification_id,
                status=EmailNotification.Status.PROCESSING,
                claim_token=claim_token,
            )
            .first()
        )

        if notification is None:
            return

        notification.status = EmailNotification.Status.SENT
        notification.sent_at = now
        notification.processing_started_at = None
        notification.claim_token = None
        notification.lease_expires_at = None
        notification.last_error = ""

        notification.save(
            update_fields=[
                "status",
                "sent_at",
                "processing_started_at",
                "claim_token",
                "lease_expires_at",
                "last_error",
                "updated_at",
            ]
        )


def _heartbeat_claim(notification_id, claim_token, stop_event):
    """Renew the claim periodically while the email backend is working."""
    # Django database connections are thread-local. Close stale connections
    # before and after the heartbeat thread uses the ORM.
    from django.db import close_old_connections

    close_old_connections()
    try:
        while not stop_event.wait(LEASE_RENEWAL_INTERVAL_SECONDS):
            try:
                if not _renew_claim(notification_id, claim_token):
                    logger.warning(
                        "Lost claim for notification %s; stopping heartbeat.",
                        notification_id,
                    )
                    return
            except Exception:
                logger.exception(
                    "Could not renew claim for notification %s.",
                    notification_id,
                )
    finally:
        close_old_connections()


def send_notification(notification):
    """Claim, send and record one notification while renewing its lease."""
    claimed = _claim_notification(notification.pk)

    if claimed is None:
        return False

    claim_token = claimed.claim_token
    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_claim,
        args=(claimed.pk, claim_token, stop_event),
        daemon=True,
        name=f"notification-heartbeat-{claimed.pk}",
    )
    heartbeat.start()

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
        _record_failure(notification.pk, claim_token, exc)
        return False

    else:
        _record_success(notification.pk, claim_token)
        return True

    finally:
        stop_event.set()
        heartbeat.join(timeout=5)


def recover_stale_notifications():
    """Recover notifications only after their ownership lease expires."""
    now = timezone.now()
    legacy_timeout = now - timedelta(
        minutes=PROCESSING_TIMEOUT_MINUTES
    )

    stale_filter = (
        Q(lease_expires_at__lte=now)
        | Q(
            lease_expires_at__isnull=True,
            processing_started_at__lte=legacy_timeout,
        )
    )

    recovered_count = 0

    with transaction.atomic():
        stale_notifications = (
            EmailNotification.objects.select_for_update()
            .filter(
                status=EmailNotification.Status.PROCESSING,
            )
            .filter(stale_filter)
        )

        for notification in stale_notifications:
            notification.status = EmailNotification.Status.PENDING
            notification.processing_started_at = None
            notification.claim_token = None
            notification.lease_expires_at = None
            notification.next_attempt_at = now
            notification.save(
                update_fields=[
                    "status",
                    "processing_started_at",
                    "claim_token",
                    "lease_expires_at",
                    "next_attempt_at",
                    "updated_at",
                ]
            )
            recovered_count += 1

    return recovered_count


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
