# Admin registrations are added by later issues.

from django.contrib import admin
from .models import Result


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("attempt", "score", "total_marks", "percentage", "evaluated_at")
    search_fields = ("attempt__student__username", "attempt__exam__title")
