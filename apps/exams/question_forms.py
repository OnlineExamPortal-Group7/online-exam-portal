"""Forms for the MCQ question bank (OEP-F-010).

Rules enforced here: 2 to 6 answer choices, exactly one correct choice, choices differ.
"""
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.accounts.models import User
from apps.administration.models import Course

from .models import Choice, Question

MIN_CHOICES = 2
MAX_CHOICES = 6


def courses_for(user):
    """Courses whose questions this user may manage."""
    if not (user.is_authenticated and user.is_active):
        return Course.objects.none()
    if user.role == User.Role.ADMINISTRATOR:
        return Course.objects.all()
    if user.role == User.Role.INSTRUCTOR:
        return Course.objects.filter(instructor=user)
    return Course.objects.none()


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ["course", "text", "difficulty", "marks"]
        widgets = {"text": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = Q(is_active=True)
        if self.instance.pk:
            # Keep the current course selectable even if it was deactivated later.
            allowed |= Q(pk=self.instance.course_id)
        self.fields["course"].queryset = courses_for(user).filter(allowed)


class BaseChoiceFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        choices = [
            data
            for data in (form.cleaned_data for form in self.forms)
            if data and not data.get("DELETE")
        ]
        if not MIN_CHOICES <= len(choices) <= MAX_CHOICES:
            raise ValidationError(
                f"Enter between {MIN_CHOICES} and {MAX_CHOICES} answer choices."
            )
        if sum(1 for data in choices if data.get("is_correct")) != 1:
            raise ValidationError("Mark exactly one choice as the correct answer.")
        texts = [data["text"].strip().lower() for data in choices]
        if len(set(texts)) != len(texts):
            raise ValidationError("Answer choices must be different from each other.")


ChoiceFormSet = inlineformset_factory(
    Question,
    Choice,
    formset=BaseChoiceFormSet,
    fields=["text", "is_correct"],
    extra=MAX_CHOICES,
    max_num=MAX_CHOICES,
    can_delete=True,
    widgets={"text": forms.TextInput(attrs={"size": 60})},
)


class QuestionFilterForm(forms.Form):
    course = forms.ModelChoiceField(queryset=Course.objects.none(), required=False)
    difficulty = forms.ChoiceField(
        choices=[("", "All difficulties")] + Question.Difficulty.choices, required=False
    )
    q = forms.CharField(label="Search text", required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = courses_for(user)
