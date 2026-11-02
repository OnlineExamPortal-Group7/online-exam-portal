from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q

from apps.accounts.models import User

from .models import Course


class AdminUserCreateForm(UserCreationForm):
    """Account details an administrator fills in for a new user (OEP-F-004)."""

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "role")

    def clean_email(self):
        # Emails are stored in lower case, so check uniqueness the same way.
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise self.instance.unique_error_message(User, ["email"])
        return email


class RoleChangeForm(forms.Form):
    role = forms.ChoiceField(choices=User.Role.choices)


class CourseForm(forms.ModelForm):
    """Course details an administrator fills in; the instructor teaches the course (OEP-F-042)."""

    class Meta:
        model = Course
        fields = ("code", "name", "description", "instructor")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = Q(role=User.Role.INSTRUCTOR, is_active=True)
        if self.instance.pk:
            # Keep the current instructor selectable even if they were deactivated later.
            allowed |= Q(pk=self.instance.instructor_id)
        self.fields["instructor"].queryset = User.objects.filter(allowed).order_by("username")
