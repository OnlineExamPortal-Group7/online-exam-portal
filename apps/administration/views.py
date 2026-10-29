from django.views.generic import ListView

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin


class UserListView(RoleRequiredMixin, ListView):
    """Administrator-only list of all user accounts (OEP-F-002, OEP-F-004)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    model = User
    ordering = ["username"]
    template_name = "administration/user_list.html"
    context_object_name = "users"
