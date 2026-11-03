"""Result review and publication (OEP-F-031).

Students may only see a score once the exam's results are published. Pages that
show scores to students must use `published_results_for(student)`.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.administration.services import audit_hook
from apps.exams.models import Exam, ExamAttempt
from apps.exams.views import evaluate_attempt, expire_attempt_if_needed

from .models import Result, ResultPublication
from .signals import results_published


def exams_for_review(user):
    """Exams whose results the user may review: those in courses the instructor teaches."""
    if not (user.is_authenticated and user.is_active and user.role == User.Role.INSTRUCTOR):
        return Exam.objects.none()
    return Exam.objects.filter(course__instructor=user)


def finalize_overdue_attempts(exam):
    """Time out and score attempts past their deadline, and score closed attempts with no result."""
    with transaction.atomic():
        overdue = ExamAttempt.objects.select_for_update().filter(
            exam=exam,
            status=ExamAttempt.Status.IN_PROGRESS,
            deadline_at__lte=timezone.now(),
        )
        for attempt in overdue:
            expire_attempt_if_needed(attempt)

        unscored = ExamAttempt.objects.filter(
            exam=exam,
            result__isnull=True,
        ).exclude(status=ExamAttempt.Status.IN_PROGRESS)
        for attempt in unscored:
            evaluate_attempt(attempt)


def is_published(exam):
    return ResultPublication.objects.filter(exam=exam).exists()


def can_publish(exam):
    """Results can be published once the exam window has closed and not before."""
    return timezone.now() >= exam.end_time and not is_published(exam)


def publish_results(exam, actor):
    """Publish an exam's results. Only the course instructor may do this, after the exam ends."""
    if not (
        actor.is_authenticated
        and actor.is_active
        and actor.role == User.Role.INSTRUCTOR
        and exam.course.instructor_id == actor.pk
    ):
        raise PermissionDenied

    if timezone.now() < exam.end_time:
        raise ValidationError(
            "Results can be published only after the exam window has closed."
        )

    with transaction.atomic():
        Exam.objects.select_for_update().get(pk=exam.pk)
        if is_published(exam):
            raise ValidationError("Results for this exam are already published.")

        finalize_overdue_attempts(exam)
        publication = ResultPublication.objects.create(exam=exam, published_by=actor)
        audit_hook("publish_results", actor, exam)
        transaction.on_commit(
            lambda: results_published.send(
                sender=ResultPublication, exam=exam, published_by=actor
            )
        )
    return publication


def results_for_exam(exam):
    """All scored results of an exam, published or not (for instructors and analytics)."""
    return (
        Result.objects.filter(attempt__exam=exam)
        .select_related("attempt__student")
        .order_by("attempt__student__username")
    )


def published_results_for(student):
    """The student's results for exams whose results are published."""
    return (
        Result.objects.filter(
            attempt__student=student,
            attempt__exam__result_publication__isnull=False,
        )
        .select_related("attempt__exam__course")
        .order_by("-attempt__exam__end_time")
    )
