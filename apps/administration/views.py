from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from apps.accounts.models import User
from apps.accounts.permissions import RoleRequiredMixin

from . import services
from .forms import AdminUserCreateForm, CourseForm, EnrolForm, RoleChangeForm, UnenrolForm
from .models import AuditLog, Course


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


class CourseDetailView(RoleRequiredMixin, DetailView):
    """Course roster: the enrolled students, plus a form to enrol more (OEP-F-042, AC-042)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    model = Course
    queryset = Course.objects.select_related("instructor")
    template_name = "administration/course_detail.html"
    context_object_name = "course"

    def get_context_data(self, **kwargs):
        enrolments = self.object.enrollments.select_related("student").order_by(
            "student__username"
        )
        return super().get_context_data(
            enrolments=enrolments, enrol_form=EnrolForm(course=self.object), **kwargs
        )


class CourseActionView(RoleRequiredMixin, View):
    """Base for POST-only actions on one course; refused actions show an error message."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    http_method_names = ["post"]

    def post(self, request, pk):
        course = get_object_or_404(Course, pk=pk)
        try:
            message = self.perform(request, course)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, message)
        return redirect(self.redirect_to(course))

    def perform(self, request, course):
        raise NotImplementedError

    def redirect_to(self, course):
        return reverse("administration:course_detail", args=[course.pk])


class CourseEnrolView(CourseActionView):
    def perform(self, request, course):
        form = EnrolForm(request.POST, course=course)
        if not form.is_valid():
            raise ValidationError("Choose active students who are not already enrolled.")
        enrolled = services.enrol_students(request.user, course, form.cleaned_data["students"])
        names = ", ".join(student.username for student in enrolled)
        return f"Enrolled {names} in {course.code}."


class CourseUnenrolView(CourseActionView):
    def perform(self, request, course):
        form = UnenrolForm(request.POST)
        if not form.is_valid():
            raise ValidationError("Choose a student to unenrol.")
        student = form.cleaned_data["student"]
        services.unenrol_student(request.user, course, student)
        return f"Unenrolled {student.username} from {course.code}."


class CourseDeactivateView(CourseActionView):
    def perform(self, request, course):
        services.set_course_active(request.user, course, False)
        return f"Deactivated {course.code}."

    def redirect_to(self, course):
        return reverse("administration:course_list")


class CourseReactivateView(CourseDeactivateView):
    def perform(self, request, course):
        services.set_course_active(request.user, course, True)
        return f"Reactivated {course.code}."


class AuditLogListView(RoleRequiredMixin, ListView):
    """Administrator-only history of recorded administrative actions (Issue #22)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)
    model = AuditLog
    template_name = "administration/audit_log_list.html"
    context_object_name = "audit_logs"
    paginate_by = 25

    def get_queryset(self):
        return AuditLog.objects.select_related("actor").order_by("-timestamp", "-pk")
