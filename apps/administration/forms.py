from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.accounts.models import User


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
