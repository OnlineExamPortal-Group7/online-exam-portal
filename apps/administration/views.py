from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, FormView, ListView, UpdateView

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin

from . import services
from .forms import AdminUserCreateForm, CourseForm, RoleChangeForm
from .models import Course


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


class CourseListView(RoleRequiredMixin, ListView):
    """Administrator-only list of all courses with their instructor and size (OEP-F-042)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    template_name = "administration/course_list.html"
    context_object_name = "courses"

    def get_queryset(self):
        return Course.objects.select_related("instructor").annotate(
            student_count=Count("enrollments")
        )


class CourseFormMixin(RoleRequiredMixin):
    """Saves the course form through the services; refused changes show as form errors."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    model = Course
    form_class = CourseForm
    template_name = "administration/course_form.html"
    success_url = reverse_lazy("administration:course_list")

    def form_valid(self, form):
        try:
            course = self.save(form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, self.success_message.format(course=course))
        return redirect(self.success_url)

    def save(self, data):
        raise NotImplementedError


class CourseCreateView(CourseFormMixin, CreateView):
    """Administrator defines a course and assigns its instructor (OEP-F-042)."""

    success_message = "Created {course}."

    def save(self, data):
        return services.create_course(self.request.user, **data)


class CourseUpdateView(CourseFormMixin, UpdateView):
    """Administrator edits a course or reassigns its instructor (OEP-F-042)."""

    success_message = "Saved {course}."

    def save(self, data):
        # Form validation already copied the new values onto self.object, so the
        # service gets a fresh copy and can see the old instructor.
        course = Course.objects.get(pk=self.object.pk)
        return services.update_course(self.request.user, course, **data)
