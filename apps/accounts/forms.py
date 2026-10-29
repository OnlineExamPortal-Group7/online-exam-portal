from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )
