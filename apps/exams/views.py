import random
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.administration.models import Enrollment

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
                exam.total_marks = sum(question.marks for question in selected_questions)
                exam.save()

                if exam.randomize_questions:
                    random.shuffle(selected_questions)

                ExamQuestion.objects.bulk_create([
                    ExamQuestion(exam=exam, question=question, position=position)
                    for position, question in enumerate(selected_questions, start=1)
                ])

            messages.success(request, "Exam created successfully.")
            return redirect("exams:create")
    else:
        form = ExamCreationForm(instructor=request.user)

    return render(request, "exams/create_exam.html", {"form": form})


def expire_attempt_if_needed(attempt):
    """Expire an attempt using the server's current time."""
    if (
        attempt.status == ExamAttempt.Status.IN_PROGRESS
        and timezone.now() >= attempt.deadline_at
    ):
        attempt.status = ExamAttempt.Status.TIMED_OUT
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])
        return True
    return attempt.status == ExamAttempt.Status.TIMED_OUT


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
            messages.error(request, "This exam is not currently available.")
            return redirect("accounts:student_dashboard")

        # Enforce course enrollment on the server once the exam is available.
        # Keep the availability response consistent for exams that have not started.
        if not Enrollment.objects.filter(student=request.user, course=exam.course).exists():
            raise PermissionDenied

        attempt = (
            ExamAttempt.objects.select_for_update()
            .filter(exam=exam, student=request.user)
            .order_by("-started_at")
            .first()
        )

        if attempt is not None:
            if expire_attempt_if_needed(attempt):
                messages.error(request, "Your exam time has expired.")
                return redirect("accounts:student_dashboard")
            if attempt.status != ExamAttempt.Status.IN_PROGRESS:
                messages.error(request, "You have already submitted this exam.")
                return redirect("accounts:student_dashboard")
        else:
            deadline = min(now + timedelta(minutes=exam.duration_minutes), exam.end_time)
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
            messages.error(request, "Your exam time has expired.")
            return redirect("accounts:student_dashboard")
        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            messages.error(request, "This attempt is no longer active.")
            return redirect("accounts:student_dashboard")

        remaining_seconds = max(
            0, int((attempt.deadline_at - timezone.now()).total_seconds())
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
        question_index = max(0, min(question_index, len(questions) - 1))
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
            messages.error(request, "Your exam time has expired.")
            return redirect("accounts:student_dashboard")
        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            return HttpResponseForbidden("This attempt is not active.")

        question = get_object_or_404(
            Question,
            pk=request.POST.get("question_id"),
            exam_usages__exam=attempt.exam,
        )
        choice_id = request.POST.get("choice_id")
        choice = None
        if choice_id:
            choice = get_object_or_404(Choice, pk=choice_id, question=question)

        Answer.objects.update_or_create(
            attempt=attempt,
            question=question,
            defaults={"selected_choice": choice},
        )

        try:
            next_question = int(request.POST.get("next_question", "0"))
        except (TypeError, ValueError):
            next_question = 0

        question_count = ExamQuestion.objects.filter(exam=attempt.exam).count()
        next_question = max(0, min(next_question, max(question_count - 1, 0)))

    attempt_url = redirect("exams:take_attempt", attempt_id=attempt.pk).url
    return redirect(f"{attempt_url}?q={next_question}")


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
            messages.error(request, "The exam deadline has passed. Your attempt has timed out.")
            return redirect("accounts:student_dashboard")
        if attempt.status != ExamAttempt.Status.IN_PROGRESS:
            messages.error(request, "This attempt is no longer active.")
            return redirect("accounts:student_dashboard")

        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])

    messages.success(request, "Your exam has been submitted.")
    return redirect("accounts:student_dashboard")
