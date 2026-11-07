import random
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.administration.models import Enrollment
from apps.results.models import Result

from .forms import ExamCreationForm
from .models import Answer, Choice, Exam, ExamAttempt, ExamQuestion, Question


# Shows the question bank, so it is Instructor-only (a subset of QUESTION_BANK_ROLES):
# administrators do not own courses and so have no questions to put in an exam.
@role_required(User.Role.INSTRUCTOR)
def create_exam(request):
    if request.method == "POST":
        form = ExamCreationForm(request.POST, instructor=request.user)

        if form.is_valid():
            with transaction.atomic():
                exam = form.save(commit=False)
                exam.created_by = request.user
                selected_questions = list(form.cleaned_data["questions"])
                exam.total_marks = sum(
                    question.marks for question in selected_questions
                )
                exam.save()

                if exam.randomize_questions:
                    random.shuffle(selected_questions)

                ExamQuestion.objects.bulk_create([
                    ExamQuestion(
                        exam=exam,
                        question=question,
                        position=position,
                    )
                    for position, question in enumerate(
                        selected_questions,
                        start=1,
                    )
                ])

            messages.success(request, "Exam created successfully.")
            return redirect("exams:create")
    else:
        form = ExamCreationForm(instructor=request.user)

    return render(request, "exams/create_exam.html", {"form": form})


def evaluate_attempt(attempt):
    """Calculate and save the MCQ result for an exam attempt."""
    exam_questions = (
        ExamQuestion.objects
        .filter(exam=attempt.exam)
        .select_related("question")
    )

    answers = {
        answer.question_id: answer
        for answer in Answer.objects.filter(
            attempt=attempt
        ).select_related("selected_choice")
    }

    score = 0
    total_marks = 0

    for exam_question in exam_questions:
        question = exam_question.question
        total_marks += question.marks
        answer = answers.get(question.pk)

        if (
            answer
            and answer.selected_choice
            and answer.selected_choice.question_id == question.pk
            and answer.selected_choice.is_correct
        ):
            score += question.marks

    result, _ = Result.objects.update_or_create(
        attempt=attempt,
        defaults={
            "score": score,
            "total_marks": total_marks,
        },
    )
    return result


def expire_attempt_if_needed(attempt):
    """Expire an attempt using the server's current time."""
    if (
        attempt.status == ExamAttempt.Status.IN_PROGRESS
        and timezone.now() >= attempt.deadline_at
    ):
        attempt.status = ExamAttempt.Status.TIMED_OUT
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])

    if attempt.status == ExamAttempt.Status.TIMED_OUT:
        evaluate_attempt(attempt)
        return True

    return False


def _parse_id(value):
    """Return value as a positive int, or None if it is missing or malformed."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _store_answer(attempt, question_id, choice_id):
    """Save (or clear) the student's choice for one question of an active attempt.

    The question must belong to the attempt's exam and the choice to that question,
    otherwise Http404 is raised. An empty choice_id clears the saved choice.
    Callers must hold a select_for_update lock on the attempt and have checked it is
    still in progress (OEP-F-022).
    """
    question = get_object_or_404(
        Question,
        pk=_parse_id(question_id),
        exam_usages__exam=attempt.exam,
    )

    choice = None
    if choice_id:
        choice = get_object_or_404(
            Choice,
            pk=_parse_id(choice_id),
            question=question,
        )

    answer, _ = Answer.objects.update_or_create(
        attempt=attempt,
        question=question,
        defaults={"selected_choice": choice},
    )
    return answer


@login_required
def start_attempt(request, exam_id):
    """Start an exam or resume the student's existing attempt."""
    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied

    with transaction.atomic():
        exam = get_object_or_404(
            Exam.objects.select_for_update(),
            pk=exam_id,
            status=Exam.Status.PUBLISHED,
        )

        now = timezone.now()
        if now < exam.start_time or now >= exam.end_time:
            messages.error(
                request,
                "This exam is not currently available.",
            )
            return redirect("accounts:student_dashboard")

        # Enforce course enrollment on the server once the exam is available.
        # Keep the availability response consistent for exams that have not started.
        if not Enrollment.objects.filter(
            student=request.user,
            course=exam.course,
        ).exists():
            raise PermissionDenied

        attempt = (
            ExamAttempt.objects.select_for_update()
            .filter(exam=exam, student=request.user)
            .order_by("-started_at")
            .first()
        )

        if attempt is not None:
            if expire_attempt_if_needed(attempt):
                messages.error(
                    request,
                    "Your exam time has expired.",
                )
                return redirect("accounts:student_dashboard")

            if attempt.status != ExamAttempt.Status.IN_PROGRESS:
                messages.error(
                    request,
                    "You have already submitted this exam.",
                )
                return redirect("accounts:student_dashboard")
        else:
            deadline = min(
                now + timedelta(minutes=exam.duration_minutes),
                exam.end_time,
            )
            attempt = ExamAttempt.objects.create(
                exam=exam,
                student=request.user,
                deadline_at=deadline,
            )

    return redirect("exams:take_attempt", attempt_id=attempt.pk)


