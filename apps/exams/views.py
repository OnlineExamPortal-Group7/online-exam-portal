import random
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, models, transaction
from django.db.models import F
from django.db.models.functions import Greatest
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


# Largest value a PositiveIntegerField holds on every supported database.
MAX_AUTOSAVE_SEQ = 2147483647


def _parse_seq(value):
    """Return the autosave sequence number, or None if none was sent.

    Raises ValueError if a number was sent but is not an integer from 1 to
    MAX_AUTOSAVE_SEQ.
    """
    if value is None or value == "":
        return None
    seq = int(value)
    if not 1 <= seq <= MAX_AUTOSAVE_SEQ:
        raise ValueError("autosave sequence out of range")
    return seq


def _resolve_answer_target(attempt, question_id, choice_id):
    """Return the (question, choice) pair a save refers to.

    The question must belong to the attempt's exam and the choice to that question,
    otherwise Http404 is raised. An empty choice_id gives choice None (clear).
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

    return question, choice


def _write_answer(attempt, question, choice, seq, newer_only):
    """Write the student's choice and return its saved_at, or None if it is stale.

    newer_only=True (versioned autosave): write only if seq is higher than the
    stored autosave_seq, and store seq. newer_only=False (form save or unversioned
    autosave): always write, and raise the stored number to seq but never lower it.
    The sequence check and the write are a single UPDATE, so an older request that
    reaches the database after a newer one cannot overwrite it (OEP-F-022).
    """
    rows = Answer.objects.filter(attempt=attempt, question=question)
    if newer_only:
        rows = rows.filter(autosave_seq__lt=seq)
        new_seq = seq
    else:
        new_seq = Greatest(
            F("autosave_seq"), seq, output_field=models.PositiveIntegerField()
        )
    saved_at = timezone.now()
    values = {
        "selected_choice": choice,
        "saved_at": saved_at,
        "autosave_seq": new_seq,
    }

    if rows.update(**values):
        return saved_at

    try:
        with transaction.atomic():
            answer = Answer.objects.create(
                attempt=attempt,
                question=question,
                selected_choice=choice,
                autosave_seq=seq,
            )
        return answer.saved_at
    except IntegrityError:
        # The row exists after all: another request created it first, or (for
        # newer_only) its stored number is not lower than seq. Retry the guarded
        # update once; if it still matches nothing, this save is stale.
        return saved_at if rows.update(**values) else None


def _store_answer(attempt, question_id, choice_id, seq=None):
    """Save (or clear) the choice from a form POST (navigation or submit).

    Form saves always write. seq is the page's latest autosave number; the stored
    number is raised to it so autosaves still in flight from that page are stale.
    A missing or malformed seq leaves the stored number unchanged.
    Callers must hold a select_for_update lock on the attempt and have checked it is
    still in progress (OEP-F-022).
    """
    question, choice = _resolve_answer_target(attempt, question_id, choice_id)
    try:
        seq = _parse_seq(seq) or 0
    except (TypeError, ValueError):
        seq = 0
    _write_answer(attempt, question, choice, seq, newer_only=False)


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
        answer.question_id: answer
        for answer in attempt.answers.all()
    }

    for question in questions:
        answer = saved_answers.get(question.pk)
        question.selected_choice_id = answer.selected_choice_id if answer else None
        # The page continues autosave numbering from here after a reload.
        question.autosave_seq = answer.autosave_seq if answer else 0

    answered_count = sum(
        1 for question in questions if question.selected_choice_id is not None
    )

    if "q" in request.GET:
        try:
            question_index = int(request.GET["q"])
        except (TypeError, ValueError):
            question_index = 0
    else:
        # Opening or reloading the attempt (e.g. after a browser crash) resumes
        # at the first unanswered question (OEP-F-022).
        question_index = next(
            (
                index
                for index, question in enumerate(questions)
                if question.selected_choice_id is None
            ),
            0,
        )

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
            "answered_count": answered_count,
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
            request.POST.get("autosave_seq"),
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

    Each request carries a per-question sequence number "seq". A request whose
    number is not higher than the stored one arrived out of order and is answered
    with 200 {"status": "stale"} so the page does not retry it. A request without
    seq is saved unconditionally and leaves the stored number unchanged.
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
            seq = _parse_seq(request.POST.get("seq"))
        except ValueError:
            return JsonResponse(
                {"saved": False, "error": "Invalid sequence number."},
                status=400,
            )

        try:
            question, choice = _resolve_answer_target(
                attempt,
                request.POST.get("question_id"),
                request.POST.get("choice_id"),
            )
        except Http404:
            return JsonResponse(
                {"saved": False, "error": "Invalid question or choice."},
                status=400,
            )

        if seq is None:
            saved_at = _write_answer(attempt, question, choice, 0, newer_only=False)
        else:
            saved_at = _write_answer(attempt, question, choice, seq, newer_only=True)

        if saved_at is None:
            stored_seq = (
                Answer.objects.filter(attempt=attempt, question=question)
                .values_list("autosave_seq", flat=True)
                .first()
            )
            return JsonResponse(
                {
                    "saved": False,
                    "status": "stale",
                    "question_id": question.pk,
                    "seq": stored_seq,
                }
            )

    payload = {
        "saved": True,
        "status": "saved",
        "question_id": question.pk,
        "choice_id": choice.pk if choice else None,
        "saved_at": saved_at.isoformat(),
    }
    if seq is not None:
        payload["seq"] = seq
    return JsonResponse(payload)


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

        # Keep the choice on the current question that the student had not yet
        # navigated away from (OEP-F-022). Only a real choice is stored, so a stale
        # or empty field never clears an answer that is already saved, and a bad id
        # never blocks the submission itself.
        if request.POST.get("question_id") and request.POST.get("choice_id"):
            try:
                _store_answer(
                    attempt,
                    request.POST["question_id"],
                    request.POST["choice_id"],
                    request.POST.get("autosave_seq"),
                )
            except Http404:
                pass

        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=["status", "submitted_at"])

        evaluate_attempt(attempt)

    messages.success(
        request,
        "Your exam has been submitted.",
    )
    return redirect("accounts:student_dashboard")


@role_required(User.Role.INSTRUCTOR)
def exam_list(request):
    """List examinations created by the signed-in instructor."""
    exams = (
        Exam.objects.filter(created_by=request.user)
        .select_related("course")
        .order_by("-created_at")
    )
    return render(request, "exams/exam_list.html", {"exams": exams})


@role_required(User.Role.INSTRUCTOR)
@require_POST
def publish_exam(request, exam_id):
    """Publish an instructor's draft exam for eligible students."""
    exam = get_object_or_404(
        Exam,
        pk=exam_id,
        created_by=request.user,
    )

    if exam.status == Exam.Status.PUBLISHED:
        messages.info(request, "This examination is already published.")
    elif exam.end_time <= timezone.now():
        messages.error(request, "Cannot publish an examination whose scheduled end time has passed.")
    elif not exam.exam_questions.exists():
        messages.error(request, "Add at least one question before publishing.")
    else:
        exam.status = Exam.Status.PUBLISHED
        exam.save(update_fields=["status", "updated_at"])
        messages.success(request, "Examination published successfully. Enrolled students can now see it.")

    return redirect("exams:exam_list")
