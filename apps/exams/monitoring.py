"""Live examination monitoring (OEP-F-040).

Instructors (for exams in courses they teach) and administrators (for every exam)
can see which students have not started, are in progress, or have submitted.

Monitoring is read-only: an attempt past its deadline that nobody has closed yet is
shown as timed out, but it is not written. Timing out and scoring still happen in
`expire_attempt_if_needed` and `results.services.finalize_overdue_attempts`.
"""
from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import DetailView, ListView, View
from django.views.generic.detail import SingleObjectMixin

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin

from .models import Exam, ExamAttempt

MONITOR_ROLES = (User.Role.INSTRUCTOR, User.Role.ADMINISTRATOR)

NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
SUBMITTED = "submitted"
TIMED_OUT = "timed_out"

STATUS_LABELS = {
    NOT_STARTED: "Not started",
    IN_PROGRESS: "In progress",
    SUBMITTED: "Submitted",
    TIMED_OUT: "Timed out",
}


def monitorable_exams(user):
    """Exams the user may monitor: all for administrators, own courses for instructors."""
    if not (user.is_authenticated and user.is_active):
        return Exam.objects.none()
    if user.role == User.Role.ADMINISTRATOR:
        return Exam.objects.all()
    if user.role == User.Role.INSTRUCTOR:
        return Exam.objects.filter(course__instructor=user)
    return Exam.objects.none()


def attempt_status(attempt, now):
    """Monitoring status for a student's attempt (None means not started)."""
    if attempt is None:
        return NOT_STARTED
    if attempt.status == ExamAttempt.Status.SUBMITTED:
        return SUBMITTED
    if attempt.status == ExamAttempt.Status.TIMED_OUT or now >= attempt.deadline_at:
        return TIMED_OUT
    return IN_PROGRESS


def monitor_snapshot(exam, now=None):
    """Status of every enrolled student (and anyone else who attempted) for one exam.

    Uses two queries however many students there are.
    """
    now = now or timezone.now()

    students = {
        student.pk: student
        for student in User.objects.filter(course_enrollments__course=exam.course)
    }
    enrolled_ids = set(students)

    # Ordered oldest first, so the latest attempt per student wins.
    attempts = {}
    for attempt in (
        ExamAttempt.objects.filter(exam=exam)
        .select_related("student")
        .order_by("started_at", "pk")
    ):
        attempts[attempt.student_id] = attempt
        students.setdefault(attempt.student_id, attempt.student)

    rows = []
    counts = {status: 0 for status in STATUS_LABELS}
    for student in sorted(students.values(), key=lambda user: user.username.lower()):
        attempt = attempts.get(student.pk)
        status = attempt_status(attempt, now)
        counts[status] += 1
        rows.append({
            "student": student,
            "enrolled": student.pk in enrolled_ids,
            "attempt": attempt,
            "status": status,
            "status_label": STATUS_LABELS[status],
            "started_at": attempt.started_at if attempt else None,
            "submitted_at": attempt.submitted_at if attempt else None,
            "deadline_at": attempt.deadline_at if attempt else None,
        })

    return {
        "exam": exam,
        "generated_at": now,
        "is_live": exam.start_time <= now < exam.end_time,
        "rows": rows,
        "counts": counts,
        "total": len(rows),
    }


RECENTLY_ENDED_LIMIT = 20


class MonitorAccessMixin(RoleRequiredMixin):
    """Instructors and administrators only; exams outside monitorable_exams give 404."""

    allowed_roles = MONITOR_ROLES

    def get_queryset(self):
        return monitorable_exams(self.request.user).select_related("course")


class MonitorExamListView(MonitorAccessMixin, ListView):
    """Exams the user can monitor: live now, upcoming, and recently ended."""

    template_name = "exams/monitor_list.html"
    context_object_name = "exams"

    def get_queryset(self):
        return super().get_queryset().exclude(status=Exam.Status.DRAFT)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        exams = context["exams"]
        context.update(
            now=now,
            live_exams=sorted(
                (e for e in exams if e.start_time <= now < e.end_time),
                key=lambda e: e.end_time,
            ),
            upcoming_exams=sorted(
                (e for e in exams if e.start_time > now),
                key=lambda e: e.start_time,
            ),
            ended_exams=sorted(
                (e for e in exams if e.end_time <= now),
                key=lambda e: e.end_time,
                reverse=True,
            )[:RECENTLY_ENDED_LIMIT],
        )
        return context


class MonitorExamDetailView(MonitorAccessMixin, DetailView):
    """Live status of every student for one exam."""

    template_name = "exams/monitor_detail.html"
    context_object_name = "exam"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        snapshot = monitor_snapshot(self.object)
        context.update(
            snapshot=snapshot,
            status_summary=[
                (status, label, snapshot["counts"][status])
                for status, label in STATUS_LABELS.items()
            ],
        )
        return context


def _iso(value):
    return value.isoformat() if value else None


def _clock(value):
    """Local wall-clock time, formatted like the detail page (H:M:S)."""
    return timezone.localtime(value).strftime("%H:%M:%S") if value else None


def snapshot_as_json(snapshot):
    """JSON-safe form of monitor_snapshot, used by the page's polling."""
    return {
        "exam_id": snapshot["exam"].pk,
        "generated_at": _iso(snapshot["generated_at"]),
        "generated_display": _clock(snapshot["generated_at"]),
        "is_live": snapshot["is_live"],
        "total": snapshot["total"],
        "counts": snapshot["counts"],
        "rows": [
            {
                "username": row["student"].username,
                "name": row["student"].get_full_name(),
                "enrolled": row["enrolled"],
                "status": row["status"],
                "status_label": row["status_label"],
                "started_at": _iso(row["started_at"]),
                "started_display": _clock(row["started_at"]),
                "submitted_at": _iso(row["submitted_at"]),
                "submitted_display": _clock(row["submitted_at"]),
            }
            for row in snapshot["rows"]
        ],
    }


@method_decorator(never_cache, name="dispatch")
class MonitorExamStatusView(MonitorAccessMixin, SingleObjectMixin, View):
    """GET only: current monitoring snapshot as JSON, polled by the detail page."""

    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        exam = self.get_object()
        return JsonResponse(snapshot_as_json(monitor_snapshot(exam)))
