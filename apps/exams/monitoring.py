"""Live examination monitoring (OEP-F-040).

Instructors (for exams in courses they teach) and administrators (for every exam)
can see which students have not started, are in progress, or have submitted.

Monitoring is read-only: an attempt past its deadline that nobody has closed yet is
shown as timed out, but it is not written. Timing out and scoring still happen in
`expire_attempt_if_needed` and `results.services.finalize_overdue_attempts`.
"""
from django.utils import timezone

from apps.accounts.models import User

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
