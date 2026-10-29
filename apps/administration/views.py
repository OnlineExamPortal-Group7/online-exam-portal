from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView, ListView

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin

from . import services
from .forms import AdminUserCreateForm, RoleChangeForm


class UserListView(RoleRequiredMixin, ListView):
    """Administrator-only list of all user accounts (OEP-F-002, OEP-F-004)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    model = User
    ordering = ["username"]
    template_name = "administration/user_list.html"
    context_object_name = "users"

    def get_context_data(self, **kwargs):
        return super().get_context_data(roles=User.Role.choices, **kwargs)


class UserCreateView(RoleRequiredMixin, FormView):
    """Administrator creates a user account with a role (OEP-F-004)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    form_class = AdminUserCreateForm
    template_name = "administration/user_form.html"
    success_url = reverse_lazy("administration:user_list")

    def form_valid(self, form):
        data = form.cleaned_data
        user = services.create_user(
            self.request.user,
            username=data["username"],
            email=data["email"],
            password=data["password1"],
            role=data["role"],
            first_name=data["first_name"],
            last_name=data["last_name"],
        )
        messages.success(self.request, f"Created {user.username} ({user.get_role_display()}).")
        return super().form_valid(form)


class UserActionView(RoleRequiredMixin, View):
    """Base for POST-only actions on one user; refused actions show an error message."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    http_method_names = ["post"]

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        try:
            message = self.perform(request, user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, message)
        return redirect("administration:user_list")

    def perform(self, request, user):
        raise NotImplementedError


class UserDeactivateView(UserActionView):
    def perform(self, request, user):
        services.deactivate(request.user, user)
        return f"Deactivated {user.username}."


class UserReactivateView(UserActionView):
    def perform(self, request, user):
        services.reactivate(request.user, user)
        return f"Reactivated {user.username}."


class UserRoleChangeView(UserActionView):
    def perform(self, request, user):
        form = RoleChangeForm(request.POST)
        if not form.is_valid():
            raise ValidationError("Choose a valid role.")
        services.change_role(request.user, user, form.cleaned_data["role"])
        return f"{user.username} is now {user.get_role_display()}."
