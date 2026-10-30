"""MCQ question bank: list, view, create, edit and delete (OEP-F-010, TC-QB-01).

Every view here is instructor/administrator only (OEP-F-014, OEP-SR-003).
"""
from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, ListView

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin

from .models import Question
from .question_forms import ChoiceFormSet, QuestionFilterForm, QuestionForm

# --- TEMPORARY: replace this block when issue #11 is merged --------------------------------
# Issue #11 adds apps/exams/access.py with QuestionBankAccessMixin and questions_for().
# These two stand-ins behave the same until then. After #11 merges, delete the block and use:
#     from .access import QuestionBankAccessMixin, questions_for
QUESTION_BANK_ROLES = (User.Role.INSTRUCTOR, User.Role.ADMINISTRATOR)


class QuestionBankAccessMixin(RoleRequiredMixin):
    allowed_roles = QUESTION_BANK_ROLES


def questions_for(user):
    """Questions the user may see: instructors their own courses', administrators all."""
    if not (user.is_authenticated and user.is_active):
        return Question.objects.none()
    if user.role == User.Role.ADMINISTRATOR:
        return Question.objects.all()
    if user.role == User.Role.INSTRUCTOR:
        return Question.objects.filter(course__instructor=user)
    return Question.objects.none()


# --- end of temporary block -----------------------------------------------------------------


def question_usage(question):
    """How many exams use the question and how many student answers refer to it."""
    return {
        "exams": question.exam_usages.count(),
        "answers": question.submitted_answers.count(),
    }


class QuestionListView(QuestionBankAccessMixin, ListView):
    template_name = "exams/questions/question_list.html"
    context_object_name = "questions"
    paginate_by = 20

    def get_filter_form(self):
        if not hasattr(self, "_filter_form"):
            self._filter_form = QuestionFilterForm(
                self.request.GET or None, user=self.request.user
            )
        return self._filter_form

    def get_queryset(self):
        queryset = (
            questions_for(self.request.user)
            .select_related("course")
            .prefetch_related("choices")
            .order_by("-updated_at", "-id")
        )
        form = self.get_filter_form()
        if form.is_bound and form.is_valid():
            data = form.cleaned_data
            if data["course"]:
                queryset = queryset.filter(course=data["course"])
            if data["difficulty"]:
                queryset = queryset.filter(difficulty=data["difficulty"])
            if data["q"]:
                queryset = queryset.filter(text__icontains=data["q"])
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["filter_form"] = self.get_filter_form()
        context["query_string"] = params.urlencode()
        return context


class QuestionDetailView(QuestionBankAccessMixin, DetailView):
    template_name = "exams/questions/question_detail.html"
    context_object_name = "question"

    def get_queryset(self):
        return (
            questions_for(self.request.user)
            .select_related("course", "created_by")
            .prefetch_related("choices")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["usage"] = question_usage(self.object)
        return context


class QuestionEditView(QuestionBankAccessMixin, View):
    """Create (creating=True) or edit a question together with its answer choices."""

    template_name = "exams/questions/question_form.html"
    creating = False
    object = None

    def load_object(self, request):
        """Fetch the question. Returns a redirect if it must not be edited."""
        if self.creating:
            return None
        self.object = get_object_or_404(questions_for(request.user), pk=self.kwargs["pk"])
        if self.object.submitted_answers.exists():
            messages.error(
                request,
                "This question has already been answered in an exam, so it can no longer be "
                "edited. Create a new question instead.",
            )
            return redirect("exams:question_detail", pk=self.object.pk)
        return None

    def render_form(self, request, form, formset, status=200):
        context = {
            "form": form,
            "formset": formset,
            "question": self.object,
            "creating": self.creating,
        }
        return render(request, self.template_name, context, status=status)

    def get(self, request, *args, **kwargs):
        blocked = self.load_object(request)
        if blocked:
            return blocked
        form = QuestionForm(instance=self.object, user=request.user)
        formset = ChoiceFormSet(instance=self.object)
        return self.render_form(request, form, formset)

    def post(self, request, *args, **kwargs):
        blocked = self.load_object(request)
        if blocked:
            return blocked
        form = QuestionForm(request.POST, instance=self.object, user=request.user)
        formset = ChoiceFormSet(request.POST, instance=self.object)
        form_ok = form.is_valid()
        formset_ok = formset.is_valid()
        if not (form_ok and formset_ok):
            return self.render_form(request, form, formset, status=200)
        try:
            with transaction.atomic():
                question = form.save(commit=False)
                if self.creating:
                    question.created_by = request.user
                    question.question_type = Question.QuestionType.MCQ
                question.save()
                formset.instance = question
                formset.save()
        except ProtectedError:
            messages.error(request, "A choice is already used in an answer and cannot be removed.")
            return self.render_form(request, form, formset, status=200)
        messages.success(request, "Question saved.")
        return redirect("exams:question_detail", pk=question.pk)


class QuestionCreateView(QuestionEditView):
    creating = True


class QuestionUpdateView(QuestionEditView):
    creating = False


class QuestionDeleteView(QuestionBankAccessMixin, View):
    template_name = "exams/questions/question_confirm_delete.html"

    def get_question(self, request):
        return get_object_or_404(questions_for(request.user), pk=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        question = self.get_question(request)
        context = {"question": question, "usage": question_usage(question)}
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        question = self.get_question(request)
        usage = question_usage(question)
        if usage["exams"] or usage["answers"]:
            messages.error(
                request, "This question is used in an exam and cannot be deleted."
            )
            return redirect("exams:question_detail", pk=question.pk)
        try:
            question.delete()
        except ProtectedError:
            messages.error(request, "This question is used in an exam and cannot be deleted.")
            return redirect("exams:question_detail", pk=question.pk)
        messages.success(request, "Question deleted.")
        return redirect("exams:question_list")
