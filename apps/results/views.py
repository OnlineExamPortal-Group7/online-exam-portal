
"""Instructor result review and publication, plus student result history."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin
from apps.exams.models import ExamAttempt

from . import services
from .models import ResultPublication


class InstructorResultsMixin(RoleRequiredMixin):
    allowed_roles = (User.Role.INSTRUCTOR,)

    def get_queryset(self):
        return (
            services.exams_for_review(self.request.user)
            .select_related("course")
            .annotate(
                results_published=Exists(
                    ResultPublication.objects.filter(exam=OuterRef("pk"))
                )
            )
            .order_by("-end_time")
        )


class ExamResultListView(InstructorResultsMixin, ListView):
    """The instructor's exams and whether their results are published."""

    template_name = "results/exam_list.html"
    context_object_name = "exams"

    def get_context_data(self, **kwargs):
        return super().get_context_data(now=timezone.now(), **kwargs)


class ExamResultReviewView(InstructorResultsMixin, DetailView):
    """Every student's score for one exam, so the instructor can check it before publishing."""

    template_name = "results/exam_review.html"
    context_object_name = "exam"

    def get_object(self, queryset=None):
        exam = super().get_object(queryset)
        services.finalize_overdue_attempts(exam)
        return exam

    def get_context_data(self, **kwargs):
        exam = self.object
        rows = review_rows(exam)
        percentages = [
            row["result"].percentage for row in rows if row["result"]
        ]
        average = (
            round(sum(percentages) / len(percentages), 2)
            if percentages else None
        )

        return super().get_context_data(
            rows=rows,
            scored_count=len(percentages),
            average_percentage=average,
            publication=ResultPublication.objects.filter(exam=exam).first(),
            window_closed=timezone.now() >= exam.end_time,
            **kwargs,
        )


class PublishResultsView(InstructorResultsMixin, View):
    """POST only: publish an exam's results so its students can see their scores."""

    http_method_names = ["post"]

    def post(self, request, pk):
        exam = get_object_or_404(self.get_queryset(), pk=pk)

        try:
            services.publish_results(exam, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request,
                "Results published. Students can now see their scores.",
            )

        return redirect("results:exam_review", pk=exam.pk)


def review_rows(exam):
    """One row per enrolled student (and anyone else who attempted), with attempt and result."""

    attempts = {}
    for attempt in (
        ExamAttempt.objects.filter(exam=exam)
        .select_related("result")
        .order_by("started_at")
    ):
        attempts[attempt.student_id] = attempt

    enrolled_ids = set(
        User.objects.filter(
            course_enrollments__course=exam.course
        ).values_list("pk", flat=True)
    )

    students = User.objects.filter(
        pk__in=enrolled_ids | set(attempts)
    ).order_by("username")

    rows = []

    for student in students:
        attempt = attempts.get(student.pk)
        rows.append({
            "student": student,
            "attempt": attempt,
            "result": getattr(attempt, "result", None) if attempt else None,
        })

    return rows


class StudentResultsMixin(RoleRequiredMixin):
    """Restrict student result pages to authenticated students."""

    allowed_roles = (User.Role.STUDENT,)


class StudentResultsListView(StudentResultsMixin, ListView):
    """Show only the logged-in student's published results."""

    template_name = "results/student_results.html"
    context_object_name = "results"

    def get_queryset(self):
        return services.published_results_for(self.request.user)


class StudentResultDetailView(StudentResultsMixin, DetailView):
    """Show details of one published result belonging to the student."""

    template_name = "results/student_result_detail.html"
    context_object_name = "result"

    def get_queryset(self):
        return services.published_results_for(self.request.user)


class StudentExamHistoryView(StudentResultsMixin, ListView):
    """Show the logged-in student's own examination attempts."""

    template_name = "results/student_history.html"
    context_object_name = "attempts"

    def get_queryset(self):
        return (
            ExamAttempt.objects.filter(student=self.request.user)
            .select_related("exam__course")
            .order_by("-started_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        published_results = {
            result.attempt_id: result
            for result in services.published_results_for(self.request.user)
        }

        for attempt in context["attempts"]:
            attempt.published_result = published_results.get(attempt.pk)

        return context
