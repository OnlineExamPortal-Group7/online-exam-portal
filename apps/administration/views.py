from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import FormView, ListView

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin

from . import services
from .forms import AdminUserCreateForm


class UserListView(RoleRequiredMixin, ListView):
    """Administrator-only list of all user accounts (OEP-F-002, OEP-F-004)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    model = User
    ordering = ["username"]
    template_name = "administration/user_list.html"
    context_object_name = "users"


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
