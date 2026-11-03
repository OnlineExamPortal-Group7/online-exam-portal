"""User, role, course and enrolment administration (OEP-F-004, OEP-F-042).

Views call these functions instead of changing users, courses or enrolments
directly, so the rules live in one place.
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.sessions import end_sessions

from .models import Course, Enrollment


def audit_hook(action, actor, target, **details):
    """AUDIT HOOK: implemented in #22 (audit log). Called after every change below."""


def _require_administrator(actor):
    if not (actor.is_authenticated and actor.role == User.Role.ADMINISTRATOR):
        raise PermissionDenied


def create_user(actor, *, username, email, password, role, first_name="", last_name=""):
    _require_administrator(actor)
    if role not in User.Role.values:
        raise ValidationError(f"Unknown role: {role}")
    user = User.objects.create_user(
        username, email, password, role=role, first_name=first_name, last_name=last_name
    )
    audit_hook("user_created", actor, user, role=role)
    return user


def deactivate(actor, user):
    _require_administrator(actor)
    if user.pk == actor.pk:
        raise ValidationError("You cannot deactivate your own account.")
    user.is_active = False
    user.save(update_fields=["is_active"])
    end_sessions(user)
    audit_hook("user_deactivated", actor, user)


def reactivate(actor, user):
    _require_administrator(actor)
    user.is_active = True
    user.save(update_fields=["is_active"])
    audit_hook("user_reactivated", actor, user)


def change_role(actor, user, role):
    _require_administrator(actor)
    if role not in User.Role.values:
        raise ValidationError(f"Unknown role: {role}")
    if user.pk == actor.pk and role != User.Role.ADMINISTRATOR:
        raise ValidationError("You cannot remove your own Administrator role.")
    old_role = user.role
    user.role = role
    user.save(update_fields=["role"])
    if role != old_role:
        end_sessions(user)
    audit_hook("role_changed", actor, user, old_role=old_role, new_role=role)


def _require_active_role(user, role):
    if not (user.is_active and user.role == role):
        label = User.Role(role).label.lower()
        raise ValidationError(f"{user.username} is not an active {label}.")


def _check_course_code(code, course=None):
    # Codes are matched case-insensitively (e.g. by CSV import), so keep them unique that way.
    code = code.strip()
    others = Course.objects.filter(code__iexact=code)
    if course is not None:
        others = others.exclude(pk=course.pk)
    if others.exists():
        raise ValidationError(f"A course with code {code} already exists.")
    return code


def create_course(actor, *, code, name, instructor, description=""):
    _require_administrator(actor)
    code = _check_course_code(code)
    _require_active_role(instructor, User.Role.INSTRUCTOR)
    course = Course.objects.create(
        code=code, name=name, description=description, instructor=instructor
    )
    audit_hook("course_created", actor, course, instructor=instructor.pk)
    return course


def update_course(actor, course, *, code, name, instructor, description=""):
    """Edit a course; changing `instructor` reassigns it (and its question bank)."""
    _require_administrator(actor)
    code = _check_course_code(code, course)
    if instructor.pk != course.instructor_id:
        _require_active_role(instructor, User.Role.INSTRUCTOR)
    old_instructor = course.instructor_id
    course.code = code
    course.name = name
    course.description = description
    course.instructor = instructor
    course.save()
    audit_hook(
        "course_updated", actor, course,
        old_instructor=old_instructor, new_instructor=instructor.pk,
    )
    return course


def set_course_active(actor, course, active):
    """Deactivate or reactivate a course; its enrolments are kept either way."""
    _require_administrator(actor)
    course.is_active = active
    course.save(update_fields=["is_active", "updated_at"])
    audit_hook("course_reactivated" if active else "course_deactivated", actor, course)


def enrol_students(actor, course, students):
    """Enrol active students in an active course; returns the newly enrolled ones.

    Students already enrolled are skipped. If any student is refused, nobody is enrolled.
    """
    _require_administrator(actor)
    if not course.is_active:
        raise ValidationError(f"{course.code} is deactivated; reactivate it first.")
    for student in students:
        _require_active_role(student, User.Role.STUDENT)
    enrolled = []
    with transaction.atomic():
        for student in students:
            _, created = Enrollment.objects.get_or_create(student=student, course=course)
            if created:
                enrolled.append(student)
    for student in enrolled:
        audit_hook("student_enrolled", actor, student, course=course.pk)
    return enrolled


def unenrol_student(actor, course, student):
    _require_administrator(actor)
    deleted, _ = Enrollment.objects.filter(student=student, course=course).delete()
    if not deleted:
        raise ValidationError(f"{student.username} is not enrolled in {course.code}.")
    audit_hook("student_unenrolled", actor, student, course=course.pk)
