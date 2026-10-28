from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Project user with a role (OEP-F-002 RBAC). Auth details come in later issues."""

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        INSTRUCTOR = "instructor", "Instructor"
        ADMINISTRATOR = "administrator", "Administrator"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
