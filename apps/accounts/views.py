
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.exams.models import Exam, ExamAttempt
from apps.results.services import published_results_for

from .models import User
from .permissions import role_required


DASHBOARD_BY_ROLE = {
    User.Role.STUDENT: "accounts:student_dashboard",
    User.Role.INSTRUCTOR: "accounts:instructor_dashboard",
    User.Role.ADMINISTRATOR: "accounts:admin_dashboard",
}


def home(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    return render(request, "home.html")


@login_required
def dashboard(request):
    """Send each signed-in user to the dashboard for their role."""
    return redirect(DASHBOARD_BY_ROLE[request.user.role])


@role_required(User.Role.STUDENT)
def student_dashboard(request):
    """Display published exams for courses in which the student is enrolled."""
    exams = (
        Exam.objects.filter(
            course__enrollments__student=request.user,
            status=Exam.Status.PUBLISHED,
        )
        .select_related("course")
        .prefetch_related(
            Prefetch(
                "attempts",
                queryset=ExamAttempt.objects.filter(
                    student=request.user
                ).order_by("-started_at"),
                to_attr="student_attempts",
            )
        )
        .order_by("start_time")
        .distinct()
    )

    # Scores are shown only once the instructor has published them (OEP-F-031).
    published = {
        result.attempt.exam_id: result
        for result in published_results_for(request.user)
    }
    exams = list(exams)
    for exam in exams:
        exam.published_result = published.get(exam.pk)

    return render(
        request,
        "accounts/dashboard.html",
        {
            "title": "Student dashboard",
            "exams": exams,
            "now": timezone.now(),
        },
    )


@role_required(User.Role.INSTRUCTOR)
def instructor_dashboard(request):
    return render(
        request,
        "accounts/dashboard.html",
        {"title": "Instructor dashboard"},
    )


@role_required(User.Role.ADMINISTRATOR)
def admin_dashboard(request):
    return render(
        request,
        "accounts/dashboard.html",
        {"title": "Administrator dashboard"},
    )
