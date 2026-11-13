
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.administration.models import Course, Enrollment
from apps.exams.models import Exam, ExamAttempt
from apps.notifications.models import EmailNotification
from apps.notifications.services import (
    BASE_RETRY_DELAY_MINUTES,
    MAX_ATTEMPTS,
    _claim_notification,
    _email_content,
    _record_failure,
    _record_success,
    _renew_claim,
    process_pending_notifications,
    queue_exam_scheduled_notifications,
    queue_results_published_notifications,
    recover_stale_notifications,
    send_notification,
)
from apps.results.models import Result, ResultPublication
from apps.results.services import publish_results


User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="test@example.com",
)
class EmailNotificationTests(TestCase):

    def setUp(self):
        self.instructor = User.objects.create_user(
            username="instructor",
            email="instructor@example.com",
            password="testpass123",
            role="instructor",
        )

        self.student = User.objects.create_user(
            username="student",
            email="student@example.com",
            password="testpass123",
            role="student",
        )

        self.student2 = User.objects.create_user(
            username="student2",
            email="student2@example.com",
            password="testpass123",
            role="student",
        )

        self.course = Course.objects.create(
            name="Computer Networks",
            code="CN101",
            instructor=self.instructor,
        )

        Enrollment.objects.create(
            student=self.student,
            course=self.course,
        )

        Enrollment.objects.create(
            student=self.student2,
            course=self.course,
        )

        now = timezone.now()

        self.exam = Exam.objects.create(
            course=self.course,
            title="Computer Networks Test",
            created_by=self.instructor,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=2),
            duration_minutes=60,
            total_marks=10,
            status=Exam.Status.DRAFT,
        )

    def create_notification(
        self,
        recipient=None,
        notification_type=EmailNotification.NotificationType.EXAM_SCHEDULED,
        status=EmailNotification.Status.PENDING,
        **kwargs,
    ):
        return EmailNotification.objects.create(
            exam=self.exam,
            recipient=recipient or self.student,
            notification_type=notification_type,
            status=status,
            **kwargs,
        )

    def make_result(self, student, score=8):
        attempt = ExamAttempt.objects.create(
            exam=self.exam,
            student=student,
            deadline_at=self.exam.end_time,
            submitted_at=self.exam.end_time,
            status=ExamAttempt.Status.SUBMITTED,
        )

        return Result.objects.create(
            attempt=attempt,
            score=score,
            total_marks=10,
        )

    def test_exam_publish_queues_notifications_for_enrolled_students(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.exam.status = Exam.Status.PUBLISHED
            self.exam.save(update_fields=["status"])

        notifications = EmailNotification.objects.filter(
            exam=self.exam,
            notification_type=(
                EmailNotification.NotificationType.EXAM_SCHEDULED
            ),
        )

        self.assertEqual(notifications.count(), 2)

        recipient_ids = set(
            notifications.values_list("recipient_id", flat=True)
        )

        self.assertEqual(
            recipient_ids,
            {self.student.pk, self.student2.pk},
        )

    def test_exam_publish_does_not_create_duplicate_notifications(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.exam.status = Exam.Status.PUBLISHED
            self.exam.save(update_fields=["status"])

        self.exam.title = "Updated Computer Networks Test"
        self.exam.save(update_fields=["title"])

        notifications = EmailNotification.objects.filter(
            exam=self.exam,
            notification_type=(
                EmailNotification.NotificationType.EXAM_SCHEDULED
            ),
        )

        self.assertEqual(notifications.count(), 2)

    def test_exam_queue_ignores_students_not_enrolled_in_course(self):
        outsider = User.objects.create_user(
            username="outsider",
            email="outsider@example.com",
            password="testpass123",
            role="student",
        )

        queue_exam_scheduled_notifications(self.exam)

        self.assertFalse(
            EmailNotification.objects.filter(
                exam=self.exam,
                recipient=outsider,
            ).exists()
        )

    def test_result_publication_queues_only_students_with_results(self):
        self.exam.end_time = timezone.now() - timedelta(hours=1)
        self.exam.start_time = self.exam.end_time - timedelta(hours=2)
        self.exam.save(update_fields=["start_time", "end_time"])

        self.make_result(self.student)

        with self.captureOnCommitCallbacks(execute=True):
            publish_results(self.exam, self.instructor)

        notifications = EmailNotification.objects.filter(
            exam=self.exam,
            notification_type=(
                EmailNotification.NotificationType.RESULTS_PUBLISHED
            ),
        )

        self.assertEqual(notifications.count(), 1)
        self.assertEqual(
            notifications.first().recipient,
            self.student,
        )

    def test_result_queue_does_not_create_duplicates(self):
        self.make_result(self.student)

        ResultPublication.objects.create(
            exam=self.exam,
            published_by=self.instructor,
        )

        queue_results_published_notifications(self.exam)
        queue_results_published_notifications(self.exam)

        notifications = EmailNotification.objects.filter(
            exam=self.exam,
            notification_type=(
                EmailNotification.NotificationType.RESULTS_PUBLISHED
            ),
        )

        self.assertEqual(notifications.count(), 1)

    def test_scheduled_email_is_sent_successfully(self):
        notification = self.create_notification()

        result = send_notification(notification)

        notification.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(
            notification.status,
            EmailNotification.Status.SENT,
        )
        self.assertEqual(notification.attempt_count, 1)
        self.assertIsNotNone(notification.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            [self.student.email],
        )

    def test_result_email_contains_score_and_percentage(self):
        self.make_result(self.student, score=8)

        ResultPublication.objects.create(
            exam=self.exam,
            published_by=self.instructor,
        )

        notification = self.create_notification(
            notification_type=(
                EmailNotification.NotificationType.RESULTS_PUBLISHED
            ),
        )

        subject, message = _email_content(notification)

        self.assertIn("Results Published", subject)
        self.assertIn("8/10", message)
        self.assertIn("80.0%", message)

    def test_failed_email_is_scheduled_for_retry(self):
        notification = self.create_notification()

        with patch(
            "apps.notifications.services.send_mail",
            side_effect=RuntimeError("SMTP server unavailable"),
        ):
            send_notification(notification)

        notification.refresh_from_db()

        expected_delay = timedelta(
            minutes=BASE_RETRY_DELAY_MINUTES
        )

        actual_delay = (
            notification.next_attempt_at
            - notification.last_attempt_at
        )

        self.assertEqual(
            notification.status,
            EmailNotification.Status.PENDING,
        )
        self.assertEqual(notification.attempt_count, 1)
        self.assertAlmostEqual(
            actual_delay.total_seconds(),
            expected_delay.total_seconds(),
            delta=0.1,
        )
        self.assertIn(
            "SMTP server unavailable",
            notification.last_error,
        )

    def test_notification_is_marked_failed_after_maximum_attempts(self):
        notification = self.create_notification(
            attempt_count=MAX_ATTEMPTS - 1,
        )

        with patch(
            "apps.notifications.services.send_mail",
            side_effect=RuntimeError("SMTP failure"),
        ):
            send_notification(notification)

        notification.refresh_from_db()

        self.assertEqual(
            notification.status,
            EmailNotification.Status.FAILED,
        )
        self.assertEqual(
            notification.attempt_count,
            MAX_ATTEMPTS,
        )

    def test_notification_without_email_address_is_not_sent(self):
        self.student.email = ""
        self.student.save(update_fields=["email"])

        notification = self.create_notification()

        result = send_notification(notification)

        notification.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(
            notification.status,
            EmailNotification.Status.PENDING,
        )
        self.assertEqual(notification.attempt_count, 1)
        self.assertIn(
            "Recipient has no email address.",
            notification.last_error,
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_stale_processing_notifications_are_recovered(self):
        notification = self.create_notification(
            status=EmailNotification.Status.PROCESSING,
            processing_started_at=(
                timezone.now() - timedelta(minutes=20)
            ),
        )

        recovered_count = recover_stale_notifications()

        notification.refresh_from_db()

        self.assertEqual(recovered_count, 1)
        self.assertEqual(
            notification.status,
            EmailNotification.Status.PENDING,
        )
        self.assertIsNone(notification.processing_started_at)

    def test_active_worker_lease_is_not_recovered(self):
        claim_token = uuid.uuid4()
        notification = self.create_notification(
            status=EmailNotification.Status.PROCESSING,
            processing_started_at=(
                timezone.now() - timedelta(minutes=20)
            ),
            claim_token=claim_token,
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )

        recovered_count = recover_stale_notifications()

        notification.refresh_from_db()

        self.assertEqual(recovered_count, 0)
        self.assertEqual(
            notification.status,
            EmailNotification.Status.PROCESSING,
        )
        self.assertEqual(notification.claim_token, claim_token)

    def test_stale_worker_cannot_update_notification_after_reclaim(self):
        old_claim_token = uuid.uuid4()
        notification = self.create_notification(
            status=EmailNotification.Status.PROCESSING,
            processing_started_at=(
                timezone.now() - timedelta(minutes=20)
            ),
            claim_token=old_claim_token,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

        self.assertEqual(recover_stale_notifications(), 1)

        new_claim = _claim_notification(notification.pk)
        self.assertIsNotNone(new_claim)
        self.assertNotEqual(new_claim.claim_token, old_claim_token)

        # The previous worker must not mark the new worker's claim as sent
        # or schedule a retry after it has lost ownership.
        _record_success(notification.pk, old_claim_token)
        _record_failure(
            notification.pk,
            old_claim_token,
            RuntimeError("late failure from old worker"),
        )

        notification.refresh_from_db()
        self.assertEqual(
            notification.status,
            EmailNotification.Status.PROCESSING,
        )
        self.assertEqual(notification.claim_token, new_claim.claim_token)

        _record_success(notification.pk, new_claim.claim_token)
        notification.refresh_from_db()

        self.assertEqual(
            notification.status,
            EmailNotification.Status.SENT,
        )
        self.assertIsNone(notification.claim_token)
        self.assertIsNone(notification.lease_expires_at)

    def test_worker_can_renew_its_own_unexpired_lease(self):
        notification = self.create_notification()
        initial_time = timezone.now()

        with patch(
            "apps.notifications.services.timezone.now",
            side_effect=[
                initial_time,
                initial_time,
                initial_time + timedelta(seconds=1),
            ],
        ):
            claim = _claim_notification(notification.pk)
            original_expiry = claim.lease_expires_at

            renewed = _renew_claim(claim.pk, claim.claim_token)

        claim.refresh_from_db()

        self.assertTrue(renewed)
        self.assertGreater(claim.lease_expires_at, original_expiry)

    def test_worker_cannot_renew_another_workers_lease(self):
        claim = _claim_notification(
            self.create_notification().pk
        )

        original_token = claim.claim_token
        renewed = _renew_claim(claim.pk, uuid.uuid4())

        claim.refresh_from_db()

        self.assertFalse(renewed)
        self.assertEqual(claim.claim_token, original_token)

    def test_pending_notification_is_processed(self):
        notification = self.create_notification()

        sent_count = process_pending_notifications()

        notification.refresh_from_db()

        self.assertEqual(sent_count, 1)
        self.assertEqual(
            notification.status,
            EmailNotification.Status.SENT,
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_notification_is_not_sent_before_retry_time(self):
        notification = self.create_notification(
            next_attempt_at=timezone.now() + timedelta(hours=1),
        )

        result = send_notification(notification)

        notification.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(
            notification.status,
            EmailNotification.Status.PENDING,
        )
        self.assertEqual(notification.attempt_count, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_active_worker_cannot_be_reclaimed_while_sending(self):
        notification = self.create_notification()
        worker_b_result = {}

        def simulate_slow_email_send(*args, **kwargs):
            # Simulate Worker A taking longer than 15 minutes.
            EmailNotification.objects.filter(
                pk=notification.pk
            ).update(
                processing_started_at=(
                    timezone.now() - timedelta(minutes=20)
                )
            )

            # Worker B attempts stale notification recovery.
            worker_b_result["recovered"] = (
                recover_stale_notifications()
            )

            # Worker B attempts to send the same notification.
            worker_b_result["sent"] = send_notification(
                notification
            )

            # Worker A completes its email operation.
            return 1

        with patch(
            "apps.notifications.services.send_mail",
            side_effect=simulate_slow_email_send,
        ) as mocked_send_mail:
            worker_a_result = send_notification(notification)

        notification.refresh_from_db()

        self.assertTrue(worker_a_result)
        self.assertEqual(worker_b_result["recovered"], 0)
        self.assertFalse(worker_b_result["sent"])
        self.assertEqual(mocked_send_mail.call_count, 1)

        self.assertEqual(
            notification.status,
            EmailNotification.Status.SENT,
        )
        self.assertIsNone(notification.claim_token)
        self.assertIsNone(notification.lease_expires_at)
