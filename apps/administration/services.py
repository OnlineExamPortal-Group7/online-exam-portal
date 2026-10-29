"""User and role administration (OEP-F-004).

Views call these functions instead of changing users directly, so the rules
live in one place.
"""
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.accounts.sessions import end_sessions


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
