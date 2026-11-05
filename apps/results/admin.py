from django.contrib import admin

from .models import Result, ResultPublication


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("attempt", "score", "total_marks", "percentage", "evaluated_at")
    search_fields = ("attempt__student__username", "attempt__exam__title")


@admin.register(ResultPublication)
class ResultPublicationAdmin(admin.ModelAdmin):
    list_display = ("exam", "published_by", "published_at")
    search_fields = ("exam__title", "published_by__username")
