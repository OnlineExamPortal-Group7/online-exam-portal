from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Superusers created from the command line are portal administrators.
        extra_fields.setdefault("role", User.Role.ADMINISTRATOR)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Portal user with a role (OEP-F-002)."""

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        INSTRUCTOR = "instructor", "Instructor"
        ADMINISTRATOR = "administrator", "Administrator"

    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)

    objects = UserManager()

    def save(self, *args, **kwargs):
        # Emails are compared case-insensitively, so store them in lower case.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
