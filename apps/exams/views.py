
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render

from apps.accounts.models import User

from .forms import ExamCreationForm
from .models import ExamQuestion


@login_required
def create_exam(request):
    if request.user.role != User.Role.INSTRUCTOR:
        raise PermissionDenied

    if request.method == "POST":
        form = ExamCreationForm(
            request.POST,
            instructor=request.user,
        )

        if form.is_valid():
            with transaction.atomic():
                exam = form.save(commit=False)
                exam.created_by = request.user

                selected_questions = list(
                    form.cleaned_data["questions"]
                )

                exam.total_marks = sum(
                    question.marks for question in selected_questions
                )
                exam.save()

                if exam.randomize_questions:
                    random.shuffle(selected_questions)

                ExamQuestion.objects.bulk_create(
                    [
                        ExamQuestion(
                            exam=exam,
                            question=question,
                            position=position,
                        )
                        for position, question in enumerate(
                            selected_questions,
                            start=1,
                        )
                    ]
                )

            messages.success(request, "Exam created successfully.")
            return redirect("exams:create")
    else:
        form = ExamCreationForm(instructor=request.user)

    return render(
        request,
        "exams/create_exam.html",
        {"form": form},
    )
