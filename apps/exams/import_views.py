"""CSV question-bank import pages (OEP-F-011). Instructors and administrators only."""
from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import FormView

from apps.accounts.permissions import RoleRequiredMixin

from .question_import import IMPORT_ROLES, MAX_FILE_BYTES, import_questions

SAMPLE_CSV = (
    "course,topic,difficulty,question,option_1,option_2,option_3,option_4,correct,marks\n"
    "CS101,Loops,easy,Which keyword starts a loop in Python?,if,for,def,class,2,1\n"
    'CS101,Functions,medium,"What does return do?",Ends the function and gives back a value,'
    "Prints a value,,,1,2\n"
)


class QuestionImportForm(forms.Form):
    file = forms.FileField(label="CSV file", help_text="UTF-8 CSV, up to 1 MB and 500 questions.")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".csv"):
            raise forms.ValidationError("Choose a .csv file.")
        if upload.size > MAX_FILE_BYTES:
            raise forms.ValidationError(f"The file is larger than {MAX_FILE_BYTES // 1024} KB.")
        return upload


class QuestionImportView(RoleRequiredMixin, FormView):
    allowed_roles = IMPORT_ROLES
    form_class = QuestionImportForm
    template_name = "exams/question_import.html"

    def form_valid(self, form):
        result = import_questions(self.request.user, form.cleaned_data["file"].read())
        if result.errors:
            return self.render_to_response(self.get_context_data(form=form, errors=result.errors))
        messages.success(self.request, f"Imported {len(result.created)} questions.")
        return redirect("exams:question_import")


class SampleCsvView(RoleRequiredMixin, View):
    allowed_roles = IMPORT_ROLES

    def get(self, request):
        response = HttpResponse(SAMPLE_CSV, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="question_import_sample.csv"'
        return response
