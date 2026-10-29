
from django import forms
from django.utils import timezone

from apps.administration.models import Course
from .models import Exam, Question


class ExamCreationForm(forms.ModelForm):
    questions = forms.ModelMultipleChoiceField(
        queryset=Question.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Exam
        fields = [
            "course",
            "title",
            "description",
            "start_time",
            "end_time",
            "duration_minutes",
            "randomize_questions",
        ]
        widgets = {
            "start_time": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "end_time": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, instructor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instructor = instructor

        if instructor is not None:
            self.fields["course"].queryset = Course.objects.filter(
                instructor=instructor,
                is_active=True,
            )
            self.fields["questions"].queryset = Question.objects.filter(
                course__instructor=instructor,
                course__is_active=True,
            ).select_related("course")

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        course = cleaned_data.get("course")
        questions = cleaned_data.get("questions")

        if start_time and end_time and end_time <= start_time:
            self.add_error(
                "end_time",
                "The end time must be after the start time.",
            )

        if start_time and start_time <= timezone.now():
            self.add_error(
                "start_time",
                "The exam start time must be in the future.",
            )

        if course and questions:
            if any(question.course_id != course.id for question in questions):
                self.add_error(
                    "questions",
                    "Select questions belonging to the chosen course.",
                )

        return cleaned_data