@login_required
def take_attempt(request, attempt_id):
    """Display one question at a time with server-calculated remaining time."""
    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied

    with transaction.atomic():
        attempt = get_object_or_404(
            ExamAttempt.objects.select_for_update().select_related("exam"),
            pk=attempt_id,
            student=request.user,
        )

        if expire_attempt_if_needed(attempt):
            messages.error(
                request,
                "Your exam time has expired.",
            )
            return redirect("accounts:student_dashboard")

        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            messages.error(
                request,
                "This attempt is no longer active.",
            )
            return redirect("accounts:student_dashboard")

        remaining_seconds = max(
            0,
            int((attempt.deadline_at - timezone.now()).total_seconds()),
        )

    questions = [
        item.question
        for item in (
            ExamQuestion.objects.filter(exam=attempt.exam)
            .select_related("question")
            .prefetch_related("question__choices")
            .order_by("position")
        )
    ]

    saved_answers = {
        answer.question_id: answer.selected_choice_id
        for answer in attempt.answers.all()
    }

    for question in questions:
        question.selected_choice_id = saved_answers.get(question.pk)

    try:
        question_index = int(request.GET.get("q", "0"))
    except (TypeError, ValueError):
        question_index = 0

    if questions:
        question_index = max(
            0,
            min(question_index, len(questions) - 1),
        )
        current_question = questions[question_index]
    else:
        current_question = None

    return render(
        request,
        "exams/take_attempt.html",
        {
            "attempt": attempt,
            "questions": questions,
            "current_question": current_question,
            "question_index": question_index,
            "question_count": len(questions),
            "remaining_seconds": remaining_seconds,
        },
    )


@login_required
def save_answer(request, attempt_id):
    """Save the current answer before navigating to another question."""
    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied

    if request.method != "POST":
        return HttpResponseForbidden("POST required.")

    with transaction.atomic():
        attempt = get_object_or_404(
            ExamAttempt.objects.select_for_update().select_related("exam"),
            pk=attempt_id,
            student=request.user,
        )

        if expire_attempt_if_needed(attempt):
            messages.error(
                request,
                "Your exam time has expired.",
            )
            return redirect("accounts:student_dashboard")

        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            return HttpResponseForbidden(
                "This attempt is not active."
            )

        _store_answer(
            attempt,
            request.POST.get("question_id"),
            request.POST.get("choice_id"),
        )

        try:
            next_question = int(
                request.POST.get("next_question", "0")
            )
        except (TypeError, ValueError):
            next_question = 0

        question_count = ExamQuestion.objects.filter(
            exam=attempt.exam
        ).count()

        next_question = max(
            0,
            min(next_question, max(question_count - 1, 0)),
        )

    attempt_url = redirect(
        "exams:take_attempt",
        attempt_id=attempt.pk,
    ).url

    return redirect(f"{attempt_url}?q={next_question}")


@login_required
@require_POST
def autosave_answer(request, attempt_id):
    """Save one answer in the background and acknowledge it as JSON (OEP-F-022).

    Called by the exam page whenever the student picks a choice, so the answer is
    on the server even if the browser crashes before the next navigation.
    """
    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied

    with transaction.atomic():
        attempt = get_object_or_404(
            ExamAttempt.objects.select_for_update().select_related("exam"),
            pk=attempt_id,
            student=request.user,
        )

        if expire_attempt_if_needed(attempt):
            return JsonResponse(
                {"saved": False, "error": "The exam deadline has passed."},
                status=409,
            )

        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            return JsonResponse(
                {"saved": False, "error": "This attempt is not active."},
                status=403,
            )

        try:
            answer = _store_answer(
                attempt,
                request.POST.get("question_id"),
                request.POST.get("choice_id"),
            )
        except Http404:
            return JsonResponse(
                {"saved": False, "error": "Invalid question or choice."},
                status=400,
            )

    return JsonResponse(
        {
            "saved": True,
            "question_id": answer.question_id,
            "choice_id": answer.selected_choice_id,
            "saved_at": answer.saved_at.isoformat(),
        }
    )


@login_required
def submit_attempt(request, attempt_id):
    """Submit an attempt while enforcing its server-side deadline."""
    if request.user.role != User.Role.STUDENT:
        raise PermissionDenied

    if request.method != "POST":
        return HttpResponseForbidden("POST required.")

    with transaction.atomic():
        attempt = get_object_or_404(
            ExamAttempt.objects.select_for_update(),
            pk=attempt_id,
            student=request.user,
        )

        if expire_attempt_if_needed(attempt):
            messages.error(
                request,
                "The exam deadline has passed. Your attempt has timed out.",
            )
            return redirect("accounts:student_dashboard")

        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            messages.error(
                request,
                "This attempt is no longer active.",
            )
            return redirect("accounts:student_dashboard")

        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])

        evaluate_attempt(attempt)

    messages.success(
        request,
        "Your exam has been submitted.",
    )
    return redirect("accounts:student_dashboard")
