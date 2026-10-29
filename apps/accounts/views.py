from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import User
from .permissions import role_required

DASHBOARD_BY_ROLE = {
    User.Role.STUDENT: "accounts:student_dashboard",
    User.Role.INSTRUCTOR: "accounts:instructor_dashboard",
    User.Role.ADMINISTRATOR: "accounts:admin_dashboard",
}


def home(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")
    return render(request, "home.html")


@login_required
def dashboard(request):
    """Send each signed-in user to the dashboard for their role."""
    return redirect(DASHBOARD_BY_ROLE[request.user.role])


@role_required(User.Role.STUDENT)
def student_dashboard(request):
    return render(request, "accounts/dashboard.html", {"title": "Student dashboard"})


@role_required(User.Role.INSTRUCTOR)
def instructor_dashboard(request):
    return render(request, "accounts/dashboard.html", {"title": "Instructor dashboard"})


@role_required(User.Role.ADMINISTRATOR)
def admin_dashboard(request):
    return render(request, "accounts/dashboard.html", {"title": "Administrator dashboard"})
