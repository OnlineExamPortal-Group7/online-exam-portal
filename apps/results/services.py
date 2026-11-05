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


def class_performance_analytics(exam):
    """
    Calculate class-wide analytics for a published examination.

    Returns score distribution and per-question correct-answer rates.
    Only attempts with saved results are included.
    """
    from django.core.exceptions import ValidationError

    from apps.exams.models import Answer, ExamQuestion

    if not is_published(exam):
        raise ValidationError(
            "Analytics are available only after results are published."
        )

    results = list(
        Result.objects.filter(
            attempt__exam=exam,
            attempt__exam__result_publication__isnull=False,
        ).select_related("attempt__student")
    )

    percentages = [
        result.percentage
        for result in results
        if result.total_marks > 0
    ]

    score_ranges = [
        {"label": "0-20%", "minimum": 0, "maximum": 20, "count": 0},
        {"label": "20-40%", "minimum": 20, "maximum": 40, "count": 0},
        {"label": "40-60%", "minimum": 40, "maximum": 60, "count": 0},
        {"label": "60-80%", "minimum": 60, "maximum": 80, "count": 0},
        {"label": "80-100%", "minimum": 80, "maximum": 100, "count": 0},
    ]

    for percentage in percentages:
        for index, score_range in enumerate(score_ranges):
            lower = score_range["minimum"]
            upper = score_range["maximum"]

            if (
                (percentage >= lower and percentage <= upper)
                if index == 0
                else (percentage > lower and percentage <= upper)
            ):
                score_range["count"] += 1
                break

    attempts = [
        result.attempt
        for result in results
    ]

    question_rows = []

    exam_questions = (
        ExamQuestion.objects.filter(exam=exam)
        .select_related("question")
        .order_by("position")
    )

    for exam_question in exam_questions:
        question = exam_question.question

        correct_count = Answer.objects.filter(
            attempt__in=attempts,
            question=question,
            selected_choice__question=question,
            selected_choice__is_correct=True,
        ).count()

        attempt_count = len(attempts)

        correct_rate = (
            round((correct_count / attempt_count) * 100, 2)
            if attempt_count else 0
        )

        question_rows.append({
            "question": question,
            "correct_count": correct_count,
            "attempt_count": attempt_count,
            "correct_rate": correct_rate,
        })

    return {
        "exam": exam,
        "scored_count": len(results),
        "average_percentage": (
            round(sum(percentages) / len(percentages), 2)
            if percentages else 0
        ),
        "total_published_score": sum(result.score for result in results),
        "total_published_marks": sum(
            result.total_marks for result in results
        ),
        "score_distribution": score_ranges,
        "question_rows": question_rows,
    }
